import { useState } from "react";

export function LoginView({ onLogin }: { onLogin: (name: string) => void }) {
  const [name, setName] = useState("");
  return (
    <div className="flex h-full items-center justify-center p-6">
      <div className="w-full max-w-sm rounded-2xl border border-white/10 bg-white/[0.03] p-6">
        <div className="mb-1 text-2xl font-semibold">
          <span className="text-cyan-400">my</span>-agent
        </div>
        <div className="mb-6 text-sm text-slate-400">多智能体应用平台 · 输入用户名进入</div>
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && onLogin(name)}
          placeholder="用户名（作为 X-User-Id）"
          className="mb-3 w-full rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm text-slate-100 outline-none placeholder:text-slate-600"
        />
        <button
          onClick={() => onLogin(name)}
          disabled={!name.trim()}
          className="w-full rounded-xl bg-cyan-600 px-3 py-2 text-sm font-medium text-white hover:bg-cyan-500 disabled:opacity-40"
        >
          进入平台
        </button>
        <div className="mt-4 text-[11px] leading-relaxed text-slate-600">
          单用户模式：用户名即身份（X-User-Id），用于 run/产物的归属校验。多租户/真鉴权为后续拓展点。
        </div>
      </div>
    </div>
  );
}
