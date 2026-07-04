import { useEffect, useMemo, useRef, useState } from "react";
import { ImagePlus, Loader2, Paperclip, Sparkles, X } from "lucide-react";
import {
  listArtifacts,
  startRun,
  uploadFileWithProgress,
  type AttachmentRef,
  type OwnerArtifact,
} from "../lib/api/client";
import { iterFrames } from "../lib/api/stream";
import { ArtifactWorkspace, useAuthedObjectUrl } from "./ArtifactWorkspace";
import type { ArtifactRef } from "../lib/sse/frameTypes";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { toast } from "sonner";

// 生图工作区（B.5）：直接输入提示词批量生图（文生图 / 上传底图做图生图），下方是生成历史网格。
// 自包含——不复用 chat 的 useRunStream：自己起一个 run（专用会话）并把 SSE 读空到终态，
// 完成后刷新历史网格。inpaint 局部重绘（画布蒙版 + /images/edits mask）为后续项，见 docs/10。

const SIZES = [
  { value: "1024x1024", label: "方形 1:1" },
  { value: "1536x1024", label: "横向 3:2" },
  { value: "1024x1536", label: "纵向 2:3" },
];
// 每次生成用一个**唯一**会话（前缀 generate:），避免固定 thread 让 checkpoint 无界累积、
// 且"猫"的历史污染下一次"狗"的生成。前缀让侧栏把它们过滤出普通对话列表（见 sessions.ts）。
const GEN_SESSION_PREFIX = "generate:";
const newGenSession = () =>
  GEN_SESSION_PREFIX + Math.random().toString(36).slice(2) + Date.now().toString(36);
const PAGE = 40;

function toRef(a: OwnerArtifact): ArtifactRef {
  return {
    resourceKey: a.resourceKey,
    name: a.name || a.fileName,
    fileName: a.fileName || a.name,
    previewUrl: `/artifacts/${a.resourceKey}`,
    downloadUrl: `/artifacts/${a.resourceKey}`,
    mimeType: a.mimeType,
    size: a.size,
    missing: false,
  };
}

function HistThumb({ art, onClick }: { art: OwnerArtifact; onClick: () => void }) {
  const objUrl = useAuthedObjectUrl(`/artifacts/${art.resourceKey}`, true);
  return (
    <button onClick={onClick} className="overflow-hidden rounded-lg border border-border transition-colors hover:border-primary/50">
      {objUrl ? (
        <img src={objUrl} alt={art.fileName} className="aspect-square w-full object-cover" />
      ) : (
        <Skeleton className="aspect-square w-full" />
      )}
    </button>
  );
}

export function GenerateWorkspace() {
  const [prompt, setPrompt] = useState("");
  const [size, setSize] = useState("1024x1024");
  const [count, setCount] = useState("1");
  const [source, setSource] = useState<AttachmentRef | null>(null);
  const [sourcePreview, setSourcePreview] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [images, setImages] = useState<OwnerArtifact[] | null>(null);
  const [selected, setSelected] = useState<OwnerArtifact | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const previewRef = useRef<string | null>(null);
  previewRef.current = sourcePreview;
  useEffect(() => () => { if (previewRef.current) URL.revokeObjectURL(previewRef.current); }, []);

  const refresh = () => {
    void listArtifacts(PAGE, undefined, "image/") // 服务端只取图片（防单页客户端过滤漏更旧的图）
      .then(setImages)
      .catch(() => setImages([]));
  };
  useEffect(refresh, []);

  const onPickSource = (files: FileList | null) => {
    const f = files?.[0];
    if (fileRef.current) fileRef.current.value = "";
    if (!f) return;
    setUploading(true);
    if (sourcePreview) URL.revokeObjectURL(sourcePreview); // 重选先回收旧预览（#17）
    setSourcePreview(URL.createObjectURL(f));
    void uploadFileWithProgress(f, newGenSession(), () => {})
      .then((ref) => setSource(ref))
      .catch(() => {
        toast.error("底图上传失败");
        setSourcePreview(null);
      })
      .finally(() => setUploading(false));
  };

  const clearSource = () => {
    if (sourcePreview) URL.revokeObjectURL(sourcePreview);
    setSource(null);
    setSourcePreview(null);
  };

  const generate = async () => {
    const p = prompt.trim();
    if (!p || generating || uploading) return;
    setGenerating(true);
    // 组合 query：显式指示生图 + 尺寸/张数提示；source 走图生图。
    const n = Number(count) || 1;
    const query =
      `生成图片（尺寸 ${size}，共 ${n} 张）：${p}` +
      (source ? "。以我上传的图片为底图进行修改（图生图）。" : "");
    try {
      const { reader } = await startRun({
        query,
        sessionId: newGenSession(), // 每次生成一个新 thread，互不污染（评审#1）
        agentType: "react",
        imageGen: true,
        attachments: source ? [source] : undefined,
      });
      // 把流读空到终态（工作区不渲染对话，只需知道何时完成）。
      for await (const _ of iterFrames(reader)) {
        /* drain */
      }
      refresh();
    } catch {
      toast.error("生成失败，请重试");
    } finally {
      setGenerating(false);
    }
  };

  const hist = useMemo(() => images ?? [], [images]);

  return (
    <div className="flex min-h-0 flex-1">
      <div className="flex min-h-0 flex-1 flex-col">
        <div className="flex items-center gap-2 border-b px-6 py-4">
          <Sparkles className="size-5 text-primary" />
          <h1 className="text-xl font-semibold tracking-tight">生图工作区</h1>
          <span className="text-xs text-stone-500">文生图 / 上传底图做图生图（gpt-image-2·low）</span>
        </div>

        <ScrollArea className="min-h-0 flex-1">
          <div className="mx-auto max-w-3xl px-6 py-5">
            {/* 生成表单 */}
            <div className="rounded-2xl border bg-card p-3 shadow-sm">
              <Textarea
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                rows={3}
                placeholder="描述你想要的图片：主体 / 风格 / 构图 / 光影…"
                className="resize-none border-0 bg-transparent shadow-none focus-visible:ring-0 dark:bg-transparent"
              />
              {/* 底图（图生图） */}
              {sourcePreview && (
                <div className="mb-2 flex items-center gap-2 px-1">
                  <img src={sourcePreview} alt="底图" className="size-12 rounded-md object-cover" />
                  <span className="text-xs text-stone-400">底图（将按提示词修改）</span>
                  <button onClick={clearSource} className="ml-auto text-stone-500 hover:text-foreground">
                    <X className="size-4" />
                  </button>
                </div>
              )}
              <div className="flex flex-wrap items-center gap-2 px-1">
                <input ref={fileRef} type="file" accept=".png,.jpg,.jpeg,.webp" className="hidden" onChange={(e) => onPickSource(e.target.files)} />
                <Button variant="ghost" size="sm" disabled={uploading} onClick={() => fileRef.current?.click()} className="gap-1.5 text-stone-400 hover:text-foreground">
                  {uploading ? <Loader2 className="size-4 animate-spin" /> : <Paperclip className="size-4" />}
                  上传底图
                </Button>
                <Select value={size} onValueChange={setSize}>
                  <SelectTrigger size="sm" className="w-28"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {SIZES.map((s) => <SelectItem key={s.value} value={s.value}>{s.label}</SelectItem>)}
                  </SelectContent>
                </Select>
                <Select value={count} onValueChange={setCount}>
                  <SelectTrigger size="sm" className="w-20"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {["1", "2", "3", "4"].map((n) => <SelectItem key={n} value={n}>{n} 张</SelectItem>)}
                  </SelectContent>
                </Select>
                <Button onClick={() => void generate()} disabled={!prompt.trim() || generating || uploading} className="ml-auto gap-1.5 bg-primary text-primary-foreground hover:bg-primary/85">
                  {generating ? <Loader2 className="size-4 animate-spin" /> : <ImagePlus className="size-4" />}
                  {generating ? "生成中…" : "生成"}
                </Button>
              </div>
            </div>

            {/* 历史网格 */}
            <div className="mt-6">
              <div className="mb-2 text-xs font-medium tracking-wide text-stone-500 uppercase">生成历史</div>
              {images === null ? (
                <div className="grid grid-cols-3 gap-3 sm:grid-cols-4">
                  {Array.from({ length: 8 }).map((_, i) => <Skeleton key={i} className="aspect-square rounded-lg" />)}
                </div>
              ) : hist.length === 0 ? (
                <div className="py-12 text-center text-sm text-stone-500">还没有生成过图片。在上面写提示词，点“生成”。</div>
              ) : (
                <div className="grid grid-cols-3 gap-3 sm:grid-cols-4">
                  {hist.map((a) => <HistThumb key={a.resourceKey} art={a} onClick={() => setSelected(a)} />)}
                </div>
              )}
            </div>
          </div>
        </ScrollArea>
      </div>

      {/* 详情预览（复用工作区） */}
      {selected && (
        <div className="flex w-[420px] shrink-0 flex-col border-l">
          <div className="flex items-center gap-2 border-b px-3 py-2">
            <span className="min-w-0 flex-1 truncate text-sm text-foreground">{selected.fileName || selected.name}</span>
            <Button variant="ghost" size="icon" onClick={() => setSelected(null)} aria-label="关闭" className="size-7 text-stone-400 hover:text-foreground">
              <X />
            </Button>
          </div>
          <div className="min-h-0 flex-1">
            <ArtifactWorkspace artifacts={[toRef(selected)]} />
          </div>
        </div>
      )}
    </div>
  );
}
