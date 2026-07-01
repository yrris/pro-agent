"""CognitionService gRPC servicer 实现（grpc.aio，server-streaming）。

按 `RunRequest.agent_type` 路由：
- "plan_solve" → Plan-Execute 图（plan→executor 子图→summary，含 replan 与并行子任务）。
- 其它（默认 "react"）→ M1 ReAct 图。

Run 是异步生成器：
1. 由 RunRequest 按 agent_type 装配初始 State。
2. graph.astream_events(version="v2", config={configurable:{thread_id:session_id}, recursion_limit, metadata})。
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
from cognition.observability.langfuse_seam import build_langfuse_callbacks

logger = logging.getLogger(__name__)

AGENT_TYPE_PLAN_SOLVE = "plan_solve"


class CognitionServicer(agent_pb2_grpc.CognitionServiceServicer):
    """一次 run = 一个 server-streaming RPC。按 agent_type 选图。"""

    def __init__(self, react_graph, settings: Settings, plan_graph=None, tool_providers=None) -> None:
        self.react_graph = react_graph
        self.plan_graph = plan_graph
        self.settings = settings
        # 工具名 → provider（local/mcp/skill），装配期从工具集构建后注入 EventMapper。
        self.tool_providers = dict(tool_providers or {})

    def _build(self, request):
        """返回 (graph, initial_state, recursion_limit)。"""
        run_id = request.run_id or "unknown"
        session_id = request.session_id or run_id
        max_steps = request.max_steps or self.settings.max_steps
        agent_type = request.agent_type or "react"

        if agent_type == AGENT_TYPE_PLAN_SOLVE and self.plan_graph is not None:
            state = {
                "query": request.query,
                "request_id": run_id,
                "session_id": session_id,
                "plan": None,
                "round": 0,
                "step": 0,
                "planner_messages": [],
                "sub_results": [],
            }
            # 外层循环 + 并行分支 join 占用 superstep，留足余量。
            recursion = 4 * int(self.settings.planner_max_steps) + 25
            return self.plan_graph, state, recursion

        state = {
            "messages": [HumanMessage(content=request.query)],
            "request_id": run_id,
            "session_id": session_id,
            "query": request.query,
            "product_files": [],
            "is_stream": True,
            "step": 0,
        }
        recursion = 2 * int(max_steps) + 5
        return self.react_graph, state, recursion

    async def Run(self, request, context):  # noqa: N802 (gRPC 方法名固定)
        run_id = request.run_id or "unknown"
        session_id = request.session_id or run_id
        agent_type = request.agent_type or "react"
        # 结构化日志：run_id/session_id/agent_type 关联键（与 Go 侧一致，跨进程串同一 run）。
        log = logging.LoggerAdapter(
            logger, {"run_id": run_id, "session_id": session_id, "agent_type": agent_type}
        )

        mapper = EventMapper(run_id, self.tool_providers)
        graph, state, recursion = self._build(request)
        metadata = {"request_id": run_id, "run_id": run_id, "session_id": session_id}
        config = {
            "configurable": {"thread_id": session_id},
            "recursion_limit": recursion,
            "metadata": metadata,
        }
        # 可选 Langfuse trace（默认关、未装即 no-op）。
        callbacks = build_langfuse_callbacks(self.settings)
        if callbacks:
            config["callbacks"] = callbacks
            metadata["langfuse_session_id"] = session_id

        log.info("run start")
        try:
            async for ev in graph.astream_events(state, version="v2", config=config):
                for out in mapper.handle(ev):
                    yield out.to_proto()
            log.info("run done")
        except asyncio.CancelledError:
            log.info("run cancelled")
            raise
        except Exception as exc:  # noqa: BLE001 — 节点异常兜底，保证流干净关闭
            log.exception("run failed")
            yield mapper.error_result(str(exc)).to_proto()
