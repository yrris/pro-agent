"""Plan-Execute 编排图（plan → executor 子图 → summary，含动态 replan 与可控并行子任务）。

映射原项目 Step2PlanExecuteNode 的外层循环（非字面照搬，落到 LangGraph 拓扑）：

    START → sop_recall → planner ──route_after_planner──▶ Send("executor", …) ×N（并行，信号量限宽）
                            ▲                              └──(计划完成/超步/ERROR)──▶ summary → END
                            └──── executor（复用 M1 ReAct 子图）──(分支 join，sub_results 经 reducer 合并)──┘

确定性 plan-lifecycle 管步骤状态（graphs/plan_lifecycle.py）；LLM 只产出步骤列表/思考。
executor 复用 M1 `build_react_graph`（原 ExecutorAgent 即任务级 ReAct）。

★ 并行控制（框架给 vs 我控制，见 docs/03 §4）★
① 并行宽度：`Send` 无内建上限 → executor 节点内用 `asyncio.Semaphore(max_parallel)` 限流
   （按 running loop 取，跨 loop 安全、不跨 run/测试泄漏）。
② reducer 并发安全：`merge_sub_results` 可交换/可结合、按 (round, branch_id) 去重、规范排序。
③ 每分支预算/超时：`asyncio.wait_for` + try/except → SubResult(status="error")，不抛出（其他分支存活）。
④ tool_call_id 跨分支唯一：executor 把 branch_id 注入子图 config.metadata，mapper 据此给
   tool_call_id 加分支前缀（并行共用 fake 模型也不会撞 id）。
⑤ 状态归约 ERROR>IDLE>FINISHED：planner 消费 sub_results 时用 `reduce_substate` 计算。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated, Any, Awaitable, Callable, Optional, Sequence, TypedDict

from langchain_core.callbacks.manager import adispatch_custom_event
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Send

from cognition.graphs.history import repair_dangling_tool_calls
from cognition.graphs.plan_lifecycle import (
    Plan,
    all_completed,
    create,
    current_step,
    current_step_index,
    ensure_executable,
    mark_step_completed,
    set_note,
    update_remaining,
)

logger = logging.getLogger(__name__)

# 子任务字面量分隔符（与原项目一致）。
SEP = "<sep>"

# 自定义事件名（mapper 据此产出 plan / task / result）。
EVENT_PLAN = "plan"
EVENT_TASK = "task"
EVENT_RESULT = "result"

# 状态归约取值。
STATE_FINISHED = "finished"
STATE_IDLE = "idle"
STATE_ERROR = "error"

PLANNER_SYSTEM = (
    "你是任务规划器。把用户任务拆解为有序、可执行的步骤，并用 planning 工具产出 "
    "{title, steps}。同一步骤内若包含可并行的子任务，用字面量 <sep> 分隔。\n"
    "{{sop}}\n"
    "请确保每个步骤自包含、产出明确。"
)


# ——————————————————————————————————————————————————————————————
# 状态与 reducer
# ——————————————————————————————————————————————————————————————
class SubResult(TypedDict, total=False):
    """单个并行子任务的执行结果（并回主状态的增量单元）。"""

    round: int
    branch_id: str
    task: str
    result: str
    observations: list[str]
    status: str  # finished | idle | error


def merge_sub_results(
    left: Optional[list[SubResult]], right: Optional[list[SubResult]]
) -> list[SubResult]:
    """sub_results 的并发安全 reducer：按 (round, branch_id) 去重、规范排序。

    可交换/可结合：同一 (round, branch_id) 只写一次（重复投递取首个），排序键确定，
    因此并行分支任意到达序合并结果一致。
    """
    merged: dict[tuple[Any, Any], SubResult] = {}
    for item in list(left or []) + list(right or []):
        if not item:
            continue
        key = (item.get("round"), item.get("branch_id"))
        if key not in merged:
            merged[key] = item
    return [
        merged[k]
        for k in sorted(merged.keys(), key=lambda k: (k[0] if k[0] is not None else 0, str(k[1])))
    ]


def reduce_substate(results: Sequence[SubResult]) -> str:
    """父状态归约（镜像 reduceParentState）：ERROR > IDLE > FINISHED。"""
    has_idle = False
    all_finished = True
    saw_any = False
    for r in results:
        saw_any = True
        st = (r or {}).get("status")
        if st == STATE_ERROR:
            return STATE_ERROR
        if st == STATE_IDLE:
            has_idle = True
        if st != STATE_FINISHED:
            all_finished = False
    if not saw_any:
        return STATE_FINISHED
    if has_idle:
        return STATE_IDLE
    return STATE_FINISHED if all_finished else STATE_IDLE


class PlanExecuteState(TypedDict, total=False):
    """Plan-Execute 图状态。"""

    query: str
    request_id: str
    session_id: str
    sop: str
    plan: Optional[Plan]
    round: int           # 当前 dispatch 轮（executor 子任务按此轮 tag/消费）
    step: int            # 预留
    reduced_state: str   # 上一轮并行归约结果（ERROR/IDLE/FINISHED）
    planner_messages: Annotated[list, add_messages]
    sub_results: Annotated[list[SubResult], merge_sub_results]


# ——————————————————————————————————————————————————————————————
# 并行控制：信号量限宽 + 每分支超时（best-effort）
# ——————————————————————————————————————————————————————————————
async def run_branch_guarded(
    sem: asyncio.Semaphore,
    timeout: float,
    coro_factory: Callable[[], Awaitable[Any]],
) -> Any:
    """在信号量限宽 + 超时下运行一个分支协程（供 executor 节点与单测复用）。"""
    async with sem:
        return await asyncio.wait_for(coro_factory(), timeout)


# ——————————————————————————————————————————————————————————————
# 解析与提示词
# ——————————————————————————————————————————————————————————————
def _parse_planning_call(ai: AIMessage) -> Optional[dict]:
    """从 planner 的 AIMessage 取 planning 工具调用参数（{command, title, steps}）。"""
    for tc in getattr(ai, "tool_calls", None) or []:
        name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", "")
        if name == "planning":
            args = tc.get("args") if isinstance(tc, dict) else getattr(tc, "args", {})
            return dict(args or {})
    return None


def _join_results(results: Sequence[SubResult]) -> str:
    """把一轮 sub_results 拼成注记文本（按 task 顺序，镜像 joinTaskResults）。"""
    parts: list[str] = []
    for r in results:
        if not r:
            continue
        parts.append(f"{r.get('task', '')} => {r.get('result', '')}".strip())
    return "\n".join(parts)


def _plan_event_data(plan: Plan) -> dict:
    return {
        "title": plan.title,
        "steps": list(plan.steps),
        "step_status": list(plan.step_status),
        "notes": list(plan.notes),
    }


def _ai_text(ai: AIMessage) -> str:
    content = getattr(ai, "content", "")
    return content if isinstance(content, str) else str(content)


# ——————————————————————————————————————————————————————————————
# 节点工厂与图装配
# ——————————————————————————————————————————————————————————————
def build_plan_execute_graph(
    planner_model: BaseChatModel,
    executor_graph: CompiledStateGraph,
    tools: Sequence[Any],
    *,
    max_steps: int = 5,
    max_parallel: int = 2,
    sop_store: Optional[Any] = None,
    branch_timeout: float = 120.0,
    react_recursion_limit: int = 85,
    checkpointer: Optional[BaseCheckpointSaver] = None,
) -> CompiledStateGraph:
    """装配并编译 Plan-Execute 图。

    Args:
        planner_model: 规划器模型（产出步骤/思考；可绑定 planning 工具）。
        executor_graph: 复用的 M1 ReAct 子图（单个子任务的执行器）。
        tools: 本地工具（已绑定在 executor_graph 上；此处保留作显式声明/seam）。
        max_steps: 外层 plan→execute 循环上限（超步→STOPPED）。
        max_parallel: 并行子任务宽度上限（信号量）。
        sop_store: 可选 SopStore（recall(query)->str|None）。
        branch_timeout: 单分支超时秒数。
    """
    # 信号量按 running loop 取，确保跨 loop（多次 astream_events / 多测试）安全、不泄漏。
    _sem_by_loop: dict[asyncio.AbstractEventLoop, asyncio.Semaphore] = {}

    def _semaphore() -> asyncio.Semaphore:
        loop = asyncio.get_running_loop()
        sem = _sem_by_loop.get(loop)
        if sem is None:
            sem = asyncio.Semaphore(max_parallel)
            _sem_by_loop[loop] = sem
        return sem

    # ---- sop_recall：召回 SOP 写入 state["sop"] ----
    def sop_recall(state: PlanExecuteState) -> dict:
        if state.get("sop"):
            return {}
        sop_text = ""
        if sop_store is not None:
            try:
                sop_text = sop_store.recall(state.get("query", "")) or ""
            except Exception as exc:  # noqa: BLE001 — 召回失败不应中断编排
                logger.warning("sop recall failed: %s", exc)
        return {"sop": sop_text}

    # ---- planner：create / replan + 发 plan、task 自定义事件 ----
    async def planner(state: PlanExecuteState) -> dict:
        rnd = int(state.get("round", 0))
        plan = state.get("plan")
        sub_results = state.get("sub_results") or []
        sop = state.get("sop") or ""
        query = state.get("query", "")
        # planner 只把 planning 当"结构化输出"解析、从不执行它 → 历史里的 planning
        # tool_calls 永远没有 ToolMessage 应答，真实 provider（DeepSeek/OpenAI/Anthropic）
        # 第二轮起会 400。入模型前做修复投影（补合成应答），state 原样累积不动。
        history = repair_dangling_tool_calls(list(state.get("planner_messages") or []))
        system = SystemMessage(content=PLANNER_SYSTEM.replace("{{sop}}", sop))

        new_msgs: list = []
        reduced: Optional[str] = None

        if plan is None:
            human = HumanMessage(
                content=f"用户任务：{query}\n请用 planning 工具创建计划（同一步骤内可用 <sep> 分隔可并行子任务）。"
            )
            ai = await planner_model.ainvoke([system, *history, human])  # → plan_thought
            new_msgs += [human, ai]
            draft = _parse_planning_call(ai)
            title = (draft or {}).get("title") or "计划"
            steps = (draft or {}).get("steps") or [query or "完成任务"]
            plan = create(title, list(steps))
            dispatch_round = rnd  # 首轮 dispatch round = 当前 round（默认 0）
        else:
            this_round = [r for r in sub_results if r.get("round") == rnd]
            reduced = reduce_substate(this_round)
            note = _join_results(this_round)
            human = HumanMessage(content=f"上一轮执行结果：\n{note}\n请审视并推进计划。")
            ai = await planner_model.ainvoke([system, *history, human])  # → plan_thought
            new_msgs += [human, ai]
            draft = _parse_planning_call(ai)

            idx = current_step_index(plan)
            if idx is not None:
                plan = set_note(plan, idx, note)
                plan = mark_step_completed(plan, idx)
            else:
                plan = ensure_executable(plan)
            # 可选 LLM replan：仅当模型显式给出 update + 新步骤且计划未完成。
            if (
                draft
                and draft.get("command") == "update"
                and draft.get("steps")
                and not all_completed(plan)
            ):
                plan = update_remaining(plan, draft.get("title"), list(draft["steps"]))
            dispatch_round = rnd + 1

        # 发计划快照（mapper 赋予 plannerRoundId，与本轮 plan_thought 同 round）。
        await adispatch_custom_event(EVENT_PLAN, _plan_event_data(plan))
        # 未完成 → 把 currentStep 按 <sep> 切分，逐个发 task。
        if not all_completed(plan):
            for sub in current_step(plan).split(SEP):
                await adispatch_custom_event(EVENT_TASK, {"text": sub})

        updates: dict = {
            "plan": plan,
            "round": dispatch_round,
            "planner_messages": new_msgs,
        }
        if reduced is not None:
            updates["reduced_state"] = reduced
        return updates

    # ---- executor：信号量限宽 + 超时；复用 ReAct 子图跑单个子任务 ----
    async def executor(state: dict, config: RunnableConfig) -> dict:
        branch_id = state.get("branch_id", "b0")
        task = state.get("task", "")
        rnd = int(state.get("round", 0))
        sop = state.get("sop", "")
        request_id = state.get("request_id", "")
        session_id = state.get("session_id", "")
        plan_title = state.get("plan_title", "")

        parent_meta = (config or {}).get("metadata") or {}
        child_config: RunnableConfig = {
            "callbacks": (config or {}).get("callbacks"),
            "tags": list((config or {}).get("tags") or []),
            # branch_id / request_id 注入子图事件 metadata：供 mapper 命名空间化 tool_call_id 与 run 归属。
            "metadata": {**parent_meta, "branch_id": branch_id, "request_id": request_id},
            "configurable": {"thread_id": f"{session_id}:{branch_id}:r{rnd}"},
            "recursion_limit": react_recursion_limit,
        }
        prompt = _executor_prompt(task, plan_title, sop)
        sub_state = {
            "messages": [HumanMessage(content=prompt)],
            "request_id": request_id,
            "session_id": session_id,
            "query": task,
            "product_files": [],
            "is_stream": True,
            "step": 0,
        }

        sem = _semaphore()
        try:
            result_state = await run_branch_guarded(
                sem, branch_timeout, lambda: executor_graph.ainvoke(sub_state, child_config)
            )
            final_text, observations = _extract_outcome(result_state)
            status = STATE_FINISHED
        except asyncio.TimeoutError:
            final_text, observations, status = (f"子任务超时（>{branch_timeout}s）", [], STATE_ERROR)
        except Exception as exc:  # noqa: BLE001 — 单分支失败不拖垮其他分支
            logger.warning("executor branch %s failed: %s", branch_id, exc)
            final_text, observations, status = (f"子任务异常：{exc}", [], STATE_ERROR)

        sub: SubResult = {
            "round": rnd,
            "branch_id": branch_id,
            "task": task,
            "result": final_text,
            "observations": observations,
            "status": status,
        }
        return {"sub_results": [sub]}

    # ---- summary：聚合 → result 自定义事件（finish 仅在此） ----
    async def summary(state: PlanExecuteState) -> dict:
        text = _summarize(state, max_steps)
        await adispatch_custom_event(EVENT_RESULT, {"text": text})
        return {}

    def route_after_planner(state: PlanExecuteState):
        return _route_after_planner(state, max_steps)

    graph = StateGraph(PlanExecuteState)
    graph.add_node("sop_recall", sop_recall)
    graph.add_node("planner", planner)
    graph.add_node("executor", executor)
    graph.add_node("summary", summary)

    graph.add_edge(START, "sop_recall")
    graph.add_edge("sop_recall", "planner")
    graph.add_conditional_edges("planner", route_after_planner, ["executor", "summary"])
    graph.add_edge("executor", "planner")
    graph.add_edge("summary", END)

    return graph.compile(checkpointer=checkpointer)


# ——————————————————————————————————————————————————————————————
# 路由（纯函数，便于单测）
# ——————————————————————————————————————————————————————————————
def _route_after_planner(state: PlanExecuteState, max_steps: int):
    """planner 之后的条件路由：完成/超步/ERROR → summary；否则按 <sep> 扇出 Send。"""
    plan = state.get("plan")
    rnd = int(state.get("round", 0))

    if all_completed(plan):
        return "summary"
    if rnd > max_steps:
        return "summary"
    if state.get("reduced_state") == STATE_ERROR:
        return "summary"

    subs = current_step(plan).split(SEP)
    return [
        Send(
            "executor",
            {
                "task": sub,
                "branch_id": f"b{i}",
                "round": rnd,
                "query": state.get("query", ""),
                "sop": state.get("sop", ""),
                "request_id": state.get("request_id", ""),
                "session_id": state.get("session_id", ""),
                "plan_title": plan.title if plan else "",
            },
        )
        for i, sub in enumerate(subs)
    ]


# 公开别名（供测试导入）。
def route_after_planner(state: PlanExecuteState, max_steps: int = 5):
    """对外的路由纯函数（默认 max_steps=5）。"""
    return _route_after_planner(state, max_steps)


# ——————————————————————————————————————————————————————————————
# 子任务提示词 / 结果抽取 / 汇总
# ——————————————————————————————————————————————————————————————
def _executor_prompt(task: str, plan_title: str, sop: str) -> str:
    parts = [f"你的任务是：{task}"]
    if plan_title:
        parts.append(f"（所属计划：{plan_title}）")
    if sop:
        parts.append(f"\n参考 SOP：\n{sop}")
    return "".join(parts)


def _extract_outcome(result_state: dict) -> tuple[str, list[str]]:
    """从 ReAct 子图终态抽取（最终答复, 观测列表）。"""
    messages = (result_state or {}).get("messages") or []
    final_text = ""
    observations: list[str] = []
    for m in messages:
        cls = type(m).__name__
        content = getattr(m, "content", "")
        text = content if isinstance(content, str) else str(content)
        if cls == "ToolMessage":
            observations.append(text)
        elif cls in ("AIMessage", "AIMessageChunk") and not getattr(m, "tool_calls", None):
            if text:
                final_text = text
    return final_text, observations


def _summarize(state: PlanExecuteState, max_steps: int) -> str:
    """聚合 notes/sub_results → 最终答复（按终止原因渲染）。"""
    plan = state.get("plan")
    rnd = int(state.get("round", 0))
    reduced = state.get("reduced_state")

    if reduced == STATE_ERROR:
        return "任务执行异常，请联系管理员，任务终止。"
    if rnd > max_steps and not all_completed(plan):
        return "达到最大迭代次数，任务终止。"

    lines: list[str] = []
    if plan is not None:
        if plan.title:
            lines.append(f"# {plan.title}")
        for i, step in enumerate(plan.steps):
            note = plan.notes[i] if i < len(plan.notes) else ""
            if note:
                lines.append(f"- {step}：{note}")
            else:
                lines.append(f"- {step}")
    if not lines:
        results = state.get("sub_results") or []
        lines = [f"- {r.get('task','')}: {r.get('result','')}" for r in results]
    return "任务已完成。\n" + "\n".join(lines)
