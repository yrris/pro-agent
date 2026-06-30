"""确定性脚本化模型，用于无需真实 LLM key 的端到端验证。

由 COGNITION_FAKE_MODEL=1 在服务启动时启用：让 ReAct 图先调用一次 calculator(2*(3+4))，
再给出最终答案。这样可以在不接任何模型 API 的前提下，把 Go↔Python 全链路真实跑通；
切换到真实模型只需去掉该开关。
"""

from __future__ import annotations

from typing import Any, List

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult


class ScriptedChatModel(BaseChatModel):
    """按预设脚本逐轮返回消息的 fake 模型（支持 bind_tools 与流式）。"""

    responses: List[AIMessage] = []
    idx: int = 0

    @property
    def _llm_type(self) -> str:
        return "scripted-fake"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "ScriptedChatModel":  # noqa: ARG002
        return self

    def _next(self) -> AIMessage:
        msg = self.responses[self.idx % len(self.responses)]
        self.idx += 1
        return msg

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ARG002
        return ChatResult(generations=[ChatGeneration(message=self._next())])

    def _stream(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ARG002
        msg = self._next()
        if msg.content:
            yield ChatGenerationChunk(message=AIMessageChunk(content=msg.content))
        yield ChatGenerationChunk(
            message=AIMessageChunk(content="", tool_calls=list(msg.tool_calls or []))
        )


def build_fake_model() -> ScriptedChatModel:
    """先 calculator(2*(3+4))、再给最终答案的脚本化模型。"""
    return ScriptedChatModel(
        responses=[
            AIMessage(
                content="我先用计算器算一下。",
                tool_calls=[{"name": "calculator", "args": {"expression": "2*(3+4)"}, "id": "call_1"}],
            ),
            AIMessage(content="答案是 14。"),
        ]
    )
