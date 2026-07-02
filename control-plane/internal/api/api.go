// Package api 暴露控制面的 HTTP/SSE 入口：发起 run（流式）、按事件回放历史、健康检查。
package api

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"log/slog"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/go-chi/chi/v5/middleware"
	"github.com/google/uuid"

	"my-agent/control-plane/internal/artifact"
	"my-agent/control-plane/internal/dispatch"
	"my-agent/control-plane/internal/event"
	"my-agent/control-plane/internal/health"
	"my-agent/control-plane/internal/store"
)

type handlers struct {
	dispatcher   *dispatch.Dispatcher
	runs         store.RunRepository
	sessions     store.SessionRepository
	events       store.EventRepository
	artifacts    artifact.Store
	healthChecks map[string]health.Check
	runTimeout   time.Duration
	log          *slog.Logger
}

// NewRouter 装配路由与中间件。artifacts 可为 nil（仅 /artifacts 不可用）；
// sessions 可为 nil（仅 /sessions 不可用）；healthChecks 可为 nil（/healthz 退化为「进程存活即 200」）；
// webDir 非空时经 NotFound 托管前端静态资源 + SPA 回退（已注册 API 路由优先匹配，零冲突）。
func NewRouter(d *dispatch.Dispatcher, runs store.RunRepository, sessions store.SessionRepository, events store.EventRepository, artifacts artifact.Store, healthChecks map[string]health.Check, runTimeout time.Duration, webDir string, log *slog.Logger) http.Handler {
	h := &handlers{dispatcher: d, runs: runs, sessions: sessions, events: events, artifacts: artifacts, healthChecks: healthChecks, runTimeout: runTimeout, log: log}
	r := chi.NewRouter()
	r.Use(middleware.RequestID)
	r.Use(middleware.Recoverer)
	r.Get("/healthz", h.healthz)
	r.Post("/runs", h.startRun)
	r.Get("/runs/{runID}/events", h.replay)
	r.Get("/sessions", h.listSessions)
	r.Get("/sessions/{sessionID}/runs", h.listSessionRuns)
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

type startRunRequest struct {
	Query     string `json:"query"`
	SessionID string `json:"sessionId"`
	AgentType string `json:"agentType"` // "react"(默认) | "plan_solve"
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
	if agentType != "plan_solve" { // 仅这两种；其余按 react 兜底
		agentType = "react"
	}
	ownerID := ownerOf(r)

	// 准入必须在写任何响应头之前，满载则干净地回 429。
	release, ok := h.dispatcher.Admit()
	if !ok {
		writeProblem(w, http.StatusTooManyRequests, "busy", "系统繁忙，请稍后重试")
		return
	}
	defer release()

	runID := uuid.NewString()
	writeSSEHeaders(w)
	w.Header().Set("X-Run-Id", runID)
	w.WriteHeader(http.StatusOK)
	sink, err := newSSESink(w)
	if err != nil {
		h.log.Error("sse sink", "err", err)
		return
	}

	runCtx, cancel := context.WithTimeout(r.Context(), h.runTimeout)
	defer cancel()

	if err := h.dispatcher.Run(runCtx, dispatch.StartCommand{
		RunID: runID, SessionID: sessionID, OwnerID: ownerID, Query: body.Query, AgentType: agentType,
	}, sink); err != nil {
		h.log.Error("run failed", "runID", runID, "err", err)
	}
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

// artifact 代理产物下载。resourceKey 形如 {runId}/{toolCallId}/{file}，
// 用首段 runId 反查 run 校验 owner，再从对象存储流式回传。
func (h *handlers) artifact(w http.ResponseWriter, r *http.Request) {
	key := chi.URLParam(r, "*")
	if key == "" {
		writeProblem(w, http.StatusNotFound, "not_found", "缺少产物 key")
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
