// Package dispatch 负责 run 的准入（有界并发 + 背压）与生命周期编排：
// 准入成功后 createRun → 打开认知流 → 由 stream.Hub 泵送 → finishRun。
package dispatch

import (
	"context"
	"errors"
	"log/slog"

	"golang.org/x/sync/semaphore"

	"my-agent/control-plane/internal/cognition"
	"my-agent/control-plane/internal/store"
	"my-agent/control-plane/internal/stream"
)

// ErrBusy 表示并发已达上限（背压）。上层应回 429“系统繁忙”。
var ErrBusy = errors.New("dispatch: system busy")

// Attachment 是已上传附件的引用（key 归属已在 api 层校验）。
type Attachment struct {
	ResourceKey string
	FileName    string
	MimeType    string
	Size        int64
}

// StartCommand 是一次 run 的启动入参。
type StartCommand struct {
	RunID        string
	SessionID    string
	OwnerID      string
	OutputFormat string // M9：输出格式（透传认知面 metadata）
	// M11 HITL：审批恢复三元组（乘 metadata 走既有 Run RPC；空=普通 run）。
	ApprovalResumeID string
	ApprovalDecision string // "approved" | "rejected"
	ApprovalComment  string
	Query            string
	AgentType        string // "react" | "plan_solve"
	Attachments      []Attachment
}

// Dispatcher 持有并发闸与运行时协作者。
type Dispatcher struct {
	sem      *semaphore.Weighted
	runs     store.RunRepository
	client   cognition.Client
	hub      *stream.Hub
	maxSteps int32
	log      *slog.Logger
}

func New(maxConcurrent int64, runs store.RunRepository, client cognition.Client, hub *stream.Hub, maxSteps int32, log *slog.Logger) *Dispatcher {
	if maxConcurrent <= 0 {
		maxConcurrent = 16
	}
	return &Dispatcher{
		sem:      semaphore.NewWeighted(maxConcurrent),
		runs:     runs,
		client:   client,
		hub:      hub,
		maxSteps: maxSteps,
		log:      log,
	}
}

// Admit 非阻塞地尝试占用一个并发槽。成功返回释放函数；失败返回 (nil, false)。
// 必须在写任何 SSE 响应头之前调用，以便满载时能干净地回 429。
func (d *Dispatcher) Admit() (release func(), ok bool) {
	if !d.sem.TryAcquire(1) {
		return nil, false
	}
	return func() { d.sem.Release(1) }, true
}

// Run 执行一次“已准入”的 run：建 run → 打开认知流 → 泵送 → 收口。
// ctx 为 run 上下文（含超时、随客户端断开取消）。finishRun 用脱离取消的上下文，
// 保证即便客户端断开也能写回终态。
func (d *Dispatcher) Run(ctx context.Context, cmd StartCommand, sink stream.Sink) error {
	agentType := cmd.AgentType
	if agentType == "" {
		agentType = "react"
	}
	// run-scoped 结构化日志：关联键与 Python 认知面一致（run_id/session_id/agent_type），
	// 便于用同一 run_id 跨进程串起 Go↔Python 全链路。
	var log *slog.Logger
	if d.log != nil {
		log = d.log.With("run_id", cmd.RunID, "session_id", cmd.SessionID, "agent_type", agentType)
	}
	if err := d.runs.CreateRun(ctx, store.CreateRunParams{
		RunID: cmd.RunID, SessionID: cmd.SessionID, OwnerID: cmd.OwnerID, EntryAgent: agentType, QueryText: cmd.Query,
	}); err != nil {
		return err
	}
	if log != nil {
		log.Info("run start")
	}

	finCtx := context.WithoutCancel(ctx)

	atts := make([]cognition.Attachment, 0, len(cmd.Attachments))
	for _, a := range cmd.Attachments {
		atts = append(atts, cognition.Attachment(a))
	}
	st, err := d.client.RunAgent(ctx, cognition.RunRequest{
		RunID: cmd.RunID, SessionID: cmd.SessionID, Query: cmd.Query, AgentType: agentType, OutputFormat: cmd.OutputFormat,
		ApprovalResumeID: cmd.ApprovalResumeID, ApprovalDecision: cmd.ApprovalDecision, ApprovalComment: cmd.ApprovalComment,
		MaxSteps: d.maxSteps, OwnerID: cmd.OwnerID, Attachments: atts,
	})
	if err != nil {
		_ = d.runs.FinishRun(finCtx, store.FinishRunParams{RunID: cmd.RunID, Status: store.StatusFailed, ErrorMsg: err.Error()})
		if log != nil {
			log.Error("open run stream failed", "err", err)
		}
		return err
	}

	res := d.hub.Pump(ctx, cmd.RunID, st, sink)
	fp := store.FinishRunParams{
		RunID: cmd.RunID, Status: res.Status, FinalSummaryText: res.Summary, ErrorMsg: res.ErrorMsg,
	}
	if res.Usage != nil {
		fp.InputTokens, fp.OutputTokens, fp.ModelCalls = res.Usage.InputTokens, res.Usage.OutputTokens, res.Usage.ModelCalls
	}
	if ferr := d.runs.FinishRun(finCtx, fp); ferr != nil && log != nil {
		log.Error("finish run failed", "err", ferr)
	}
	if log != nil {
		log.Info("run finished", "status", res.Status)
	}
	return nil
}
