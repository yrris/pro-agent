# my-agent

一个**多智能体应用平台**：**Go 控制面 + Python(LangGraph) 认知面** 的双平面架构。

- **Go 控制面**：API/流式（SSE/WebSocket）、并发与调度、背压/降载、执行事实记录与历史回放分发、健康与可观测。
- **Python 认知面**：用 LangGraph 表达 ReAct / Plan-Execute 混合编排与 Agentic RAG，承载工具（本地 / MCP / Skill）、记忆、模型路由。
- 两面以 **gRPC 流式** 通信，Go 唯一对外。

## 核心能力

- 多智能体混合编排（ReAct + Plan-Execute，动态 replan、可控并行子任务）
- 统一工具生态（本地工具 / MCP 三传输 / Skill 渐进式披露）与产物沉淀复用
- Agentic RAG（基于 Qdrant 的 dense+sparse 混合 + 多模态 + 多轮反思 + rerank）
- 执行过程可观测、可回放（实时与历史同构）

## 技术栈

后端控制面 Go · 认知面 Python + LangGraph · LLM Claude/DeepSeek · 向量库 Qdrant · 存储 PostgreSQL · 缓存 Redis · 对象存储 MinIO · 事件 NATS · 前端 React + TypeScript

## 快速开始

```bash
# 1. 起依赖（PostgreSQL / Qdrant / Redis / MinIO / NATS）
cd deploy && cp .env.example .env && docker compose up -d

# 2.（后续里程碑补充）启动控制面 / 认知面 / 前端
```

> 详细架构与开发计划见项目内 `docs/`（开发者本地文档，未纳入版本库）。
