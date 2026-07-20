// 工作区「动态」页签：顶部产物翻页器（驱动 ArtifactPreview）+ 下方时序 feed
// （artifact 项 / web_search 来源组，图片项带缩略）。focus(sources) 由父层传 scrollTo 滚到对应组。

import { useEffect, useMemo, useRef, useState } from "react";
import { BarChart3, ChevronLeft, ChevronRight, FileText, Globe, Image as ImageIcon } from "lucide-react";
import type { ArtifactRef } from "../../lib/sse/frameTypes";
import { sourceHostname } from "../../lib/sse/toolPayloads";
import { isChartArtifact, type ActivityItem } from "../../lib/workspaceFeed";
import { ArtifactPreview, useAuthedObjectUrl } from "../ArtifactWorkspace";
import { ScrollArea } from "@/components/ui/scroll-area";

function human(size: number) {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

// feed 里的 artifact 行：类型图标（图表/图片/文件）+ 文件名 + 大小；图片带缩略；点击切 pager。
function ArtifactRow({
  art,
  toolName,
  active,
  onClick,
}: {
  art: ArtifactRef;
  toolName?: string;
  active: boolean;
  onClick: () => void;
}) {
  const name = art.fileName || art.name;
  const mime = art.mimeType || "";
  const isImg = mime.startsWith("image/");
  const thumb = useAuthedObjectUrl(`/artifacts/${art.resourceKey}`, isImg && !art.missing);
  const Icon = isChartArtifact({ name, mimeType: mime }) ? BarChart3 : isImg ? ImageIcon : FileText;
  return (
    <button
      onClick={onClick}
      title={name}
      className={`flex w-full items-center gap-2 rounded-lg border px-2 py-1.5 text-left transition-colors ${
        active ? "border-primary/50 bg-primary/10" : "border-border/60 hover:border-border hover:bg-accent/50"
      }`}
    >
      <span className="flex size-8 shrink-0 items-center justify-center overflow-hidden rounded bg-muted">
        {isImg && thumb ? (
          <img src={thumb} alt="" className="size-full object-cover" />
        ) : (
          <Icon className="size-4 text-muted-foreground" />
        )}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-xs text-foreground">{name}</span>
        <span className="block truncate text-[10px] text-muted-foreground">
          {human(art.size)}
          {toolName ? ` · ${toolName}` : ""}
        </span>
      </span>
    </button>
  );
}

function SourcesGroup({ item }: { item: Extract<ActivityItem, { kind: "sources" }> }) {
  return (
    <div className="space-y-1">
      <div className="flex items-center gap-1.5 px-1 text-xs text-muted-foreground">
        <Globe className="size-3.5 shrink-0" />
        <span className="min-w-0 truncate">{item.query || "网页搜索"}</span>
        <span className="shrink-0 text-[10px] text-muted-foreground/70">{item.sources.length} 个来源</span>
      </div>
      {item.sources.map((s, i) => (
        <a
          key={`${s.url}-${i}`}
          href={s.url}
          target="_blank"
          rel="noopener noreferrer"
          className="block rounded-lg border border-border/60 px-2 py-1.5 transition-colors hover:border-border hover:bg-accent/50"
        >
          <span className="block truncate text-xs text-foreground">{s.title}</span>
          <span className="block truncate text-[10px] text-muted-foreground">{sourceHostname(s.url)}</span>
          {s.snippet && (
            <span className="mt-0.5 line-clamp-2 block text-[11px] leading-snug text-muted-foreground/80">
              {s.snippet}
            </span>
          )}
        </a>
      ))}
    </div>
  );
}

export function ActivityTab({
  artifacts,
  activity,
  scrollTo,
  onScrolled,
}: {
  artifacts: ArtifactRef[];
  activity: ActivityItem[];
  scrollTo: string | null; // sources 组的 toolCallId
  onScrolled: () => void;
}) {
  // 翻页器：null=跟随最新（"生成即所见"），新产物到达自动回落最新。
  const [idx, setIdx] = useState<number | null>(null);
  const prevLen = useRef(artifacts.length);
  useEffect(() => {
    if (artifacts.length > prevLen.current) setIdx(null);
    prevLen.current = artifacts.length;
  }, [artifacts.length]);
  const current = idx == null ? artifacts.length - 1 : Math.min(idx, artifacts.length - 1);
  const indexByKey = useMemo(
    () => new Map(artifacts.map((a, i) => [a.resourceKey, i])),
    [artifacts],
  );

  // focus(sources)：滚到对应来源组
  const groupRefs = useRef(new Map<string, HTMLDivElement>());
  useEffect(() => {
    if (!scrollTo) return;
    groupRefs.current.get(scrollTo)?.scrollIntoView({ behavior: "smooth", block: "start" });
    onScrolled();
  }, [scrollTo, onScrolled]);

  if (artifacts.length === 0 && activity.length === 0)
    return (
      <div className="flex h-full items-center justify-center p-6 text-center text-sm leading-relaxed text-muted-foreground">
        运行产物与搜索来源会实时出现在这里
      </div>
    );

  return (
    <div className="flex h-full min-h-0 flex-col">
      {artifacts.length > 0 && (
        <div className="flex min-h-0 flex-[3] flex-col border-b">
          <div
            data-testid="artifact-pager"
            className="flex items-center justify-center gap-1 border-b px-2 py-1"
          >
            <button
              onClick={() => setIdx(Math.max(0, current - 1))}
              disabled={current <= 0}
              aria-label="上一个产物"
              className="rounded p-1 text-muted-foreground transition-colors hover:text-foreground disabled:pointer-events-none disabled:opacity-40"
            >
              <ChevronLeft className="size-4" />
            </button>
            <span className="text-xs text-muted-foreground tabular-nums">
              {current + 1}/{artifacts.length}
            </span>
            <button
              onClick={() => setIdx(Math.min(artifacts.length - 1, current + 1))}
              disabled={current >= artifacts.length - 1}
              aria-label="下一个产物"
              className="rounded p-1 text-muted-foreground transition-colors hover:text-foreground disabled:pointer-events-none disabled:opacity-40"
            >
              <ChevronRight className="size-4" />
            </button>
          </div>
          <div className="min-h-0 flex-1">
            {artifacts[current] && <ArtifactPreview art={artifacts[current]} />}
          </div>
        </div>
      )}
      <ScrollArea className="min-h-0 flex-[2]">
        <div className="space-y-2 p-2">
          {activity.map((item) =>
            item.kind === "artifact" ? (
              <ArtifactRow
                key={item.art.resourceKey}
                art={item.art}
                toolName={item.toolName}
                active={indexByKey.get(item.art.resourceKey) === current}
                onClick={() => {
                  const i = indexByKey.get(item.art.resourceKey);
                  if (i != null) setIdx(i);
                }}
              />
            ) : (
              <div
                key={item.toolCallId}
                ref={(el) => {
                  if (el) groupRefs.current.set(item.toolCallId, el);
                  else groupRefs.current.delete(item.toolCallId);
                }}
              >
                <SourcesGroup item={item} />
              </div>
            ),
          )}
        </div>
      </ScrollArea>
    </div>
  );
}
