import { memo, useEffect, useState } from "react";
import type { ArtifactRef } from "../lib/sse/frameTypes";
import { downloadArtifact } from "../lib/api/client";
import { getUserId } from "../lib/identity";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";

function human(size: number) {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

function FilePreview({ art }: { art: ArtifactRef }) {
  const url = `/artifacts/${art.resourceKey}`;
  const mime = art.mimeType || "";
  if (art.missing) return <div className="p-4 text-sm text-stone-500">文件已删除或不可用</div>;
  if (mime.startsWith("image/")) return <img src={url} alt={art.name} className="max-h-80 rounded-lg" />;
  if (mime === "application/pdf") return <iframe src={url} title={art.name} className="h-96 w-full rounded-lg bg-white" />;
  if (mime.startsWith("text/") || mime.includes("json") || mime.includes("markdown"))
    return <TextPreview url={url} />;
  return <div className="p-4 text-sm text-stone-400">该类型（{mime || "未知"}）暂不支持内联预览，请下载查看。</div>;
}

function TextPreview({ url }: { url: string }) {
  const [text, setText] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    setText(null);
    void fetch(url, { headers: { "X-User-Id": getUserId() || "anonymous" } })
      .then((r) => r.text())
      .then((t) => alive && setText(t.slice(0, 20000)))
      .catch(() => alive && setText("（预览失败）"));
    return () => {
      alive = false;
    };
  }, [url]);
  if (text === null) {
    return (
      <div className="space-y-2">
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-5/6" />
        <Skeleton className="h-4 w-2/3" />
      </div>
    );
  }
  return <pre className="max-h-80 overflow-auto whitespace-pre-wrap rounded-lg bg-black/30 p-3 text-xs text-stone-200">{text}</pre>;
}

// memo：ChatView 每个流式帧都会重渲，但 artifacts 数组只在产物变化时换引用，
// 工作区（含预览 iframe/图片）无关帧不重渲。
export const ArtifactWorkspace = memo(function ArtifactWorkspace({ artifacts }: { artifacts: ArtifactRef[] }) {
  const [active, setActive] = useState<string | null>(null);
  const current = artifacts.find((a) => a.resourceKey === active) ?? artifacts[artifacts.length - 1];

  if (artifacts.length === 0) {
    return (
      <div className="flex h-full items-center justify-center p-6 text-center text-sm text-stone-500">
        产物工作区
        <br />
        运行产出的文件（报告、图表等）会出现在这里，可预览与下载。
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      <div className="border-b p-3 text-sm font-medium text-stone-300">产物工作区 ({artifacts.length})</div>
      <Tabs value={current?.resourceKey ?? ""} onValueChange={setActive} className="border-b p-3">
        <TabsList className="h-auto flex-wrap justify-start gap-1 bg-transparent p-0">
          {artifacts.map((a) => (
            <TabsTrigger
              key={a.resourceKey}
              value={a.resourceKey}
              className={`rounded-lg border px-2 py-1 text-xs data-[state=active]:border-primary/50 data-[state=active]:bg-primary/10 data-[state=active]:text-primary ${
                a.missing ? "opacity-50" : ""
              }`}
            >
              {a.fileName || a.name}
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>
      {current && (
        <div className="flex-1 overflow-auto p-3">
          <div className="mb-2 flex items-center gap-2">
            <span className="min-w-0 flex-1 truncate text-sm text-stone-200">{current.fileName || current.name}</span>
            <span className="text-xs text-stone-500">{human(current.size)}</span>
            <Button
              size="sm"
              variant="secondary"
              onClick={() => void downloadArtifact(current.resourceKey, current.fileName || current.name)}
              className="h-auto bg-primary px-2 py-1 text-xs text-primary-foreground hover:bg-primary/85"
            >
              下载
            </Button>
          </div>
          <FilePreview art={current} />
        </div>
      )}
    </div>
  );
});
