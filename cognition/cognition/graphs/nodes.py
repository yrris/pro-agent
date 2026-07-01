"""ReAct 图的节点实现。

`make_think_node(model)` 返回 `agent`/think 节点：调用绑定了工具的模型，产出一条
AIMessage（可能含 tool_calls），并把 step +1。模型通过工厂注入，便于测试传入 fake。

act（工具执行）节点直接复用 `langgraph.prebuilt.ToolNode`，不在此重造。
"""

from __future__ import annotations

from typing import Callable, Optional

from langchain_core.language_models.chat_models import BaseChatModel

from cognition.graphs.history import HistoryPolicy, plan_history_reduction
from cognition.graphs.state import AgentState


def make_think_node(
    model: BaseChatModel, *, history_policy: Optional[HistoryPolicy] = None
) -> Callable[[AgentState], dict]:
    """构造 think 节点（闭包注入模型）。

    注意：节点内用 `model.invoke`。在 `graph.astream_events(version="v2")` 上下文中，
    LangGraph 会请求流式，BaseChatModel 据此走 `_stream` 路径，从而产出 token 流。

    若给定 history_policy，则在入模型前对累积 messages 做「token 预算·近期优先」只读投影
    （不改 state、不写 events），把有界视图喂给模型。
    """

    def think(state: AgentState) -> dict:
        step = int(state.get("step", 0))
        messages = state["messages"]
        if history_policy is not None:
            messages = plan_history_reduction(messages, history_policy).messages
        ai_msg = model.invoke(messages)
        return {"messages": [ai_msg], "step": step + 1}

    return think
