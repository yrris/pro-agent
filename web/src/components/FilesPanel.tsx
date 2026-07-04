import { memo, useCallback, useEffect, useRef, useState } from "react";
import { CalendarClock, Database, FileText, Loader2, RotateCw, Trash2, Upload, X } from "lucide-react";
import { toast } from "sonner";
import type { ArtifactRef } from "../lib/sse/frameTypes";
import { deleteKbDoc, downloadArtifact, ingestKbDoc, listKbDocs, uploadFile, type KbDoc } from "../lib/api/client";
import { ArtifactWorkspace } from "./ArtifactWorkspace";
import { SchedulesPanel } from "./SchedulesPanel";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

const KB_ACCEPT = ".txt,.md,.markdown,.csv,.json,.xml,.yaml,.yml,.log,.pdf,.docx,.xlsx";

function fmtDate(unixSec: number): string {
  if (!unixSec) return "";
  const d = new Date(unixSec * 1000);
  return `${d.getMonth() + 1}/${d.getDate()}`;
}

// 知识库页签：owner 级文档列表（跨会话）+ 删除 + 面板内上传即入库。
// 删除语义（对齐业界，UI 里明示）：只影响此后的检索，历史对话与回放不受影响。
function KnowledgePanel() {
  const [docs, setDocs] = useState<KbDoc[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const refresh = useCallback(async () => {
    try {
      setDocs(await listKbDocs());
    } catch {
      setDocs([]);
      toast.error("知识库列表加载失败");
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const onPick = async (files: FileList | null) => {
    const list = Array.from(files ?? []);
    if (fileRef.current) fileRef.current.value = "";
    if (!list.length) return;
    setBusy(true);
    try {
      for (const f of list) {
        const ref = await uploadFile(f, "");
        const r = await ingestKbDoc(ref);
        if (r.ok) toast.success(`已入库：${f.name}`);
        else toast.warning(`${f.name}：${r.message || "未入库"}`);
      }
      await refresh();
    } catch {
      toast.error("上传入库失败");
    } finally {
      setBusy(false);
    }
  };

  const onDelete = async (d: KbDoc) => {
    if (confirming !== d.sourceId) {
      setConfirming(d.sourceId); // 两步确认：再点一次才真删
      setTimeout(() => setConfirming((c) => (c === d.sourceId ? null : c)), 3000);
      return;
    }
    setConfirming(null);
    try {
      await deleteKbDoc(d.sourceId);
      toast.success(`已从知识库移除：${d.fileName}`);
      await refresh();
    } catch {
      toast.error("删除失败");
    }
  };

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-1.5 border-b px-3 py-2">
        <span className="min-w-0 flex-1 truncate text-xs text-stone-500">
          个人知识库（跨会话可检索）
        </span>
        <input
          ref={fileRef}
          type="file"
          multiple
          accept={KB_ACCEPT}
          className="hidden"
          onChange={(e) => void onPick(e.target.files)}
        />
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant="ghost"
              size="icon"
              disabled={busy}
              onClick={() => fileRef.current?.click()}
              aria-label="上传入库"
              className="size-7 text-stone-400 hover:text-foreground"
            >
              {busy ? <Loader2 className="animate-spin" /> : <Upload />}
            </Button>
          </TooltipTrigger>
          <TooltipContent>上传文档入库（文本/PDF）</TooltipContent>
        </Tooltip>
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant="ghost"
              size="icon"
              onClick={() => void refresh()}
              aria-label="刷新"
              className="size-7 text-stone-400 hover:text-foreground"
            >
              <RotateCw />
            </Button>
          </TooltipTrigger>
          <TooltipContent>刷新列表</TooltipContent>
        </Tooltip>
      </div>
      <ScrollArea className="min-h-0 flex-1">
        <div className="p-2">
          {docs === null && <div className="p-3 text-xs text-stone-500">加载中…</div>}
          {docs?.length === 0 && (
            <div className="p-4 text-center text-xs leading-relaxed text-stone-500">
              知识库为空。
              <br />
              上传文档，或在对话里发送附件（文本/PDF 自动入库）。
            </div>
          )}
          {docs?.map((d) => (
            <div
              key={d.sourceId}
              className="group mb-1 flex items-center gap-2 rounded-lg border border-transparent px-2 py-1.5 hover:border-border hover:bg-accent/50"
            >
              <FileText className="size-4 shrink-0 text-stone-500" />
              <div className="min-w-0 flex-1">
                {d.downloadUrl ? (
                  <button
                    onClick={() => void downloadArtifact(d.sourceId, d.fileName)}
                    title="下载原文件"
                    className="block max-w-full truncate text-left text-sm text-stone-200 hover:text-primary"
                  >
                    {d.fileName}
                  </button>
                ) : (
                  <div className="truncate text-sm text-stone-200">{d.fileName}</div>
                )}
                <div className="text-[10px] text-stone-500">
                  {d.chunks} 段{d.createdAt ? ` · ${fmtDate(d.createdAt)}` : ""}
                </div>
              </div>
              <button
                onClick={() => void onDelete(d)}
                title={confirming === d.sourceId ? "再点一次确认删除" : "从知识库移除"}
                className={`shrink-0 rounded p-1 transition-colors ${
                  confirming === d.sourceId
                    ? "bg-destructive/20 text-destructive"
                    : "text-stone-500 opacity-0 hover:text-destructive group-hover:opacity-100"
                }`}
              >
                <Trash2 className="size-3.5" />
              </button>
            </div>
          ))}
        </div>
      </ScrollArea>
      <div className="border-t p-2 text-[10px] leading-relaxed text-stone-600">
        删除只影响此后的检索（含旧会话里再提问）；已生成的历史回答与回放不受影响。
      </div>
    </div>
  );
}

// Files 面板 = 产物（本会话）| 知识库（跨会话）两个页签，右上单一入口开关。
export const FilesPanel = memo(function FilesPanel({
  artifacts,
  onClose,
  onOpenSession,
}: {
  artifacts: ArtifactRef[];
  onClose: () => void;
  onOpenSession?: (sessionId: string) => void;
}) {
  const [tab, setTab] = useState<"artifacts" | "kb" | "schedules">("artifacts");
  return (
    <div className="flex h-full flex-col border-l bg-background">
      <div className="flex items-center gap-1 border-b px-2 py-1.5">
        <button
          onClick={() => setTab("artifacts")}
          className={`flex items-center gap-1.5 rounded-lg px-2.5 py-1 text-sm transition-colors ${
            tab === "artifacts" ? "bg-accent text-foreground" : "text-stone-500 hover:text-foreground"
          }`}
        >
          <FileText className="size-3.5" />
          产物{artifacts.length > 0 ? ` ${artifacts.length}` : ""}
        </button>
        <button
          onClick={() => setTab("kb")}
          className={`flex items-center gap-1.5 rounded-lg px-2.5 py-1 text-sm transition-colors ${
            tab === "kb" ? "bg-accent text-foreground" : "text-stone-500 hover:text-foreground"
          }`}
        >
          <Database className="size-3.5" />
          知识库
        </button>
        <button
          onClick={() => setTab("schedules")}
          className={`flex items-center gap-1.5 rounded-lg px-2.5 py-1 text-sm transition-colors ${
            tab === "schedules" ? "bg-accent text-foreground" : "text-stone-500 hover:text-foreground"
          }`}
        >
          <CalendarClock className="size-3.5" />
          定时
        </button>
        <button
          onClick={onClose}
          aria-label="关闭"
          className="ml-auto rounded p-1.5 text-stone-400 transition-colors hover:text-foreground"
        >
          <X className="size-4" />
        </button>
      </div>
      <div className="min-h-0 flex-1">
        {/* 两页签常挂载、以 hidden 切换：切走再切回不丢 ArtifactWorkspace 的选中项与 KB 列表 */}
        <div className={tab === "artifacts" ? "h-full" : "hidden"}>
          <ArtifactWorkspace artifacts={artifacts} />
        </div>
        <div className={tab === "kb" ? "h-full" : "hidden"}>
          <KnowledgePanel />
        </div>
        <div className={tab === "schedules" ? "h-full" : "hidden"}>
          <SchedulesPanel onOpenSession={onOpenSession} />
        </div>
      </div>
    </div>
  );
});
