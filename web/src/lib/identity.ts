// 身份（单用户）：登录 = 用户名存 localStorage，所有请求带 X-User-Id。
// 多租户/真鉴权是 docs/00 §4.2 拓展点，只在此处留单点。

const KEY = "my-agent.userId";

export function getUserId(): string {
  try {
    return localStorage.getItem(KEY) ?? "";
  } catch {
    return "";
  }
}

export function setUserId(id: string): void {
  try {
    localStorage.setItem(KEY, id);
  } catch {
    /* ignore */
  }
}

export function clearUserId(): void {
  try {
    localStorage.removeItem(KEY);
  } catch {
    /* ignore */
  }
}
