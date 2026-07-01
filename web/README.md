# my-agent web

现代化前端：流式对话、计划视图、工具卡片、artifact 工作区、历史回放、健康徽章。
React 19 + Vite + TypeScript + Tailwind v4 + 手写组件。

## 启动（开发）

```bash
# 前置：控制面(:8080) 与认知面(:50051) 已启动（见 docs/使用与验收指南.md）
cd web
npm install
npm run dev            # http://localhost:5173（Vite 已代理 /runs、/artifacts、/healthz → :8080）
```

登录：输入任意用户名（作为 `X-User-Id`，用于 run/产物归属）。

## 脚本

- `npm run dev` — 开发服务器（含 dev proxy）
- `npm run typecheck` — `tsc --noEmit`
- `npm run build` — 类型检查 + 生产构建到 `dist/`
- `npm run test` — vitest（SSE 解析 / 事件归并 / 会话 纯逻辑单测）

## 架构（简）

- `src/lib/`（纯逻辑，可单测）：`sse/parseSSE`（切帧）、`sse/reducer`（按 messageId 原位更新归并）、`api/`（client/stream，注入 X-User-Id、POST+fetch 流式）、`identity`、`sessions`。
- `src/hooks/`：`useRunStream`（驱动 fetch→parse→reduce，rAF 节流）、`useHealth`、`useAuth`。
- `src/components/`、`src/views/`：只读 `RunState` 的展示层。

后端契约与设计取舍见 `docs/07-前端与体验-设计与取舍.md`；配置/启动/验收见 `docs/使用与验收指南.md`。

## 换后端地址

默认代理到 `http://localhost:8080`；改 `VITE_BACKEND` 环境变量或 `vite.config.ts` 的 proxy target。

## 生产部署（说明，未实装）

`npm run build` 产出 `dist/`，可由 Go 控制面 `FileServer` 托管（单端口免 CORS），或置于反向代理后。
