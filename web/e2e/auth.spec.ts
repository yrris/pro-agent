// auth.spec（docs/11 §4.3）：登录/登出/身份头。
// 锚点 = 登录页真实文案（placeholder“用户名（作为 X-User-Id）”+ 按钮“进入平台”）——
// 文案即 UI 契约，改文案应当红（docs/11 §4.3 已知风险①，登记为特性）。
import { expect, test } from "@playwright/test";
import { freshUserId } from "./helpers";

test("UI 登录后请求携带 X-User-Id，登出回到登录页", async ({ page }) => {
  const userId = freshUserId();
  await page.goto("/");

  // 登录页形态
  const nameInput = page.getByPlaceholder("用户名（作为 X-User-Id）");
  await expect(nameInput).toBeVisible();
  const enter = page.getByRole("button", { name: "进入平台" });
  await expect(enter).toBeDisabled(); // 空用户名不可进入

  // 登录：进入后 App 会立刻拉 GET /sessions——用它断言身份头注入
  await nameInput.fill(userId);
  const sessionsReq = page.waitForRequest(
    (req) => req.url().includes("/sessions") && req.method() === "GET",
  );
  await enter.click();
  const req = await sessionsReq;
  expect(req.headers()["x-user-id"]).toBe(userId);

  // 已登录形态：侧栏 + 账号底栏显示当前用户
  await expect(page.getByRole("button", { name: "新对话" })).toBeVisible();
  await expect(page.getByTitle(userId)).toBeVisible();

  // 登出：清身份，回登录页
  await page.getByRole("button", { name: "退出" }).click();
  await expect(page.getByPlaceholder("用户名（作为 X-User-Id）")).toBeVisible();
  await expect(page.getByRole("button", { name: "新对话" })).toHaveCount(0);
});
