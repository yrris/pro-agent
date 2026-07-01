// SSE 帧与归并后视图模型。字段名逐字对齐 control-plane/internal/event/codec.go 的 ToSSEFrame。

export type MessageType =
  | "tool_thought"
  | "tool_call"
  | "tool_result"
  | "result"
  | "plan_thought"
  | "plan"
  | "task"
  | "heartbeat";

export interface ArtifactRef {
  resourceKey: string;
  name: string;
  previewUrl: string;
  downloadUrl: string;
  fileName: string;
  mimeType: string;
  size: number;
  missing: boolean;
}

export interface ToolResultFrame {
  toolName: string;
  toolParam?: unknown;
  toolResult: string;
  toolCallId: string;
}

export interface PlanFrame {
  title: string;
  steps: string[];
  stepStatus: string[];
  notes: string[];
}

export interface ResultMap {
  status?: string;
  toolName?: string;
  toolCallId?: string;
  toolProvider?: string;
  dispatchIndex?: number;
  summary?: string;
  input?: unknown;
  errorMsg?: string;
  plannerRoundId?: string;
}

export interface SseFrame {
  requestId: string;
  messageId: string;
  seq: number;
  messageType: MessageType;
  messageTime: string;
  isFinal: boolean;
  finish: boolean;
  toolThought?: string;
  toolResult?: ToolResultFrame;
  result?: string;
  planThought?: string;
  plan?: PlanFrame;
  task?: string;
  resultMap?: ResultMap;
  artifactRefs?: ArtifactRef[];
}

// —— 归并后的视图模型（组件只读） ——
export interface ThoughtView {
  kind: "tool" | "plan";
  text: string;
  plannerRoundId?: string;
}

export interface ToolCallView {
  toolCallId: string;
  toolName: string;
  toolProvider: string;
  status: string; // running | success | failed
  dispatchIndex: number;
  summary: string;
  input?: unknown;
  errorMsg?: string;
}

export interface ToolResultView {
  toolCallId: string;
  toolName: string;
  text: string;
}

export interface PlanView {
  title: string;
  steps: string[];
  stepStatus: string[];
  notes: string[];
  plannerRoundId?: string;
}

export interface TaskView {
  text: string;
}

export type OrderKind = "thought" | "toolCall" | "toolResult" | "plan" | "task" | "result";
export interface OrderEntry {
  kind: OrderKind;
  key: string;
}

export interface RunState {
  runId: string;
  thoughts: Record<string, ThoughtView>;
  toolCalls: Record<string, ToolCallView>;
  toolResults: ToolResultView[];
  plan?: PlanView;
  plannerRounds: PlanView[];
  tasks: TaskView[];
  result?: { text: string; artifacts: ArtifactRef[] };
  artifacts: ArtifactRef[];
  finished: boolean;
  order: OrderEntry[];
  unknown: SseFrame[];
}

export function emptyRunState(runId = ""): RunState {
  return {
    runId,
    thoughts: {},
    toolCalls: {},
    toolResults: [],
    plannerRounds: [],
    tasks: [],
    artifacts: [],
    finished: false,
    order: [],
    unknown: [],
  };
}
