"""gRPC 服务入口（grpc.aio）。

`python -m cognition.server.grpc_server` 在配置端口上启动认知服务。
M1：单模型（按 Settings 选 provider）+ 本地工具 + ReAct 图；可选 Postgres checkpointer。
"""

from __future__ import annotations

import asyncio
import logging
import signal

import grpc

from cognition._genproto import agent_pb2_grpc
from cognition.checkpoint.postgres import build_checkpointer
from cognition.config import Settings, get_settings
from cognition.graphs.react import build_react_graph
from cognition.providers.router import select_model
from cognition.server.servicer import CognitionServicer
from cognition.tools.registry import get_local_tools

logger = logging.getLogger(__name__)


async def serve(settings: Settings | None = None) -> None:
    """启动 gRPC 服务并阻塞直至终止。"""
    settings = settings or get_settings()

    tools = get_local_tools()
    # 给 agent 节点的模型绑定工具（M1：role 走 complex → 配置的 provider）。
    # COGNITION_FAKE_MODEL=1 时改用确定性脚本化模型，用于无 key 的端到端验证。
    if settings.fake_model:
        from cognition.providers.fake import build_fake_model

        logger.info("using scripted fake model (no LLM key)")
        model = build_fake_model().bind_tools(tools)
    else:
        model = select_model("complex", tools=tools, settings=settings)

    aclose = None
    checkpointer = None
    if settings.pg_dsn:
        checkpointer, aclose = await build_checkpointer(settings.pg_dsn)
        logger.info("postgres checkpointer enabled")

    graph = build_react_graph(model, tools, checkpointer=checkpointer, max_steps=settings.max_steps)

    server = grpc.aio.server()
    agent_pb2_grpc.add_CognitionServiceServicer_to_server(
        CognitionServicer(graph, settings), server
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
        if aclose is not None:
            await aclose()
        logger.info("cognition gRPC server stopped")


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(serve())


if __name__ == "__main__":
    main()
