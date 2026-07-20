import { useCallback, useEffect, useState } from "react";
import { Shield } from "lucide-react";
import { toast } from "sonner";
import {
  adminStats,
  listAllRuns,
  listUsers,
  setUserRole,
  type AdminRun,
  type AdminUser,
  type UsageReport,
} from "../lib/api/client";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

// D3 管理后台（docs/17 §3.4）：页头 + Tabs 分区（用户 / 全部运行 / 系统用量）。
// 列表用 div 行（不引 table）；跨 owner 数据全走 /admin/*（后端 requireAdmin 门控，前端仅展示）。
// currentUserId 用于用户行禁用"给自己降权"（后端也会 400，前端先行拦一道 UX）。

function fmtDate(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleString();
}

function UsersTab({ currentUserId }: { currentUserId: string }) {
  const [users, setUsers] = useState<AdminUser[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setUsers(await listUsers());
    } catch {
      setUsers([]);
      toast.error("用户列表加载失败");
    }
  }, []);
  useEffect(() => {
    void refresh();
  }, [refresh]);

  const toggleRole = async (u: AdminUser) => {
    const next = u.role === "admin" ? "user" : "admin";
    setBusy(u.userId);
    try {
      await setUserRole(u.userId, next);
      toast.success(`已将 ${u.username} 设为${next === "admin" ? "管理员" : "普通用户"}`);
      await refresh();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "改角色失败");
    } finally {
      setBusy(null);
    }
  };

  return (
    <ScrollArea className="min-h-0 flex-1">
      <div className="space-y-1.5 px-6 py-3" data-testid="admin-users">
        {users === null && <div className="p-3 text-xs text-muted-foreground/70">加载中…</div>}
        {users?.length === 0 && <div className="p-3 text-xs text-muted-foreground/70">还没有用户。</div>}
        {users?.map((u) => (
          <div
            key={u.userId}
            className="flex items-center gap-3 rounded-lg border border-transparent px-3 py-2 hover:border-border hover:bg-accent/50"
            data-testid="admin-user-row"
          >
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <span className="truncate text-sm text-foreground">{u.username}</span>
                <Badge variant={u.role === "admin" ? "default" : "secondary"}>{u.role}</Badge>
              </div>
              <div className="mt-0.5 text-[10px] text-muted-foreground/70">
                {u.runCount} 次运行 · 注册于 {fmtDate(u.createdAt)}
              </div>
            </div>
            <Button
              variant="outline"
              size="sm"
              className="h-7 text-xs"
              disabled={busy === u.userId || u.userId === currentUserId}
              title={u.userId === currentUserId ? "不能修改自己的角色" : ""}
              onClick={() => void toggleRole(u)}
            >
              {u.role === "admin" ? "降为普通" : "设为管理员"}
            </Button>
          </div>
        ))}
      </div>
    </ScrollArea>
  );
}

function statusColor(s: string): string {
  if (s === "SUCCESS") return "text-success";
  if (s === "RUNNING") return "text-primary";
  return "text-destructive";
}

function RunsTab() {
  const [runs, setRuns] = useState<AdminRun[] | null>(null);
  const refresh = useCallback(async () => {
    try {
      setRuns(await listAllRuns(100));
    } catch {
      setRuns([]);
      toast.error("运行列表加载失败");
    }
  }, []);
  useEffect(() => {
    void refresh();
  }, [refresh]);

  return (
    <ScrollArea className="min-h-0 flex-1">
      <div className="space-y-1 px-6 py-3" data-testid="admin-runs">
        {runs === null && <div className="p-3 text-xs text-muted-foreground/70">加载中…</div>}
        {runs?.length === 0 && <div className="p-3 text-xs text-muted-foreground/70">还没有任何运行。</div>}
        {runs?.map((r) => (
          <div
            key={r.runId}
            className="flex items-center gap-3 rounded-lg border border-transparent px-3 py-2 hover:border-border hover:bg-accent/50"
            data-testid="admin-run-row"
          >
            <div className="min-w-0 flex-1">
              <div className="truncate text-sm text-foreground">{r.query || "（无查询）"}</div>
              <div className="mt-0.5 flex items-center gap-1.5 text-[10px] text-muted-foreground/70">
                <Badge variant="secondary">{r.ownerId}</Badge>
                <span>{r.agentType}</span>
                <span>·</span>
                <span>{fmtDate(r.createdAt)}</span>
              </div>
            </div>
            <span className={`shrink-0 text-xs ${statusColor(r.status)}`}>{r.status}</span>
          </div>
        ))}
      </div>
    </ScrollArea>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg border p-4">
      <div className="text-[11px] uppercase tracking-wide text-muted-foreground/70">{label}</div>
      <div className="mt-1 text-2xl font-semibold text-foreground">{value.toLocaleString()}</div>
    </div>
  );
}

function StatsTab() {
  const [report, setReport] = useState<UsageReport | null>(null);
  const [failed, setFailed] = useState(false); // #16：与 report 分离的"已失败"态，区分加载中 vs 加载失败
  const refresh = useCallback(async () => {
    setFailed(false); // 进入/重试即回"加载中"，直到成功或再次失败
    try {
      setReport(await adminStats(30));
    } catch {
      setFailed(true); // 置错误态：不再永久卡"加载中…"，给出错误提示 + 重试入口
      toast.error("系统用量加载失败");
    }
  }, []);
  useEffect(() => {
    void refresh();
  }, [refresh]);

  return (
    <ScrollArea className="min-h-0 flex-1">
      <div className="space-y-5 px-6 py-4" data-testid="admin-stats">
        {report ? (
          <>
            <div className="text-xs text-muted-foreground/70">最近 {report.days} 天，全平台跨用户聚合。</div>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <Stat label="运行数" value={report.totals.runs} />
              <Stat label="输入 token" value={report.totals.inputTokens} />
              <Stat label="输出 token" value={report.totals.outputTokens} />
              <Stat label="模型调用" value={report.totals.modelCalls} />
            </div>
            <div>
              <div className="mb-2 text-sm font-medium text-foreground/90">按模式</div>
              <div className="space-y-1">
                {report.byAgent.length === 0 && <div className="text-xs text-muted-foreground/70">暂无数据。</div>}
                {report.byAgent.map((a) => (
                  <div key={a.agentType} className="flex items-center justify-between rounded-lg border px-3 py-2 text-sm">
                    <span className="text-foreground/90">{a.agentType}</span>
                    <span className="text-muted-foreground/70">
                      {a.runs} 次 · {a.inputTokens + a.outputTokens} token
                    </span>
                  </div>
                ))}
              </div>
            </div>
          </>
        ) : failed ? (
          <div className="flex items-center gap-3 p-3 text-xs text-muted-foreground/70" data-testid="admin-stats-error">
            <span>系统用量加载失败。</span>
            <Button variant="outline" size="sm" className="h-7 text-xs" onClick={() => void refresh()}>
              重试
            </Button>
          </div>
        ) : (
          <div className="p-3 text-xs text-muted-foreground/70">加载中…</div>
        )}
      </div>
    </ScrollArea>
  );
}

export function AdminPanel({ currentUserId }: { currentUserId: string }) {
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {/* 页头（照 ArtifactsGallery 范式） */}
      <div className="flex items-center gap-2 border-b px-6 py-4">
        <Shield className="size-5 text-primary" />
        <h1 className="text-xl font-semibold tracking-tight">管理后台</h1>
        <span className="text-xs text-muted-foreground/70">用户 · 全部运行 · 系统用量（跨 owner）</span>
      </div>
      <Tabs defaultValue="users" className="flex min-h-0 flex-1 flex-col gap-0">
        <div className="px-6 py-3">
          <TabsList data-testid="admin-tabs">
            <TabsTrigger value="users">用户</TabsTrigger>
            <TabsTrigger value="runs">全部运行</TabsTrigger>
            <TabsTrigger value="stats">系统用量</TabsTrigger>
          </TabsList>
        </div>
        <TabsContent value="users" className="flex min-h-0 flex-col">
          <UsersTab currentUserId={currentUserId} />
        </TabsContent>
        <TabsContent value="runs" className="flex min-h-0 flex-col">
          <RunsTab />
        </TabsContent>
        <TabsContent value="stats" className="flex min-h-0 flex-col">
          <StatsTab />
        </TabsContent>
      </Tabs>
    </div>
  );
}
