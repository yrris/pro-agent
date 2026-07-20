package event

// NUL 净化（22P05 回归）：web_fetch 抓到含 NUL 页面曾毒死整个 run。
// PostgreSQL jsonb 拒绝字符串中的 U+0000 转义（"unsupported Unicode escape sequence"）；
// FromProto 入口净化（实时/账本同源，replay ≡ live 保持），MarshalPayload 出口兜底
//（覆盖未逐字段净化的生产者，如 Approval.Input map）。

import (
	"bytes"
	"testing"

	agentv1 "my-agent/control-plane/internal/genproto/agent/v1"
)

// nulEscape 是 JSON 里 NUL 的转义形态（6 个 ASCII 字符），jsonb 落库的违禁项。
var nulEscape = []byte{'\\', 'u', '0', '0', '0', '0'}

func TestFromProtoSanitizesNUL(t *testing.T) {
	ev := &agentv1.Event{
		RunId: "r", Seq: 1, MessageId: "m",
		Type: agentv1.EventType_EVENT_TYPE_TOOL_RESULT,
		Payload: &agentv1.Event_ToolResult{ToolResult: &agentv1.ToolPayload{
			ToolCallId: "c1", ToolName: "web_fetch",
			ToolResult: "前\x00后", Summary: "s\x00",
		}},
	}
	env, err := FromProto(ev)
	if err != nil {
		t.Fatalf("FromProto: %v", err)
	}
	if env.Tool.ToolResult != "前�后" || env.Tool.Summary != "s�" {
		t.Fatalf("NUL not sanitized: %q %q", env.Tool.ToolResult, env.Tool.Summary)
	}
	payload, err := env.MarshalPayload()
	if err != nil {
		t.Fatalf("MarshalPayload: %v", err)
	}
	if bytes.Contains(payload, nulEscape) {
		t.Fatalf("payload still contains NUL escape: %s", payload)
	}
}

func TestMarshalPayloadSanitizesNULFallback(t *testing.T) {
	env := Envelope{
		Type:   TypeResult,
		Result: &ResultPayload{Text: "x\x00y"}, // 绕过 FromProto 直接构造（兜底路径）
	}
	payload, err := env.MarshalPayload()
	if err != nil {
		t.Fatalf("MarshalPayload: %v", err)
	}
	if bytes.Contains(payload, nulEscape) {
		t.Fatalf("payload still contains NUL escape: %s", payload)
	}
	if !bytes.Contains(payload, []byte("x�y")) {
		t.Fatalf("not replaced with U+FFFD: %s", payload)
	}
}
