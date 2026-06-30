// Package api 暴露控制面的 HTTP/SSE 入口：发起 run（流式）、按事件回放历史、健康检查。
package api

import (
	"context"
	"encoding/json"
	"errors"
	"log/slog"
	"net/http"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/go-chi/chi/v5/middleware"
	"github.com/google/uuid"

	"my-agent/control-plane/internal/dispatch"
	"my-agent/control-plane/internal/store"
)

type handlers struct {
	dispatcher *dispatch.Dispatcher
	runs       store.RunRepository
	events     store.EventRepository
	runTimeout time.Duration
	log        *slog.Logger
}

// NewRouter 装配路由与中间件。
func NewRouter(d *dispatch.Dispatcher, runs store.RunRepository, events store.EventRepository, runTimeout time.Duration, log *slog.Logger) http.Handler {
	h := &handlers{dispatcher: d, runs: runs, events: events, runTimeout: runTimeout, log: log}
	r := chi.NewRouter()
	r.Use(middleware.RequestID)
	r.Use(middleware.Recoverer)
	r.Get("/healthz", func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("ok"))
	})
	r.Post("/runs", h.startRun)
	r.Get("/runs/{runID}/events", h.replay)
	return r
}

type startRunRequest struct {
	Query     string `json:"query"`
	SessionID string `json:"sessionId"`
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
		RunID: runID, SessionID: sessionID, OwnerID: ownerID, Query: body.Query,
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

// ownerOf 解析调用方身份（本阶段单用户：X-User-Id 头，缺省 anonymous）。多租户/RBAC 留待拓展。
func ownerOf(r *http.Request) string {
	if v := r.Header.Get("X-User-Id"); v != "" {
		return v
	}
	return "anonymous"
}

func writeProblem(w http.ResponseWriter, status int, code, msg string) {
	w.Header().Set("Content-Type", "application/json")
	if status == http.StatusTooManyRequests {
		w.Header().Set("Retry-After", "1")
	}
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(map[string]string{"code": code, "message": msg})
}
