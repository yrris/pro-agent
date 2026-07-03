"""CognitionService gRPC servicer 实现（grpc.aio，server-streaming）。

按 `RunRequest.agent_type` 路由：
- "plan_solve" → Plan-Execute 图（plan→executor 子图→summary，含 replan 与并行子任务）。
- 其它（默认 "react"）→ M1 ReAct 图。

Run 是异步生成器：
1. 由 RunRequest 按 agent_type 装配初始 State。
2. graph.astream_events(version="v2", config={configurable:{thread_id:session_id}, recursion_limit, metadata})。
3. 逐事件喂 EventMapper，yield Event.to_proto()。
4. 客户端取消（CancelledError）→ 干净停止；节点异常 → 发终态 result(finish, error) 关闭流。
"""

from __future__ import annotations

import asyncio
import logging

from langchain_core.messages import HumanMessage

from cognition._genproto import agent_pb2, agent_pb2_grpc
from cognition.attachments import attachment_note, build_attachment_message, normalize_attachments
from cognition.config import Settings
from cognition.events.mapper import EventMapper
from cognition.observability.langfuse_seam import build_langfuse_callbacks

logger = logging.getLogger(__name__)

AGENT_TYPE_PLAN_SOLVE = "plan_solve"
AGENT_TYPE_DEEP_RESEARCH = "deep_research"


def resolve_kb_id(request) -> str:
    """解析本 run 的知识库归属（纯函数，单点解析后经 config metadata 供
    knowledge_search 与附件入库共用）。

    owner 级优先（`owner:{owner_id}`，Go 经 RunRequest.metadata["owner_id"] 传入）：
    用户上传的文档跨会话可检索（"用户自有知识库"语义）。无 owner（旧 Go/直连
    gRPC）回退会话级 `sess:{session_id}`。**绝不返回空串**——kb_id=="" 在检索层
    意味着无隔离全库查询。
    """
    meta = getattr(request, "metadata", None) or {}
    owner = str(meta.get("owner_id", "") or "")
    if owner:
        return f"owner:{owner}"
    sid = str(getattr(request, "session_id", "") or getattr(request, "run_id", "") or "run")
    return f"sess:{sid}"


class CognitionServicer(agent_pb2_grpc.CognitionServiceServicer):
    """一次 run = 一个 server-streaming RPC。按 agent_type 选图。"""

    def __init__(
        self,
        react_graph,
        settings: Settings,
        plan_graph=None,
        research_graph=None,
        tool_providers=None,
        ingest_attachments_fn=None,
    ) -> None:
        self.react_graph = react_graph
        self.plan_graph = plan_graph
        # plan 家族路由表：deep_research 缺省回退 plan_solve 图（提示词非研究版但可用）。
        self.plan_graphs = {
            k: g
            for k, g in {
                AGENT_TYPE_PLAN_SOLVE: plan_graph,
                AGENT_TYPE_DEEP_RESEARCH: research_graph or plan_graph,
            }.items()
            if g is not None
        }
        self.settings = settings
        # 工具名 → provider（local/mcp/skill），装配期从工具集构建后注入 EventMapper。
        self.tool_providers = dict(tool_providers or {})
        # 附件入库（同步可调用 (att_dicts, kb_id)->list[入库文件名]；Run 内经 to_thread 调用）。
        self.ingest_attachments_fn = ingest_attachments_fn

    def _build(self, request, ingested_names: tuple[str, ...] = ()):
        """返回 (graph, initial_state, recursion_limit)。"""
        run_id = request.run_id or "unknown"
        session_id = request.session_id or run_id
        max_steps = request.max_steps or self.settings.max_steps
        agent_type = request.agent_type or "react"
        attachments = normalize_attachments(getattr(request, "attachments", []) or [])

        if agent_type in self.plan_graphs:
            # plan 家族（plan_solve/deep_research）不做图片多模态（planner 无 messages
            # 接缝，见 docs/08 §4 已知限制）：附件以短注记进 query，文本类已入知识库。
            query = request.query
            if attachments:
                query = f"{request.query}\n{attachment_note(attachments, ingested_names)}"
            state = {
                "query": query,
                "request_id": run_id,
                "session_id": session_id,
                "plan": None,
                "round": 0,
                "step": 0,
                # 显式清残留：同会话上一次 run 若以 ERROR 收场，reduced_state 会随
                # checkpoint 延续，新 run 会被 route_after_planner 直接送去 summary。
                "reduced_state": "",
                "output_format": dict(getattr(request, "metadata", {}) or {}).get("output_format", ""),
                "planner_messages": [],
                "sub_results": [],
            }
            # 外层循环 + 并行分支 join 占用 superstep，留足余量。
            # recursion 预算按 agent_type 取各自轮次上限——deep_research 轮次更多，
            # 硬绑 planner_max_steps 会在研究后期 GraphRecursionError。
            steps_budget = (
                int(self.settings.research_max_steps)
                if agent_type == AGENT_TYPE_DEEP_RESEARCH
                else int(self.settings.planner_max_steps)
            )
            recursion = 4 * steps_budget + 25
            return self.plan_graphs[agent_type], state, recursion

        if attachments:
            # 附件消息：文本块（query+清单注记）+ 图片 pro_attachment 引用块
            #（checkpoint 只存引用，base64 在 think 投影期按需展开）。
            human = build_attachment_message(request.query, attachments, ingested_names)
        else:
            human = HumanMessage(content=request.query)
        state = {
            "messages": [human],
            "request_id": run_id,
            "session_id": session_id,
            "query": request.query,
            "product_files": attachments,  # M1 起预留的 seam，本期起实装
            "is_stream": True,
            "step": 0,
        }
        recursion = 2 * int(max_steps) + 5
        return self.react_graph, state, recursion

    async def IngestDocument(self, request, context):  # noqa: N802 (gRPC 方法名固定)
        """Files 面板"上传即入库"（UX-1）：不经对话轮，直接把已上传对象送入 owner 知识库。

        复用 Run 前置入库的同一条管线（build_ingestor：下载→提取→分块→内容寻址幂等
        upsert），语义与"随消息附件入库"完全一致——同一文件两种入口不会产生重复向量。
        kb 归属由服务端从 owner_id 推导，客户端不可指定（与 kb config 优先同一条纪律）。
        """
        owner = str(request.owner_id or "")
        if not owner:
            return agent_pb2.IngestDocumentResponse(ok=False, message="缺少 owner_id")
        if self.ingest_attachments_fn is None:
            return agent_pb2.IngestDocumentResponse(ok=False, message="RAG 未启用（COGNITION_RAG_ENABLED=false）")
        kb_id = f"owner:{owner}"
        atts = normalize_attachments([request.attachment])
        try:
            # 与 Run 前置入库同款 to_thread：同步下载/嵌入不得占 grpc.aio 事件循环。
            names = await asyncio.to_thread(self.ingest_attachments_fn, atts, kb_id)
        except Exception as exc:  # noqa: BLE001 — 管理操作失败以 message 上浮，不抛 gRPC 错
            logger.warning("IngestDocument failed for %s: %s", kb_id, exc)
            return agent_pb2.IngestDocumentResponse(ok=False, kb_id=kb_id, message=f"入库失败: {exc}")
        if not names:
            return agent_pb2.IngestDocumentResponse(
                ok=False, kb_id=kb_id, message="无可入库文本（仅支持文本/Markdown/CSV/JSON/PDF）"
            )
        logger.info("document ingested into %s: %s", kb_id, list(names))
        return agent_pb2.IngestDocumentResponse(ok=True, kb_id=kb_id)

    async def Run(self, request, context):  # noqa: N802 (gRPC 方法名固定)
        run_id = request.run_id or "unknown"
        session_id = request.session_id or run_id
        agent_type = request.agent_type or "react"
        # 结构化日志：run_id/session_id/agent_type 关联键（与 Go 侧一致，跨进程串同一 run）。
        log = logging.LoggerAdapter(
            logger, {"run_id": run_id, "session_id": session_id, "agent_type": agent_type}
        )

        mapper = EventMapper(run_id, self.tool_providers)
        kb_id = resolve_kb_id(request)

        # —— 附件入库预步（run 前同步：read-your-writes，刚上传就能问到）——
        # 必须 to_thread：embedder/下载是同步阻塞，裸调会冻结 grpc.aio 单事件循环上的
        # 全部并发 run。整体 best-effort：入库失败不阻断 run（附件仍以注记/引用块在场）。
        ingested: tuple[str, ...] = ()
        attachments = list(getattr(request, "attachments", []) or [])
        if attachments and self.ingest_attachments_fn is not None:
            from cognition.attachments import normalize_attachments

            try:
                names = await asyncio.to_thread(
                    self.ingest_attachments_fn, normalize_attachments(attachments), kb_id
                )
                ingested = tuple(names or ())
                if ingested:
                    log.info("attachments ingested into %s: %s", kb_id, list(ingested))
            except Exception as exc:  # noqa: BLE001 — 入库是增强路径，绝不拖垮 run
                log.warning("attachment ingest failed: %s", exc)

        graph, state, recursion = self._build(request, ingested)
        # kb_id 单点解析进 metadata：knowledge_search（config 优先）与附件入库共用；
        # attachments 白名单供 script_runner 的 input_files 按文件名解析（M9）；
        # plan_solve 的 executor 分支经 child_config metadata spread 自动透传。
        metadata = {
            "request_id": run_id,
            "run_id": run_id,
            "session_id": session_id,
            "kb_id": kb_id,
            "agent_type": agent_type,  # 研究模式的提示门与检索产物例外共用（M9）
        }
        output_format = dict(request.metadata).get("output_format", "")
        if output_format:
            # per-run 输出格式走 config（react think 调用期临时前置 system；
            # plan 的 executor 分支经 metadata spread 同机制获得）——不进 checkpoint。
            metadata["output_format"] = output_format
        if attachments:
            import json as _json

            from cognition.attachments import normalize_attachments as _norm

            metadata["attachments"] = _json.dumps(_norm(attachments), ensure_ascii=False)
        config = {
            "configurable": {"thread_id": session_id},
            "recursion_limit": recursion,
            "metadata": metadata,
        }
        # 可选 Langfuse trace（默认关、未装即 no-op）。
        callbacks = build_langfuse_callbacks(self.settings)
        if callbacks:
            config["callbacks"] = callbacks
            metadata["langfuse_session_id"] = session_id

        log.info("run start")
        try:
            async for ev in graph.astream_events(state, version="v2", config=config):
                for out in mapper.handle(ev):
                    yield out.to_proto()
            log.info("run done")
        except asyncio.CancelledError:
            log.info("run cancelled")
            raise
        except Exception as exc:  # noqa: BLE001 — 节点异常兜底，保证流干净关闭
            log.exception("run failed")
            yield mapper.error_result(str(exc)).to_proto()
