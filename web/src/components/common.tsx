import { useState, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

export function Markdown({ children }: { children: string }) {
  return (
    <div className="prose-sm leading-relaxed break-words [&_pre]:overflow-auto [&_pre]:rounded-lg [&_pre]:bg-black/40 [&_pre]:p-3 [&_code]:text-cyan-300 [&_a]:text-cyan-400 [&_a]:underline [&_ul]:list-disc [&_ul]:pl-5 [&_ol]:list-decimal [&_ol]:pl-5 [&_h1]:font-semibold [&_h2]:font-semibold [&_h3]:font-semibold">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{children}</ReactMarkdown>
    </div>
  );
}

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
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="rounded-xl border border-white/10 bg-white/[0.03]">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-white/[0.04]"
      >
        <span className={`text-xs text-slate-400 transition-transform ${open ? "rotate-90" : ""}`}>▶</span>
        <span className="flex-1 min-w-0 truncate">{title}</span>
        {right}
      </button>
      {open && <div className="border-t border-white/10 px-3 py-2 text-sm">{children}</div>}
    </div>
  );
}

const STATUS_STYLE: Record<string, string> = {
  running: "bg-blue-500/15 text-blue-300 border-blue-500/30",
  success: "bg-emerald-500/15 text-emerald-300 border-emerald-500/30",
  failed: "bg-rose-500/15 text-rose-300 border-rose-500/30",
};

export function ToolStatusBadge({ status }: { status: string }) {
  const cls = STATUS_STYLE[status] ?? "bg-slate-500/15 text-slate-300 border-slate-500/30";
  return (
    <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs ${cls}`}>
      {status === "running" && <span className="pulse-dot">●</span>}
      {status}
    </span>
  );
}

export function ProviderTag({ provider }: { provider: string }) {
  const cls =
    provider === "mcp"
      ? "bg-violet-500/15 text-violet-300"
      : provider === "skill"
        ? "bg-amber-500/15 text-amber-300"
        : "bg-slate-500/15 text-slate-300";
  return <span className={`rounded px-1.5 py-0.5 text-[10px] uppercase ${cls}`}>{provider}</span>;
}
