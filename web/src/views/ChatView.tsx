import { useEffect, useMemo, useRef, useState } from "react";
import { MessageList } from "../components/chat";
import { ArtifactWorkspace } from "../components/ArtifactWorkspace";
import type { ArtifactRef } from "../lib/sse/frameTypes";
import type { RunStatus, RunTurn } from "../hooks/useRunStream";
import { SAMPLE_QUESTIONS } from "../config";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";

function Composer({
  disabled,
  placeholder,
  onSubmit,
}: {
  disabled: boolean;
  placeholder: string;
  onSubmit: (q: string) => void;
}) {
  const [text, setText] = useState("");
  const submit = () => {
    const q = text.trim();
    if (!q || disabled) return;
    onSubmit(q);
    setText("");
  };
  return (
    <div className="border-t p-3">
      <div className="flex items-end gap-2">
        {/* M8 座位：附件按钮与文件 chips 加在 Textarea 左侧；M9 座位：输出格式选择器加在发送按钮左侧 */}
        <Textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              // 输入法组合期间的 Enter 只用于选词上屏（中文打英文单词等），不发送。
              // isComposing 为标准判定；keyCode 229 兜 Safari/旧 Chromium 在
              // compositionend 前后派发 keydown 的时序差（对齐 ChatGPT/Claude 行为）。
              if (e.nativeEvent.isComposing || e.keyCode === 229) return;
              e.preventDefault();
              submit();
            }
          }}
          rows={2}
          placeholder={placeholder}
          disabled={disabled}
          className="min-h-0 flex-1 resize-none"
        />
        <Button onClick={submit} disabled={disabled} className="rounded-xl px-4">
          发送
        </Button>
      </div>
    </div>
  );
}

// M7：单 RunState 视图升级为 timeline+live 多轮会话视图。
// 历史轮次只读堆叠展示；Composer 仅在「载入历史/运行中」时禁用——载入完即可继续对话。
export function ChatView({
  timeline,
  live,
  status,
  loadingHistory,
  onSubmit,
}: {
  timeline: RunTurn[];
  live: RunTurn | null;
  status: RunStatus;
  loadingHistory: boolean;
  onSubmit: (q: string) => void;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [timeline.length, live?.state.order.length, live?.state.result?.text, status]);

  const empty = timeline.length === 0 && !live && !loadingHistory;
  // artifact 工作区聚合整个会话（历史轮 + 当前轮）的产物。useMemo 依赖数组标识：
  // reducer 只在产物帧到达时才替换 artifacts 数组，token 帧不会触发重算/工作区重渲。
  const liveArtifacts = live?.state.artifacts;
  const artifacts: ArtifactRef[] = useMemo(
    () => [...timeline.flatMap((t) => t.state.artifacts), ...(liveArtifacts ?? [])],
    [timeline, liveArtifacts],
  );

  const composerDisabled = loadingHistory || status === "running";
  const placeholder = loadingHistory
    ? "正在载入历史会话…"
    : status === "running"
      ? "运行中…完成后可继续提问"
      : "输入问题，Enter 发送，Shift+Enter 换行（历史会话可直接继续对话）";

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
                  <Button
                    key={q}
                    variant="outline"
                    onClick={() => onSubmit(q)}
                    className="block h-auto w-full px-3 py-2 text-left text-sm font-normal text-slate-300"
                  >
                    {q}
                  </Button>
                ))}
              </div>
            </div>
          ) : (
            <div className="mx-auto max-w-3xl">
              {timeline.map((turn) => (
                <div key={turn.runId} className="mb-6">
                  <MessageList state={turn.state} query={turn.query} />
                  {turn.failed && (
                    <div className="mt-1 text-xs text-amber-400">
                      ⚠ 此轮未走到终态（中断/出错/仍在运行），仅展示已落库部分
                    </div>
                  )}
                </div>
              ))}
              {live && <MessageList state={live.state} query={live.query} />}
              {loadingHistory && (
                <div className="mt-3 space-y-2">
                  <div className="text-sm text-slate-500 pulse-dot">● 载入历史会话…</div>
                  <Skeleton className="h-16 w-3/4" />
                  <Skeleton className="h-10 w-1/2" />
                </div>
              )}
              {status === "running" && <div className="mt-3 text-sm text-slate-500 pulse-dot">● 运行中…</div>}
              {status === "error" && (
                <div className="mt-3 text-sm text-rose-400">运行出错，请查看健康状态或重试。</div>
              )}
            </div>
          )}
        </div>
        <Composer disabled={composerDisabled} placeholder={placeholder} onSubmit={onSubmit} />
      </div>
      <div className="hidden w-96 shrink-0 border-l lg:block">
        <ArtifactWorkspace artifacts={artifacts} />
      </div>
    </div>
  );
}
