// 控制面 HTTP 客户端。全走相对路径（Vite proxy 转 :8080，零 CORS）；统一注入 X-User-Id。

import { getUserId } from "../identity";

function headers(json = false): Record<string, string> {
  const h: Record<string, string> = { "X-User-Id": getUserId() || "anonymous" };
  if (json) h["Content-Type"] = "application/json";
  return h;
}

export interface StartRunArgs {
  query: string;
  sessionId: string;
  agentType: string; // "react" | "plan_solve"
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
