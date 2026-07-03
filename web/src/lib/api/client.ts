// 控制面 HTTP 客户端。全走相对路径（Vite proxy 转 :8080，零 CORS）；统一注入 X-User-Id。

import { getUserId } from "../identity";

function headers(json = false): Record<string, string> {
  const h: Record<string, string> = { "X-User-Id": getUserId() || "anonymous" };
  if (json) h["Content-Type"] = "application/json";
  return h;
}

// 已上传附件的引用（POST /uploads 的返回；run body 只带引用不带字节）。
export interface AttachmentRef {
  resourceKey: string;
  fileName: string;
  mimeType: string;
  size: number;
}

export interface StartRunArgs {
  query: string;
  sessionId: string;
  agentType: string; // "react" | "plan_solve" | "deep_research"
  attachments?: AttachmentRef[];
  outputFormat?: string; // M9：html/docs/ppt/table（空=自由格式）
}

export interface RunHandle {
  runId: string;
  reader: ReadableStreamDefaultReader<Uint8Array>;
}

// 发起 run：POST /runs，从响应头 X-Run-Id 取 runId，返回 body reader（流式 SSE）。
export async function startRun(args: StartRunArgs, signal?: AbortSignal): Promise<RunHandle> {
  const res = await fetch("/runs", {
    method: "POST",
    headers: headers(true),
    body: JSON.stringify(args),
    signal,
  });
  if (!res.ok || !res.body) {
    throw new Error(`startRun failed: ${res.status}`);
  }
  const runId = res.headers.get("X-Run-Id") ?? "";
  return { runId, reader: res.body.getReader() };
}

// 回放：GET /runs/{runId}/events，同样返回 body reader（与实时同一解析器）。
export async function replay(runId: string, signal?: AbortSignal): Promise<ReadableStreamDefaultReader<Uint8Array>> {
  const res = await fetch(`/runs/${encodeURIComponent(runId)}/events`, { headers: headers(), signal });
  if (!res.ok || !res.body) throw new Error(`replay failed: ${res.status}`);
  return res.body.getReader();
}

// 上传附件：multipart POST /uploads。注意 headers() 必须**无参**调用——绝不能手动设
// Content-Type，浏览器需自动生成 multipart boundary。
export async function uploadFile(
  file: File,
  sessionId: string,
  signal?: AbortSignal,
): Promise<AttachmentRef> {
  const fd = new FormData();
  fd.append("file", file);
  const res = await fetch(`/uploads?sessionId=${encodeURIComponent(sessionId)}`, {
    method: "POST",
    headers: headers(),
    body: fd,
    signal,
  });
  if (!res.ok) throw new Error(`upload failed: ${res.status}`);
  return (await res.json()) as AttachmentRef;
}

// 下载 artifact：必须带 X-User-Id（owner 校验），故用 fetch→blob→a[download]，不能裸 <a href>。
export async function downloadArtifact(resourceKey: string, fileName: string): Promise<void> {
  const res = await fetch(`/artifacts/${resourceKey}`, { headers: headers() });
  if (!res.ok) throw new Error(`download failed: ${res.status}`);
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = fileName || "download";
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

// —— M7 会话端点（服务端权威会话列表；proto/SSE 零改动） ——

export interface ServerSession {
  sessionId: string;
  title: string;
  entryAgent: string;
  runCount: number;
  createdAt: string; // ISO 8601
  lastActiveAt: string; // ISO 8601
}

// 会话列表：GET /sessions（runs 表按 owner 聚合，lastActiveAt 降序）。
export async function listServerSessions(limit = 50): Promise<ServerSession[]> {
  const res = await fetch(`/sessions?limit=${limit}`, { headers: headers() });
  if (!res.ok) throw new Error(`listSessions failed: ${res.status}`);
  const body = (await res.json()) as { sessions?: ServerSession[] };
  return body.sessions ?? [];
}

export interface SessionRunMeta {
  runId: string;
  query: string;
  agentType: string;
  status: string;
  finalSummary?: string;
  errorMsg?: string;
  createdAt: string; // ISO 8601
}

// 会话内 run 元数据（created_at 升序）；事件仍走 GET /runs/{id}/events 逐 run 回放。
export async function listSessionRuns(sessionId: string, signal?: AbortSignal): Promise<SessionRunMeta[]> {
  const res = await fetch(`/sessions/${encodeURIComponent(sessionId)}/runs`, { headers: headers(), signal });
  if (!res.ok) throw new Error(`listSessionRuns failed: ${res.status}`);
  const body = (await res.json()) as { runs?: SessionRunMeta[] };
  return body.runs ?? [];
}

export interface HealthReport {
  healthy: boolean;
  checks: Record<string, string>;
}

export async function healthz(): Promise<HealthReport> {
  try {
    const res = await fetch("/healthz");
    const body = (await res.json()) as HealthReport;
    return { healthy: !!body.healthy, checks: body.checks ?? {} };
  } catch {
    return { healthy: false, checks: { network: "unreachable" } };
  }
}
