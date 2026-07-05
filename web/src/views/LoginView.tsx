import { useState } from "react";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";

// D3（docs/17）：密码登录 + 自助注册切换。前端 gate 非安全边界——真校验在后端（bcrypt +
// requireAdmin）。提交 async：成功由上层跳转，失败展示后端 message（用户名或密码错误 / 已被占用）。
export function LoginView({
  onLogin,
  onRegister,
}: {
  onLogin: (username: string, password: string) => Promise<void>;
  onRegister: (username: string, password: string) => Promise<void>;
}) {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const canSubmit = username.trim().length > 0 && password.length >= 6 && !busy;

  const submit = async () => {
    if (!canSubmit) return;
    setBusy(true);
    setError("");
    try {
      if (mode === "login") await onLogin(username.trim(), password);
      else await onRegister(username.trim(), password);
    } catch (e) {
      setError(e instanceof Error ? e.message : "操作失败，请重试");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex h-full items-center justify-center p-6">
      <Card className="w-full max-w-sm" data-testid="login-card">
        <CardHeader>
          <CardTitle className="text-2xl font-semibold">
            <span className="text-primary">pro</span>-agent
          </CardTitle>
          <CardDescription>
            {mode === "login" ? "登录进入多智能体应用平台" : "注册新账号"}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Input
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            placeholder="用户名"
            autoComplete="username"
            className="mb-3"
            data-testid="login-username"
          />
          <Input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && void submit()}
            placeholder="密码（至少 6 位）"
            autoComplete={mode === "login" ? "current-password" : "new-password"}
            className="mb-3"
            data-testid="login-password"
          />
          {error && (
            <div className="mb-3 text-xs text-destructive" data-testid="login-error">
              {error}
            </div>
          )}
          <Button
            onClick={() => void submit()}
            disabled={!canSubmit}
            className="w-full"
            data-testid="login-submit"
          >
            {busy && <Loader2 className="mr-1 size-4 animate-spin" />}
            {mode === "login" ? "登录" : "注册"}
          </Button>
          <button
            type="button"
            onClick={() => {
              setMode((m) => (m === "login" ? "register" : "login"));
              setError("");
            }}
            className="mt-4 w-full text-center text-xs text-stone-500 hover:text-foreground"
            data-testid="login-toggle"
          >
            {mode === "login" ? "没有账号？注册一个" : "已有账号？去登录"}
          </button>
          <div className="mt-4 text-[11px] leading-relaxed text-stone-600">
            账号即身份（owner），用于 run/产物/知识库的归属与隔离。管理员可在管理后台管理用户与查看系统用量。
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
