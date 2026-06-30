package api_test

import (
	"context"
	"encoding/json"
	"io"
	"log/slog"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"reflect"
	"strings"
	"testing"
	"time"

	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/test/bufconn"
	"google.golang.org/protobuf/types/known/structpb"

	"my-agent/control-plane/internal/api"
	"my-agent/control-plane/internal/cognition"
	"my-agent/control-plane/internal/dispatch"
	agentv1 "my-agent/control-plane/internal/genproto/agent/v1"
	"my-agent/control-plane/internal/store"
	"my-agent/control-plane/internal/stream"
)

const ts = int64(1700000000000)

// fakeCog 是一个进程内的认知面假实现：把一次 ReAct(1 工具) run 的 5 个 golden 事件流出。
type fakeCog struct {
	agentv1.UnimplementedCognitionServiceServer
}

func (f *fakeCog) Run(req *agentv1.RunRequest, srv grpc.ServerStreamingServer[agentv1.Event]) error {
	in, _ := structpb.NewStruct(map[string]any{"expression": "2*(3+4)"})
	runID := req.GetRunId()
	events := []*agentv1.Event{
		{Seq: 1, RunId: runID, MessageId: runID + ":think:1", Type: agentv1.EventType_EVENT_TYPE_TOOL_THOUGHT, TsUnixMs: ts, IsFinal: true,
			Payload: &agentv1.Event_ToolThought{ToolThought: &agentv1.ThoughtPayload{Text: "先算一下"}}},
		{Seq: 2, RunId: runID, MessageId: "tc1", Type: agentv1.EventType_EVENT_TYPE_TOOL_CALL, TsUnixMs: ts, IsFinal: false,
			Payload: &agentv1.Event_ToolCall{ToolCall: &agentv1.ToolPayload{ToolCallId: "tc1", ToolName: "calculator", ToolProvider: "local", Status: agentv1.ToolCallStatus_TOOL_CALL_STATUS_RUNNING, DispatchIndex: 1, Input: in, Summary: "正在调用 calculator"}}},
		{Seq: 3, RunId: runID, MessageId: "tc1", Type: agentv1.EventType_EVENT_TYPE_TOOL_CALL, TsUnixMs: ts, IsFinal: true,
			Payload: &agentv1.Event_ToolCall{ToolCall: &agentv1.ToolPayload{ToolCallId: "tc1", ToolName: "calculator", ToolProvider: "local", Status: agentv1.ToolCallStatus_TOOL_CALL_STATUS_SUCCESS, DispatchIndex: 1, Input: in, Summary: "calculator 调用完成"}}},
		{Seq: 4, RunId: runID, MessageId: "tr1", Type: agentv1.EventType_EVENT_TYPE_TOOL_RESULT, TsUnixMs: ts, IsFinal: true,
			Payload: &agentv1.Event_ToolResult{ToolResult: &agentv1.ToolPayload{ToolCallId: "tc1", ToolName: "calculator", Input: in, ToolResult: "14"}}},
		{Seq: 5, RunId: runID, MessageId: "res1", Type: agentv1.EventType_EVENT_TYPE_RESULT, TsUnixMs: ts, IsFinal: true, Finish: true,
			Payload: &agentv1.Event_Result{Result: &agentv1.ResultPayload{Text: "答案是 14"}}},
	}
	for _, e := range events {
		if err := srv.Send(e); err != nil {
			return err
		}
	}
	return nil
}

func discardLogger() *slog.Logger { return slog.New(slog.NewTextHandler(io.Discard, nil)) }

// parseSSE 提取所有 `event: message` 帧的 data JSON（跳过心跳）。
func parseSSE(body string) []map[string]any {
	var frames []map[string]any
	for _, block := range strings.Split(body, "\n\n") {
		if !strings.Contains(block, "event: message") {
			continue
		}
		for _, line := range strings.Split(block, "\n") {
			if strings.HasPrefix(line, "data: ") {
				var m map[string]any
				if err := json.Unmarshal([]byte(strings.TrimPrefix(line, "data: ")), &m); err == nil {
					frames = append(frames, m)
				}
			}
		}
	}
	return frames
}

// 全链路：POST /runs → dispatch → hub → store(真实 PG) → SSE；再 GET 回放，断言重放==实时。
func TestEndToEnd_RunAndReplay(t *testing.T) {
	dsn := os.Getenv("TEST_PG_DSN")
	if dsn == "" {
		t.Skip("TEST_PG_DSN 未设置，跳过端到端集成测试")
	}
	ctx := context.Background()
	pool, err := store.NewPool(ctx, dsn)
	if err != nil {
		t.Fatalf("NewPool: %v", err)
	}
	t.Cleanup(pool.Close)
	if err := store.Migrate(ctx, pool); err != nil {
		t.Fatalf("Migrate: %v", err)
	}
	if _, err := pool.Exec(ctx, `TRUNCATE events, runs CASCADE`); err != nil {
		t.Fatalf("truncate: %v", err)
	}

	// 进程内 gRPC 假认知面（bufconn）。
	lis := bufconn.Listen(1 << 20)
	gsrv := grpc.NewServer()
	agentv1.RegisterCognitionServiceServer(gsrv, &fakeCog{})
	go func() { _ = gsrv.Serve(lis) }()
	t.Cleanup(gsrv.Stop)
	conn, err := grpc.NewClient("passthrough:///bufnet",
		grpc.WithContextDialer(func(ctx context.Context, _ string) (net.Conn, error) { return lis.DialContext(ctx) }),
		grpc.WithTransportCredentials(insecure.NewCredentials()))
	if err != nil {
		t.Fatalf("grpc client: %v", err)
	}
	client := cognition.NewClient(conn)

	runs := store.NewRunRepository(pool)
	events := store.NewEventRepository(pool)
	hub := stream.NewHub(events, time.Hour, discardLogger())
	d := dispatch.New(4, runs, client, hub, 40, discardLogger())
	router := api.NewRouter(d, runs, events, time.Minute, discardLogger())

	// 1) 发起 run，捕获 SSE。
	req := httptest.NewRequest(http.MethodPost, "/runs", strings.NewReader(`{"query":"算 2*(3+4)","sessionId":"s1"}`))
	req.Header.Set("X-User-Id", "u1")
	rec := httptest.NewRecorder()
	router.ServeHTTP(rec, req)

	runID := rec.Header().Get("X-Run-Id")
	if runID == "" {
		t.Fatalf("missing X-Run-Id")
	}
	live := parseSSE(rec.Body.String())
	if len(live) != 5 {
		t.Fatalf("expected 5 live frames, got %d: %s", len(live), rec.Body.String())
	}
	wantTypes := []string{"tool_thought", "tool_call", "tool_call", "tool_result", "result"}
	for i, f := range live {
		if f["messageType"] != wantTypes[i] {
			t.Fatalf("frame %d type=%v want %s", i, f["messageType"], wantTypes[i])
		}
		if int(f["seq"].(float64)) != i+1 {
			t.Fatalf("frame %d seq=%v", i, f["seq"])
		}
		if f["requestId"] != runID {
			t.Fatalf("frame %d requestId=%v want %s", i, f["requestId"], runID)
		}
	}
	if live[4]["finish"] != true {
		t.Fatalf("last frame finish should be true")
	}
	if live[0]["finish"] == true {
		t.Fatalf("non-result frame finish should be false")
	}

	// 2) run 终态应为 SUCCESS。
	run, err := runs.GetRun(ctx, runID)
	if err != nil || run.Status != store.StatusSuccess {
		t.Fatalf("expected SUCCESS run, got %+v err=%v", run, err)
	}

	// 3) 回放，断言与实时逐帧一致（重放==实时）。
	rreq := httptest.NewRequest(http.MethodGet, "/runs/"+runID+"/events", nil)
	rreq.Header.Set("X-User-Id", "u1")
	rrec := httptest.NewRecorder()
	router.ServeHTTP(rrec, rreq)
	replay := parseSSE(rrec.Body.String())
	if !reflect.DeepEqual(replay, live) {
		t.Fatalf("replay != live\nlive:   %v\nreplay: %v", live, replay)
	}

	// 4) 越权回放应 403。
	freq := httptest.NewRequest(http.MethodGet, "/runs/"+runID+"/events", nil)
	freq.Header.Set("X-User-Id", "intruder")
	frec := httptest.NewRecorder()
	router.ServeHTTP(frec, freq)
	if frec.Code != http.StatusForbidden {
		t.Fatalf("expected 403 for other owner, got %d", frec.Code)
	}
}
