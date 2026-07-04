// Package api 暴露控制面的 HTTP/SSE 入口：发起 run（流式）、按事件回放历史、健康检查。
package api

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"log/slog"
	"net/http"
	"os"
	"strconv"
	"strings"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/go-chi/chi/v5/middleware"
	"github.com/google/uuid"

	"my-agent/control-plane/internal/artifact"
	"my-agent/control-plane/internal/cognition"
	"my-agent/control-plane/internal/dispatch"
	"my-agent/control-plane/internal/event"
	"my-agent/control-plane/internal/health"
	"my-agent/control-plane/internal/kb"
	"my-agent/control-plane/internal/store"
)

type handlers struct {
	dispatcher     *dispatch.Dispatcher
	runs           store.RunRepository
	sessions       store.SessionRepository
	events         store.EventRepository
	artifacts      artifact.Store
	healthChecks   map[string]health.Check
	kb             kb.Store
	cog            cognition.Client
	stats          store.StatsRepository
	artifactList   store.ArtifactListRepository
	schedules      store.SchedulesRepository
	runTimeout     time.Duration
	maxUploadBytes int64
	log            *slog.Logger
}

// NewRouter 装配路由与中间件。artifacts 可为 nil（仅 /artifacts 不可用）；
// sessions 可为 nil（仅 /sessions 不可用）；healthChecks 可为 nil（/healthz 退化为「进程存活即 200」）；
// webDir 非空时经 NotFound 托管前端静态资源 + SPA 回退（已注册 API 路由优先匹配，零冲突）。
func NewRouter(d *dispatch.Dispatcher, runs store.RunRepository, sessions store.SessionRepository, events store.EventRepository, artifacts artifact.Store, healthChecks map[string]health.Check, kbStore kb.Store, cog cognition.Client, stats store.StatsRepository, artifactList store.ArtifactListRepository, schedules store.SchedulesRepository, runTimeout time.Duration, webDir string, log *slog.Logger) http.Handler {
	h := &handlers{
		dispatcher: d, runs: runs, sessions: sessions, events: events, artifacts: artifacts,
		healthChecks: healthChecks, kb: kbStore, cog: cog, stats: stats, artifactList: artifactList, schedules: schedules, runTimeout: runTimeout,
		maxUploadBytes: DefaultMaxUploadBytes, log: log,
	}
	if v := os.Getenv("MAX_UPLOAD_BYTES"); v != "" {
		if n, err := strconv.ParseInt(v, 10, 64); err == nil && n > 0 {
			h.maxUploadBytes = n
		}
	}
	r := chi.NewRouter()
	r.Use(middleware.RequestID)
	r.Use(middleware.Recoverer)
	r.Get("/healthz", h.healthz)
	r.Post("/runs", h.startRun)
	r.Get("/runs/{runID}/events", h.replay)
	r.Post("/runs/{runID}/approvals", h.resolveApproval) // M11 HITL：决议→恢复 run（SSE）
	r.Get("/sessions", h.listSessions)
	r.Get("/sessions/{sessionID}/runs", h.listSessionRuns)
	r.Post("/uploads", h.upload)
	// UX-1 Files 面板：用户知识库管理（读/删直连 Qdrant；上传入库走认知面 gRPC）。
	r.Get("/kb/docs", h.listKbDocs)
	r.Post("/kb/docs", h.ingestKbDoc)
	r.Delete("/kb/docs", h.deleteKbDoc)
	r.Get("/stats/usage", h.usageStats) // M11 成本面板（owner 域聚合，纯读）
	// M11 定时任务（Proactive）：owner 域 CRUD；触发由 internal/scheduler。
	r.Get("/schedules", h.listSchedules)
	r.Post("/schedules", h.createSchedule)
	r.Delete("/schedules/{scheduleID}", h.deleteSchedule)
	r.Post("/schedules/{scheduleID}/toggle", h.toggleSchedule)
	r.Get("/artifacts", h.listArtifacts) // 跨会话产物画廊（owner 域）——与下面的对象代理精确路由共存
	r.Get("/artifacts/*", h.artifact)
	if webDir != "" {
		r.NotFound(spaHandler(webDir))
	}
	return r
}

// healthz 并发探测已注入的依赖（PG / 认知面），聚合成单一判定。
func (h *handlers) healthz(w http.ResponseWriter, r *http.Request) {
	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()
	rep := health.RunChecks(ctx, h.healthChecks)
	writeJSON(w, rep.HTTPStatus, map[string]any{"healthy": rep.Healthy, "checks": rep.Body})
}

type attachmentRef struct {
	ResourceKey string `json:"resourceKey"`
	FileName    string `json:"fileName"`
	MimeType    string `json:"mimeType"`
	Size        int64  `json:"size"`
}

type startRunRequest struct {
	Query        string          `json:"query"`
	SessionID    string          `json:"sessionId"`
	AgentType    string          `json:"agentType"`    // "react"(默认) | "plan_solve" | "deep_research"
	OutputFormat string          `json:"outputFormat"` // M9：html/docs/ppt/table（空=自由格式）
	Attachments  []attachmentRef `json:"attachments"`
}

func (h *handlers) startRun(w http.ResponseWriter, r *http.Request) {
	var body startRunRequest
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil || body.Query == "" {
		writeProblem(w, http.StatusBadRequest, "bad_request", "query 必填")
		return
	}
	sessionID := body.SessionID
	if sessionID == "" {
		sessionID = uuid.NewString()
	}
	agentType := body.AgentType
	switch agentType {
	case "plan_solve", "deep_research": // 三档模式：快速(react)/深度思考/深度研究
	default:
		agentType = "react"
	}
	ownerID := ownerOf(r)
	// 附件 key 防伪造闸门：只接受当前用户自己的 uploads 对象——否则任何人可把
	// 他人 upload key 塞进 attachments，让认知面替他读取内容/写进知识库。
	atts := make([]dispatch.Attachment, 0, len(body.Attachments))
	for _, a := range body.Attachments {
		if !ValidateAttachmentKey(ownerID, a.ResourceKey) {
			writeProblem(w, http.StatusForbidden, "forbidden", "附件不属于当前用户："+a.ResourceKey)
			return
		}
		atts = append(atts, dispatch.Attachment{
			ResourceKey: a.ResourceKey, FileName: a.FileName, MimeType: a.MimeType, Size: a.Size,
		})
	}

	h.streamRun(w, r, dispatch.StartCommand{
		SessionID: sessionID, OwnerID: ownerID, Query: body.Query, AgentType: agentType, OutputFormat: body.OutputFormat,
		Attachments: atts,
	})
}

// streamRun：准入 → SSE 头 + X-Run-Id → 以 SSE 流承载一次 run（startRun 与审批恢复共用）。
// cmd.RunID 留空则生成；准入必须在写任何响应头之前，满载干净回 429。
func (h *handlers) streamRun(w http.ResponseWriter, r *http.Request, cmd dispatch.StartCommand) {
	release, ok := h.dispatcher.Admit()
	if !ok {
		writeProblem(w, http.StatusTooManyRequests, "busy", "系统繁忙，请稍后重试")
		return
	}
	defer release()

	if cmd.RunID == "" {
		cmd.RunID = uuid.NewString()
	}
	writeSSEHeaders(w)
	w.Header().Set("X-Run-Id", cmd.RunID)
	w.WriteHeader(http.StatusOK)
	sink, err := newSSESink(w)
	if err != nil {
		h.log.Error("sse sink", "err", err)
		return
	}

	runCtx, cancel := context.WithTimeout(r.Context(), h.runTimeout)
	defer cancel()

	if err := h.dispatcher.Run(runCtx, cmd, sink); err != nil {
		h.log.Error("run failed", "runID", cmd.RunID, "err", err)
	}
}

type resolveApprovalRequest struct {
	ApprovalID string `json:"approvalId"`
	Approved   bool   `json:"approved"`
	Comment    string `json:"comment"`
}

// resolveApproval：POST /runs/{runID}/approvals —— 审批=run 边界的恢复端。
// 归属校验循 replay 模式；响应即新 run 的 SSE 流（与 POST /runs 同构，X-Run-Id 可取）。
// 决议乘 metadata 走既有 Run RPC；认知面校验 pending interrupt 匹配（伪造/过期→优雅收尾）。
func (h *handlers) resolveApproval(w http.ResponseWriter, r *http.Request) {
	runID := chi.URLParam(r, "runID")
	run, err := h.runs.GetRun(r.Context(), runID)
	if errors.Is(err, store.ErrRunNotFound) {
		writeProblem(w, http.StatusNotFound, "not_found", "run 不存在")
		return
	}
	if err != nil {
		writeProblem(w, http.StatusInternalServerError, "internal", err.Error())
		return
	}
	if run.OwnerID != ownerOf(r) {
		writeProblem(w, http.StatusForbidden, "forbidden", "无权访问该 run")
		return
	}
	var body resolveApprovalRequest
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil || body.ApprovalID == "" {
		writeProblem(w, http.StatusBadRequest, "bad_request", "approvalId 必填")
		return
	}
	verdict, decision := "通过", "approved"
	if !body.Approved {
		verdict, decision = "拒绝", "rejected"
	}
	query := "[审批] " + verdict
	if body.Comment != "" {
		query += "：" + body.Comment
	}
	h.streamRun(w, r, dispatch.StartCommand{
		SessionID: run.SessionID, OwnerID: run.OwnerID, Query: query, AgentType: "react",
		ApprovalResumeID: body.ApprovalID, ApprovalDecision: decision, ApprovalComment: body.Comment,
	})
}

func (h *handlers) replay(w http.ResponseWriter, r *http.Request) {
	runID := chi.URLParam(r, "runID")
	run, err := h.runs.GetRun(r.Context(), runID)
	if errors.Is(err, store.ErrRunNotFound) {
		writeProblem(w, http.StatusNotFound, "not_found", "run 不存在")
		return
	}
	if err != nil {
		writeProblem(w, http.StatusInternalServerError, "internal", err.Error())
		return
	}
	if run.OwnerID != ownerOf(r) {
		writeProblem(w, http.StatusForbidden, "forbidden", "无权访问该 run")
		return
	}
	envelopes, err := h.events.ListByRun(r.Context(), runID)
	if err != nil {
		writeProblem(w, http.StatusInternalServerError, "internal", err.Error())
		return
	}
	// 自证不变量：seq 无空洞、finish 仅 result 且至多一条。违反只告警、不阻断回放（可能是崩溃残留）。
	if verr := event.ValidateSequence(envelopes); verr != nil {
		h.log.Warn("replay sequence invariant violated", "runID", runID, "err", verr)
	}

	writeSSEHeaders(w)
	w.WriteHeader(http.StatusOK)
	sink, err := newSSESink(w)
	if err != nil {
		return
	}
	// 用与实时完全相同的编码器逐条重发 → 重放帧与实时逐字段一致。
	for _, e := range envelopes {
		if err := sink.WriteFrame(e); err != nil {
			return
		}
	}
}

// artifact 代理产物下载。两类 key、两种鉴权：
//   - uploads/{owner}/…（M8 上传对象）：owner 前置于 key，比对第二段即可，免查库
//     ——必须在 runID 反查之前特判（其首段 "uploads" 不是 runID）。
//   - {runId}/{toolCallId}/{file}（运行产物）：用首段 runId 反查 run 校验 owner。
func (h *handlers) artifact(w http.ResponseWriter, r *http.Request) {
	key := chi.URLParam(r, "*")
	if key == "" {
		writeProblem(w, http.StatusNotFound, "not_found", "缺少产物 key")
		return
	}
	if strings.HasPrefix(key, "uploads/") {
		if OwnerOfUploadKey(key) != ownerOf(r) {
			writeProblem(w, http.StatusForbidden, "forbidden", "无权访问该产物")
			return
		}
		h.serveObject(w, r, key)
		return
	}
	runID := key
	if i := strings.IndexByte(key, '/'); i > 0 {
		runID = key[:i]
	}
	run, err := h.runs.GetRun(r.Context(), runID)
	if errors.Is(err, store.ErrRunNotFound) {
		writeProblem(w, http.StatusNotFound, "not_found", "run 不存在")
		return
	}
	if err != nil {
		writeProblem(w, http.StatusInternalServerError, "internal", err.Error())
		return
	}
	if run.OwnerID != ownerOf(r) {
		writeProblem(w, http.StatusForbidden, "forbidden", "无权访问该产物")
		return
	}
	h.serveObject(w, r, key)
}

// serveObject 鉴权通过后的公共回传路径（uploads 与运行产物共用）。
func (h *handlers) serveObject(w http.ResponseWriter, r *http.Request, key string) {
	if h.artifacts == nil {
		writeProblem(w, http.StatusServiceUnavailable, "no_artifact_store", "产物存储未配置")
		return
	}
	obj, err := h.artifacts.Open(r.Context(), key)
	if errors.Is(err, artifact.ErrNotFound) {
		writeProblem(w, http.StatusNotFound, "not_found", "产物不存在")
		return
	}
	if err != nil {
		writeProblem(w, http.StatusInternalServerError, "internal", err.Error())
		return
	}
	defer obj.Body.Close()
	w.Header().Set("Content-Type", obj.ContentType)
	if obj.Size > 0 {
		w.Header().Set("Content-Length", strconv.FormatInt(obj.Size, 10))
	}
	w.WriteHeader(http.StatusOK)
	_, _ = io.Copy(w, obj.Body)
}

// —— M7 会话端点（只读投影，proto/SSE 零改动；设计与取舍见 docs/08 §2） ——

// sessionSummaryJSON 是 GET /sessions 的响应行（camelCase，与 SSE 帧字段风格一致）。
type sessionSummaryJSON struct {
	SessionID    string    `json:"sessionId"`
	Title        string    `json:"title"`
	EntryAgent   string    `json:"entryAgent"`
	RunCount     int       `json:"runCount"`
	CreatedAt    time.Time `json:"createdAt"`
	LastActiveAt time.Time `json:"lastActiveAt"`
}

// listSessions 返回调用方的会话列表：runs 表按 session_id 聚合，lastActiveAt 降序。
func (h *handlers) listSessions(w http.ResponseWriter, r *http.Request) {
	if h.sessions == nil {
		writeProblem(w, http.StatusServiceUnavailable, "no_session_store", "会话存储未配置")
		return
	}
	limit := 0
	if v := r.URL.Query().Get("limit"); v != "" {
		n, err := strconv.Atoi(v)
		if err != nil || n < 0 {
			writeProblem(w, http.StatusBadRequest, "bad_request", "limit 必须是非负整数")
			return
		}
		limit = n
	}
	list, err := h.sessions.ListSessions(r.Context(), ownerOf(r), limit)
	if err != nil {
		writeProblem(w, http.StatusInternalServerError, "internal", err.Error())
		return
	}
	out := make([]sessionSummaryJSON, 0, len(list))
	for _, s := range list {
		out = append(out, sessionSummaryJSON{
			SessionID: s.SessionID, Title: s.Title, EntryAgent: s.EntryAgent,
			RunCount: s.RunCount, CreatedAt: s.CreatedAt, LastActiveAt: s.LastActiveAt,
		})
	}
	writeJSON(w, http.StatusOK, map[string]any{"sessions": out})
}

// sessionRunJSON 是 GET /sessions/{id}/runs 的响应行（run 元数据，不内嵌事件——
// 前端对每个 run 复用 GET /runs/{runID}/events 回放，保持「回放==实时」单点维护）。
type sessionRunJSON struct {
	RunID        string    `json:"runId"`
	Query        string    `json:"query"`
	AgentType    string    `json:"agentType"`
	Status       string    `json:"status"`
	FinalSummary string    `json:"finalSummary,omitempty"`
	ErrorMsg     string    `json:"errorMsg,omitempty"`
	CreatedAt    time.Time `json:"createdAt"`
}

// listSessionRuns 返回会话内 run 元数据（created_at 升序）。owner 过滤在 SQL 里，
// 他人会话与不存在的会话同样返回空 → 统一 404，不泄露存在性。
func (h *handlers) listSessionRuns(w http.ResponseWriter, r *http.Request) {
	if h.sessions == nil {
		writeProblem(w, http.StatusServiceUnavailable, "no_session_store", "会话存储未配置")
		return
	}
	sessionID := chi.URLParam(r, "sessionID")
	runs, err := h.sessions.ListRunsBySession(r.Context(), ownerOf(r), sessionID)
	if err != nil {
		writeProblem(w, http.StatusInternalServerError, "internal", err.Error())
		return
	}
	if len(runs) == 0 {
		writeProblem(w, http.StatusNotFound, "not_found", "会话不存在")
		return
	}
	out := make([]sessionRunJSON, 0, len(runs))
	for _, run := range runs {
		j := sessionRunJSON{
			RunID: run.RunID, Query: run.QueryText, AgentType: run.EntryAgent,
			Status: run.Status, CreatedAt: run.CreatedAt,
		}
		if run.FinalSummaryText != nil {
			j.FinalSummary = *run.FinalSummaryText
		}
		if run.ErrorMsg != nil {
			j.ErrorMsg = *run.ErrorMsg
		}
		out = append(out, j)
	}
	writeJSON(w, http.StatusOK, map[string]any{"sessionId": sessionID, "runs": out})
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}

// ownerOf 解析调用方身份（本阶段单用户：X-User-Id 头，缺省 anonymous）。多租户/RBAC 留待拓展。
func ownerOf(r *http.Request) string {
	if v := r.Header.Get("X-User-Id"); v != "" {
		return v
	}
	return "anonymous"
}

func writeProblem(w http.ResponseWriter, status int, code, msg string) {
	if status == http.StatusTooManyRequests {
		w.Header().Set("Retry-After", "1")
	}
	writeJSON(w, status, map[string]string{"code": code, "message": msg})
}

// usageStats：GET /stats/usage?days=30 —— runs 表 owner 域聚合（合计/按天/按模式）。
func (h *handlers) usageStats(w http.ResponseWriter, r *http.Request) {
	if h.stats == nil {
		writeProblem(w, http.StatusServiceUnavailable, "no_stats", "统计未启用")
		return
	}
	days := 30
	if v := r.URL.Query().Get("days"); v != "" {
		if n, err := strconv.Atoi(v); err == nil {
			days = n
		}
	}
	report, err := h.stats.UsageReport(r.Context(), ownerOf(r), days)
	if err != nil {
		h.log.Error("usage stats failed", "err", err)
		writeProblem(w, http.StatusInternalServerError, "internal", "统计查询失败")
		return
	}
	writeJSON(w, http.StatusOK, report)
}


// listArtifacts：GET /artifacts?limit=100 —— 跨会话产物画廊（owner 域，纯读）。
func (h *handlers) listArtifacts(w http.ResponseWriter, r *http.Request) {
	if h.artifactList == nil {
		writeProblem(w, http.StatusServiceUnavailable, "no_artifact_list", "产物列表未启用")
		return
	}
	limit := 100
	if v := r.URL.Query().Get("limit"); v != "" {
		if n, err := strconv.Atoi(v); err == nil {
			limit = n
		}
	}
	items, err := h.artifactList.ListByOwner(r.Context(), ownerOf(r), limit)
	if err != nil {
		h.log.Error("list artifacts failed", "err", err)
		writeProblem(w, http.StatusInternalServerError, "internal", "产物列表查询失败")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"artifacts": items})
}
