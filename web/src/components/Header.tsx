import { AGENT_TYPES } from "../config";
import type { HealthReport } from "../lib/api/client";

function HealthBadge({ report }: { report: HealthReport | null }) {
  const color = !report ? "bg-slate-500" : report.healthy ? "bg-emerald-500" : "bg-rose-500";
  const label = !report ? "检测中" : report.healthy ? "健康" : "异常";
  const detail = report ? Object.entries(report.checks).map(([k, v]) => `${k}: ${v}`).join("\n") : "";
  return (
    <div className="group relative">
      <span className="inline-flex items-center gap-1.5 rounded-full border border-white/10 px-2 py-1 text-xs text-slate-300">
        <span className={`h-2 w-2 rounded-full ${color}`} />
        {label}
      </span>
      {detail && (
        <div className="pointer-events-none absolute right-0 top-full z-10 mt-1 hidden whitespace-pre rounded-lg border border-white/10 bg-slate-900 p-2 text-xs text-slate-300 group-hover:block">
          {detail}
        </div>
      )}
    </div>
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
    <header className="flex items-center gap-3 border-b border-white/10 px-4 py-3">
      <span className="text-lg font-semibold tracking-tight">
        <span className="text-cyan-400">my</span>-agent
      </span>
      <span className="hidden text-xs text-slate-500 sm:inline">多智能体平台</span>
      <div className="ml-4 flex items-center gap-2">
        <span className="text-xs text-slate-500">模式</span>
        <select
          value={agentType}
          onChange={(e) => onAgentType(e.target.value)}
          className="rounded-lg border border-white/10 bg-white/5 px-2 py-1 text-sm text-slate-200 outline-none"
        >
          {AGENT_TYPES.map((a) => (
            <option key={a.value} value={a.value} className="bg-slate-900">
              {a.label}
            </option>
          ))}
        </select>
      </div>
      <div className="ml-auto flex items-center gap-3">
        <HealthBadge report={health} />
        <span className="text-sm text-slate-400">👤 {userId}</span>
        <button onClick={onLogout} className="rounded-lg px-2 py-1 text-xs text-slate-400 hover:bg-white/5 hover:text-slate-200">
          退出
        </button>
      </div>
    </header>
  );
}
