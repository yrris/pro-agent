import { useEffect, useMemo, useState } from "react";
import { FileImage, FileText, FolderOpen, RotateCw, Search, X } from "lucide-react";
import { listArtifacts, type OwnerArtifact } from "../lib/api/client";
import type { ArtifactRef } from "../lib/sse/frameTypes";
import { ArtifactWorkspace, useAuthedObjectUrl } from "./ArtifactWorkspace";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

// 侧栏"产物"导航 = 跨会话产物画廊（对齐 Claude 官网 Artifacts 页）：
// GET /artifacts（owner 域，已去重）→ 卡片网格（图片带缩略图）+ 搜索/类型筛选；
// 点卡片 → 右侧详情复用 ChatView 同款 ArtifactWorkspace（预览+下载+跳回来源会话）。

// OwnerArtifact → ArtifactRef（ArtifactWorkspace 的入参形状；画廊产物恒非 missing）。
function toRef(a: OwnerArtifact): ArtifactRef {
  return {
    resourceKey: a.resourceKey,
    name: a.name || a.fileName,
    fileName: a.fileName || a.name,
    previewUrl: a.previewUrl || `/artifacts/${a.resourceKey}`,
    downloadUrl: a.downloadUrl || `/artifacts/${a.resourceKey}`,
    mimeType: a.mimeType,
    size: a.size,
    missing: false,
  };
}

function kindOf(mime: string): "image" | "doc" {
  return mime.startsWith("image/") ? "image" : "doc";
}

function Thumb({ art }: { art: OwnerArtifact }) {
  const isImg = art.mimeType.startsWith("image/");
  const objUrl = useAuthedObjectUrl(`/artifacts/${art.resourceKey}`, isImg);
  if (isImg) {
    return objUrl ? (
      <img src={objUrl} alt={art.fileName} className="h-28 w-full rounded-t-xl object-cover" />
    ) : (
      <Skeleton className="h-28 w-full rounded-t-xl" />
    );
  }
  return (
    <div className="flex h-28 w-full items-center justify-center rounded-t-xl bg-black/20">
      <FileText className="size-9 text-stone-500" />
    </div>
  );
}

export function ArtifactsGallery({ onOpenSession }: { onOpenSession?: (sessionId: string) => void }) {
  const [items, setItems] = useState<OwnerArtifact[] | null>(null);
  const [q, setQ] = useState("");
  const [kind, setKind] = useState<"all" | "image" | "doc">("all");
  const [selected, setSelected] = useState<OwnerArtifact | null>(null);

  const refresh = () => {
    setItems(null);
    void listArtifacts(200)
      .then(setItems)
      .catch(() => setItems([]));
  };
  useEffect(refresh, []);

  const filtered = useMemo(() => {
    const list = items ?? [];
    const needle = q.trim().toLowerCase();
    return list.filter((a) => {
      if (kind !== "all" && kindOf(a.mimeType) !== kind) return false;
      if (needle && !(a.fileName || a.name).toLowerCase().includes(needle)) return false;
      return true;
    });
  }, [items, q, kind]);

  return (
    <div className="flex min-h-0 flex-1">
      <div className="flex min-h-0 flex-1 flex-col">
        {/* 页头 */}
        <div className="flex items-center gap-2 border-b px-6 py-4">
          <FolderOpen className="size-5 text-primary" />
          <h1 className="text-xl font-semibold tracking-tight">产物</h1>
          <span className="text-xs text-stone-500">跨会话生成的图片、报告、网页等</span>
          <Button
            variant="ghost"
            size="icon"
            onClick={refresh}
            aria-label="刷新"
            className="ml-auto size-8 text-stone-400 hover:text-foreground"
          >
            <RotateCw />
          </Button>
        </div>
        {/* 搜索 + 类型筛选 */}
        <div className="flex items-center gap-2 px-6 py-3">
          <div className="relative min-w-0 flex-1">
            <Search className="absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-stone-500" />
            <Input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="搜索产物名…"
              className="h-9 pl-8"
            />
          </div>
          <Select value={kind} onValueChange={(v) => setKind(v as typeof kind)}>
            <SelectTrigger size="sm" className="w-28">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">全部类型</SelectItem>
              <SelectItem value="image">图片</SelectItem>
              <SelectItem value="doc">文档</SelectItem>
            </SelectContent>
          </Select>
        </div>
        {/* 网格 */}
        <ScrollArea className="min-h-0 flex-1">
          <div className="px-6 pb-8">
            {items === null && (
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
                {Array.from({ length: 8 }).map((_, i) => (
                  <Skeleton key={i} className="h-44 rounded-xl" />
                ))}
              </div>
            )}
            {items !== null && filtered.length === 0 && (
              <div className="flex flex-col items-center justify-center py-20 text-center text-sm text-stone-500">
                <FileImage className="mb-2 size-8 text-stone-600" />
                {items.length === 0 ? "还没有任何产物。生成图片/报告/网页后会归档在这里。" : "没有匹配的产物。"}
              </div>
            )}
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
              {filtered.map((a) => (
                <button
                  key={a.resourceKey}
                  onClick={() => setSelected(a)}
                  className={`overflow-hidden rounded-xl border text-left transition-colors hover:border-primary/50 ${
                    selected?.resourceKey === a.resourceKey ? "border-primary/60" : "border-border"
                  }`}
                >
                  <Thumb art={a} />
                  <div className="p-2.5">
                    <div className="truncate text-sm text-stone-200">{a.fileName || a.name}</div>
                    <div className="mt-0.5 truncate text-[10px] text-stone-500">{a.mimeType || "文件"}</div>
                  </div>
                </button>
              ))}
            </div>
          </div>
        </ScrollArea>
      </div>
      {/* 详情：复用 ChatView 同款工作区（单产物） */}
      {selected && (
        <div className="flex w-[420px] shrink-0 flex-col border-l">
          <div className="flex items-center gap-2 border-b px-3 py-2">
            <span className="min-w-0 flex-1 truncate text-sm text-foreground">{selected.fileName || selected.name}</span>
            {onOpenSession && (
              <Button
                variant="ghost"
                size="sm"
                className="h-7 text-xs text-stone-400 hover:text-foreground"
                onClick={() => onOpenSession(selected.sessionId)}
              >
                打开来源会话
              </Button>
            )}
            <Button
              variant="ghost"
              size="icon"
              onClick={() => setSelected(null)}
              aria-label="关闭"
              className="size-7 text-stone-400 hover:text-foreground"
            >
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
