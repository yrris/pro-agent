import { describe, expect, it } from "vitest";
import { applyFrame, reduceFrames } from "./reducer";
import { emptyRunState, type SseFrame } from "./frameTypes";

const f = (o: Partial<SseFrame>): SseFrame =>
  ({ requestId: "r", messageId: "m", seq: 1, messageType: "result", messageTime: "0", isFinal: false, finish: false, ...o }) as SseFrame;

describe("applyFrame", () => {
  it("accumulates thought text on same messageId", () => {
    let s = emptyRunState();
    s = applyFrame(s, f({ messageType: "tool_thought", messageId: "t1", toolThought: "Hel" }));
    s = applyFrame(s, f({ messageType: "tool_thought", messageId: "t1", toolThought: "lo" }));
    expect(s.thoughts["t1"].text).toBe("Hello");
    expect(s.order.filter((e) => e.kind === "thought")).toHaveLength(1);
  });

  it("overwrites tool_call on same messageId (running -> success)", () => {
    let s = emptyRunState();
    s = applyFrame(s, f({ messageType: "tool_call", messageId: "c1", resultMap: { status: "running", toolName: "calc", toolCallId: "c1" } }));
    s = applyFrame(s, f({ messageType: "tool_call", messageId: "c1", resultMap: { status: "success", toolName: "calc", toolCallId: "c1" } }));
    expect(Object.keys(s.toolCalls)).toHaveLength(1);
    expect(s.toolCalls["c1"].status).toBe("success");
    expect(s.order.filter((e) => e.kind === "toolCall")).toHaveLength(1);
  });

  it("appends tool_result and links toolCallId + merges artifacts", () => {
    let s = emptyRunState();
    s = applyFrame(s, f({
      messageType: "tool_result", messageId: "c1:result",
      toolResult: { toolName: "report", toolResult: "ok", toolCallId: "c1" },
      artifactRefs: [{ resourceKey: "r/c1/a.md", name: "a", previewUrl: "", downloadUrl: "/artifacts/r/c1/a.md", fileName: "a.md", mimeType: "text/markdown", size: 3, missing: false }],
    }));
    expect(s.toolResults).toHaveLength(1);
    expect(s.toolResults[0].toolCallId).toBe("c1");
    expect(s.artifacts).toHaveLength(1);
  });

  it("replaces plan snapshot and groups planner rounds", () => {
    let s = emptyRunState();
    s = applyFrame(s, f({ messageType: "plan", plan: { title: "P", steps: ["a", "b"], stepStatus: ["in_progress", "not_started"], notes: [] }, resultMap: { plannerRoundId: "r1" } }));
    s = applyFrame(s, f({ messageType: "plan", plan: { title: "P", steps: ["a", "b"], stepStatus: ["completed", "in_progress"], notes: [] }, resultMap: { plannerRoundId: "r1" } }));
    expect(s.plan?.stepStatus[0]).toBe("completed"); // 快照替换
    expect(s.plannerRounds).toHaveLength(1); // 同轮替换
    s = applyFrame(s, f({ messageType: "plan", plan: { title: "P", steps: ["c"], stepStatus: ["in_progress"], notes: [] }, resultMap: { plannerRoundId: "r2" } }));
    expect(s.plannerRounds).toHaveLength(2); // 跨轮追加
  });

  it("adds tasks", () => {
    let s = emptyRunState();
    s = applyFrame(s, f({ messageType: "task", task: "子任务A" }));
    s = applyFrame(s, f({ messageType: "task", task: "子任务B" }));
    expect(s.tasks.map((t) => t.text)).toEqual(["子任务A", "子任务B"]);
  });

  it("sets result and finished on finish", () => {
    let s = emptyRunState();
    s = applyFrame(s, f({ messageType: "result", result: "答案", finish: true }));
    expect(s.result?.text).toBe("答案");
    expect(s.finished).toBe(true);
  });

  it("dedupes artifacts by resourceKey", () => {
    const art = (k: string) => ({ resourceKey: k, name: k, previewUrl: "", downloadUrl: "", fileName: k, mimeType: "", size: 1, missing: false });
    let s = emptyRunState();
    s = applyFrame(s, f({ messageType: "tool_result", toolResult: { toolName: "t", toolResult: "", toolCallId: "c" }, artifactRefs: [art("k1")] }));
    s = applyFrame(s, f({ messageType: "result", result: "x", finish: true, artifactRefs: [art("k1"), art("k2")] }));
    expect(s.artifacts.map((a) => a.resourceKey).sort()).toEqual(["k1", "k2"]);
  });

  it("does not throw on unknown messageType", () => {
    const s = applyFrame(emptyRunState(), f({ messageType: "external_tool_result" as never }));
    expect(s.unknown).toHaveLength(1);
  });

  it("ignores heartbeat", () => {
    const s0 = emptyRunState();
    expect(applyFrame(s0, f({ messageType: "heartbeat" }))).toBe(s0);
  });

  it("reduceFrames replays a full run deterministically", () => {
    const frames = [
      f({ messageType: "tool_thought", messageId: "t", toolThought: "think" }),
      f({ messageType: "tool_call", messageId: "c", resultMap: { status: "success", toolName: "calc", toolCallId: "c" } }),
      f({ messageType: "result", result: "done", finish: true }),
    ];
    const s = reduceFrames(frames);
    expect(s.finished).toBe(true);
    expect(s.order.map((e) => e.kind)).toEqual(["thought", "toolCall", "result"]);
  });
});
