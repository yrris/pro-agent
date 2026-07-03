import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useAuth } from "./hooks/useAuth";
import { useHealth } from "./hooks/useHealth";
import { useRunStream } from "./hooks/useRunStream";
import { LoginView } from "./views/LoginView";
import { ChatView } from "./views/ChatView";
import { Header } from "./components/Header";
import { Sidebar } from "./components/Sidebar";
import { listServerSessions, type AttachmentRef, type ServerSession } from "./lib/api/client";
import {
  createSession,
  listSessions as listLocalSessions,
  mergeSessions,
  pruneSessions,
  type SessionMeta,
} from "./lib/sessions";
import { loadUiPrefs, saveUiPrefs, clampArtifactsWidth } from "./lib/uiPrefs";
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";

export default function App() {
  const { userId, isAuthed, login, logout } = useAuth();
  const health = useHealth();
  const run = useRunStream();

  const [agentType, setAgentType] = useState("react");
  // UX-1 三栏布局状态：侧栏开合持久化；Artifacts 面板默认关（右上图标开），宽度可拖并记忆。
  const [prefs] = useState(loadUiPrefs);
  const [sidebarOpen, setSidebarOpen] = useState(prefs.sidebarOpen);
  const [artifactsOpen, setArtifactsOpen] = useState(false);
  const [artifactsWidth, setArtifactsWidth] = useState(prefs.artifactsWidth);
  useEffect(() => {
    saveUiPrefs({ sidebarOpen, artifactsWidth });
  }, [sidebarOpen, artifactsWidth]);
  // 会话列表 = 服务端（权威）+ 本地草稿（未落库新会话）两个状态的纯函数派生，
  // 不再手工同步——任何一侧更新，列表自动重算。
  const [serverSessions, setServerSessions] = useState<ServerSession[]>([]);
  const [drafts, setDrafts] = useState<SessionMeta[]>(() => listLocalSessions());
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null);
  const sessions = useMemo(() => mergeSessions(serverSessions, drafts), [serverSessions, drafts]);

  const refreshSessions = useCallback(async () => {
    try {
      const server = await listServerSessions();
      setServerSessions(server);
      // 已落库的会话由服务端接管，从本地草稿修剪（防无界膨胀）。
      setDrafts(pruneSessions(server.map((s) => s.sessionId)));
    } catch {
      /* 服务端暂不可达：沿用现有列表（本地草稿兜底），不清空视图 */
    }
  }, []);

  // 登录后：重读该用户的本地草稿（按用户隔离）并拉服务端列表。
  useEffect(() => {
    if (!isAuthed) return;
    setDrafts(listLocalSessions());
    void refreshSessions();
  }, [isAuthed, refreshSessions]);

  // run 结束后再刷一次列表（状态/lastActiveAt 已落库）。
  useEffect(() => {
    if (run.status === "done" || run.status === "error") void refreshSessions();
  }, [run.status, refreshSessions]);

  // 进入会话：载入整段历史（hook 内取列表+逐 run 回放，同一代际防切换竞态）→
  // 可直接继续对话。重复点击同一会话 = 重新载入（失败后的重试入口）。
  const selectSession = useCallback(
    async (id: string) => {
      setCurrentSessionId(id);
      const view = sessions.find((s) => s.id === id);
      if (view?.pendingLocal) {
        if (view.agentType) setAgentType(view.agentType);
        run.resetAll(); // 本地草稿会话：还没有 run，无历史可载
        return;
      }
      const metas = await run.loadSession(id);
      if (metas && metas.length > 0) {
        const last = metas[metas.length - 1];
        if (last.agentType) setAgentType(last.agentType); // 恢复该会话最近使用的 agent
      }
    },
    [sessions, run],
  );

  // 首次拿到会话列表且尚未选中任何会话 → 自动进入最近会话（刷新页面后直接续聊）。
  const didAutoSelect = useRef(false);
  useEffect(() => {
    if (didAutoSelect.current || currentSessionId || sessions.length === 0) return;
    didAutoSelect.current = true;
    void selectSession(sessions[0].id);
  }, [sessions, currentSessionId, selectSession]);

  // currentSessionId 一定出自本 UI（新建草稿或会话列表），存在即信任——
  // 不查 sessions 派生列表（异步刷新未落地时会误判不存在而重复建会话）。
  const ensureSessionId = useCallback((): string => {
    if (currentSessionId) return currentSessionId;
    const s = createSession("新会话", agentType);
    setDrafts(listLocalSessions());
    setCurrentSessionId(s.id);
    return s.id;
  }, [currentSessionId, agentType]);

  const onSubmit = useCallback(
    async (q: string, attachments?: AttachmentRef[], outputFormat?: string) => {
      const sid = ensureSessionId();
      const runId = await run.start(q, agentType, sid, attachments, outputFormat);
      if (runId) void refreshSessions(); // run 已落库：标题/runCount/lastActiveAt 即时更新
    },
    [ensureSessionId, agentType, run, refreshSessions],
  );

  // M11 HITL：审批决议（稳定引用——MessageList memo 纪律）。
  const onApprovalDecision = useCallback(
    (approvalId: string, approved: boolean, comment?: string) => {
      void run.resumeApproval(approvalId, approved, comment).then((runId) => {
        if (runId) void refreshSessions();
      });
    },
    [run, refreshSessions],
  );

  const onNewSession = useCallback(() => {
    // 已停在一个空草稿上就复用它，避免连点"新会话"堆积幽灵草稿。
    const currentView = sessions.find((s) => s.id === currentSessionId);
    if (currentView?.pendingLocal) {
      run.resetAll();
      return;
    }
    const s = createSession("新会话", agentType);
    setDrafts(listLocalSessions());
    setCurrentSessionId(s.id);
    run.resetAll();
  }, [sessions, currentSessionId, agentType, run]);

  if (!isAuthed) return <LoginView onLogin={login} />;
  return (
    <TooltipProvider delayDuration={200}>
    <div className="flex h-full flex-col">
      <Toaster position="top-center" />
      <Header
        health={health}
        userId={userId}
        onLogout={logout}
        sidebarOpen={sidebarOpen}
        onToggleSidebar={() => setSidebarOpen((v) => !v)}
        artifactsOpen={artifactsOpen}
        onToggleArtifacts={() => setArtifactsOpen((v) => !v)}
      />
      <div className="flex min-h-0 flex-1">
        {sidebarOpen && (
          <Sidebar
            sessions={sessions}
            currentSessionId={currentSessionId}
            onNewSession={onNewSession}
            onSelectSession={(id) => void selectSession(id)}
          />
        )}
        <ChatView
          timeline={run.timeline}
          live={run.live}
          status={run.status}
          loadingHistory={run.loadingHistory}
          onSubmit={onSubmit}
          agentType={agentType}
          onAgentType={setAgentType}
          uploadSessionId={currentSessionId ?? ""}
          artifactsOpen={artifactsOpen}
          onArtifactsOpenChange={setArtifactsOpen}
          artifactsWidth={artifactsWidth}
          onArtifactsWidthChange={(w) => setArtifactsWidth(clampArtifactsWidth(w))}
          onApprovalDecision={onApprovalDecision}
        />
      </div>
    </div>
    </TooltipProvider>
  );
}
