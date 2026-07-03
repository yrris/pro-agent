"""输出格式注入（M9 B6）。

不变量（压测修正的核心）：SystemMessage **只活在单次模型调用里**——
state/checkpoint 永不出现它。持久化会累积互相矛盾的格式指令，且中位 system
消息会被 langchain-anthropic 拒绝（续聊切 Claude 即 400）。
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from cognition.config import Settings
from cognition.graphs.nodes import format_prompt_from_config, make_think_node
from cognition.graphs.plan_execute import PLANNER_SYSTEM, compose_planner_system

PROMPTS = Settings().output_format_prompts


class _CaptureModel:
    """记录每次 invoke 收到的消息序列。"""

    def __init__(self):
        self.calls: list[list] = []

    def invoke(self, messages):
        self.calls.append(list(messages))
        return AIMessage(content="ok")


def test_format_prompt_from_config_matrix():
    assert format_prompt_from_config({"metadata": {"output_format": "table"}}, PROMPTS) == PROMPTS["table"]
    assert format_prompt_from_config({"metadata": {"output_format": "nope"}}, PROMPTS) == ""  # 未知值忽略
    assert format_prompt_from_config({"metadata": {}}, PROMPTS) == ""
    assert format_prompt_from_config(None, PROMPTS) == ""
    assert format_prompt_from_config({"metadata": {"output_format": "html"}}, {}) == ""


def test_think_injects_ephemeral_system_only_for_this_invoke():
    model = _CaptureModel()
    think = make_think_node(model, format_prompts=PROMPTS)  # type: ignore[arg-type]
    state = {"messages": [HumanMessage(content="问题")], "step": 0}

    out = think(state, config={"metadata": {"output_format": "table"}})
    # 模型看到 leading SystemMessage + 原消息。
    sent = model.calls[0]
    assert isinstance(sent[0], SystemMessage) and "表格" in sent[0].content
    assert isinstance(sent[1], HumanMessage)
    # 零残留：节点返回的 update 只有 AIMessage，state 原样（checkpoint 不会收到 system）。
    assert all(not isinstance(m, SystemMessage) for m in out["messages"])
    assert all(not isinstance(m, SystemMessage) for m in state["messages"])

    # 第二轮无格式 run：同一图/同一 state，不再注入。
    think(state, config={"metadata": {}})
    assert all(not isinstance(m, SystemMessage) for m in model.calls[1])


def test_compose_planner_system():
    text = compose_planner_system(PLANNER_SYSTEM, "SOP内容", "ppt", PROMPTS)
    assert "SOP内容" in text and PROMPTS["ppt"] in text
    # 未知/空格式 → 原样。
    assert compose_planner_system(PLANNER_SYSTEM, "s", "nope", PROMPTS) == PLANNER_SYSTEM.replace("{{sop}}", "s")
    assert compose_planner_system(PLANNER_SYSTEM, "s", "", PROMPTS) == PLANNER_SYSTEM.replace("{{sop}}", "s")
