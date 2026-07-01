import { describe, expect, it } from "vitest";
import { addSessionTo, appendRunTo, type SessionMeta } from "./sessions";

const s = (id: string): SessionMeta => ({ id, title: id, agentType: "react", runIds: [], createdAt: 1 });

describe("sessions pure logic", () => {
  it("addSessionTo prepends and dedupes by id", () => {
    const out = addSessionTo([s("a")], s("b"));
    expect(out.map((x) => x.id)).toEqual(["b", "a"]);
    expect(addSessionTo(out, s("b")).map((x) => x.id)).toEqual(["b", "a"]);
  });

  it("appendRunTo appends runId to the right session, no dup", () => {
    let list = [s("a"), s("b")];
    list = appendRunTo(list, "a", "run1");
    list = appendRunTo(list, "a", "run1"); // 幂等
    list = appendRunTo(list, "b", "run2");
    expect(list.find((x) => x.id === "a")!.runIds).toEqual(["run1"]);
    expect(list.find((x) => x.id === "b")!.runIds).toEqual(["run2"]);
  });
});
