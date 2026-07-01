import { useCallback, useMemo, useState } from "react";
import { useAuth } from "./hooks/useAuth";
import { useHealth } from "./hooks/useHealth";
import { useRunStream } from "./hooks/useRunStream";
import { LoginView } from "./views/LoginView";
import { ChatView } from "./views/ChatView";
import { Header } from "./components/Header";
import { Sidebar } from "./components/Sidebar";
import { createSession, listSessions, recordRun, type SessionMeta } from "./lib/sessions";

export default function App() {
  const { userId, isAuthed, login, logout } = useAuth();
  const health = useHealth();
  const run = useRunStream();

  const [agentType, setAgentType] = useState("react");
  const [sessions, setSessions] = useState<SessionMeta[]>(() => listSessions());
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(() => sessions[0]?.id ?? null);
  const [query, setQuery] = useState("");
  const [activeRunId, setActiveRunId] = useState("");

  const refreshSessions = useCallback(() => setSessions(listSessions()), []);

  const ensureSession = useCallback((): SessionMeta => {
    const found = sessions.find((s) => s.id === currentSessionId);
    if (found) return found;
    const s = createSession("会话 " + (sessions.length + 1), agentType);
    refreshSessions();
    setCurrentSessionId(s.id);
    return s;
  }, [sessions, currentSessionId, agentType, refreshSessions]);

  const onSubmit = useCallback(
    async (q: string) => {
      const session = ensureSession();
      setQuery(q);
      const runId = await run.start(q, agentType, session.id);
      if (runId) {
        recordRun(session.id, runId);
        setActiveRunId(runId);
        refreshSessions();
      }
    },
    [ensureSession, agentType, run, refreshSessions],
  );

  const onReplay = useCallback(
    (runId: string) => {
      setQuery("");
      setActiveRunId(runId);
      void run.replayRun(runId);
    },
    [run],
  );

  const onNewSession = useCallback(() => {
    const s = createSession("会话 " + (sessions.length + 1), agentType);
    refreshSessions();
    setCurrentSessionId(s.id);
    run.reset();
    setQuery("");
    setActiveRunId("");
  }, [sessions.length, agentType, refreshSessions, run]);

  const onSelectSession = useCallback((id: string) => {
    setCurrentSessionId(id);
  }, []);

  const shell = useMemo(
    () => (
      <div className="flex h-full flex-col">
        <Header
          agentType={agentType}
          onAgentType={setAgentType}
          health={health}
          userId={userId}
          onLogout={logout}
        />
        <div className="flex min-h-0 flex-1">
          <Sidebar
            sessions={sessions}
            currentSessionId={currentSessionId}
            onNewSession={onNewSession}
            onSelectSession={onSelectSession}
            onReplay={onReplay}
            activeRunId={activeRunId}
          />
          <ChatView
            state={run.state}
            status={run.status}
            replaying={run.replaying}
            query={query}
            onSubmit={onSubmit}
          />
        </div>
      </div>
    ),
    [agentType, health, userId, logout, sessions, currentSessionId, onNewSession, onSelectSession, onReplay, activeRunId, run.state, run.status, run.replaying, query, onSubmit],
  );

  if (!isAuthed) return <LoginView onLogin={login} />;
  return shell;
}
