import { describe, expect, it } from "vitest";
import { ARTIFACTS_MAX_W, ARTIFACTS_MIN_W, clampArtifactsWidth } from "./uiPrefs";

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
