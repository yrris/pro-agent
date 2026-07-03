import { memo, useState } from "react";
import { Check, Copy, Paperclip } from "lucide-react";
import type { AttachmentRef } from "../lib/api/client";
import type { ApprovalView, PlanView as PlanViewT, RunState, ToolCallView } from "../lib/sse/frameTypes";
import { Collapsible, Markdown, ProviderTag, ToolStatusBadge } from "./common";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";

function UserBubble({ text }: { text: string }) {
  return (
    <div className="flex justify-end">
      <div className="max-w-[80%] rounded-2xl rounded-br-sm bg-white/[0.07] px-4 py-2 text-sm text-stone-100">
        {text}
      </div>
    </div>
  );
}

function ThoughtBlock({ kind, text, running }: { kind: "tool" | "plan"; text: string; running?: boolean }) {
  if (!text.trim()) return null;
  const label = kind === "plan" ? "规划思考" : "思考";
  // 过程可见但不喧宾夺主：流式期间展开跟读，run 结束折叠为一行摘要
  //（折叠/展开由 MessageList 的 key 带 running 标志触发重挂载实现）。
  const excerpt = text.trim().split("\n")[0].slice(0, 42);
  return (
    <Collapsible
      title={
        <span className="min-w-0 text-stone-400">
          💭 {label}
          {!running && <span className="ml-1 text-xs text-stone-500">· {excerpt}…</span>}
        </span>
      }
      defaultOpen={!!running}
    >
      <div className="whitespace-pre-wrap text-stone-300">{text}</div>
    </Collapsible>
  );
}

function PlanCard({ plan }: { plan: PlanViewT }) {
  const done = plan.stepStatus.filter((s) => s === "completed").length;
  const pct = plan.steps.length ? Math.round((done / plan.steps.length) * 100) : 0;
  return (
    <Card className="gap-0 border-indigo-500/30 bg-indigo-500/[0.06] py-3">
      <CardContent className="px-3">
        <div className="mb-2 flex items-center gap-2">
          <span className="text-indigo-300">📋 {plan.title || "计划"}</span>
          <span className="text-xs text-stone-400">
            {done}/{plan.steps.length}
          </span>
          <Progress value={pct} className="ml-auto h-1.5 w-24 bg-white/10 [&>[data-slot=progress-indicator]]:bg-indigo-400" />
        </div>
        <ol className="space-y-1">
          {plan.steps.map((step, i) => {
            const st = plan.stepStatus[i] ?? "not_started";
            const icon = st === "completed" ? "✅" : st === "in_progress" ? "⏳" : "⬜";
            return (
              <li key={i} className={`flex gap-2 text-sm ${st === "in_progress" ? "text-indigo-200" : "text-stone-300"}`}>
                <span>{icon}</span>
                <span className="min-w-0 flex-1">{step}</span>
              </li>
            );
          })}
        </ol>
      </CardContent>
    </Card>
  );
}

function TaskChip({ text }: { text: string }) {
  return (
    <Badge
      variant="outline"
      className="gap-2 rounded-lg border-amber-500/25 bg-amber-500/[0.06] px-3 py-1.5 text-sm font-normal text-amber-100"
    >
      <span>🧩 子任务</span>
      <span className="text-stone-300">{text}</span>
    </Badge>
  );
}

function ToolCard({ call, resultText }: { call: ToolCallView; resultText?: string }) {
  const title = (
    <span className="flex items-center gap-2">
      <span className="text-stone-200">🔧 {call.toolName || "tool"}</span>
      <ProviderTag provider={call.toolProvider} />
    </span>
  );
  return (
    <Collapsible title={title} right={<ToolStatusBadge status={call.status} />} defaultOpen={call.status !== "success"}>
      {call.summary && <div className="mb-2 text-stone-400">{call.summary}</div>}
      {call.input != null && (
        <div className="mb-2">
          <div className="mb-1 text-xs text-stone-500">入参</div>
          <pre className="overflow-auto rounded-lg bg-black/40 p-2 text-xs text-stone-200">
            {JSON.stringify(call.input, null, 2)}
          </pre>
        </div>
      )}
      {call.errorMsg && <div className="mb-2 text-rose-300">错误：{call.errorMsg}</div>}
      {resultText != null && (
        <div>
          <div className="mb-1 text-xs text-stone-500">观察结果</div>
          <pre className="max-h-64 overflow-auto whitespace-pre-wrap rounded-lg bg-black/30 p-2 text-xs text-stone-200">
            {resultText}
          </pre>
        </div>
      )}
    </Collapsible>
  );
}

function Conclusion({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* 剪贴板被拒绝（非 https 等）：静默 */
    }
  };
  return (
    <Card className="gap-0 rounded-2xl rounded-bl-sm border-emerald-500/25 bg-emerald-500/[0.05] px-4 py-3">
      <div className="mb-1 text-xs text-emerald-300">结论</div>
      <Markdown>{text || "（空）"}</Markdown>
      <div className="mt-2 flex justify-end border-t border-white/5 pt-1.5">
        <button
          onClick={() => void copy()}
          title="复制结论"
          className="flex items-center gap-1 text-xs text-stone-500 transition-colors hover:text-foreground"
        >
          {copied ? <Check className="size-3.5 text-emerald-400" /> : <Copy className="size-3.5" />}
          {copied ? "已复制" : "复制"}
        </button>
      </div>
    </Card>
  );
}

// M11 HITL：人工审批卡。live/最后一轮可操作（onDecide 传入且 pending）；
// 其余（历史回放/已决议）只读展示。决议后按钮即禁用（本地补丁 + 后端幂等校验双保险）。
export function ApprovalCard({
  approval,
  onDecide,
}: {
  approval: ApprovalView;
  // 返回决议是否成功——失败（网络/429/无 pending）时重置 busy 让卡可重试。
  onDecide?: (approvalId: string, approved: boolean, comment?: string) => Promise<boolean> | void;
}) {
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const pending = approval.status === "pending";
  const actionable = pending && !!onDecide && !busy;
  const decide = async (approved: boolean) => {
    if (!onDecide) return;
    setBusy(true);
    const ok = await onDecide(approval.approvalId, approved, comment.trim() || undefined);
    if (ok === false) setBusy(false); // 失败复位（成功时本轮已归档/替换，busy 随卸载消失）
  };
  return (
    <Card className="gap-0 border-amber-500/30 bg-amber-500/[0.06] px-4 py-3">
      <div className="mb-1 flex items-center gap-2 text-sm">
        <span className="text-amber-300">🖐 需要人工审批</span>
        <span className="text-stone-300">{approval.toolName}</span>
        {approval.status === "approved" && <Badge className="bg-emerald-500/15 text-emerald-300">已批准</Badge>}
        {approval.status === "rejected" && <Badge className="bg-rose-500/15 text-rose-300">已拒绝</Badge>}
        {pending && !onDecide && <Badge className="bg-amber-500/15 text-amber-300">等待决议</Badge>}
      </div>
      {approval.reason && <div className="mb-2 text-xs text-stone-400">{approval.reason}</div>}
      {approval.input != null && (
        <pre className="mb-2 overflow-auto rounded-lg bg-black/30 p-2 text-xs text-stone-200">
          {JSON.stringify(approval.input, null, 2)}
        </pre>
      )}
      {actionable && (
        <div className="flex items-center gap-2">
          <input
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            placeholder="备注（可选）"
            className="min-w-0 flex-1 rounded-lg border bg-transparent px-2 py-1 text-xs text-stone-200 outline-none focus:border-stone-500"
          />
          <button
            onClick={() => void decide(true)}
            className="rounded-lg bg-emerald-600/80 px-3 py-1 text-xs text-white transition-colors hover:bg-emerald-600"
          >
            批准
          </button>
          <button
            onClick={() => void decide(false)}
            className="rounded-lg bg-rose-600/70 px-3 py-1 text-xs text-white transition-colors hover:bg-rose-600"
          >
            拒绝
          </button>
        </div>
      )}
      {busy && <div className="text-xs text-stone-500 pulse-dot">● 正在提交决议…</div>}
    </Card>
  );
}

// 发送轮的附件 chips（挂在用户气泡下方；历史回放轮无附件元数据=已知限制）。
function AttachmentRow({ attachments }: { attachments?: AttachmentRef[] }) {
  if (!attachments?.length) return null;
  return (
    <div className="flex flex-wrap justify-end gap-1.5">
      {attachments.map((a) => (
        <Badge key={a.resourceKey} variant="outline" className="gap-1 font-normal text-stone-400">
          <Paperclip className="size-3" />
          <span className="max-w-40 truncate">{a.fileName}</span>
        </Badge>
      ))}
    </div>
  );
}

// memo：多轮 timeline 里历史轮的 props 引用稳定，流式期间只有 live 轮重渲，
// 每帧渲染成本不随会话长度增长。
export const MessageList = memo(function MessageList({
  state,
  query,
  attachments,
  running,
  onApprovalDecision,
}: {
  state: RunState;
  query?: string;
  attachments?: AttachmentRef[];
  running?: boolean;
  // M11：仅 live 轮/最后一轮传入（历史回放只读）；带上本轮 runId（恢复不依赖 liveRef）。
  onApprovalDecision?: (
    runId: string,
    approvalId: string,
    approved: boolean,
    comment?: string,
  ) => Promise<boolean> | void;
}) {
  const resultByCall = new Map(state.toolResults.map((r) => [r.toolCallId, r.text]));
  return (
    <div className="space-y-3">
      {query && <UserBubble text={query} />}
      <AttachmentRow attachments={attachments} />
      {state.order.map((entry, idx) => {
        const k = `${entry.kind}:${entry.key}:${idx}`;
        switch (entry.kind) {
          case "thought": {
            const t = state.thoughts[entry.key];
            // key 带 running：run 结束时重挂载 → 未受控 Collapsible 从展开态收拢为摘要行。
            return t ? <ThoughtBlock key={`${k}:${running ? "r" : "d"}`} kind={t.kind} text={t.text} running={running} /> : null;
          }
          case "plan": {
            const round = state.plannerRounds.find((r) => (r.plannerRoundId ?? "plan") === entry.key) ?? state.plan;
            return round ? <PlanCard key={k} plan={round} /> : null;
          }
          case "task":
            return <TaskChip key={k} text={state.tasks[Number(entry.key)]?.text ?? ""} />;
          case "toolCall": {
            const call = state.toolCalls[entry.key];
            // key 带成功标志：工具成功那一帧重挂载 → 自动折叠（运行中/失败保持展开）。
            return call ? (
              <ToolCard
                key={`${k}:${call.status === "success" ? "s" : "r"}`}
                call={call}
                resultText={resultByCall.get(call.toolCallId)}
              />
            ) : null;
          }
          case "approval": {
            const a = state.approvals[entry.key];
            if (!a) return null;
            const onDecide = onApprovalDecision
              ? (aid: string, ap: boolean, c?: string) => onApprovalDecision(state.runId, aid, ap, c)
              : undefined;
            return <ApprovalCard key={k} approval={a} onDecide={onDecide} />;
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
        <div className="text-xs text-stone-500">（{state.unknown.length} 条暂不支持的事件，已忽略）</div>
      )}
    </div>
  );
});
