"""ReAct 图的节点实现。

`make_think_node(model)` 返回 `agent`/think 节点：调用绑定了工具的模型，产出一条
AIMessage（可能含 tool_calls），并把 step +1。模型通过工厂注入，便于测试传入 fake。

act（工具执行）节点直接复用 `langgraph.prebuilt.ToolNode`，不在此重造。
"""

from __future__ import annotations

from typing import Callable, Optional

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import SystemMessage
from langchain_core.runnables import RunnableConfig

from cognition.graphs.history import (
    HistoryPolicy,
    plan_history_reduction,
    repair_dangling_tool_calls,
)
from cognition.graphs.state import AgentState


def format_prompt_from_config(config: Optional[RunnableConfig], prompts: dict[str, str]) -> str:
    """从 config.metadata 取 output_format 并映射为提示词（未知值/缺省→空串）。

    per-run 值走 config 而非 state：绝不把 SystemMessage 写进 checkpoint——
    持久化后不同格式的多轮 run 会累积互相矛盾的指令，且中位 system 消息会被
    langchain-anthropic 直接拒绝（续聊切 Claude 即 400）。
    """
    if not config or not prompts:
        return ""
    fmt = str((config.get("metadata") or {}).get("output_format", "") or "")
    return prompts.get(fmt, "")


# 生图模式指令（Composer 生图开关置位 → metadata.image_gen）：引导模型可靠调用
# image_generate（含图生图 source_images），并在指定输出格式时用对应技能把图嵌入。
IMAGE_GEN_INSTRUCTION = (
    "【生图模式已开启】用户希望本轮生成图片。请务必调用 image_generate 工具产出图片："
    "prompt 写清主体/风格/构图/光影（可先查 image-style-library 技能的风格模板）。"
    "若用户上传了图片附件，把其文件名填入 image_generate 的 source_images 参数做图生图/编辑。"
    "若同时指定了输出格式（如网页/文档/PPT），先生成图片，再用对应技能"
    "（frontend-design 做网页、ppt-generation 做文档/PPT）把生成的图片与文字一起编排进最终产物。"
)


def leading_prompt_from_config(
    config: Optional[RunnableConfig], format_prompts: Optional[dict[str, str]]
) -> str:
    """把 image_gen 指令与 output_format 提示词拼成**一条** leading system 文本（可空）。

    合并成一条：多条中位/前置 system 消息在续聊切 Claude 时会被 langchain-anthropic 拒；
    单条 leading 是验证过的安全形态。两者正交，各有则用空行分隔。
    """
    parts: list[str] = []
    meta = (config.get("metadata") or {}) if config else {}
    if str(meta.get("image_gen", "") or "").lower() in ("1", "true", "yes"):
        parts.append(IMAGE_GEN_INSTRUCTION)
    fmt = format_prompt_from_config(config, format_prompts or {})
    if fmt:
        parts.append(fmt)
    return "\n\n".join(parts)


def make_think_node(
    model: BaseChatModel,
    *,
    history_policy: Optional[HistoryPolicy] = None,
    expander: Optional[Callable[[list], list]] = None,
    format_prompts: Optional[dict[str, str]] = None,
) -> Callable[[AgentState], dict]:
    """构造 think 节点（闭包注入模型）。

    注意：节点内用 `model.invoke`。在 `graph.astream_events(version="v2")` 上下文中，
    LangGraph 会请求流式，BaseChatModel 据此走 `_stream` 路径，从而产出 token 流。

    入模型前三道只读投影（都不改 state、不写 events），顺序固定：
    1. `repair_dangling_tool_calls`：修复悬空 tool_calls/孤儿 ToolMessage——工具崩溃
       当轮留下的病态 checkpoint 会让此后每轮 provider 400（线程永久污染），修复投影
       让已污染的旧会话自动痊愈；
    2. 若给定 history_policy，做「token 预算·近期优先」裁剪（附件引用块按固定估价，
       见 history.IMAGE_CHAR_COST）；
    3. 若给定 expander，把 pro_attachment 引用块展开为真实内容（base64 图片/占位文本）
       ——放最后：裁剪按占位估价，展开后的大 base64 只活在本次模型调用里。
    """

    def think(state: AgentState, config: RunnableConfig = None) -> dict:  # type: ignore[assignment]
        step = int(state.get("step", 0))
        messages = repair_dangling_tool_calls(state["messages"])
        if history_policy is not None:
            messages = plan_history_reduction(messages, history_policy).messages
        if expander is not None:
            messages = expander(messages)
        # 生图指令 + 输出格式：调用期临时前置**单条** leading SystemMessage（只活在本次
        # invoke，不进 checkpoint；plan 的 executor 分支经 metadata spread 免费获得）。
        prefix = leading_prompt_from_config(config, format_prompts)
        if prefix:
            messages = [SystemMessage(content=prefix), *messages]
        ai_msg = model.invoke(messages)
        return {"messages": [ai_msg], "step": step + 1}

    return think
