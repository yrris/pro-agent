// 工作区「文件」页签：复用 FilesPanel 的列表形态（Artifacts / 上传内容两段 FileCard）
// + 下方 ArtifactPreview。选中态由父层（WorkspacePanel）托管，focus(artifact) 可直接选中。

import { useMemo } from "react";
import type { ArtifactRef } from "../../lib/sse/frameTypes";
import type { AttachmentRef } from "../../lib/api/client";
import { ArtifactPreview } from "../ArtifactWorkspace";
import { FileCard, uploadToRef } from "../FilesPanel";
import { ScrollArea } from "@/components/ui/scroll-area";

export function FilesTab({
  artifacts,
  uploads,
  selectedKey,
  onSelect,
}: {
  artifacts: ArtifactRef[];
  uploads: AttachmentRef[];
  selectedKey: string | null;
  onSelect: (resourceKey: string) => void;
}) {
  const uploadRefs = useMemo(() => uploads.map(uploadToRef), [uploads]);
  const all = useMemo(() => [...artifacts, ...uploadRefs], [artifacts, uploadRefs]);
  // 默认选中：最新一份产物；无产物则第一份上传（与 FilesPanel 一致）。
  const selected =
    all.find((a) => a.resourceKey === selectedKey) ??
    (artifacts.length > 0 ? artifacts[artifacts.length - 1] : uploadRefs[0]);
  const total = all.length;

  if (total === 0)
    return (
      <div className="flex h-full items-center justify-center p-6 text-center text-sm leading-relaxed text-muted-foreground">
        本对话的产物与上传的文件
        <br />
        会出现在这里，可预览下载。
      </div>
    );

  return (
    <div className="flex h-full min-h-0 flex-col">
      <ScrollArea className="max-h-[45%] shrink-0 border-b">
        <div className="space-y-1 p-2">
          {artifacts.length > 0 && (
            <>
              <div className="px-1 pt-0.5 pb-1 text-[10px] font-medium tracking-wide text-muted-foreground uppercase">
                Artifacts · {artifacts.length}
              </div>
              {artifacts.map((a) => (
                <FileCard
                  key={a.resourceKey}
                  art={a}
                  active={selected?.resourceKey === a.resourceKey}
                  onClick={() => onSelect(a.resourceKey)}
                />
              ))}
            </>
          )}
          {uploadRefs.length > 0 && (
            <>
              <div className="px-1 pt-1.5 pb-1 text-[10px] font-medium tracking-wide text-muted-foreground uppercase">
                上传内容 · {uploadRefs.length}
              </div>
              {uploadRefs.map((a) => (
                <FileCard
                  key={a.resourceKey}
                  art={a}
                  active={selected?.resourceKey === a.resourceKey}
                  onClick={() => onSelect(a.resourceKey)}
                />
              ))}
            </>
          )}
        </div>
      </ScrollArea>
      <div className="min-h-0 flex-1">{selected && <ArtifactPreview art={selected} />}</div>
    </div>
  );
}
