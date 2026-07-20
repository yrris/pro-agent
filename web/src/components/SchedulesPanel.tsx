import { useCallback, useEffect, useState } from "react";
import { CalendarClock, Loader2, Plus, RotateCw, Trash2 } from "lucide-react";
import { toast } from "sonner";
import {
  createSchedule,
  deleteSchedule,
  listSchedules,
  toggleSchedule,
  type ScheduleItem,
} from "../lib/api/client";
import { AGENT_TYPES } from "../config";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";

const INTERVALS = [
  { value: 300, label: "每 5 分钟" },
  { value: 900, label: "每 15 分钟" },
  { value: 3600, label: "每小时" },
  { value: 21600, label: "每 6 小时" },
  { value: 86400, label: "每天" },
] as const;

function intervalLabel(s: number): string {
  return INTERVALS.find((i) => i.value === s)?.label ?? `每 ${s} 秒`;
}

// 定时任务页签（M11 Proactive）：创建/列表/开关/删除。产出走既有 run/会话链路——
// 触发的 run 出现在对应会话里（sched-* 固定会话，thread 记忆延续）。
export function SchedulesPanel({ onOpenSession }: { onOpenSession?: (sessionId: string) => void }) {
  const [items, setItems] = useState<ScheduleItem[] | null>(null);
  const [creating, setCreating] = useState(false);
  const [busy, setBusy] = useState(false);
  const [query, setQuery] = useState("");
  const [agentType, setAgentType] = useState("react");
  const [interval, setIntervalS] = useState(3600);
  const [confirming, setConfirming] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setItems(await listSchedules());
    } catch {
      setItems([]);
      toast.error("定时任务加载失败");
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const create = async () => {
    if (!query.trim()) return;
    setBusy(true);
    try {
      await createSchedule({ query: query.trim(), agentType, intervalSeconds: interval });
      toast.success("定时任务已创建");
      setQuery("");
      setCreating(false);
      await refresh();
    } catch {
      toast.error("创建失败");
    } finally {
      setBusy(false);
    }
  };

  const onDelete = async (it: ScheduleItem) => {
    if (confirming !== it.scheduleId) {
      setConfirming(it.scheduleId);
      setTimeout(() => setConfirming((c) => (c === it.scheduleId ? null : c)), 3000);
      return;
    }
    setConfirming(null);
    try {
      await deleteSchedule(it.scheduleId);
      await refresh();
    } catch {
      toast.error("删除失败");
    }
  };

  const onToggle = async (it: ScheduleItem) => {
    try {
      await toggleSchedule(it.scheduleId, !it.enabled);
      await refresh();
    } catch {
      toast.error("更新失败");
    }
  };

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-1.5 border-b px-3 py-2">
        <span className="min-w-0 flex-1 truncate text-xs text-muted-foreground/70">定时任务（Proactive）</span>
        <Button
          variant="ghost"
          size="icon"
          onClick={() => setCreating((v) => !v)}
          aria-label="新建定时任务"
          className="size-7 text-muted-foreground hover:text-foreground"
        >
          <Plus />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          onClick={() => void refresh()}
          aria-label="刷新"
          className="size-7 text-muted-foreground hover:text-foreground"
        >
          <RotateCw />
        </Button>
      </div>

      {creating && (
        <div className="space-y-2 border-b p-3">
          <Textarea
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            rows={2}
            placeholder="定时执行的任务，例如：检查我的知识库里有没有关于 X 的新结论并总结"
            className="min-h-0 resize-none text-sm"
          />
          <div className="flex items-center gap-1.5">
            <Select value={String(interval)} onValueChange={(v) => setIntervalS(Number(v))}>
              <SelectTrigger size="sm" className="flex-1">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {INTERVALS.map((i) => (
                  <SelectItem key={i.value} value={String(i.value)}>
                    {i.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Select value={agentType} onValueChange={setAgentType}>
              <SelectTrigger size="sm" className="flex-1">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {AGENT_TYPES.map((a) => (
                  <SelectItem key={a.value} value={a.value}>
                    {a.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Button
              size="sm"
              onClick={() => void create()}
              disabled={busy || !query.trim()}
              className="bg-primary text-primary-foreground hover:bg-primary/85"
            >
              {busy ? <Loader2 className="animate-spin" /> : "创建"}
            </Button>
          </div>
        </div>
      )}

      <ScrollArea className="min-h-0 flex-1">
        <div className="p-2">
          {items === null && <div className="p-3 text-xs text-muted-foreground/70">加载中…</div>}
          {items?.length === 0 && !creating && (
            <div className="p-4 text-center text-xs leading-relaxed text-muted-foreground/70">
              还没有定时任务。
              <br />点 + 创建：平台会按间隔自动运行，产出进对应会话。
            </div>
          )}
          {items?.map((it) => (
            <div
              key={it.scheduleId}
              className="group mb-1.5 rounded-lg border border-transparent px-2 py-1.5 hover:border-border hover:bg-accent/50"
            >
              <div className="flex items-center gap-2">
                <CalendarClock className={`size-4 shrink-0 ${it.enabled ? "text-primary" : "text-muted-foreground/60"}`} />
                <button
                  onClick={() => onOpenSession?.(it.sessionId)}
                  title="打开该任务的会话"
                  className="min-w-0 flex-1 truncate text-left text-sm text-foreground hover:text-primary"
                >
                  {it.query}
                </button>
                <button
                  onClick={() => void onDelete(it)}
                  title={confirming === it.scheduleId ? "再点一次确认删除" : "删除"}
                  className={`shrink-0 rounded p-1 transition-colors ${
                    confirming === it.scheduleId
                      ? "bg-destructive/20 text-destructive"
                      : "text-muted-foreground/70 opacity-0 hover:text-destructive group-hover:opacity-100"
                  }`}
                >
                  <Trash2 className="size-3.5" />
                </button>
              </div>
              <div className="mt-0.5 flex items-center gap-2 pl-6 text-[10px] text-muted-foreground/70">
                <span>{intervalLabel(it.intervalSeconds)}</span>
                <span>·</span>
                <button onClick={() => void onToggle(it)} className="hover:text-foreground">
                  {it.enabled ? "运行中（点击暂停）" : "已暂停（点击启用）"}
                </button>
              </div>
            </div>
          ))}
        </div>
      </ScrollArea>
      <div className="border-t p-2 text-[10px] leading-relaxed text-muted-foreground/60">
        触发的运行会出现在任务专属会话里（列表单条目、上下文延续）；系统繁忙时顺延到下个周期。
      </div>
    </div>
  );
}
