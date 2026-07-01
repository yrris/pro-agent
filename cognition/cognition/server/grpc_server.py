"""gRPC 服务入口（grpc.aio）。

`python -m cognition.server.grpc_server` 在配置端口上启动认知服务。
启动时构建两套图：ReAct（agent_type=react）与 Plan-Execute（agent_type=plan_solve），
由 servicer 按 agent_type 路由。模型按角色分层（router.select_model）；可选 Postgres checkpointer。
COGNITION_FAKE_MODEL=1 时改用确定性脚本化模型（无 LLM key 端到端验证）。
"""

from __future__ import annotations

import asyncio
import logging
import signal

import grpc

from cognition._genproto import agent_pb2_grpc
from cognition.checkpoint.postgres import build_checkpointer
from cognition.config import Settings, get_settings
from cognition.graphs.plan_execute import build_plan_execute_graph
from cognition.graphs.react import build_react_graph
from cognition.providers.router import select_model
from cognition.server.servicer import CognitionServicer
from cognition.sop import default_sop_store
from cognition.tools.registry import build_tool_suite

logger = logging.getLogger(__name__)


async def serve(settings: Settings | None = None) -> None:
    """启动 gRPC 服务并阻塞直至终止。"""
    settings = settings or get_settings()

    # 装配期聚合 local + MCP + Skill 工具；provider_map 注入事件映射，tool_closers 停机时关闭。
    tools, provider_map, tool_closers = await build_tool_suite(settings)

    if settings.fake_model:
        from cognition.providers.fake import (
            build_fake_executor_model,
            build_fake_model,
            build_fake_plan_model,
        )

        logger.info("using scripted fake model (no LLM key)")
        react_model = build_fake_model().bind_tools(tools)
        planner_model = build_fake_plan_model()
        executor_model = build_fake_executor_model().bind_tools(tools)
    else:
        react_model = select_model("executor", tools=tools, settings=settings)
        planner_model = select_model("planner", settings=settings)
        executor_model = select_model("executor", tools=tools, settings=settings)

    aclose = None
    checkpointer = None
    if settings.pg_dsn:
        checkpointer, aclose = await build_checkpointer(settings.pg_dsn)
        logger.info("postgres checkpointer enabled")

    react_graph = build_react_graph(
        react_model, tools, checkpointer=checkpointer, max_steps=settings.max_steps
    )

    # Plan-Execute：executor 复用一套 ReAct 子图（无 checkpointer，分支级 thread 隔离）。
    executor_subgraph = build_react_graph(executor_model, tools, max_steps=settings.max_steps)
    plan_graph = build_plan_execute_graph(
        planner_model,
        executor_subgraph,
        tools,
        max_steps=settings.planner_max_steps,
        max_parallel=settings.max_parallel_tasks,
        sop_store=default_sop_store(),
        branch_timeout=settings.branch_timeout_seconds,
        react_recursion_limit=2 * settings.max_steps + 5,
        checkpointer=checkpointer,
    )

    server = grpc.aio.server()
    agent_pb2_grpc.add_CognitionServiceServicer_to_server(
        CognitionServicer(react_graph, settings, plan_graph=plan_graph, tool_providers=provider_map),
        server,
    )
    listen = f"{settings.grpc_host}:{settings.grpc_port}"
    server.add_insecure_port(listen)

    await server.start()
    logger.info("cognition gRPC server listening on %s", listen)

    # 优雅停机
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, ValueError):
            # 某些平台/非主线程不支持信号处理。
            pass

    try:
        await stop.wait()
    finally:
        await server.stop(grace=5.0)
        for close in tool_closers:  # 关闭 MCP worker task / 子进程
            try:
                await close()
            except Exception as exc:  # noqa: BLE001
                logger.warning("tool 资源关闭失败: %s", exc)
        if aclose is not None:
            await aclose()
        logger.info("cognition gRPC server stopped")


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(serve())


if __name__ == "__main__":
    main()
