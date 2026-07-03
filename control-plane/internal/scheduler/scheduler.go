// Package scheduler：定时触发 Proactive run（M11）。
//
// 控制面作为调度中枢的论据实装：ticker 扫描到期 schedules → 复用 Dispatcher 准入/
// 事件链路发起 headless run（NullSink——事件仍先落账本，会话列表/回放照常可见）。
//
// 次序纪律（压测定稿）：**先 Admit 后 Claim**——反序会在满载时推进 next_run_at 却没跑，
// 静默丢一拍；Admit 失败即留行，下个 tick 重试。调度并发有独立小信号量（默认 2），
// 不吃满交互用户的准入配额。同 thread 重叠护栏：上一发 run 仍 RUNNING 则跳过本拍。
package scheduler

import (
	"context"
	"log/slog"
	"time"

	"github.com/google/uuid"

	"my-agent/control-plane/internal/dispatch"
	"my-agent/control-plane/internal/event"
	"my-agent/control-plane/internal/store"
)

// nullSink：headless run 的空写端——事件仍由 hub 先落账本（持久化在前、展示为空），
// 会话列表/回放照常可见调度产生的 run。
type nullSink struct{}

func (nullSink) WriteFrame(event.Envelope) error { return nil }
func (nullSink) WriteHeartbeat() error           { return nil }

// Scheduler 周期扫描并触发到期任务。
type Scheduler struct {
	repo       store.SchedulesRepository
	runs       store.RunRepository
	dispatcher *dispatch.Dispatcher
	runTimeout time.Duration
	tick       time.Duration
	slots      chan struct{} // 调度并发独立上限
	log        *slog.Logger
}

// New 构造调度器。maxConcurrent 独立于 Dispatcher 全局准入（防调度吃满交互配额）。
func New(repo store.SchedulesRepository, runs store.RunRepository, d *dispatch.Dispatcher,
	runTimeout, tick time.Duration, maxConcurrent int, log *slog.Logger) *Scheduler {
	if maxConcurrent <= 0 {
		maxConcurrent = 2
	}
	if tick <= 0 {
		tick = 30 * time.Second
	}
	return &Scheduler{
		repo: repo, runs: runs, dispatcher: d,
		runTimeout: runTimeout, tick: tick,
		slots: make(chan struct{}, maxConcurrent), log: log,
	}
}

// Run 阻塞运行至 ctx 取消（main 优雅停机时 cancel）。
func (s *Scheduler) Run(ctx context.Context) {
	ticker := time.NewTicker(s.tick)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			s.fireDue(ctx)
		}
	}
}

func (s *Scheduler) fireDue(ctx context.Context) {
	due, err := s.repo.ListDue(ctx, 16)
	if err != nil {
		s.log.Warn("scheduler list due failed", "err", err)
		return
	}
	for _, sched := range due {
		// 同 thread 重叠护栏：上一发仍在跑（慢 run 或长审批链）→ 跳过本拍不认领。
		if sched.LastRunID != "" {
			if run, err := s.runs.GetRun(ctx, sched.LastRunID); err == nil && run.Status == store.StatusRunning {
				continue
			}
		}
		// 调度自有小信号量：满即本拍不再触发（行未认领，下拍重试）。
		select {
		case s.slots <- struct{}{}:
		default:
			return
		}
		// 先 Admit 后 Claim（反序满载时静默丢一拍）。
		release, ok := s.dispatcher.Admit()
		if !ok {
			<-s.slots
			return // 系统满载：留行，下个 tick 重试
		}
		runID := uuid.NewString()
		claimed, err := s.repo.Claim(ctx, sched.ScheduleID, runID)
		if err != nil || !claimed {
			release()
			<-s.slots
			if err != nil {
				s.log.Warn("scheduler claim failed", "err", err)
			}
			continue // 已被禁用/边界竞争：放弃本条
		}
		go func(sched store.Schedule) {
			defer release()
			defer func() { <-s.slots }()
			// headless：不依附任何 HTTP 请求，自建超时上下文。
			runCtx, cancel := context.WithTimeout(context.Background(), s.runTimeout)
			defer cancel()
			s.log.Info("scheduled run fired", "scheduleId", sched.ScheduleID, "runId", runID)
			if err := s.dispatcher.Run(runCtx, dispatch.StartCommand{
				RunID: runID, SessionID: sched.SessionID, OwnerID: sched.OwnerID,
				Query: sched.QueryText, AgentType: sched.AgentType,
			}, nullSink{}); err != nil {
				s.log.Warn("scheduled run failed", "scheduleId", sched.ScheduleID, "err", err)
			}
		}(sched)
	}
}
