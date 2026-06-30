"""把 LangGraph `astream_events(version="v2")` 事件确定性映射成共享 schema Event。

约定（务必与契约一致）：
- 用 run_id（= RunRequest.run_id，图级 run 身份）做 Event.run_id 与 think 消息 id；
  astream_events 自带的 run_id 是每次 LLM/工具调用的 id，不是图级 run id，这里不用它。
- seq 每 run 单调、无空洞、从 1。
- think 步序自增计数：每次 on_chat_model_start(node="agent") +1，作为该轮 thought 的 step
  与 message_id 后缀。

映射规则：
- on_chat_model_start(agent) → 开 tool_thought（is_final=False），message_id=f"{run_id}:think:{step}"。
- on_chat_model_stream(agent) → tool_thought 增量（is_final=False，同 message_id，delta 文本）；
  空文本块跳过。
- on_chat_model_end(agent)：
  * 有 tool_calls → (a) 封口 tool_thought（is_final=True）；
    (b) 每个 tool_call 发 tool_call(status=running, is_final=False, message_id==tool_call_id,
        tool_provider="local", input=args, dispatch_index 本轮从 1 起, summary="正在调用 {name}")。
  * 无 tool_calls → 发 result(finish=True, is_final=True, text=AIMessage content)。
- on_tool_end(tools)：按 ToolMessage.tool_call_id 匹配 running 的 tool_call：
  * status != "error" → tool_call(status=success, is_final=True, summary="{name} 调用完成")
    然后 tool_result(is_final=True, tool_result=observation, artifact_refs 来自 ToolMessage.artifact)。
  * status == "error" → tool_call(status=failed, is_final=True, error_msg, summary="{name} 调用失败")
    然后 tool_result(is_final=True, tool_result=error 文本)（保证回放完整）。

保证：seq 单调无空洞；finish=True 恰好一次且仅在 result；tool_call 的 running 与
success/failed 共享同一个 tool_call_id（作为 message_id）。
"""

from __future__ import annotations

from typing import Any, Optional

from cognition.events.schema import (
    ArtifactRef,
    Event,
    EventType,
    ResultPayload,
    ThoughtPayload,
    ToolCallStatus,
    ToolPayload,
    now_unix_ms,
)
from cognition.providers.reasoning import extract_text_delta

_AGENT_NODE = "agent"
_TOOLS_NODE = "tools"


class EventMapper:
    """单个 run 的有状态映射器（非线程安全，按 run 实例化）。"""

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self._seq = 0
        self._think_step = 0           # think 轮计数（1 起）
        self._dispatch_index = 0       # 当前 think 轮内工具序（1 起，每轮重置）
        self._current_think_mid = ""   # 当前 think 轮的 message_id
        # tool_call_id -> {"name": str, "dispatch_index": int, "step": int}
        self._running: dict[str, dict[str, Any]] = {}
        self._finished = False         # finish 是否已发出（保证恰好一次）

    # —— 内部小工具 ——
    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def _think_mid(self) -> str:
        return f"{self.run_id}:think:{self._think_step}"

    # —— 主入口 ——
    def handle(self, event: dict) -> list[Event]:
        """消费一个 astream_events v2 事件，返回 0..N 个 schema Event。"""
        et = event.get("event")
        node = (event.get("metadata") or {}).get("langgraph_node")

        if et == "on_chat_model_start" and node == _AGENT_NODE:
            return self._on_chat_start()
        if et == "on_chat_model_stream" and node == _AGENT_NODE:
            return self._on_chat_stream(event)
        if et == "on_chat_model_end" and node == _AGENT_NODE:
            return self._on_chat_end(event)
        if et == "on_tool_end" and node == _TOOLS_NODE:
            return self._on_tool_end(event)
        return []

    # —— 各事件处理 ——
    def _on_chat_start(self) -> list[Event]:
        self._think_step += 1
        self._dispatch_index = 0
        self._current_think_mid = self._think_mid()
        return [
            Event(
                seq=self._next_seq(),
                run_id=self.run_id,
                message_id=self._current_think_mid,
                type=EventType.TOOL_THOUGHT,
                ts_unix_ms=now_unix_ms(),
                is_final=False,
                finish=False,
                step=str(self._think_step),
                tool_thought=ThoughtPayload(text=""),
            )
        ]

    def _on_chat_stream(self, event: dict) -> list[Event]:
        chunk = (event.get("data") or {}).get("chunk")
        text = extract_text_delta(chunk)
        if not text:
            return []
        return [
            Event(
                seq=self._next_seq(),
                run_id=self.run_id,
                message_id=self._current_think_mid or self._think_mid(),
                type=EventType.TOOL_THOUGHT,
                ts_unix_ms=now_unix_ms(),
                is_final=False,
                finish=False,
                step=str(self._think_step),
                tool_thought=ThoughtPayload(text=text),
            )
        ]

    def _on_chat_end(self, event: dict) -> list[Event]:
        out = (event.get("data") or {}).get("output")
        tool_calls = list(getattr(out, "tool_calls", None) or [])
        events: list[Event] = []

        if tool_calls:
            # (a) 封口当前 thought
            events.append(
                Event(
                    seq=self._next_seq(),
                    run_id=self.run_id,
                    message_id=self._current_think_mid or self._think_mid(),
                    type=EventType.TOOL_THOUGHT,
                    ts_unix_ms=now_unix_ms(),
                    is_final=True,
                    finish=False,
                    step=str(self._think_step),
                    tool_thought=ThoughtPayload(text=""),
                )
            )
            # (b) 逐个 tool_call(running)
            for tc in tool_calls:
                tcid = str(tc.get("id") or "")
                name = str(tc.get("name") or "")
                args = tc.get("args") or {}
                if not isinstance(args, dict):
                    args = {}
                self._dispatch_index += 1
                self._running[tcid] = {
                    "name": name,
                    "dispatch_index": self._dispatch_index,
                    "step": self._think_step,
                }
                events.append(
                    Event(
                        seq=self._next_seq(),
                        run_id=self.run_id,
                        message_id=tcid,
                        type=EventType.TOOL_CALL,
                        ts_unix_ms=now_unix_ms(),
                        is_final=False,
                        finish=False,
                        step=str(self._think_step),
                        tool_call=ToolPayload(
                            tool_call_id=tcid,
                            tool_name=name,
                            tool_provider="local",
                            status=ToolCallStatus.RUNNING,
                            dispatch_index=self._dispatch_index,
                            input=args,
                            summary=f"正在调用 {name}",
                        ),
                    )
                )
            return events

        # 无 tool_calls → 终态 result
        text = extract_text_delta(out)
        events.append(self._make_result(text))
        return events

    def _on_tool_end(self, event: dict) -> list[Event]:
        out = (event.get("data") or {}).get("output")
        tcid = str(getattr(out, "tool_call_id", "") or "")
        info = self._running.get(tcid, {})
        name = str(info.get("name") or getattr(out, "name", "") or "")
        dispatch_index = int(info.get("dispatch_index", 0))
        step = str(info.get("step", self._think_step))
        status = getattr(out, "status", "success")
        content = getattr(out, "content", "")
        observation = content if isinstance(content, str) else str(content)
        artifact = getattr(out, "artifact", None)

        events: list[Event] = []

        if status == "error":
            events.append(
                Event(
                    seq=self._next_seq(),
                    run_id=self.run_id,
                    message_id=tcid,
                    type=EventType.TOOL_CALL,
                    ts_unix_ms=now_unix_ms(),
                    is_final=True,
                    finish=False,
                    step=step,
                    tool_call=ToolPayload(
                        tool_call_id=tcid,
                        tool_name=name,
                        tool_provider="local",
                        status=ToolCallStatus.FAILED,
                        dispatch_index=dispatch_index,
                        summary=f"{name} 调用失败",
                        error_msg=observation,
                    ),
                )
            )
            events.append(
                Event(
                    seq=self._next_seq(),
                    run_id=self.run_id,
                    message_id=f"{tcid}:result",
                    type=EventType.TOOL_RESULT,
                    ts_unix_ms=now_unix_ms(),
                    is_final=True,
                    finish=False,
                    step=step,
                    tool_result=ToolPayload(
                        tool_call_id=tcid,
                        tool_name=name,
                        tool_provider="local",
                        dispatch_index=dispatch_index,
                        tool_result=observation,
                    ),
                )
            )
        else:
            events.append(
                Event(
                    seq=self._next_seq(),
                    run_id=self.run_id,
                    message_id=tcid,
                    type=EventType.TOOL_CALL,
                    ts_unix_ms=now_unix_ms(),
                    is_final=True,
                    finish=False,
                    step=step,
                    tool_call=ToolPayload(
                        tool_call_id=tcid,
                        tool_name=name,
                        tool_provider="local",
                        status=ToolCallStatus.SUCCESS,
                        dispatch_index=dispatch_index,
                        summary=f"{name} 调用完成",
                    ),
                )
            )
            events.append(
                Event(
                    seq=self._next_seq(),
                    run_id=self.run_id,
                    message_id=f"{tcid}:result",
                    type=EventType.TOOL_RESULT,
                    ts_unix_ms=now_unix_ms(),
                    is_final=True,
                    finish=False,
                    step=step,
                    tool_result=ToolPayload(
                        tool_call_id=tcid,
                        tool_name=name,
                        tool_provider="local",
                        dispatch_index=dispatch_index,
                        tool_result=observation,
                        artifact_refs=_coerce_artifacts(artifact),
                    ),
                )
            )

        self._running.pop(tcid, None)
        return events

    # —— result 构造与终态错误 ——
    def _make_result(self, text: str, *, message_id: Optional[str] = None) -> Event:
        self._finished = True
        return Event(
            seq=self._next_seq(),
            run_id=self.run_id,
            message_id=message_id or f"{self.run_id}:result",
            type=EventType.RESULT,
            ts_unix_ms=now_unix_ms(),
            is_final=True,
            finish=True,
            step=str(self._think_step),
            result=ResultPayload(text=text),
        )

    def error_result(self, message: str) -> Event:
        """节点异常时的终态 result（把错误放进 text，关闭 run）。"""
        return self._make_result(f"运行出错: {message}")


def _coerce_artifacts(artifact: Any) -> list[ArtifactRef]:
    """把 ToolMessage.artifact 尽力转成 ArtifactRef 列表（M1 一般为空）。"""
    if not artifact:
        return []
    items = artifact if isinstance(artifact, list) else [artifact]
    refs: list[ArtifactRef] = []
    for item in items:
        if isinstance(item, ArtifactRef):
            refs.append(item)
        elif isinstance(item, dict):
            try:
                refs.append(ArtifactRef(**{k: v for k, v in item.items() if k in ArtifactRef.model_fields}))
            except Exception:
                continue
    return refs
