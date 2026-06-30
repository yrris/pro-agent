package store_test

import (
	"context"
	"encoding/json"
	"errors"
	"os"
	"reflect"
	"testing"

	"github.com/jackc/pgx/v5/pgxpool"

	"my-agent/control-plane/internal/event"
	"my-agent/control-plane/internal/store"
)

const ts = int64(1700000000000)

// 集成测试需要一个 PostgreSQL。设置 TEST_PG_DSN 后运行；否则跳过。
// 例：TEST_PG_DSN=postgres://agent:agent_pwd@localhost:55432/my_agent go test ./internal/store/...
func testPool(t *testing.T) *pgxpool.Pool {
	t.Helper()
	dsn := os.Getenv("TEST_PG_DSN")
	if dsn == "" {
		t.Skip("TEST_PG_DSN 未设置，跳过 store 集成测试")
	}
	ctx := context.Background()
	pool, err := store.NewPool(ctx, dsn)
	if err != nil {
		t.Fatalf("NewPool: %v", err)
	}
	if err := store.Migrate(ctx, pool); err != nil {
		t.Fatalf("Migrate: %v", err)
	}
	if _, err := pool.Exec(ctx, `TRUNCATE events, runs CASCADE`); err != nil {
		t.Fatalf("truncate: %v", err)
	}
	t.Cleanup(pool.Close)
	return pool
}

func jsonSemEqual(t *testing.T, a, b []byte) bool {
	t.Helper()
	var x, y any
	if err := json.Unmarshal(a, &x); err != nil {
		t.Fatalf("unmarshal a: %v (%s)", err, a)
	}
	if err := json.Unmarshal(b, &y); err != nil {
		t.Fatalf("unmarshal b: %v (%s)", err, b)
	}
	return reflect.DeepEqual(x, y)
}

func goldenEnvelopes() []event.Envelope {
	in := json.RawMessage(`{"expression":"2*(3+4)"}`)
	return []event.Envelope{
		{Seq: 1, RunID: "r1", MessageID: "r1:think:1", Type: event.TypeToolThought, TSUnixMs: ts, IsFinal: true,
			Thought: &event.ThoughtPayload{Text: "先算一下"}},
		{Seq: 2, RunID: "r1", MessageID: "tc1", Type: event.TypeToolCall, TSUnixMs: ts, IsFinal: false,
			Tool: &event.ToolPayload{ToolCallID: "tc1", ToolName: "calculator", ToolProvider: "local", Status: event.StatusRunning, DispatchIndex: 1, Input: in, Summary: "正在调用 calculator"}},
		{Seq: 3, RunID: "r1", MessageID: "tc1", Type: event.TypeToolCall, TSUnixMs: ts, IsFinal: true,
			Tool: &event.ToolPayload{ToolCallID: "tc1", ToolName: "calculator", ToolProvider: "local", Status: event.StatusSuccess, DispatchIndex: 1, Input: in, Summary: "calculator 调用完成"}},
		{Seq: 4, RunID: "r1", MessageID: "tr1", Type: event.TypeToolResult, TSUnixMs: ts, IsFinal: true,
			Tool: &event.ToolPayload{ToolCallID: "tc1", ToolName: "calculator", Input: in, ToolResult: "14",
				Artifacts: []event.ArtifactRef{{ResourceKey: "k1", Name: "n1", Size: 7}}}},
		{Seq: 5, RunID: "r1", MessageID: "res1", Type: event.TypeResult, TSUnixMs: ts, IsFinal: true, Finish: true,
			Result: &event.ResultPayload{Text: "答案是 14"}},
	}
}

func TestRunLifecycle(t *testing.T) {
	pool := testPool(t)
	ctx := context.Background()
	repo := store.NewRunRepository(pool)

	if err := repo.CreateRun(ctx, store.CreateRunParams{RunID: "run-life", SessionID: "s1", OwnerID: "o1", QueryText: "hi"}); err != nil {
		t.Fatalf("CreateRun: %v", err)
	}
	got, err := repo.GetRun(ctx, "run-life")
	if err != nil {
		t.Fatalf("GetRun: %v", err)
	}
	if got.Status != store.StatusRunning || got.FinishedAt != nil {
		t.Fatalf("expected RUNNING & no finishedAt, got %+v", got)
	}
	if err := repo.FinishRun(ctx, store.FinishRunParams{RunID: "run-life", Status: store.StatusSuccess, FinalSummaryText: "做完了"}); err != nil {
		t.Fatalf("FinishRun: %v", err)
	}
	got, _ = repo.GetRun(ctx, "run-life")
	if got.Status != store.StatusSuccess || got.FinalSummaryText == nil || *got.FinalSummaryText != "做完了" || got.FinishedAt == nil {
		t.Fatalf("unexpected finished run: %+v", got)
	}
	if _, err := repo.GetRun(ctx, "nope"); !errors.Is(err, store.ErrRunNotFound) {
		t.Fatalf("expected ErrRunNotFound, got %v", err)
	}
}

// 头号不变量（存储层）：append 后按 seq 重放，渲染帧与原始帧逐字段一致。
func TestEventAppendListReplay(t *testing.T) {
	pool := testPool(t)
	ctx := context.Background()
	runs := store.NewRunRepository(pool)
	events := store.NewEventRepository(pool)

	if err := runs.CreateRun(ctx, store.CreateRunParams{RunID: "r1", SessionID: "s1", OwnerID: "o1", QueryText: "算 2*(3+4)"}); err != nil {
		t.Fatalf("CreateRun: %v", err)
	}
	golden := goldenEnvelopes()
	for _, e := range golden {
		if err := e.Validate(); err != nil {
			t.Fatalf("golden seq %d invalid: %v", e.Seq, err)
		}
		if err := events.Append(ctx, e); err != nil {
			t.Fatalf("Append seq %d: %v", e.Seq, err)
		}
	}

	got, err := events.ListByRun(ctx, "r1")
	if err != nil {
		t.Fatalf("ListByRun: %v", err)
	}
	if len(got) != len(golden) {
		t.Fatalf("expected %d events, got %d", len(golden), len(got))
	}
	for i := range got {
		if got[i].Seq != uint64(i+1) {
			t.Fatalf("seq order broken at %d: %d", i, got[i].Seq)
		}
		wantFrame, _ := event.ToSSEFrame(golden[i])
		gotFrame, _ := event.ToSSEFrame(got[i])
		if !jsonSemEqual(t, gotFrame, wantFrame) {
			t.Errorf("replay frame mismatch at seq %d\n got: %s\nwant: %s", got[i].Seq, gotFrame, wantFrame)
		}
	}
}

func TestDuplicateSeq(t *testing.T) {
	pool := testPool(t)
	ctx := context.Background()
	runs := store.NewRunRepository(pool)
	events := store.NewEventRepository(pool)

	if err := runs.CreateRun(ctx, store.CreateRunParams{RunID: "rdup", SessionID: "s1", OwnerID: "o1", QueryText: "x"}); err != nil {
		t.Fatalf("CreateRun: %v", err)
	}
	e := event.Envelope{Seq: 1, RunID: "rdup", MessageID: "m", Type: event.TypeToolThought, TSUnixMs: ts, Thought: &event.ThoughtPayload{Text: "x"}}
	if err := events.Append(ctx, e); err != nil {
		t.Fatalf("first append: %v", err)
	}
	if err := events.Append(ctx, e); !errors.Is(err, store.ErrDuplicateSeq) {
		t.Fatalf("expected ErrDuplicateSeq, got %v", err)
	}
}
