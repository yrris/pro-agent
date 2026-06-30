"""手搓 ReAct 图（think⇄act 环）。

刻意不使用 `create_react_agent`：自掌事件 schema 映射、maxSteps 优雅终止、工具错误→failed
映射；但复用 prebuilt `ToolNode` 执行工具（不重造工具执行）。

拓扑：START → agent →(条件)→ {tools, END}；tools → agent。
"""

from __future__ import annotations

from typing import Optional, Sequence

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.tools import BaseTool
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode

from cognition.graphs.nodes import make_think_node
from cognition.graphs.state import AgentState, route_after_agent


def build_react_graph(
    model: BaseChatModel,
    tools: Sequence[BaseTool],
    checkpointer: Optional[BaseCheckpointSaver] = None,
    *,
    max_steps: int = 40,
) -> CompiledStateGraph:
    """装配并编译 ReAct 图。

    Args:
        model: 已（或将）绑定工具的 chat 模型。
        tools: 本地工具列表（用于 ToolNode）。
        checkpointer: 可选 Postgres checkpointer（None 则不持久化，便于测试）。
        max_steps: ReAct 循环上限（注入路由纯函数）。
    """
    graph = StateGraph(AgentState)
    graph.add_node("agent", make_think_node(model))
    graph.add_node("tools", ToolNode(list(tools)))

    graph.add_edge(START, "agent")

    def _route(state: AgentState):
        return route_after_agent(state, max_steps)

    graph.add_conditional_edges("agent", _route, {"tools": "tools", END: END})
    graph.add_edge("tools", "agent")

    return graph.compile(checkpointer=checkpointer)
