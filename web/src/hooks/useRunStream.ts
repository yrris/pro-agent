// 驱动一次 run：startRun/replay → iterFrames → applyFrame → RunState。
// 用 rAF 合并同一动画帧内的多次 applyFrame，避免高频 token 帧引起 DOM 风暴。

import { useCallback, useRef, useState } from "react";
import { replay, startRun } from "../lib/api/client";
import { iterFrames } from "../lib/api/stream";
import { applyFrame } from "../lib/sse/reducer";
import { emptyRunState, type RunState } from "../lib/sse/frameTypes";

export type RunStatus = "idle" | "running" | "done" | "error";

export function useRunStream() {
  const [state, setState] = useState<RunState>(() => emptyRunState());
  const [status, setStatus] = useState<RunStatus>("idle");
  const [error, setError] = useState<string>("");
  const [replaying, setReplaying] = useState(false);

  const stateRef = useRef<RunState>(state);
  const rafRef = useRef<number | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const flush = useCallback(() => {
    rafRef.current = null;
    setState(stateRef.current);
  }, []);

  const scheduleFlush = useCallback(() => {
    if (rafRef.current != null) return;
    rafRef.current =
      typeof requestAnimationFrame !== "undefined"
        ? requestAnimationFrame(flush)
        : (setTimeout(flush, 16) as unknown as number);
  }, [flush]);

  const reset = useCallback((runId = "") => {
    abortRef.current?.abort();
    const s = emptyRunState(runId);
    stateRef.current = s;
    setState(s);
    setError("");
  }, []);

  const pump = useCallback(
    async (reader: ReadableStreamDefaultReader<Uint8Array>) => {
      try {
        for await (const frame of iterFrames(reader)) {
          stateRef.current = applyFrame(stateRef.current, frame);
          scheduleFlush();
        }
        flush();
        setStatus(stateRef.current.finished ? "done" : "done");
      } catch (e) {
        flush();
        setStatus("error");
        setError(e instanceof Error ? e.message : String(e));
      }
    },
    [flush, scheduleFlush],
  );

  const start = useCallback(
    async (query: string, agentType: string, sessionId: string): Promise<string> => {
      reset();
      setReplaying(false);
      setStatus("running");
      const ac = new AbortController();
      abortRef.current = ac;
      try {
        const { runId, reader } = await startRun({ query, sessionId, agentType }, ac.signal);
        stateRef.current = { ...stateRef.current, runId };
        setState(stateRef.current);
        void pump(reader);
        return runId;
      } catch (e) {
        setStatus("error");
        setError(e instanceof Error ? e.message : String(e));
        return "";
      }
    },
    [pump, reset],
  );

  const replayRun = useCallback(
    async (runId: string) => {
      reset(runId);
      setReplaying(true);
      setStatus("running");
      const ac = new AbortController();
      abortRef.current = ac;
      try {
        const reader = await replay(runId, ac.signal);
        await pump(reader);
      } catch (e) {
        setStatus("error");
        setError(e instanceof Error ? e.message : String(e));
      }
    },
    [pump, reset],
  );

  const cancel = useCallback(() => {
    abortRef.current?.abort();
    setStatus((s) => (s === "running" ? "idle" : s));
  }, []);

  return { state, status, error, replaying, start, replayRun, cancel, reset };
}
