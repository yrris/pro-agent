package event

import (
	"encoding/json"
	"fmt"
	"strconv"

	agentv1 "my-agent/control-plane/internal/genproto/agent/v1"
)

// FromProto 把 gRPC 收到的 proto Event 转换为规范 Envelope。
// seq 由 Python 分配，这里原样带入；Go 侧的单调/无空洞校验在 stream 层做。
func FromProto(p *agentv1.Event) (Envelope, error) {
	if p == nil {
		return Envelope{}, fmt.Errorf("event: nil proto event")
	}
	e := Envelope{
		SchemaVersion: SchemaVersion,
		Seq:           p.GetSeq(),
		RunID:         p.GetRunId(),
		MessageID:     p.GetMessageId(),
		Type:          eventTypeFromProto(p.GetType()),
		TSUnixMs:      p.GetTsUnixMs(),
		IsFinal:       p.GetIsFinal(),
		Finish:        p.GetFinish(),
		Step:          p.GetStep(),
	}
	switch payload := p.GetPayload().(type) {
	case *agentv1.Event_ToolThought: // tool_thought 与 plan_thought 共用此槽
		e.Thought = &ThoughtPayload{
			Text:           payload.ToolThought.GetText(),
			PlannerRoundID: payload.ToolThought.GetPlannerRoundId(),
		}
	case *agentv1.Event_Plan:
		e.Plan = &PlanPayload{
			Title:          payload.Plan.GetTitle(),
			Steps:          payload.Plan.GetSteps(),
			StepStatus:     payload.Plan.GetStepStatus(),
			Notes:          payload.Plan.GetNotes(),
			PlannerRoundID: payload.Plan.GetPlannerRoundId(),
		}
	case *agentv1.Event_Task:
		e.Task = &TaskPayload{Text: payload.Task.GetText()}
	case *agentv1.Event_ToolCall:
		tool, err := toolPayloadFromProto(payload.ToolCall)
		if err != nil {
			return Envelope{}, err
		}
		e.Tool = tool
	case *agentv1.Event_ToolResult:
		tool, err := toolPayloadFromProto(payload.ToolResult)
		if err != nil {
			return Envelope{}, err
		}
		e.Tool = tool
	case *agentv1.Event_Result:
		e.Result = &ResultPayload{
			Text:      payload.Result.GetText(),
			Artifacts: artifactsFromProto(payload.Result.GetArtifactRefs()),
		}
		if u := payload.Result.GetUsage(); u != nil && (u.GetInputTokens() != 0 || u.GetOutputTokens() != 0 || u.GetModelCalls() != 0) {
			e.Result.Usage = &UsagePayload{
				InputTokens: u.GetInputTokens(), OutputTokens: u.GetOutputTokens(), ModelCalls: u.GetModelCalls(),
			}
		}
	case *agentv1.Event_Approval:
		e.Approval = &ApprovalPayload{
			ApprovalID:         payload.Approval.GetApprovalId(),
			ToolName:           payload.Approval.GetToolName(),
			Input:              payload.Approval.GetInput().AsMap(),
			Reason:             payload.Approval.GetReason(),
			PendingToolCallIDs: payload.Approval.GetPendingToolCallIds(),
		}
	}
	return e, nil
}

func toolPayloadFromProto(p *agentv1.ToolPayload) (*ToolPayload, error) {
	if p == nil {
		return nil, fmt.Errorf("event: nil tool payload")
	}
	var input json.RawMessage
	if p.GetInput() != nil {
		raw, err := json.Marshal(p.GetInput().AsMap())
		if err != nil {
			return nil, fmt.Errorf("event: marshal tool input: %w", err)
		}
		input = raw
	}
	return &ToolPayload{
		ToolCallID:    p.GetToolCallId(),
		ToolName:      p.GetToolName(),
		ToolProvider:  p.GetToolProvider(),
		Status:        toolStatusFromProto(p.GetStatus()),
		DispatchIndex: p.GetDispatchIndex(),
		Input:         input,
		ToolResult:    p.GetToolResult(),
		Summary:       p.GetSummary(),
		ErrorMsg:      p.GetErrorMsg(),
		Artifacts:     artifactsFromProto(p.GetArtifactRefs()),
	}, nil
}

func artifactsFromProto(in []*agentv1.ArtifactRef) []ArtifactRef {
	if len(in) == 0 {
		return nil
	}
	out := make([]ArtifactRef, 0, len(in))
	for _, a := range in {
		out = append(out, ArtifactRef{
			ResourceKey: a.GetResourceKey(),
			Name:        a.GetName(),
			PreviewURL:  a.GetPreviewUrl(),
			DownloadURL: a.GetDownloadUrl(),
			FileName:    a.GetFileName(),
			MimeType:    a.GetMimeType(),
			Size:        a.GetSize(),
			Missing:     a.GetMissing(),
		})
	}
	return out
}

func eventTypeFromProto(t agentv1.EventType) MessageType {
	switch t {
	case agentv1.EventType_EVENT_TYPE_TOOL_THOUGHT:
		return TypeToolThought
	case agentv1.EventType_EVENT_TYPE_TOOL_CALL:
		return TypeToolCall
	case agentv1.EventType_EVENT_TYPE_TOOL_RESULT:
		return TypeToolResult
	case agentv1.EventType_EVENT_TYPE_RESULT:
		return TypeResult
	case agentv1.EventType_EVENT_TYPE_PLAN_THOUGHT:
		return TypePlanThought
	case agentv1.EventType_EVENT_TYPE_PLAN:
		return TypePlan
	case agentv1.EventType_EVENT_TYPE_TASK:
		return TypeTask
	case agentv1.EventType_EVENT_TYPE_APPROVAL_REQUEST:
		return TypeApprovalRequest
	default:
		return ""
	}
}

func toolStatusFromProto(s agentv1.ToolCallStatus) ToolStatus {
	switch s {
	case agentv1.ToolCallStatus_TOOL_CALL_STATUS_RUNNING:
		return StatusRunning
	case agentv1.ToolCallStatus_TOOL_CALL_STATUS_SUCCESS:
		return StatusSuccess
	case agentv1.ToolCallStatus_TOOL_CALL_STATUS_FAILED:
		return StatusFailed
	default:
		return ""
	}
}

// sseFrame 是浏览器经 SSE 收到的 JSON 形状，字段名兼容原 AgentResponse。
type sseFrame struct {
	RequestID    string           `json:"requestId"`
	MessageID    string           `json:"messageId"`
	Seq          uint64           `json:"seq"`
	MessageType  string           `json:"messageType"`
	MessageTime  string           `json:"messageTime"`
	IsFinal      bool             `json:"isFinal"`
	Finish       bool             `json:"finish"`
	ToolThought  string           `json:"toolThought,omitempty"`
	ToolResult   *sseToolResult   `json:"toolResult,omitempty"`
	Result       string           `json:"result,omitempty"`
	PlanThought  string           `json:"planThought,omitempty"`
	Plan         *planFrame       `json:"plan,omitempty"`
	Task         string           `json:"task,omitempty"`
	ResultMap    map[string]any   `json:"resultMap,omitempty"`
	ArtifactRefs []ArtifactRef    `json:"artifactRefs,omitempty"`
	Approval     *ApprovalPayload `json:"approval,omitempty"` // M11 HITL
}

// planFrame 是 SSE 里 plan 对象的形状（plannerRoundId 放 resultMap，不在此）。
type planFrame struct {
	Title      string   `json:"title"`
	Steps      []string `json:"steps"`
	StepStatus []string `json:"stepStatus"`
	Notes      []string `json:"notes"`
}

type sseToolResult struct {
	ToolName   string          `json:"toolName"`
	ToolParam  json.RawMessage `json:"toolParam,omitempty"`
	ToolResult string          `json:"toolResult"`
	ToolCallID string          `json:"toolCallId"`
}

// ToSSEFrame 把 Envelope 渲染成浏览器 SSE 帧的 JSON（data: 部分）。
// 实时与回放共用此函数，是“重放=实时”不变量的唯一渲染点。
func ToSSEFrame(e Envelope) ([]byte, error) {
	frame := sseFrame{
		RequestID:   e.RunID,
		MessageID:   e.MessageID,
		Seq:         e.Seq,
		MessageType: string(e.Type),
		MessageTime: strconv.FormatInt(e.TSUnixMs, 10),
		IsFinal:     e.IsFinal,
		Finish:      e.Finish,
	}
	switch e.Type {
	case TypeToolThought:
		if e.Thought != nil {
			frame.ToolThought = e.Thought.Text
		}
	case TypeToolCall:
		if e.Tool != nil {
			frame.ResultMap = map[string]any{
				"status":        string(e.Tool.Status),
				"toolName":      e.Tool.ToolName,
				"toolCallId":    e.Tool.ToolCallID,
				"toolProvider":  e.Tool.ToolProvider,
				"dispatchIndex": e.Tool.DispatchIndex,
				"summary":       e.Tool.Summary,
			}
			if len(e.Tool.Input) > 0 {
				frame.ResultMap["input"] = json.RawMessage(e.Tool.Input)
			}
			if e.Tool.ErrorMsg != "" {
				frame.ResultMap["errorMsg"] = e.Tool.ErrorMsg
			}
		}
	case TypeToolResult:
		if e.Tool != nil {
			frame.ToolResult = &sseToolResult{
				ToolName:   e.Tool.ToolName,
				ToolParam:  e.Tool.Input,
				ToolResult: e.Tool.ToolResult,
				ToolCallID: e.Tool.ToolCallID,
			}
			frame.ArtifactRefs = e.Tool.Artifacts
		}
	case TypeResult:
		if e.Result != nil {
			frame.Result = e.Result.Text
			frame.ArtifactRefs = e.Result.Artifacts
		}
	case TypePlanThought:
		if e.Thought != nil {
			frame.PlanThought = e.Thought.Text
			if e.Thought.PlannerRoundID != "" {
				frame.ResultMap = map[string]any{"plannerRoundId": e.Thought.PlannerRoundID}
			}
		}
	case TypePlan:
		if e.Plan != nil {
			frame.Plan = &planFrame{
				Title:      e.Plan.Title,
				Steps:      e.Plan.Steps,
				StepStatus: e.Plan.StepStatus,
				Notes:      e.Plan.Notes,
			}
			if e.Plan.PlannerRoundID != "" {
				frame.ResultMap = map[string]any{"plannerRoundId": e.Plan.PlannerRoundID}
			}
		}
	case TypeTask:
		if e.Task != nil {
			frame.Task = e.Task.Text
		}
	case TypeApprovalRequest:
		if e.Approval != nil {
			frame.Approval = e.Approval // 结构体直接入帧（camelCase json tag 已定）
		}
	}
	return json.Marshal(frame)
}

// MarshalPayload 序列化 Envelope 的活跃 payload，用于 events 表的 payload JSONB 列。
// run_id/seq/type 等作为列单独存，故这里只存类型相关的 body。
func (e Envelope) MarshalPayload() ([]byte, error) {
	switch e.Type {
	case TypeToolThought, TypePlanThought:
		return json.Marshal(e.Thought)
	case TypeToolCall, TypeToolResult:
		return json.Marshal(e.Tool)
	case TypeResult:
		return json.Marshal(e.Result)
	case TypePlan:
		return json.Marshal(e.Plan)
	case TypeTask:
		return json.Marshal(e.Task)
	case TypeApprovalRequest:
		return json.Marshal(e.Approval)
	default:
		return nil, fmt.Errorf("event: cannot marshal payload for type %q", e.Type)
	}
}

// UnmarshalPayload 从 payload JSONB 重建 Envelope 的活跃 payload。
// 调用方需先设置 e.Type（来自 message_type 列）。
func (e *Envelope) UnmarshalPayload(data []byte) error {
	switch e.Type {
	case TypeToolThought, TypePlanThought:
		var p ThoughtPayload
		if err := json.Unmarshal(data, &p); err != nil {
			return err
		}
		e.Thought = &p
	case TypeToolCall, TypeToolResult:
		var p ToolPayload
		if err := json.Unmarshal(data, &p); err != nil {
			return err
		}
		e.Tool = &p
	case TypeResult:
		var p ResultPayload
		if err := json.Unmarshal(data, &p); err != nil {
			return err
		}
		e.Result = &p
	case TypePlan:
		var p PlanPayload
		if err := json.Unmarshal(data, &p); err != nil {
			return err
		}
		e.Plan = &p
	case TypeTask:
		var p TaskPayload
		if err := json.Unmarshal(data, &p); err != nil {
			return err
		}
		e.Task = &p
	case TypeApprovalRequest:
		var p ApprovalPayload
		if err := json.Unmarshal(data, &p); err != nil {
			return err
		}
		e.Approval = &p
	default:
		return fmt.Errorf("event: cannot unmarshal payload for type %q", e.Type)
	}
	return nil
}
