import { useEffect, useRef, useState } from "react";
import { MessageList } from "../components/chat";
import { ArtifactWorkspace } from "../components/ArtifactWorkspace";
import type { RunState } from "../lib/sse/frameTypes";
import type { RunStatus } from "../hooks/useRunStream";
import { SAMPLE_QUESTIONS } from "../config";

function Composer({ disabled, onSubmit }: { disabled: boolean; onSubmit: (q: string) => void }) {
  const [text, setText] = useState("");
  const submit = () => {
    const q = text.trim();
    if (!q || disabled) return;
    onSubmit(q);
    setText("");
  };
  return (
    <div className="border-t border-white/10 p-3">
      <div className="flex items-end gap-2">
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
          rows={2}
          placeholder={disabled ? "回放模式下不可输入" : "输入问题，Enter 发送，Shift+Enter 换行"}
          disabled={disabled}
          className="flex-1 resize-none rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm text-slate-100 outline-none placeholder:text-slate-600 disabled:opacity-50"
        />
        <button
          onClick={submit}
          disabled={disabled}
          className="rounded-xl bg-cyan-600 px-4 py-2 text-sm font-medium text-white hover:bg-cyan-500 disabled:opacity-40"
        >
          发送
        </button>
      </div>
    </div>
  );
}

export function ChatView({
  state,
  status,
  replaying,
  query,
  onSubmit,
}: {
  state: RunState;
  status: RunStatus;
  replaying: boolean;
  query: string;
  onSubmit: (q: string) => void;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [state.order.length, state.result?.text, status]);

  const empty = state.order.length === 0 && !query;

  return (
    <div className="flex min-w-0 flex-1">
      <div className="flex min-w-0 flex-1 flex-col">
        <div ref={scrollRef} className="flex-1 overflow-auto p-4">
          {empty ? (
            <div className="mx-auto mt-16 max-w-md text-center">
              <div className="mb-2 text-2xl">🤖</div>
              <div className="mb-4 text-slate-400">向平台提问，试试：</div>
              <div className="space-y-2">
                {SAMPLE_QUESTIONS.map((q) => (
                  <button
                    key={q}
                    onClick={() => onSubmit(q)}
                    className="block w-full rounded-lg border border-white/10 px-3 py-2 text-left text-sm text-slate-300 hover:bg-white/5"
                  >
                    {q}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="mx-auto max-w-3xl">
              {replaying && <div className="mb-3 text-center text-xs text-amber-300">历史回放（只读）</div>}
              <MessageList state={state} query={query} />
              {status === "running" && <div className="mt-3 text-sm text-slate-500 pulse-dot">● 运行中…</div>}
              {status === "error" && <div className="mt-3 text-sm text-rose-400">运行出错，请查看健康状态或重试。</div>}
            </div>
          )}
        </div>
        <Composer disabled={replaying || status === "running"} onSubmit={onSubmit} />
      </div>
      <div className="hidden w-96 shrink-0 border-l border-white/10 lg:block">
        <ArtifactWorkspace artifacts={state.artifacts} />
      </div>
    </div>
  );
}
