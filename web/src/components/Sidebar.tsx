import { useEffect, useRef, useState } from "react";
import {
  CalendarClock,
  ChartColumn,
  Database,
  FolderOpen,
  GitBranch,
  LogOut,
  ImagePlus,
  MessageSquare,
  PanelLeft,
  Plus,
  Trash2,
} from "lucide-react";
import type { SessionView } from "../lib/sessions";
import type { NavView } from "../lib/uiPrefs";
import type { HealthReport } from "../lib/api/client";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

// 侧栏 = 导航中枢（对齐 Claude 官网）：品牌+折叠 / 新对话 / 导航项(对话·产物·知识库·定时)
// / 会话列表（仅"对话"视图下）/ 账号底栏（健康·成本·用户·退出）。顶栏已移除。

function NavItem({
  icon,
  label,
  active,
  onClick,
}: {
  icon: React.ReactNode;
  label: string;
  active?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={`flex w-full items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-sm transition-colors ${
        active ? "bg-accent text-foreground" : "text-stone-400 hover:bg-accent/50 hover:text-foreground"
      }`}
    >
      {icon}
      {label}
    </button>
  );
}

export // 会话行：hover 出删除钮，两步确认（再点一次才真删）。
function SessionRow({
  s,
  active,
  onSelect,
  onDelete,
}: {
  s: SessionView;
  active: boolean;
  onSelect: () => void;
  onDelete: () => void;
}) {
  const [confirming, setConfirming] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => { if (timerRef.current) clearTimeout(timerRef.current); }, []);
  return (
    <div
      className={`group relative mb-1 rounded-lg border transition-colors ${
        active ? "border-primary/40 bg-primary/10" : "border-transparent hover:bg-accent/50"
      }`}
    >
      <button onClick={onSelect} className="block w-full p-2 pr-8 text-left">
        <div className="flex items-center gap-1">
          {/* docs/14：分叉会话标记（继承父会话历史的新时间线） */}
          {s.forkedFrom && (
            <span title="分叉会话" className="shrink-0 text-stone-500">
              <GitBranch className="size-3" />
            </span>
          )}
          <div className="truncate text-sm text-stone-200">{s.title || "（无标题）"}</div>
        </div>
        <div className="mt-0.5 flex items-center gap-1 text-[10px] text-stone-500">
          <span>{s.agentType}</span>
          <span>·</span>
          <span>{s.pendingLocal ? "新会话" : `${s.runCount} 轮`}</span>
        </div>
      </button>
      <button
        onClick={(e) => {
          e.stopPropagation();
          if (!confirming) {
            setConfirming(true);
            if (timerRef.current) clearTimeout(timerRef.current);
            timerRef.current = setTimeout(() => setConfirming(false), 3000);
            return;
          }
          onDelete();
        }}
        title={confirming ? "再点一次确认删除" : "删除会话"}
        className={`absolute right-1.5 top-1.5 rounded p-1 transition-colors ${
          confirming
            ? "bg-destructive/20 text-destructive"
            : "text-stone-500 opacity-0 hover:text-destructive group-hover:opacity-100"
        }`}
      >
        <Trash2 className="size-3.5" />
      </button>
    </div>
  );
}

export function Sidebar({
  sessions,
  currentSessionId,
  activeNav,
  onNavChange,
  onNewSession,
  onSelectSession,
  onDeleteSession,
  onToggleSidebar,
  health,
  userId,
  onOpenUsage,
  onLogout,
}: {
  sessions: SessionView[];
  currentSessionId: string | null;
  activeNav: NavView;
  onNavChange: (v: NavView) => void;
  onNewSession: () => void;
  onSelectSession: (id: string) => void;
  onDeleteSession: (id: string) => void;
  onToggleSidebar: () => void;
  health: HealthReport | null;
  userId: string;
  onOpenUsage: () => void;
  onLogout: () => void;
}) {
  const healthColor = !health ? "bg-stone-500" : health.healthy ? "bg-emerald-500" : "bg-rose-500";
  const healthLabel = !health ? "检测中" : health.healthy ? "健康" : "异常";
  const healthDetail = health
    ? Object.entries(health.checks)
        .map(([k, v]) => `${k}: ${v}`)
        .join("\n")
    : "";

  return (
    <aside className="flex w-64 shrink-0 flex-col border-r bg-background">
      {/* 品牌 + 折叠 */}
      <div className="flex items-center gap-1 px-3 py-3">
        <span className="flex-1 text-lg font-semibold tracking-tight">
          <span className="text-primary">pro</span>-agent
        </span>
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant="ghost"
              size="icon"
              onClick={onToggleSidebar}
              aria-label="收起侧边栏"
              className="size-7 text-stone-400 hover:text-foreground"
            >
              <PanelLeft />
            </Button>
          </TooltipTrigger>
          <TooltipContent>收起侧边栏</TooltipContent>
        </Tooltip>
      </div>

      {/* 新对话 + 导航项 */}
      <div className="space-y-0.5 px-2">
        <Button
          onClick={onNewSession}
          className="mb-1 w-full justify-start gap-2 bg-primary text-primary-foreground hover:bg-primary/85"
        >
          <Plus className="size-4" />
          新对话
        </Button>
        <NavItem icon={<MessageSquare className="size-4" />} label="对话" active={activeNav === "chat"} onClick={() => onNavChange("chat")} />
        <NavItem icon={<ImagePlus className="size-4" />} label="生图" active={activeNav === "generate"} onClick={() => onNavChange("generate")} />
        <NavItem icon={<FolderOpen className="size-4" />} label="产物" active={activeNav === "artifacts"} onClick={() => onNavChange("artifacts")} />
        <NavItem icon={<Database className="size-4" />} label="知识库" active={activeNav === "kb"} onClick={() => onNavChange("kb")} />
        <NavItem icon={<CalendarClock className="size-4" />} label="定时任务" active={activeNav === "schedules"} onClick={() => onNavChange("schedules")} />
      </div>

      {/* 会话列表（仅"对话"视图下显示） */}
      {activeNav === "chat" && (
        <>
          <div className="px-3 pt-3 pb-1 text-[10px] font-medium tracking-wide text-stone-600 uppercase">
            最近对话
          </div>
          <ScrollArea className="min-h-0 flex-1">
            <div className="px-2 pb-2">
              {sessions.length === 0 && <div className="px-2 py-3 text-xs text-stone-500">还没有会话</div>}
              {sessions.map((s) => (
                <SessionRow
                  key={s.id}
                  s={s}
                  active={s.id === currentSessionId}
                  onSelect={() => onSelectSession(s.id)}
                  onDelete={() => onDeleteSession(s.id)}
                />
              ))}
            </div>
          </ScrollArea>
        </>
      )}
      {activeNav !== "chat" && <div className="flex-1" />}

      {/* 账号底栏：健康 · 成本 · 用户 · 退出 */}
      <div className="flex items-center gap-1.5 border-t px-3 py-2">
        <Tooltip>
          <TooltipTrigger asChild>
            <span className="flex items-center gap-1.5 text-xs text-stone-400">
              <span className={`h-2 w-2 rounded-full ${healthColor}`} />
              {healthLabel}
            </span>
          </TooltipTrigger>
          {healthDetail && (
            <TooltipContent align="start" className="whitespace-pre text-xs">
              {healthDetail}
            </TooltipContent>
          )}
        </Tooltip>
        <div className="ml-auto flex items-center gap-0.5">
          <Tooltip>
            <TooltipTrigger asChild>
              <Button variant="ghost" size="icon" onClick={onOpenUsage} aria-label="用量与成本" className="size-7 text-stone-400 hover:text-foreground">
                <ChartColumn />
              </Button>
            </TooltipTrigger>
            <TooltipContent>用量与成本</TooltipContent>
          </Tooltip>
          <span className="max-w-20 truncate px-1 text-xs text-stone-400" title={userId}>
            {userId}
          </span>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button variant="ghost" size="icon" onClick={onLogout} aria-label="退出" className="size-7 text-stone-400 hover:text-foreground">
                <LogOut />
              </Button>
            </TooltipTrigger>
            <TooltipContent>退出</TooltipContent>
          </Tooltip>
        </div>
      </div>
    </aside>
  );
}
