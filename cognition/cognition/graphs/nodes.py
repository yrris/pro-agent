"""ReAct 图的节点实现。

`make_think_node(model)` 返回 `agent`/think 节点：调用绑定了工具的模型，产出一条
AIMessage（可能含 tool_calls），并把 step +1。模型通过工厂注入，便于测试传入 fake。

act（工具执行）节点直接复用 `langgraph.prebuilt.ToolNode`，不在此重造。
"""

from __future__ import annotations

from typing import Callable, Optional

from langchain_core.language_models.chat_models import BaseChatModel

from cognition.graphs.history import (
    HistoryPolicy,
    plan_history_reduction,
    repair_dangling_tool_calls,
)
from cognition.graphs.state import AgentState


def make_think_node(
    model: BaseChatModel, *, history_policy: Optional[HistoryPolicy] = None
) -> Callable[[AgentState], dict]:
    """构造 think 节点（闭包注入模型）。

    注意：节点内用 `model.invoke`。在 `graph.astream_events(version="v2")` 上下文中，
    LangGraph 会请求流式，BaseChatModel 据此走 `_stream` 路径，从而产出 token 流。

    入模型前两道只读投影（都不改 state、不写 events）：
    1. `repair_dangling_tool_calls`：修复悬空 tool_calls/孤儿 ToolMessage——工具崩溃
       当轮留下的病态 checkpoint 会让此后每轮 provider 400（线程永久污染），修复投影
       让已污染的旧会话自动痊愈；
    2. 若给定 history_policy，再做「token 预算·近期优先」裁剪。
    """

    def think(state: AgentState) -> dict:
        step = int(state.get("step", 0))
        messages = repair_dangling_tool_calls(state["messages"])
        if history_policy is not None:
            messages = plan_history_reduction(messages, history_policy).messages
        ai_msg = model.invoke(messages)
        return {"messages": [ai_msg], "step": step + 1}

    return think
