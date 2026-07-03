import { AGENT_TYPES } from "../config";
import type { HealthReport } from "../lib/api/client";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
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

export function Header({
  agentType,
  onAgentType,
  health,
  userId,
  onLogout,
}: {
  agentType: string;
  onAgentType: (v: string) => void;
  health: HealthReport | null;
  userId: string;
  onLogout: () => void;
}) {
  return (
    <header className="flex items-center gap-3 border-b px-4 py-3">
      <span className="text-lg font-semibold tracking-tight">
        <span className="text-primary">pro</span>-agent
      </span>
      <span className="hidden text-xs text-stone-500 sm:inline">多智能体平台</span>
      <div className="ml-4 flex items-center gap-2">
        <span className="text-xs text-stone-500">模式</span>
        <Select value={agentType} onValueChange={onAgentType}>
          {/* M9 座位：三档模式（快速/深度思考/深度研究）与输出格式选择器落位于此 */}
          <SelectTrigger size="sm" className="min-w-28">
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
      </div>
      <div className="ml-auto flex items-center gap-3">
        <HealthBadge report={health} />
        <span className="text-sm text-stone-400">👤 {userId}</span>
        <Button variant="ghost" size="sm" onClick={onLogout} className="text-xs text-stone-400">
          退出
        </Button>
      </div>
    </header>
  );
}
