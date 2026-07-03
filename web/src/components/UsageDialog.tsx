import { useEffect, useState } from "react";
import { getUsageStats, type UsageReport } from "../lib/api/client";
import { AGENT_TYPES } from "../config";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";

function fmt(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

function agentLabel(v: string): string {
  return AGENT_TYPES.find((a) => a.value === v)?.label ?? v;
}

// 成本与用量面板（M11）：runs 账本聚合的纯读投影；纯 CSS 条形，无图表库。
// token 数为模型上报的 usage_metadata 累计；换算金额留给用户按各家单价自行估（多 provider 单价不一）。
export function UsageDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (v: boolean) => void }) {
  const [report, setReport] = useState<UsageReport | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!open) return;
    let alive = true;
    setReport(null);
    setFailed(false);
    getUsageStats(30)
      .then((r) => alive && setReport(r))
      .catch(() => alive && setFailed(true));
    return () => {
      alive = false;
    };
  }, [open]);

  const maxDay = Math.max(1, ...(report?.daily.map((d) => d.inputTokens + d.outputTokens) ?? [1]));

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogTitle>用量与成本（近 30 天）</DialogTitle>
        <DialogDescription>
          事件账本聚合的只读投影；token 为模型上报的累计值（中断/超时的 run 不计）。
        </DialogDescription>
        {failed && <div className="text-sm text-rose-400">加载失败，请稍后重试。</div>}
        {!report && !failed && (
          <div className="space-y-2">
            <Skeleton className="h-14 w-full" />
            <Skeleton className="h-24 w-full" />
          </div>
        )}
        {report && (
          <div className="space-y-4">
            <div className="grid grid-cols-4 gap-2 text-center">
              {[
                ["运行次数", fmt(report.totals.runs)],
                ["输入 tokens", fmt(report.totals.inputTokens)],
                ["输出 tokens", fmt(report.totals.outputTokens)],
                ["模型调用", fmt(report.totals.modelCalls)],
              ].map(([label, value]) => (
                <div key={label} className="rounded-xl border bg-card px-2 py-3">
                  <div className="text-lg font-semibold text-foreground">{value}</div>
                  <div className="text-[10px] text-stone-500">{label}</div>
                </div>
              ))}
            </div>

            {report.daily.length > 0 && (
              <div>
                <div className="mb-1.5 text-xs text-stone-500">每日 token（输入+输出）</div>
                <div className="flex h-20 items-end gap-1">
                  {report.daily.map((d) => (
                    <div
                      key={d.date}
                      title={`${d.date}：${fmt(d.inputTokens)} 入 / ${fmt(d.outputTokens)} 出（${d.runs} 次）`}
                      className="min-w-2 flex-1 rounded-t bg-primary/70 transition-colors hover:bg-primary"
                      style={{ height: `${Math.max(6, ((d.inputTokens + d.outputTokens) / maxDay) * 100)}%` }}
                    />
                  ))}
                </div>
              </div>
            )}

            {report.byAgent.length > 0 && (
              <div className="space-y-1">
                <div className="text-xs text-stone-500">按模式</div>
                {report.byAgent.map((a) => (
                  <div key={a.agentType} className="flex items-center gap-2 text-sm">
                    <span className="w-20 shrink-0 text-stone-300">{agentLabel(a.agentType)}</span>
                    <span className="text-xs text-stone-500">
                      {a.runs} 次 · {fmt(a.inputTokens)} 入 / {fmt(a.outputTokens)} 出
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
