import { describe, expect, it } from "vitest";
import { ARTIFACTS_MAX_W, ARTIFACTS_MIN_W, clampArtifactsWidth, loadUiPrefs } from "./uiPrefs";

describe("clampArtifactsWidth", () => {
  it("夹取到 [MIN, MAX] 且取整", () => {
    expect(clampArtifactsWidth(100)).toBe(ARTIFACTS_MIN_W);
    expect(clampArtifactsWidth(10_000)).toBe(ARTIFACTS_MAX_W);
    expect(clampArtifactsWidth(400.6)).toBe(401);
  });
  it("非法值回退默认", () => {
    expect(clampArtifactsWidth(Number.NaN)).toBe(384);
    expect(clampArtifactsWidth(Number.POSITIVE_INFINITY)).toBe(384);
  });
});

describe("theme 偏好", () => {
  it("无存储/未知值默认 light；显式 dark 才是 dark", () => {
    // node 环境无 localStorage → 走 catch 分支 → 默认 light
    expect(loadUiPrefs().theme).toBe("light");

    const store: Record<string, string> = {};
    (globalThis as { localStorage?: unknown }).localStorage = {
      getItem: (k: string) => store[k] ?? null,
      setItem: (k: string, v: string) => {
        store[k] = v;
      },
    };
    try {
      store["my-agent.ui"] = JSON.stringify({ theme: "dark" });
      expect(loadUiPrefs().theme).toBe("dark");
      store["my-agent.ui"] = JSON.stringify({ theme: "banana" });
      expect(loadUiPrefs().theme).toBe("light");
    } finally {
      delete (globalThis as { localStorage?: unknown }).localStorage;
    }
  });
});
