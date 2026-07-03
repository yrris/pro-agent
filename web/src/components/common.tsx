import { type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import rehypeHighlight from "rehype-highlight";
import "highlight.js/styles/github-dark-dimmed.css";
import remarkGfm from "remark-gfm";
import { Badge } from "@/components/ui/badge";
import {
  Collapsible as UICollapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";

export function Markdown({ children }: { children: string }) {
  return (
    <div className="prose-sm leading-relaxed break-words [&_pre]:overflow-auto [&_pre]:rounded-lg [&_pre]:bg-black/40 [&_pre]:p-3 [&_:not(pre)>code]:text-amber-200/90 [&_pre_code]:bg-transparent [&_a]:text-primary [&_a]:underline [&_ul]:list-disc [&_ul]:pl-5 [&_ol]:list-decimal [&_ol]:pl-5 [&_h1]:font-semibold [&_h2]:font-semibold [&_h3]:font-semibold">
      <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeHighlight]}>{children}</ReactMarkdown>
    </div>
  );
}

// 换装说明：导出名与 props 签名保持 M6 原样（调用方 chat.tsx 零改动），
// 内部改为 shadcn/Radix Collapsible；▶ caret 用 data-state 驱动旋转。
export function Collapsible({
  title,
  defaultOpen = false,
  children,
  right,
}: {
  title: ReactNode;
  defaultOpen?: boolean;
  children: ReactNode;
  right?: ReactNode;
}) {
  return (
    <UICollapsible defaultOpen={defaultOpen} className="rounded-xl border bg-card">
      <CollapsibleTrigger className="group flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-white/[0.04]">
        <span className="text-xs text-stone-400 transition-transform group-data-[state=open]:rotate-90">
          ▶
        </span>
        <span className="min-w-0 flex-1 truncate">{title}</span>
        {right}
      </CollapsibleTrigger>
      <CollapsibleContent className="border-t px-3 py-2 text-sm">{children}</CollapsibleContent>
    </UICollapsible>
  );
}

const STATUS_STYLE: Record<string, string> = {
  running: "bg-blue-500/15 text-blue-300 border-blue-500/30",
  success: "bg-emerald-500/15 text-emerald-300 border-emerald-500/30",
  failed: "bg-rose-500/15 text-rose-300 border-rose-500/30",
};

export function ToolStatusBadge({ status }: { status: string }) {
  const cls = STATUS_STYLE[status] ?? "bg-stone-500/15 text-stone-300 border-stone-500/30";
  return (
    <Badge className={`gap-1 rounded-full font-normal ${cls}`}>
      {status === "running" && <span className="pulse-dot">●</span>}
      {status}
    </Badge>
  );
}

export function ProviderTag({ provider }: { provider: string }) {
  const cls =
    provider === "mcp"
      ? "bg-violet-500/15 text-violet-300"
      : provider === "skill"
        ? "bg-amber-500/15 text-amber-300"
        : "bg-stone-500/15 text-stone-300";
  return (
    <Badge variant="secondary" className={`rounded px-1.5 py-0.5 text-[10px] uppercase ${cls}`}>
      {provider}
    </Badge>
  );
}
