"""CognitionService gRPC servicer 实现（grpc.aio，server-streaming）。

Run 是异步生成器：
1. 由 RunRequest 装配 AgentState（query 入 messages）。
2. graph.astream_events(version="v2", config={configurable:{thread_id:session_id}, recursion_limit})。
3. 逐事件喂 EventMapper，yield Event.to_proto()。
4. 客户端取消（CancelledError）→ 干净停止；节点异常 → 发终态 result(finish, error) 关闭流。
"""

from __future__ import annotations

import asyncio
import logging

from langchain_core.messages import HumanMessage

from cognition._genproto import agent_pb2_grpc
from cognition.config import Settings
from cognition.events.mapper import EventMapper

logger = logging.getLogger(__name__)


class CognitionServicer(agent_pb2_grpc.CognitionServiceServicer):
    """一次 run = 一个 server-streaming RPC。"""

    def __init__(self, graph, settings: Settings) -> None:
        self.graph = graph
        self.settings = settings

    async def Run(self, request, context):  # noqa: N802 (gRPC 方法名固定)
        run_id = request.run_id or "unknown"
        session_id = request.session_id or run_id
        max_steps = request.max_steps or self.settings.max_steps

        mapper = EventMapper(run_id)

        state = {
            "messages": [HumanMessage(content=request.query)],
            "request_id": run_id,
            "session_id": session_id,
            "query": request.query,
            "product_files": [],
            "is_stream": True,
            "step": 0,
        }
        config = {
            "configurable": {"thread_id": session_id},
            # think+act 各占一个 superstep，留余量。
            "recursion_limit": 2 * int(max_steps) + 5,
        }

        try:
            async for ev in self.graph.astream_events(state, version="v2", config=config):
                for out in mapper.handle(ev):
                    yield out.to_proto()
        except asyncio.CancelledError:
            # 客户端断开/取消：停止图执行，不再发事件。
            logger.info("run %s cancelled", run_id)
            raise
        except Exception as exc:  # noqa: BLE001 — 节点异常兜底，保证流干净关闭
            logger.exception("run %s failed", run_id)
            yield mapper.error_result(str(exc)).to_proto()
