import type { SessionView } from "../lib/sessions";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";

// M7：会话列表来自服务端账本（GET /sessions，runs 聚合），点击进入整段会话；
// 不再提供"逐 run 回放"按钮——历史与继续对话统一在 ChatView 的 timeline 里。
export function Sidebar({
  sessions,
  currentSessionId,
  onNewSession,
  onSelectSession,
}: {
  sessions: SessionView[];
  currentSessionId: string | null;
  onNewSession: () => void;
  onSelectSession: (id: string) => void;
}) {
  return (
    <aside className="flex w-64 shrink-0 flex-col border-r">
      <div className="p-3">
        <Button
          onClick={onNewSession}
          variant="secondary"
          className="w-full bg-cyan-600/30 text-cyan-100 hover:bg-cyan-600/50"
        >
          ＋ 新会话
        </Button>
      </div>
      <ScrollArea className="min-h-0 flex-1">
        <div className="px-2 pb-3">
          {sessions.length === 0 && <div className="px-2 py-4 text-xs text-slate-500">还没有会话</div>}
          {sessions.map((s) => (
            <button
              key={s.id}
              onClick={() => onSelectSession(s.id)}
              className={`mb-2 block w-full rounded-lg border p-2 text-left ${
                s.id === currentSessionId ? "border-cyan-500/40 bg-cyan-500/[0.06]" : "hover:bg-accent"
              }`}
            >
              <div className="truncate text-sm text-slate-200">{s.title || "（无标题）"}</div>
              <div className="mt-0.5 flex items-center gap-1 text-[10px] text-slate-500">
                <span>{s.agentType}</span>
                <span>·</span>
                <span>{s.pendingLocal ? "新会话" : `${s.runCount} 轮`}</span>
              </div>
            </button>
          ))}
        </div>
      </ScrollArea>
      <div className="border-t p-2 text-[10px] leading-relaxed text-slate-600">
        会话列表来自服务端账本（runs 聚合）；点开旧会话载入全部历史后可直接继续对话，模型记得上文。
      </div>
    </aside>
  );
}
