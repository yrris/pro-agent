// 会话与 runId 历史（localStorage 维护，因后端无会话列表端点）。纯逻辑、可单测。

export interface SessionMeta {
  id: string;
  title: string;
  agentType: string;
  runIds: string[];
  createdAt: number;
}

const KEY = "my-agent.sessions";

function read(): SessionMeta[] {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as SessionMeta[]) : [];
  } catch {
    return [];
  }
}

function write(list: SessionMeta[]): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(list));
  } catch {
    /* ignore */
  }
}

export function listSessions(): SessionMeta[] {
  return read().sort((a, b) => b.createdAt - a.createdAt);
}

// 纯函数核心（便于单测）：把新会话插到列表头。
export function addSessionTo(list: SessionMeta[], s: SessionMeta): SessionMeta[] {
  return [s, ...list.filter((x) => x.id !== s.id)];
}

// 纯函数核心：把 runId 追加到指定会话。
export function appendRunTo(list: SessionMeta[], sessionId: string, runId: string): SessionMeta[] {
  return list.map((s) =>
    s.id === sessionId && !s.runIds.includes(runId) ? { ...s, runIds: [...s.runIds, runId] } : s,
  );
}

export function createSession(title: string, agentType: string): SessionMeta {
  const s: SessionMeta = {
    id: cryptoRandomId(),
    title: title || "新会话",
    agentType,
    runIds: [],
    createdAt: Date.now(),
  };
  write(addSessionTo(read(), s));
  return s;
}

export function recordRun(sessionId: string, runId: string): void {
  write(appendRunTo(read(), sessionId, runId));
}

function cryptoRandomId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return "s-" + Math.random().toString(36).slice(2);
}
