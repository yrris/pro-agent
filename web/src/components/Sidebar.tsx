import type { SessionMeta } from "../lib/sessions";

export function Sidebar({
  sessions,
  currentSessionId,
  onNewSession,
  onSelectSession,
  onReplay,
  activeRunId,
}: {
  sessions: SessionMeta[];
  currentSessionId: string | null;
  onNewSession: () => void;
  onSelectSession: (id: string) => void;
  onReplay: (runId: string) => void;
  activeRunId: string;
}) {
  return (
    <aside className="flex w-64 shrink-0 flex-col border-r border-white/10">
      <div className="p-3">
        <button
          onClick={onNewSession}
          className="w-full rounded-lg bg-cyan-600/30 px-3 py-2 text-sm text-cyan-100 hover:bg-cyan-600/50"
        >
          ＋ 新会话
        </button>
      </div>
      <div className="flex-1 overflow-auto px-2 pb-3">
        {sessions.length === 0 && <div className="px-2 py-4 text-xs text-slate-500">还没有会话</div>}
        {sessions.map((s) => (
          <div
            key={s.id}
            className={`mb-2 rounded-lg border p-2 ${
              s.id === currentSessionId ? "border-cyan-500/40 bg-cyan-500/[0.06]" : "border-white/10"
            }`}
          >
            <button onClick={() => onSelectSession(s.id)} className="mb-1 block w-full truncate text-left text-sm text-slate-200">
              {s.title}
              <span className="ml-1 text-[10px] text-slate-500">{s.agentType}</span>
            </button>
            {s.runIds.length > 0 && (
              <div className="space-y-0.5">
                {s.runIds.map((rid, i) => (
                  <button
                    key={rid}
                    onClick={() => onReplay(rid)}
                    title={rid}
                    className={`block w-full truncate rounded px-1.5 py-0.5 text-left text-[11px] hover:bg-white/5 ${
                      rid === activeRunId ? "text-cyan-300" : "text-slate-400"
                    }`}
                  >
                    ↺ 回放 run #{i + 1}
                  </button>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
      <div className="border-t border-white/10 p-2 text-[10px] leading-relaxed text-slate-600">
        会话历史存于本地浏览器（后端无会话端点）；回放读 /runs/{"{id}"}/events，与实时同构。
      </div>
    </aside>
  );
}
