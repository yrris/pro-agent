import { useEffect, useMemo, useRef, useState } from "react";
import { Loader2, Paperclip, RotateCw, X } from "lucide-react";
import { MessageList } from "../components/chat";
import { ArtifactWorkspace } from "../components/ArtifactWorkspace";
import type { ArtifactRef } from "../lib/sse/frameTypes";
import type { RunStatus, RunTurn } from "../hooks/useRunStream";
import { OUTPUT_FORMATS, SAMPLE_QUESTIONS } from "../config";
import { uploadFile, type AttachmentRef } from "../lib/api/client";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";

// 附件条目：选文件即上传（run body 只带引用），失败可重试。
interface PendingAttachment {
  id: string;
  file: File;
  status: "uploading" | "done" | "error";
  ref?: AttachmentRef;
}

const ACCEPT = ".png,.jpg,.jpeg,.webp,.gif,.txt,.md,.markdown,.csv,.json,.xml,.yaml,.yml,.log,.pdf";

function AttachmentChips({
  items,
  onRemove,
  onRetry,
}: {
  items: PendingAttachment[];
  onRemove: (id: string) => void;
  onRetry: (id: string) => void;
}) {
  if (items.length === 0) return null;
  return (
    <div className="mb-2 flex flex-wrap gap-1.5">
      {items.map((a) => (
        <Badge
          key={a.id}
          variant="outline"
          className={`gap-1 font-normal ${a.status === "error" ? "border-rose-500/40 text-rose-300" : "text-stone-300"}`}
        >
          {a.status === "uploading" && <Loader2 className="animate-spin" />}
          <span className="max-w-40 truncate">{a.file.name}</span>
          {a.status === "error" && (
            <button onClick={() => onRetry(a.id)} title="上传失败，点击重试" className="hover:text-rose-100">
              <RotateCw className="size-3" />
            </button>
          )}
          <button onClick={() => onRemove(a.id)} title="移除" className="hover:text-stone-100">
            <X className="size-3" />
          </button>
        </Badge>
      ))}
    </div>
  );
}

function Composer({
  disabled,
  placeholder,
  onSubmit,
  uploadSessionId,
  agentType,
}: {
  disabled: boolean;
  placeholder: string;
  onSubmit: (q: string, attachments?: AttachmentRef[], outputFormat?: string) => void;
  uploadSessionId: string;
  agentType: string;
}) {
  const [text, setText] = useState("");
  const [atts, setAtts] = useState<PendingAttachment[]>([]);
  const [format, setFormat] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  const doUpload = (item: PendingAttachment) => {
    setAtts((xs) => xs.map((x) => (x.id === item.id ? { ...x, status: "uploading" } : x)));
    uploadFile(item.file, uploadSessionId)
      .then((ref) =>
        setAtts((xs) => xs.map((x) => (x.id === item.id ? { ...x, status: "done", ref } : x))),
      )
      .catch(() =>
        setAtts((xs) => xs.map((x) => (x.id === item.id ? { ...x, status: "error" } : x))),
      );
  };

  const onPick = (files: FileList | null) => {
    for (const f of Array.from(files ?? [])) {
      const item: PendingAttachment = { id: `${Date.now()}-${f.name}`, file: f, status: "uploading" };
      setAtts((xs) => [...xs, item]);
      doUpload(item);
    }
    if (fileRef.current) fileRef.current.value = ""; // 允许再次选择同一文件
  };

  const uploading = atts.some((a) => a.status === "uploading");
  const submit = () => {
    const q = text.trim();
    if (!q || disabled || uploading) return;
    const refs = atts.filter((a) => a.status === "done" && a.ref).map((a) => a.ref!) ;
    onSubmit(q, refs.length ? refs : undefined, format || undefined);
    setText("");
    setAtts([]);
  };
  return (
    <div className="border-t p-3">
      <AttachmentChips
        items={atts}
        onRemove={(id) => setAtts((xs) => xs.filter((x) => x.id !== id))}
        onRetry={(id) => {
          const item = atts.find((x) => x.id === id);
          if (item) doUpload(item);
        }}
      />
      <div className="flex items-end gap-2">
        <input
          ref={fileRef}
          type="file"
          multiple
          accept={ACCEPT}
          className="hidden"
          onChange={(e) => onPick(e.target.files)}
        />
        <Button
          variant="ghost"
          size="icon"
          title="上传附件（图片进多模态；文本/PDF 自动入个人知识库可检索）"
          disabled={disabled}
          onClick={() => fileRef.current?.click()}
        >
          <Paperclip />
        </Button>
        {/* 输出格式（M9）：仅深度思考/深度研究可选（对齐原项目）；值经 startRun.outputFormat 透传 */}
        <Select value={format || "free"} onValueChange={(v) => setFormat(v === "free" ? "" : v)}>
          <SelectTrigger
            size="sm"
            disabled={agentType === "react"}
            title={agentType === "react" ? "快速模式不指定输出格式" : "输出格式"}
            className="w-24 shrink-0 border-stone-700 bg-stone-900 text-stone-300"
          >
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {OUTPUT_FORMATS.map((f) => (
              <SelectItem key={f.value || "free"} value={f.value || "free"}>
                {f.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
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
        <Button onClick={submit} disabled={disabled || uploading} className="rounded-xl px-4">
          {uploading ? "上传中…" : "发送"}
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
  uploadSessionId,
  agentType,
}: {
  timeline: RunTurn[];
  live: RunTurn | null;
  status: RunStatus;
  loadingHistory: boolean;
  onSubmit: (q: string, attachments?: AttachmentRef[], outputFormat?: string) => void;
  uploadSessionId: string;
  agentType: string;
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
              <div className="mb-4 text-stone-400">向平台提问，试试：</div>
              <div className="space-y-2">
                {SAMPLE_QUESTIONS.map((q) => (
                  <Button
                    key={q}
                    variant="outline"
                    onClick={() => onSubmit(q)}
                    className="block h-auto w-full px-3 py-2 text-left text-sm font-normal text-stone-300"
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
                  <MessageList state={turn.state} query={turn.query} attachments={turn.attachments} />
                  {turn.failed && (
                    <div className="mt-1 text-xs text-amber-400">
                      ⚠ 此轮未走到终态（中断/出错/仍在运行），仅展示已落库部分
                    </div>
                  )}
                </div>
              ))}
              {live && <MessageList state={live.state} query={live.query} attachments={live.attachments} />}
              {loadingHistory && (
                <div className="mt-3 space-y-2">
                  <div className="text-sm text-stone-500 pulse-dot">● 载入历史会话…</div>
                  <Skeleton className="h-16 w-3/4" />
                  <Skeleton className="h-10 w-1/2" />
                </div>
              )}
              {status === "running" && <div className="mt-3 text-sm text-stone-500 pulse-dot">● 运行中…</div>}
              {status === "error" && (
                <div className="mt-3 text-sm text-rose-400">运行出错，请查看健康状态或重试。</div>
              )}
            </div>
          )}
        </div>
        <Composer
          disabled={composerDisabled}
          placeholder={placeholder}
          onSubmit={onSubmit}
          uploadSessionId={uploadSessionId}
          agentType={agentType}
        />
      </div>
      <div className="hidden w-96 shrink-0 border-l lg:block">
        <ArtifactWorkspace artifacts={artifacts} />
      </div>
    </div>
  );
}
