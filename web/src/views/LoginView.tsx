import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";

export function LoginView({ onLogin }: { onLogin: (name: string) => void }) {
  const [name, setName] = useState("");
  return (
    <div className="flex h-full items-center justify-center p-6">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle className="text-2xl font-semibold">
            <span className="text-cyan-400">my</span>-agent
          </CardTitle>
          <CardDescription>多智能体应用平台 · 输入用户名进入</CardDescription>
        </CardHeader>
        <CardContent>
          <Input
            value={name}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && onLogin(name)}
            placeholder="用户名（作为 X-User-Id）"
            className="mb-3"
          />
          <Button onClick={() => onLogin(name)} disabled={!name.trim()} className="w-full">
            进入平台
          </Button>
          <div className="mt-4 text-[11px] leading-relaxed text-slate-600">
            单用户模式：用户名即身份（X-User-Id），用于 run/产物的归属校验。多租户/真鉴权为后续拓展点。
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
