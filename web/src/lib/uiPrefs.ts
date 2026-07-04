// UI 偏好（侧栏开合/Artifacts 面板开合与宽度）：localStorage 持久化，
// key 沿用 `my-agent.` 前缀约定（identity/sessions 同款）。纯函数 + 容错读写。

const KEY = "my-agent.ui";

// 左侧栏导航项 = 主区视图路由（对齐 Claude 官网侧栏导航）。
export type NavView = "chat" | "generate" | "artifacts" | "kb" | "schedules";
const NAV_VIEWS: NavView[] = ["chat", "generate", "artifacts", "kb", "schedules"];

export interface UiPrefs {
  sidebarOpen: boolean;
  artifactsWidth: number;
  activeNav: NavView;
}

export const ARTIFACTS_MIN_W = 320;
export const ARTIFACTS_MAX_W = 720;

export function clampArtifactsWidth(w: number): number {
  if (!Number.isFinite(w)) return 384;
  return Math.min(ARTIFACTS_MAX_W, Math.max(ARTIFACTS_MIN_W, Math.round(w)));
}

const DEFAULTS: UiPrefs = { sidebarOpen: true, artifactsWidth: 384, activeNav: "chat" };

export function loadUiPrefs(): UiPrefs {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return { ...DEFAULTS };
    const parsed = JSON.parse(raw) as Partial<UiPrefs>;
    return {
      sidebarOpen: typeof parsed.sidebarOpen === "boolean" ? parsed.sidebarOpen : DEFAULTS.sidebarOpen,
      artifactsWidth: clampArtifactsWidth(parsed.artifactsWidth ?? DEFAULTS.artifactsWidth),
      activeNav: NAV_VIEWS.includes(parsed.activeNav as NavView) ? (parsed.activeNav as NavView) : "chat",
    };
  } catch {
    return { ...DEFAULTS };
  }
}

export function saveUiPrefs(prefs: UiPrefs): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(prefs));
  } catch {
    /* 隐私模式等存不进就算了，仅影响下次打开的记忆 */
  }
}
