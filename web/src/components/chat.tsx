import { memo } from "react";
import type { PlanView as PlanViewT, RunState, ToolCallView } from "../lib/sse/frameTypes";
import { Collapsible, Markdown, ProviderTag, ToolStatusBadge } from "./common";

function UserBubble({ text }: { text: string }) {
  return (
    <div className="flex justify-end">
      <div className="max-w-[80%] rounded-2xl rounded-br-sm bg-cyan-600/25 px-4 py-2 text-sm text-cyan-50">
        {text}
      </div>
    </div>
  );
}

function ThoughtBlock({ kind, text }: { kind: "tool" | "plan"; text: string }) {
  if (!text.trim()) return null;
  const label = kind === "plan" ? "规划思考" : "思考";
  return (
    <Collapsible title={<span className="text-slate-400">💭 {label}</span>} defaultOpen>
      <div className="whitespace-pre-wrap text-slate-300">{text}</div>
    </Collapsible>
  );
}

function PlanCard({ plan }: { plan: PlanViewT }) {
  const done = plan.stepStatus.filter((s) => s === "completed").length;
  const pct = plan.steps.length ? Math.round((done / plan.steps.length) * 100) : 0;
  return (
    <div className="rounded-xl border border-indigo-500/30 bg-indigo-500/[0.06] p-3">
      <div className="mb-2 flex items-center gap-2">
        <span className="text-indigo-300">📋 {plan.title || "计划"}</span>
        <span className="text-xs text-slate-400">
          {done}/{plan.steps.length}
        </span>
        <div className="ml-auto h-1.5 w-24 overflow-hidden rounded-full bg-white/10">
          <div className="h-full bg-indigo-400" style={{ width: `${pct}%` }} />
        </div>
      </div>
      <ol className="space-y-1">
        {plan.steps.map((step, i) => {
          const st = plan.stepStatus[i] ?? "not_started";
          const icon = st === "completed" ? "✅" : st === "in_progress" ? "⏳" : "⬜";
          return (
            <li key={i} className={`flex gap-2 text-sm ${st === "in_progress" ? "text-indigo-200" : "text-slate-300"}`}>
              <span>{icon}</span>
              <span className="min-w-0 flex-1">{step}</span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

function TaskChip({ text }: { text: string }) {
  return (
    <div className="inline-flex items-center gap-2 rounded-lg border border-amber-500/25 bg-amber-500/[0.06] px-3 py-1.5 text-sm text-amber-100">
      <span>🧩 子任务</span>
      <span className="text-slate-300">{text}</span>
    </div>
  );
}

function ToolCard({ call, resultText }: { call: ToolCallView; resultText?: string }) {
  const title = (
    <span className="flex items-center gap-2">
      <span className="text-slate-200">🔧 {call.toolName || "tool"}</span>
      <ProviderTag provider={call.toolProvider} />
    </span>
  );
  return (
    <Collapsible title={title} right={<ToolStatusBadge status={call.status} />} defaultOpen={call.status !== "success"}>
      {call.summary && <div className="mb-2 text-slate-400">{call.summary}</div>}
      {call.input != null && (
        <div className="mb-2">
          <div className="mb-1 text-xs text-slate-500">入参</div>
          <pre className="overflow-auto rounded-lg bg-black/40 p-2 text-xs text-cyan-200">
            {JSON.stringify(call.input, null, 2)}
          </pre>
        </div>
      )}
      {call.errorMsg && <div className="mb-2 text-rose-300">错误：{call.errorMsg}</div>}
      {resultText != null && (
        <div>
          <div className="mb-1 text-xs text-slate-500">观察结果</div>
          <pre className="max-h-64 overflow-auto whitespace-pre-wrap rounded-lg bg-black/30 p-2 text-xs text-slate-200">
            {resultText}
          </pre>
        </div>
      )}
    </Collapsible>
  );
}

function Conclusion({ text }: { text: string }) {
  return (
    <div className="rounded-2xl rounded-bl-sm border border-emerald-500/25 bg-emerald-500/[0.05] px-4 py-3">
      <div className="mb-1 text-xs text-emerald-300">结论</div>
      <Markdown>{text || "（空）"}</Markdown>
    </div>
  );
}

// 预留：Proactive/审批卡片位（当前后端不发此类事件，占位不渲染）。
export function ApprovalCardSlot() {
  return null;
}

// memo：多轮 timeline 里历史轮的 props 引用稳定，流式期间只有 live 轮重渲，
// 每帧渲染成本不随会话长度增长。
export const MessageList = memo(function MessageList({ state, query }: { state: RunState; query?: string }) {
  const resultByCall = new Map(state.toolResults.map((r) => [r.toolCallId, r.text]));
  return (
    <div className="space-y-3">
      {query && <UserBubble text={query} />}
      {state.order.map((entry, idx) => {
        const k = `${entry.kind}:${entry.key}:${idx}`;
        switch (entry.kind) {
          case "thought": {
            const t = state.thoughts[entry.key];
            return t ? <ThoughtBlock key={k} kind={t.kind} text={t.text} /> : null;
          }
          case "plan": {
            const round = state.plannerRounds.find((r) => (r.plannerRoundId ?? "plan") === entry.key) ?? state.plan;
            return round ? <PlanCard key={k} plan={round} /> : null;
          }
          case "task":
            return <TaskChip key={k} text={state.tasks[Number(entry.key)]?.text ?? ""} />;
          case "toolCall": {
            const call = state.toolCalls[entry.key];
            return call ? <ToolCard key={k} call={call} resultText={resultByCall.get(call.toolCallId)} /> : null;
          }
          case "result":
            return state.result ? <Conclusion key={k} text={state.result.text} /> : null;
          case "toolResult":
            return null; // 观察结果已并入对应 ToolCard
          default:
            return null;
        }
      })}
      {state.unknown.length > 0 && (
        <div className="text-xs text-slate-500">（{state.unknown.length} 条暂不支持的事件，已忽略）</div>
      )}
    </div>
  );
});
