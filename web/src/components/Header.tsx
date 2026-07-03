import { FolderOpen, PanelLeft } from "lucide-react";
import type { HealthReport } from "../lib/api/client";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

function HealthBadge({ report }: { report: HealthReport | null }) {
  const color = !report ? "bg-stone-500" : report.healthy ? "bg-emerald-500" : "bg-rose-500";
  const label = !report ? "检测中" : report.healthy ? "健康" : "异常";
  const detail = report
    ? Object.entries(report.checks)
        .map(([k, v]) => `${k}: ${v}`)
        .join("\n")
    : "";
  const badge = (
    <Badge variant="outline" className="gap-1.5 rounded-full text-xs font-normal text-stone-300">
      <span className={`h-2 w-2 rounded-full ${color}`} />
      {label}
    </Badge>
  );
  if (!detail) return badge;
  return (
    <Tooltip>
      <TooltipTrigger asChild>{badge}</TooltipTrigger>
      <TooltipContent align="end" className="whitespace-pre text-xs">
        {detail}
      </TooltipContent>
    </Tooltip>
  );
}

function IconAction({
  label,
  active,
  onClick,
  children,
}: {
  label: string;
  active?: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          onClick={onClick}
          aria-label={label}
          className={active ? "bg-accent text-foreground" : "text-stone-400 hover:text-foreground"}
        >
          {children}
        </Button>
      </TooltipTrigger>
      <TooltipContent>{label}</TooltipContent>
    </Tooltip>
  );
}

// UX-1：顶栏精简为「侧栏开关 + 品牌」/「健康 + Files(产物区) + 身份」。
// 模式/输出格式选择器已内嵌 Composer 胶囊（对齐 Claude 官网布局）。
export function Header({
  health,
  userId,
  onLogout,
  sidebarOpen,
  onToggleSidebar,
  artifactsOpen,
  onToggleArtifacts,
}: {
  health: HealthReport | null;
  userId: string;
  onLogout: () => void;
  sidebarOpen: boolean;
  onToggleSidebar: () => void;
  artifactsOpen: boolean;
  onToggleArtifacts: () => void;
}) {
  return (
    <header className="flex items-center gap-2 border-b px-3 py-2">
      <IconAction label={sidebarOpen ? "收起侧边栏" : "展开侧边栏"} onClick={onToggleSidebar}>
        <PanelLeft />
      </IconAction>
      <span className="text-lg font-semibold tracking-tight">
        <span className="text-primary">pro</span>-agent
      </span>
      <span className="hidden text-xs text-stone-500 sm:inline">多智能体平台</span>
      <div className="ml-auto flex items-center gap-1.5">
        <HealthBadge report={health} />
        <IconAction label="Files（产物与文件）" active={artifactsOpen} onClick={onToggleArtifacts}>
          <FolderOpen />
        </IconAction>
        <span className="px-1 text-sm text-stone-400">👤 {userId}</span>
        <Button variant="ghost" size="sm" onClick={onLogout} className="text-xs text-stone-400">
          退出
        </Button>
      </div>
    </header>
  );
}
