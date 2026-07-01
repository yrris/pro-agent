import { useEffect, useState } from "react";
import type { ArtifactRef } from "../lib/sse/frameTypes";
import { downloadArtifact } from "../lib/api/client";
import { getUserId } from "../lib/identity";

function human(size: number) {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

function FilePreview({ art }: { art: ArtifactRef }) {
  const url = `/artifacts/${art.resourceKey}`;
  const mime = art.mimeType || "";
  if (art.missing) return <div className="p-4 text-sm text-slate-500">文件已删除或不可用</div>;
  if (mime.startsWith("image/")) return <img src={url} alt={art.name} className="max-h-80 rounded-lg" />;
  if (mime === "application/pdf") return <iframe src={url} title={art.name} className="h-96 w-full rounded-lg bg-white" />;
  if (mime.startsWith("text/") || mime.includes("json") || mime.includes("markdown"))
    return <TextPreview url={url} />;
  return <div className="p-4 text-sm text-slate-400">该类型（{mime || "未知"}）暂不支持内联预览，请下载查看。</div>;
}

function TextPreview({ url }: { url: string }) {
  const [text, setText] = useState<string>("加载中…");
  useEffect(() => {
    let alive = true;
    void fetch(url, { headers: { "X-User-Id": getUserId() || "anonymous" } })
      .then((r) => r.text())
      .then((t) => alive && setText(t.slice(0, 20000)))
      .catch(() => alive && setText("（预览失败）"));
    return () => {
      alive = false;
    };
  }, [url]);
  return <pre className="max-h-80 overflow-auto whitespace-pre-wrap rounded-lg bg-black/30 p-3 text-xs text-slate-200">{text}</pre>;
}

export function ArtifactWorkspace({ artifacts }: { artifacts: ArtifactRef[] }) {
  const [active, setActive] = useState<string | null>(null);
  const current = artifacts.find((a) => a.resourceKey === active) ?? artifacts[artifacts.length - 1];

  if (artifacts.length === 0) {
    return (
      <div className="flex h-full items-center justify-center p-6 text-center text-sm text-slate-500">
        产物工作区
        <br />
        运行产出的文件（报告、图表等）会出现在这里，可预览与下载。
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-white/10 p-3 text-sm font-medium text-slate-300">产物工作区 ({artifacts.length})</div>
      <div className="flex flex-wrap gap-2 border-b border-white/10 p-3">
        {artifacts.map((a) => (
          <button
            key={a.resourceKey}
            onClick={() => setActive(a.resourceKey)}
            className={`rounded-lg border px-2 py-1 text-xs ${
              current?.resourceKey === a.resourceKey
                ? "border-cyan-500/50 bg-cyan-500/10 text-cyan-200"
                : "border-white/10 text-slate-300 hover:bg-white/5"
            } ${a.missing ? "opacity-50" : ""}`}
          >
            {a.fileName || a.name}
          </button>
        ))}
      </div>
      {current && (
        <div className="flex-1 overflow-auto p-3">
          <div className="mb-2 flex items-center gap-2">
            <span className="min-w-0 flex-1 truncate text-sm text-slate-200">{current.fileName || current.name}</span>
            <span className="text-xs text-slate-500">{human(current.size)}</span>
            <button
              onClick={() => void downloadArtifact(current.resourceKey, current.fileName || current.name)}
              className="rounded-lg bg-cyan-600/30 px-2 py-1 text-xs text-cyan-100 hover:bg-cyan-600/50"
            >
              下载
            </button>
          </div>
          <FilePreview art={current} />
        </div>
      )}
    </div>
  );
}
