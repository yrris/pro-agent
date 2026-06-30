package stream

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"testing"
	"time"

	"my-agent/control-plane/internal/event"
	"my-agent/control-plane/internal/store"
)

const ts = int64(1700000000000)

// ---- 测试替身 ----

type recvItem struct {
	e   event.Envelope
	err error
}

type fakeStream struct {
	items []recvItem
	i     int
	block chan struct{} // 非空时，items 耗尽后阻塞（模拟无事件的长连接）
}

func (f *fakeStream) Recv() (event.Envelope, error) {
	if f.i < len(f.items) {
		it := f.items[f.i]
		f.i++
		return it.e, it.err
	}
	if f.block != nil {
		<-f.block
	}
	return event.Envelope{}, io.EOF
}

type fakeSink struct {
	frames     []event.Envelope
	heartbeats int
}

func (s *fakeSink) WriteFrame(e event.Envelope) error { s.frames = append(s.frames, e); return nil }
func (s *fakeSink) WriteHeartbeat() error             { s.heartbeats++; return nil }

type fakeEventRepo struct{ appended []event.Envelope }

func (r *fakeEventRepo) Append(_ context.Context, e event.Envelope) error {
	r.appended = append(r.appended, e)
	return nil
}
func (r *fakeEventRepo) ListByRun(context.Context, string) ([]event.Envelope, error) {
	return r.appended, nil
}

func goldenEnvelopes() []event.Envelope {
	in := json.RawMessage(`{"expression":"2*(3+4)"}`)
	return []event.Envelope{
		{Seq: 1, RunID: "r1", MessageID: "r1:think:1", Type: event.TypeToolThought, TSUnixMs: ts, IsFinal: true, Thought: &event.ThoughtPayload{Text: "先算一下"}},
		{Seq: 2, RunID: "r1", MessageID: "tc1", Type: event.TypeToolCall, TSUnixMs: ts, Tool: &event.ToolPayload{ToolCallID: "tc1", ToolName: "calculator", ToolProvider: "local", Status: event.StatusRunning, DispatchIndex: 1, Input: in, Summary: "正在调用 calculator"}},
		{Seq: 3, RunID: "r1", MessageID: "tc1", Type: event.TypeToolCall, TSUnixMs: ts, IsFinal: true, Tool: &event.ToolPayload{ToolCallID: "tc1", ToolName: "calculator", ToolProvider: "local", Status: event.StatusSuccess, DispatchIndex: 1, Input: in, Summary: "calculator 调用完成"}},
		{Seq: 4, RunID: "r1", MessageID: "tr1", Type: event.TypeToolResult, TSUnixMs: ts, IsFinal: true, Tool: &event.ToolPayload{ToolCallID: "tc1", ToolName: "calculator", Input: in, ToolResult: "14"}},
		{Seq: 5, RunID: "r1", MessageID: "res1", Type: event.TypeResult, TSUnixMs: ts, IsFinal: true, Finish: true, Result: &event.ResultPayload{Text: "答案是 14"}},
	}
}

func newHub(repo store.EventRepository) *Hub {
	// 心跳设很长，避免测试期触发。
	return NewHub(repo, time.Hour, nil)
}

func TestPump_HappyPath(t *testing.T) {
	items := []recvItem{}
	for _, e := range goldenEnvelopes() {
		items = append(items, recvItem{e: e})
	}
	repo := &fakeEventRepo{}
	sink := &fakeSink{}
	res := newHub(repo).Pump(context.Background(), "r1", &fakeStream{items: items}, sink)

	if res.Status != store.StatusSuccess || res.Summary != "答案是 14" {
		t.Fatalf("expected SUCCESS/答案是 14, got %+v", res)
	}
	if len(repo.appended) != 5 || len(sink.frames) != 5 {
		t.Fatalf("expected 5 persisted & 5 sent, got %d/%d", len(repo.appended), len(sink.frames))
	}
	for i, e := range repo.appended { // 先落库后展示，且顺序一致
		if e.Seq != uint64(i+1) {
			t.Fatalf("persist seq order broken at %d: %d", i, e.Seq)
		}
	}
}

func TestPump_SeqGap(t *testing.T) {
	g := goldenEnvelopes()
	items := []recvItem{{e: g[0]}, {e: g[2]}} // seq 1 then 3 (gap)
	repo := &fakeEventRepo{}
	res := newHub(repo).Pump(context.Background(), "r1", &fakeStream{items: items}, &fakeSink{})
	if res.Status != store.StatusFailed || res.ErrorCode != "SEQ_GAP" {
		t.Fatalf("expected FAILED/SEQ_GAP, got %+v", res)
	}
	if len(repo.appended) != 1 {
		t.Fatalf("expected only seq 1 persisted, got %d", len(repo.appended))
	}
}

func TestPump_RecvError(t *testing.T) {
	g := goldenEnvelopes()
	items := []recvItem{{e: g[0]}, {err: errors.New("boom")}}
	repo := &fakeEventRepo{}
	res := newHub(repo).Pump(context.Background(), "r1", &fakeStream{items: items}, &fakeSink{})
	if res.Status != store.StatusFailed || res.ErrorCode != "STREAM_RECV_ERROR" {
		t.Fatalf("expected FAILED/STREAM_RECV_ERROR, got %+v", res)
	}
}

func TestPump_EOFWithoutFinish(t *testing.T) {
	g := goldenEnvelopes()
	items := []recvItem{{e: g[0]}} // 一个非 finish 事件后流结束
	repo := &fakeEventRepo{}
	res := newHub(repo).Pump(context.Background(), "r1", &fakeStream{items: items}, &fakeSink{})
	if res.Status != store.StatusFailed || res.ErrorCode != "STREAM_EOF_NO_FINISH" {
		t.Fatalf("expected FAILED/STREAM_EOF_NO_FINISH, got %+v", res)
	}
}

func TestPump_ClientDisconnect(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	go func() { time.Sleep(20 * time.Millisecond); cancel() }()
	res := newHub(&fakeEventRepo{}).Pump(ctx, "r1", &fakeStream{block: make(chan struct{})}, &fakeSink{})
	if res.Status != store.StatusStopped || res.ErrorCode != "CLIENT_GONE" {
		t.Fatalf("expected STOPPED/CLIENT_GONE, got %+v", res)
	}
}
