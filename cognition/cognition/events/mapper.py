"""把 LangGraph `astream_events(version="v2")` 事件确定性映射成共享 schema Event。

M1（ReAct）规则不变：agent 节点的 on_chat_model_* → tool_thought；on_chat_model_end 带
tool_calls → tool_call(running)，无 tool_calls → result(finish)；tools 节点 on_tool_end →
tool_call(success/failed) + tool_result。

M2（Plan-Execute）加性扩展——按 `metadata.langgraph_node`（及子图注入的 `branch_id`）区分：
- **planner 节点**的 on_chat_model_* → **plan_thought**（带 plannerRoundId，每个 planner round 稳定）；
  planner 的 tool_calls（planning）不产出 tool_call 事件，仅封口 thought。
- **自定义事件**（节点内 `adispatch_custom_event`）：
  - name="plan" → **plan** 快照（PlanPayload，复用当前 plannerRoundId）。
  - name="task" → **task**（TaskPayload，**无** plannerRoundId）。
  - name="result" → **result**（finish=True，整 run 终态，恰一次）。
- **executor（ReAct 子图，节点 agent/tools，metadata 带 branch_id）**：仍产出 tool_thought /
  tool_call / tool_result，但：
  - think/tool 的 message_id、tool_call_id 都按 branch_id **命名空间化**（并行共用 fake 模型也不撞 id）；
  - 子任务最终答复（无 tool_calls）**不**产出 result/finish（终态 result 只由 summary 的自定义事件给出）。

不变量：seq 每 run 单调、无空洞、从 1（并行事件按到达序分配）；finish=True 恰好一次且仅在 result；
tool_call 的 running 与 success/failed 共享同一（命名空间化的）tool_call_id。
"""

from __future__ import annotations

from typing import Any, Optional

from cognition.events.schema import (
    ArtifactRef,
    Event,
    EventType,
    PlanPayload,
    ResultPayload,
    TaskPayload,
    ThoughtPayload,
    ToolCallStatus,
    ToolPayload,
    now_unix_ms,
)
from cognition.providers.reasoning import extract_text_delta

_AGENT_NODE = "agent"
_TOOLS_NODE = "tools"
_PLANNER_NODE = "planner"


class EventMapper:
    """单个 run 的有状态映射器（非线程安全，按 run 实例化）。"""

    def __init__(self, run_id: str, tool_providers: Optional[dict[str, str]] = None) -> None:
        self.run_id = run_id
        self._seq = 0
        self._finished = False
        # 工具名 → provider（local/mcp/skill）。装配期从工具集构建后注入；缺省即 "local"（向后兼容）。
        self._tool_providers: dict[str, str] = dict(tool_providers or {})

        # planner round 追踪（planner 非并行，单槽即可）。
        self._planner_round = 0
        self._planner_round_id = ""
        self._planner_think_mid = ""

        # executor（per-branch）think 追踪：branch -> 状态。branch "" 表示独立 ReAct（M1）。
        self._branch_think_step: dict[str, int] = {}
        self._branch_think_mid: dict[str, str] = {}
        self._branch_dispatch: dict[str, int] = {}

        # 进行中的工具调用，键为命名空间化后的 tool_call_id。
        self._running: dict[str, dict[str, Any]] = {}

        # task 序号（保证 task 的 message_id 唯一）。
        self._task_no = 0

    # —— 内部小工具 ——
    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    @staticmethod
    def _norm_branch(branch: Any) -> str:
        return str(branch) if branch else ""

    def _ns_tcid(self, branch: str, tcid: str) -> str:
        return f"{branch}:{tcid}" if branch else tcid

    def _provider_for(self, tool_name: str) -> str:
        """按工具名解析 provider；未登记默认 "local"（MCP 工具名已 namespaced）。"""
        return self._tool_providers.get(tool_name, "local")

    def _exec_think_mid(self, branch: str, step: int) -> str:
        return f"{self.run_id}:{branch}:think:{step}" if branch else f"{self.run_id}:think:{step}"

    # —— 主入口 ——
    def handle(self, event: dict) -> list[Event]:
        """消费一个 astream_events v2 事件，返回 0..N 个 schema Event。"""
        et = event.get("event")
        md = event.get("metadata") or {}
        node = md.get("langgraph_node")

        if et == "on_custom_event":
            name = event.get("name")
            if name == "plan":
                return self._on_plan(event)
            if name == "task":
                return self._on_task(event)
            if name == "result":
                return self._on_result(event)
            return []

        if node == _PLANNER_NODE:
            if et == "on_chat_model_start":
                return self._on_planner_start()
            if et == "on_chat_model_stream":
                return self._on_planner_stream(event)
            if et == "on_chat_model_end":
                return self._on_planner_end()
            return []

        if node == _AGENT_NODE:
            branch = self._norm_branch(md.get("branch_id"))
            if et == "on_chat_model_start":
                return self._on_exec_start(branch)
            if et == "on_chat_model_stream":
                return self._on_exec_stream(event, branch)
            if et == "on_chat_model_end":
                return self._on_exec_end(event, branch)
            return []

        if node == _TOOLS_NODE and et == "on_tool_end":
            branch = self._norm_branch(md.get("branch_id"))
            return self._on_tool_end(event, branch)

        return []

    # ——————————————————————————————————————————————————————————
    # planner → plan_thought
    # ——————————————————————————————————————————————————————————
    def _on_planner_start(self) -> list[Event]:
        self._planner_round += 1
        self._planner_round_id = f"{self.run_id}:planner:{self._planner_round}"
        self._planner_think_mid = f"{self.run_id}:plan_thought:{self._planner_round}"
        return [
            Event(
                seq=self._next_seq(),
                run_id=self.run_id,
                message_id=self._planner_think_mid,
                type=EventType.PLAN_THOUGHT,
                ts_unix_ms=now_unix_ms(),
                is_final=False,
                step=str(self._planner_round),
                tool_thought=ThoughtPayload(text="", planner_round_id=self._planner_round_id),
            )
        ]

    def _on_planner_stream(self, event: dict) -> list[Event]:
        text = extract_text_delta((event.get("data") or {}).get("chunk"))
        if not text:
            return []
        return [
            Event(
                seq=self._next_seq(),
                run_id=self.run_id,
                message_id=self._planner_think_mid,
                type=EventType.PLAN_THOUGHT,
                ts_unix_ms=now_unix_ms(),
                is_final=False,
                step=str(self._planner_round),
                tool_thought=ThoughtPayload(text=text, planner_round_id=self._planner_round_id),
            )
        ]

    def _on_planner_end(self) -> list[Event]:
        # planner 的 tool_calls（planning）不产出 tool_call；仅封口 thought。
        return [
            Event(
                seq=self._next_seq(),
                run_id=self.run_id,
                message_id=self._planner_think_mid or f"{self.run_id}:plan_thought:{self._planner_round}",
                type=EventType.PLAN_THOUGHT,
                ts_unix_ms=now_unix_ms(),
                is_final=True,
                step=str(self._planner_round),
                tool_thought=ThoughtPayload(text="", planner_round_id=self._planner_round_id),
            )
        ]

    # ——————————————————————————————————————————————————————————
    # 自定义事件 → plan / task / result
    # ——————————————————————————————————————————————————————————
    def _on_plan(self, event: dict) -> list[Event]:
        data = event.get("data") or {}
        return [
            Event(
                seq=self._next_seq(),
                run_id=self.run_id,
                message_id=f"{self.run_id}:plan:{self._planner_round}",
                type=EventType.PLAN,
                ts_unix_ms=now_unix_ms(),
                is_final=True,
                step=str(self._planner_round),
                plan=PlanPayload(
                    title=str(data.get("title", "")),
                    steps=list(data.get("steps", []) or []),
                    step_status=list(data.get("step_status", []) or []),
                    notes=list(data.get("notes", []) or []),
                    planner_round_id=self._planner_round_id,
                ),
            )
        ]

    def _on_task(self, event: dict) -> list[Event]:
        data = event.get("data") or {}
        self._task_no += 1
        return [
            Event(
                seq=self._next_seq(),
                run_id=self.run_id,
                message_id=f"{self.run_id}:task:{self._task_no}",
                type=EventType.TASK,
                ts_unix_ms=now_unix_ms(),
                is_final=True,
                step=str(self._planner_round),
                task=TaskPayload(text=str(data.get("text", ""))),
            )
        ]

    def _on_result(self, event: dict) -> list[Event]:
        data = event.get("data") or {}
        return [self._make_result(str(data.get("text", "")))]

    # ——————————————————————————————————————————————————————————
    # executor（ReAct 子图）→ tool_thought / tool_call / tool_result
    # ——————————————————————————————————————————————————————————
    def _on_exec_start(self, branch: str) -> list[Event]:
        step = self._branch_think_step.get(branch, 0) + 1
        self._branch_think_step[branch] = step
        self._branch_dispatch[branch] = 0
        mid = self._exec_think_mid(branch, step)
        self._branch_think_mid[branch] = mid
        return [
            Event(
                seq=self._next_seq(),
                run_id=self.run_id,
                message_id=mid,
                type=EventType.TOOL_THOUGHT,
                ts_unix_ms=now_unix_ms(),
                is_final=False,
                step=str(step),
                tool_thought=ThoughtPayload(text=""),
            )
        ]

    def _on_exec_stream(self, event: dict, branch: str) -> list[Event]:
        text = extract_text_delta((event.get("data") or {}).get("chunk"))
        if not text:
            return []
        step = self._branch_think_step.get(branch, 0)
        mid = self._branch_think_mid.get(branch) or self._exec_think_mid(branch, step)
        return [
            Event(
                seq=self._next_seq(),
                run_id=self.run_id,
                message_id=mid,
                type=EventType.TOOL_THOUGHT,
                ts_unix_ms=now_unix_ms(),
                is_final=False,
                step=str(step),
                tool_thought=ThoughtPayload(text=text),
            )
        ]

    def _on_exec_end(self, event: dict, branch: str) -> list[Event]:
        out = (event.get("data") or {}).get("output")
        tool_calls = list(getattr(out, "tool_calls", None) or [])
        step = self._branch_think_step.get(branch, 0)
        mid = self._branch_think_mid.get(branch) or self._exec_think_mid(branch, step)
        events: list[Event] = []

        if tool_calls:
            # 封口当前 thought。
            events.append(
                Event(
                    seq=self._next_seq(),
                    run_id=self.run_id,
                    message_id=mid,
                    type=EventType.TOOL_THOUGHT,
                    ts_unix_ms=now_unix_ms(),
                    is_final=True,
                    step=str(step),
                    tool_thought=ThoughtPayload(text=""),
                )
            )
            for tc in tool_calls:
                raw = str(tc.get("id") or "")
                name = str(tc.get("name") or "")
                args = tc.get("args") or {}
                if not isinstance(args, dict):
                    args = {}
                tcid = self._ns_tcid(branch, raw)
                self._branch_dispatch[branch] = self._branch_dispatch.get(branch, 0) + 1
                di = self._branch_dispatch[branch]
                self._running[tcid] = {"name": name, "dispatch_index": di, "step": step}
                events.append(
                    Event(
                        seq=self._next_seq(),
                        run_id=self.run_id,
                        message_id=tcid,
                        type=EventType.TOOL_CALL,
                        ts_unix_ms=now_unix_ms(),
                        is_final=False,
                        step=str(step),
                        tool_call=ToolPayload(
                            tool_call_id=tcid,
                            tool_name=name,
                            tool_provider=self._provider_for(name),
                            status=ToolCallStatus.RUNNING,
                            dispatch_index=di,
                            input=args,
                            summary=f"正在调用 {name}",
                        ),
                    )
                )
            return events

        # 无 tool_calls：分支内（branch 非空）= 子任务最终答复，不产出 result；
        # 独立 ReAct（branch 为空，M1）= 终态 result(finish)。
        if branch:
            events.append(
                Event(
                    seq=self._next_seq(),
                    run_id=self.run_id,
                    message_id=mid,
                    type=EventType.TOOL_THOUGHT,
                    ts_unix_ms=now_unix_ms(),
                    is_final=True,
                    step=str(step),
                    tool_thought=ThoughtPayload(text=""),
                )
            )
            return events
        events.append(self._make_result(extract_text_delta(out)))
        return events

    def _on_tool_end(self, event: dict, branch: str) -> list[Event]:
        out = (event.get("data") or {}).get("output")
        raw = str(getattr(out, "tool_call_id", "") or "")
        tcid = self._ns_tcid(branch, raw)
        info = self._running.get(tcid, {})
        name = str(info.get("name") or getattr(out, "name", "") or "")
        dispatch_index = int(info.get("dispatch_index", 0))
        step = str(info.get("step", self._branch_think_step.get(branch, 0)))
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
                    step=step,
                    tool_call=ToolPayload(
                        tool_call_id=tcid,
                        tool_name=name,
                        tool_provider=self._provider_for(name),
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
                    step=step,
                    tool_result=ToolPayload(
                        tool_call_id=tcid,
                        tool_name=name,
                        tool_provider=self._provider_for(name),
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
                    step=step,
                    tool_call=ToolPayload(
                        tool_call_id=tcid,
                        tool_name=name,
                        tool_provider=self._provider_for(name),
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
                    step=step,
                    tool_result=ToolPayload(
                        tool_call_id=tcid,
                        tool_name=name,
                        tool_provider=self._provider_for(name),
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
            step="result",
            result=ResultPayload(text=text),
        )

    def error_result(self, message: str) -> Event:
        """节点异常时的终态 result（把错误放进 text，关闭 run）。"""
        return self._make_result(f"运行出错: {message}")


def _coerce_artifacts(artifact: Any) -> list[ArtifactRef]:
    """把 ToolMessage.artifact 尽力转成 ArtifactRef 列表。"""
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
