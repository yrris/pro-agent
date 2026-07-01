"""确定性脚本化模型，用于无需真实 LLM key 的端到端验证。

由 COGNITION_FAKE_MODEL=1 在服务启动时启用：
- ReAct（agent_type=react）：先调用一次 calculator(2*(3+4))，再给最终答案。
- Plan-Execute（agent_type=plan_solve）：planner 产出 2 步计划（步骤1 含两个 <sep> 子任务、
  步骤2 单任务），executor 每个子任务做一次 calculator 调用，最后 finish→summary。

切换到真实模型只需去掉该开关。

并行安全：Plan-Execute 的 executor 会并行复用同一个 fake 模型实例，因此 executor / planner
的 fake **必须无状态**（按传入 messages 决策，而非可变 idx 计数），否则并行分支会相互踩踏
（idx 串号）、且服务长驻时跨 run 泄漏状态。`ScriptedChatModel`（idx 版）仅留给 M1 单 ReAct。
"""

from __future__ import annotations

from typing import Any, Callable, List

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, ToolMessage
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


class MessageDrivenChatModel(BaseChatModel):
    """无状态 fake 模型：按传入 messages 决定返回，可安全并行复用。

    `decide(messages) -> AIMessage` 不得依赖任何可变实例状态，从而对并行分支与跨 run 复用安全。
    """

    decide: Callable[[List[BaseMessage]], AIMessage]

    @property
    def _llm_type(self) -> str:
        return "message-driven-fake"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "MessageDrivenChatModel":  # noqa: ARG002
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ARG002
        return ChatResult(generations=[ChatGeneration(message=self.decide(list(messages)))])

    def _stream(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ARG002
        msg = self.decide(list(messages))
        if msg.content:
            yield ChatGenerationChunk(message=AIMessageChunk(content=msg.content))
        yield ChatGenerationChunk(
            message=AIMessageChunk(content="", tool_calls=list(msg.tool_calls or []))
        )


def _has_prior_plan(messages: List[BaseMessage]) -> bool:
    """历史中是否已有 planning 工具调用（用于区分 create / replan，无状态）。"""
    for m in messages:
        if isinstance(m, AIMessage):
            for tc in m.tool_calls or []:
                if (tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", "")) == "planning":
                    return True
    return False


def _fake_planner_decide(messages: List[BaseMessage]) -> AIMessage:
    """fake planner：首轮产出 2 步计划（步骤1 两个 <sep> 子任务、步骤2 单任务）；其后只思考、不改步骤。

    计划推进由确定性 plan-lifecycle 完成（mark_step_completed 自动推进/收尾），因此 replan 轮
    不必再产出步骤——只给一段思考文本即可（plan_thought）。
    """
    if not _has_prior_plan(messages):
        return AIMessage(
            content="我来把任务拆成可并行的步骤。",
            tool_calls=[
                {
                    "name": "planning",
                    "args": {
                        "command": "create",
                        "title": "计算并汇总",
                        "steps": ["计算 2+3<sep>计算 4*5", "计算 10-1"],
                    },
                    "id": "plan_create",
                }
            ],
        )
    return AIMessage(content="上一轮子任务已完成，继续推进计划。")


def _fake_executor_decide(messages: List[BaseMessage]) -> AIMessage:
    """fake executor（无状态）：未执行过工具→调一次 calculator；已有工具结果→给最终答复。"""
    has_tool_result = any(isinstance(m, ToolMessage) for m in messages)
    if has_tool_result:
        return AIMessage(content="子任务完成。")
    return AIMessage(
        content="我用计算器算一下。",
        tool_calls=[{"name": "calculator", "args": {"expression": "1+1"}, "id": "call_1"}],
    )


def _fake_rag_decide(messages: List[BaseMessage]) -> AIMessage:
    """fake RAG 模型：按提示词关键字分派 route/expand/reflect/generate 响应（无状态）。"""
    text = "".join(str(getattr(m, "content", "")) for m in messages)
    if "只回答 YES 或 NO" in text:  # route
        simple = any(g in text for g in ("你好", "谢谢", "hello", "hi"))
        return AIMessage(content="NO" if simple else "YES")
    if "拆解成" in text:  # expand
        return AIMessage(content="子问题一\n子问题二")
    if "是否足够" in text:  # reflect：一轮即判足够
        return AIMessage(content='{"is_answer": true, "rewrite_query": ""}')
    if "直接" in text:  # direct（simple 路径）
        return AIMessage(content="这是直接回答。")
    return AIMessage(content="根据检索到的证据作答〔1〕。")  # generate


def build_fake_rag_model() -> MessageDrivenChatModel:
    """RAG 子图的 fake 模型（无状态、按提示词关键字分派）。"""
    return MessageDrivenChatModel(decide=_fake_rag_decide)


def build_fake_plan_model() -> MessageDrivenChatModel:
    """plan_solve 的 fake planner（无状态、可安全并行/跨 run 复用）。"""
    return MessageDrivenChatModel(decide=_fake_planner_decide)


def build_fake_executor_model() -> MessageDrivenChatModel:
    """plan_solve 的 fake executor（无状态、可安全并行复用）。"""
    return MessageDrivenChatModel(decide=_fake_executor_decide)
