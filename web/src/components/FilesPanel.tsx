import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { FileText, Image as ImageIcon, Loader2, RotateCw, Trash2, Upload, X } from "lucide-react";
import { toast } from "sonner";
import type { ArtifactRef } from "../lib/sse/frameTypes";
import type { AttachmentRef } from "../lib/api/client";
import { deleteKbDoc, downloadArtifact, ingestKbDoc, listKbDocs, uploadFile, type KbDoc } from "../lib/api/client";
import { ArtifactPreview, useAuthedObjectUrl } from "./ArtifactWorkspace";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

// 上传附件 → ArtifactRef 形态（复用预览/下载；uploads 也由 /artifacts/* 代理带 owner 校验服务）。
function uploadToRef(a: AttachmentRef): ArtifactRef {
  return {
    resourceKey: a.resourceKey,
    name: a.fileName,
    fileName: a.fileName,
    mimeType: a.mimeType,
    size: a.size,
    previewUrl: `/artifacts/${a.resourceKey}`,
    downloadUrl: `/artifacts/${a.resourceKey}`,
    missing: false,
  };
}

// dock 卡片：图片显缩略图、其余显类型图标；active 高亮，点击选中预览。
function FileCard({ art, active, onClick }: { art: ArtifactRef; active: boolean; onClick: () => void }) {
  const isImg = (art.mimeType || "").startsWith("image/");
  const thumb = useAuthedObjectUrl(`/artifacts/${art.resourceKey}`, isImg && !art.missing);
  return (
    <button
      onClick={onClick}
      title={art.fileName || art.name}
      className={`flex w-full items-center gap-2 rounded-lg border px-2 py-1.5 text-left transition-colors ${
        active ? "border-primary/50 bg-primary/10" : "border-border/60 hover:border-border hover:bg-accent/50"
      }`}
    >
      <span className="flex size-8 shrink-0 items-center justify-center overflow-hidden rounded bg-black/20">
        {isImg && thumb ? (
          <img src={thumb} alt="" className="size-full object-cover" />
        ) : isImg ? (
          <ImageIcon className="size-4 text-stone-500" />
        ) : (
          <FileText className="size-4 text-stone-500" />
        )}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-xs text-stone-200">{art.fileName || art.name}</span>
        <span className="block truncate text-[10px] text-stone-500">{(art.mimeType || "文件").split(";")[0]}</span>
      </span>
    </button>
  );
}

const KB_ACCEPT = ".txt,.md,.markdown,.csv,.json,.xml,.yaml,.yml,.log,.pdf,.docx,.xlsx";

function fmtDate(unixSec: number): string {
  if (!unixSec) return "";
  const d = new Date(unixSec * 1000);
  return `${d.getMonth() + 1}/${d.getDate()}`;
}

// 知识库视图：owner 级文档列表（跨会话）+ 删除 + 面板内上传即入库。
// 删除语义（对齐业界，UI 里明示）：只影响此后的检索，历史对话与回放不受影响。
// 导出：侧栏导航"知识库"整页渲染它（不再是 Files dock 页签）。
export function KnowledgePanel() {
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

// Files 右 dock = **仅本对话**的 Artifacts（生成产物）与 Content（上传内容）两段（实时"生成即所见"）。
// 作用域是当前会话（区别于侧栏"产物"跨会话画廊）。知识库/定时已移到侧栏导航整页。
// 上传附件仅当前会话实时轮携带（历史回放轮不含 = M8 既有限制，载入旧会话时"上传内容"段为空）。
export const FilesPanel = memo(function FilesPanel({
  artifacts,
  uploads = [],
  onClose,
}: {
  artifacts: ArtifactRef[];
  uploads?: AttachmentRef[];
  onClose: () => void;
}) {
  const uploadRefs = useMemo(() => uploads.map(uploadToRef), [uploads]);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  // 新产物到达即切到最新（"生成即所见"）；清掉手动选择回落默认。
  const prevArtLen = useRef(artifacts.length);
  useEffect(() => {
    if (artifacts.length > prevArtLen.current) setSelectedKey(null);
    prevArtLen.current = artifacts.length;
  }, [artifacts.length]);

  const all = useMemo(() => [...artifacts, ...uploadRefs], [artifacts, uploadRefs]);
  // 默认选中：最新一份产物；无产物则第一份上传。
  const selected =
    all.find((a) => a.resourceKey === selectedKey) ??
    (artifacts.length > 0 ? artifacts[artifacts.length - 1] : uploadRefs[0]);
  const total = artifacts.length + uploadRefs.length;

  return (
    <div className="flex h-full flex-col border-l bg-background">
      <div className="flex items-center gap-1.5 border-b px-3 py-2">
        <FileText className="size-3.5 text-stone-400" />
        <span className="text-sm text-foreground">当前对话{total > 0 ? ` · ${total}` : ""}</span>
        <button
          onClick={onClose}
          aria-label="关闭"
          className="ml-auto rounded p-1.5 text-stone-400 transition-colors hover:text-foreground"
        >
          <X className="size-4" />
        </button>
      </div>

      {total === 0 ? (
        <div className="flex flex-1 items-center justify-center p-6 text-center text-sm leading-relaxed text-stone-500">
          本对话的产物（报告/图表/生成图等）
          <br />
          与上传的文件会出现在这里，可预览下载。
        </div>
      ) : (
        <>
          {/* 索引：两段卡片（Artifacts 生成 / 上传内容），点击选中预览 */}
          <ScrollArea className="max-h-[45%] shrink-0 border-b">
            <div className="space-y-1 p-2">
              {artifacts.length > 0 && (
                <>
                  <div className="px-1 pt-0.5 pb-1 text-[10px] font-medium tracking-wide text-stone-500 uppercase">
                    Artifacts · {artifacts.length}
                  </div>
                  {artifacts.map((a) => (
                    <FileCard key={a.resourceKey} art={a} active={selected?.resourceKey === a.resourceKey} onClick={() => setSelectedKey(a.resourceKey)} />
                  ))}
                </>
              )}
              {uploadRefs.length > 0 && (
                <>
                  <div className="px-1 pt-1.5 pb-1 text-[10px] font-medium tracking-wide text-stone-500 uppercase">
                    上传内容 · {uploadRefs.length}
                  </div>
                  {uploadRefs.map((a) => (
                    <FileCard key={a.resourceKey} art={a} active={selected?.resourceKey === a.resourceKey} onClick={() => setSelectedKey(a.resourceKey)} />
                  ))}
                </>
              )}
            </div>
          </ScrollArea>
          {/* 预览：选中项 */}
          <div className="min-h-0 flex-1">{selected && <ArtifactPreview art={selected} />}</div>
        </>
      )}
    </div>
  );
});
