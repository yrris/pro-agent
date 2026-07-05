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
  imageGen?: boolean; // 生图开关：置位则后端注入生图指令（可配合上传图做图生图 + 输出格式嵌入）
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

// 带上传进度的附件上传：fetch 无法报告 request-body 上传进度，故用 XHR 订阅
// xhr.upload.onprogress。同样**只设 X-User-Id**，绝不手设 Content-Type（浏览器自动生成
// multipart boundary）。onProgress 回 0..1；响应在 loaded===total 之后到，故 done 判 onload。
export function uploadFileWithProgress(
  file: File,
  sessionId: string,
  onProgress: (pct: number) => void,
  signal?: AbortSignal,
): Promise<AttachmentRef> {
  return new Promise((resolve, reject) => {
    const fd = new FormData();
    fd.append("file", file);
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `/uploads?sessionId=${encodeURIComponent(sessionId)}`);
    xhr.setRequestHeader("X-User-Id", getUserId() || "anonymous");
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress(e.loaded / e.total);
    };
    xhr.onload = () => {
      if (xhr.status < 200 || xhr.status >= 300) {
        reject(new Error(`upload failed: ${xhr.status}`));
        return;
      }
      try {
        resolve(JSON.parse(xhr.responseText) as AttachmentRef); // 坏 JSON 不能逃出 Promise
      } catch {
        reject(new Error("upload failed: bad response"));
      }
    };
    xhr.onerror = () => reject(new Error("upload failed: network"));
    xhr.onabort = () => reject(new Error("upload aborted")); // 无此则 abort 后 Promise 永挂
    if (signal) signal.addEventListener("abort", () => xhr.abort());
    xhr.send(fd);
  });
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
  forkedFrom?: string; // docs/14：父会话 id（分叉会话才有；侧栏据此画分叉标记）
}

// 会话列表：GET /sessions（runs 表按 owner 聚合，lastActiveAt 降序）。
export async function listServerSessions(limit = 50): Promise<ServerSession[]> {
  const res = await fetch(`/sessions?limit=${limit}`, { headers: headers() });
  if (!res.ok) throw new Error(`listSessions failed: ${res.status}`);
  const body = (await res.json()) as { sessions?: ServerSession[] };
  return body.sessions ?? [];
}

// 删除会话：DELETE /sessions/{id}（owner 域删 runs+events）。404=会话不存在/非本人。
export async function deleteSession(sessionId: string): Promise<void> {
  const res = await fetch(`/sessions/${encodeURIComponent(sessionId)}`, {
    method: "DELETE",
    headers: headers(),
  });
  if (!res.ok && res.status !== 404) throw new Error(`deleteSession failed: ${res.status}`);
}

export interface SessionRunMeta {
  runId: string;
  query: string;
  agentType: string;
  status: string;
  finalSummary?: string;
  errorMsg?: string;
  createdAt: string; // ISO 8601
  inherited?: boolean; // docs/14：继承自父会话的只读投影轮（原 runId，回放零改动）
}

// 会话内 run 元数据（created_at 升序）；事件仍走 GET /runs/{id}/events 逐 run 回放。
export async function listSessionRuns(sessionId: string, signal?: AbortSignal): Promise<SessionRunMeta[]> {
  const res = await fetch(`/sessions/${encodeURIComponent(sessionId)}/runs`, { headers: headers(), signal });
  if (!res.ok) throw new Error(`listSessionRuns failed: ${res.status}`);
  const body = (await res.json()) as { runs?: SessionRunMeta[] };
  return body.runs ?? [];
}

// docs/14 会话分叉：POST /sessions/{id}/fork —— 从某轮之后分叉出新会话，返回新 sessionId。
// 新会话 timeline 继承父会话截至该轮的历史（只读投影）；首条消息触发认知面 checkpoint 播种。
export async function forkSession(sessionId: string, afterRunId: string): Promise<string> {
  const res = await fetch(`/sessions/${encodeURIComponent(sessionId)}/fork`, {
    method: "POST",
    headers: headers(true),
    body: JSON.stringify({ afterRunId }),
  });
  if (!res.ok) throw new Error(`forkSession failed: ${res.status}`);
  const body = (await res.json()) as { sessionId: string };
  return body.sessionId;
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


// —— UX-1 Files 面板：用户知识库管理 ——

export interface KbDoc {
  sourceId: string;
  fileName: string;
  chunks: number;
  createdAt: number; // unix 秒
  downloadUrl?: string; // uploads 来源附带；脚本灌库来源无
}

export async function listKbDocs(): Promise<KbDoc[]> {
  const res = await fetch("/kb/docs", { headers: headers() });
  if (!res.ok) throw new Error(`listKbDocs failed: ${res.status}`);
  const data = (await res.json()) as { docs: KbDoc[] };
  return data.docs ?? [];
}

export async function deleteKbDoc(sourceId: string): Promise<void> {
  const res = await fetch(`/kb/docs?source=${encodeURIComponent(sourceId)}`, {
    method: "DELETE",
    headers: headers(),
  });
  if (!res.ok) throw new Error(`deleteKbDoc failed: ${res.status}`);
}

// 面板"上传即入库"（不经对话轮）：先 /uploads 拿引用，再 POST /kb/docs 送认知面入库。
export async function ingestKbDoc(ref: AttachmentRef): Promise<{ ok: boolean; message?: string }> {
  const res = await fetch("/kb/docs", {
    method: "POST",
    headers: headers(true),
    body: JSON.stringify(ref),
  });
  if (!res.ok) throw new Error(`ingestKbDoc failed: ${res.status}`);
  return (await res.json()) as { ok: boolean; message?: string };
}


// —— M11 HITL：审批决议（响应即恢复 run 的 SSE 流，与 startRun 同构） ——

export async function resolveApproval(
  runId: string,
  approvalId: string,
  approved: boolean,
  comment?: string,
  signal?: AbortSignal,
): Promise<RunHandle> {
  const res = await fetch(`/runs/${encodeURIComponent(runId)}/approvals`, {
    method: "POST",
    headers: headers(true),
    body: JSON.stringify({ approvalId, approved, comment: comment ?? "" }),
    signal,
  });
  if (!res.ok || !res.body) throw new Error(`resolveApproval failed: ${res.status}`);
  return { runId: res.headers.get("X-Run-Id") ?? "", reader: res.body.getReader() };
}


// —— M11 成本面板 / 定时任务 ——

export interface UsageTotals {
  runs: number;
  inputTokens: number;
  outputTokens: number;
  modelCalls: number;
}

export interface UsageReport {
  days: number;
  totals: UsageTotals;
  daily: { date: string; runs: number; inputTokens: number; outputTokens: number }[];
  byAgent: { agentType: string; runs: number; inputTokens: number; outputTokens: number }[];
}

export async function getUsageStats(days = 30): Promise<UsageReport> {
  const res = await fetch(`/stats/usage?days=${days}`, { headers: headers() });
  if (!res.ok) throw new Error(`getUsageStats failed: ${res.status}`);
  return (await res.json()) as UsageReport;
}

export interface ScheduleItem {
  scheduleId: string;
  sessionId: string;
  query: string;
  agentType: string;
  intervalSeconds: number;
  enabled: boolean;
  nextRunAt: string;
  lastRunId?: string;
  createdAt: string;
}

export async function listSchedules(): Promise<ScheduleItem[]> {
  const res = await fetch("/schedules", { headers: headers() });
  if (!res.ok) throw new Error(`listSchedules failed: ${res.status}`);
  const data = (await res.json()) as { schedules: ScheduleItem[] };
  return data.schedules ?? [];
}

export async function createSchedule(body: {
  query: string;
  agentType: string;
  intervalSeconds: number;
}): Promise<void> {
  const res = await fetch("/schedules", {
    method: "POST",
    headers: headers(true),
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`createSchedule failed: ${res.status}`);
}

export async function deleteSchedule(id: string): Promise<void> {
  const res = await fetch(`/schedules/${encodeURIComponent(id)}`, {
    method: "DELETE",
    headers: headers(),
  });
  if (!res.ok) throw new Error(`deleteSchedule failed: ${res.status}`);
}

export async function toggleSchedule(id: string, enabled: boolean): Promise<void> {
  const res = await fetch(`/schedules/${encodeURIComponent(id)}/toggle`, {
    method: "POST",
    headers: headers(true),
    body: JSON.stringify({ enabled }),
  });
  if (!res.ok) throw new Error(`toggleSchedule failed: ${res.status}`);
}


// —— 跨会话产物画廊（Files 侧栏"产物"导航） ——

export interface OwnerArtifact {
  runId: string;
  sessionId: string;
  resourceKey: string;
  name: string;
  fileName: string;
  downloadUrl: string;
  previewUrl: string;
  mimeType: string;
  size: number;
  tsUnixMs: number;
}

// 游标分页（B.11）：before=上一页末项 tsUnixMs，beforeKey=其 resourceKey（防同 ts 页边界丢/重）。
// mime 前缀（如 "image/"）服务端过滤（生图工作区只要图片，客户端在单页过滤会漏更旧的图）。
export async function listArtifacts(
  limit = 60,
  cursor?: { beforeTS: number; beforeKey: string },
  mime?: string,
): Promise<OwnerArtifact[]> {
  const q = new URLSearchParams({ limit: String(limit) });
  if (cursor) {
    q.set("before", String(cursor.beforeTS));
    q.set("beforeKey", cursor.beforeKey);
  }
  if (mime) q.set("mime", mime);
  const res = await fetch(`/artifacts?${q}`, { headers: headers() });
  if (!res.ok) throw new Error(`listArtifacts failed: ${res.status}`);
  const data = (await res.json()) as { artifacts: OwnerArtifact[] };
  return data.artifacts ?? [];
}
