"""knowledge_search 工具：把 Agentic RAG 子图包成一个本地工具暴露给外层图。

外层 ReAct/Plan-Execute 只看到一次 tool_call/tool_result；答案作 observation（内联〔n〕），
来源作 `search-results.md` ArtifactRef（复用 report.py 的惰性/可降级 MinIO 上传与 Go /artifacts 代理）。
子图内部的 route/expand/retrieve/reflect/rerank/generate 事件不外泄（proto/Go 零改）。
"""

from __future__ import annotations

from typing import Annotated, Any, Optional

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, InjectedToolCallId, StructuredTool

from cognition.config import Settings
from cognition.rag.citation import sources_to_artifact_md
from cognition.tools.report import _maybe_upload, _run_id_from_config

_FILE_NAME = "search-results.md"
_MIME = "text/markdown"


def _kb_id_from_config(config: Optional[RunnableConfig]) -> str:
    """从 RunnableConfig.metadata 取当前 run 的 kb_id（servicer 注入，工具层只读）。"""
    if not config:
        return ""
    meta = config.get("metadata") or {}
    return str(meta.get("kb_id") or "")


def build_knowledge_search_tool(subgraph: Any, settings: Settings) -> BaseTool:
    """用编译好的 RAG 子图构建 knowledge_search 工具（装配期一次）。"""

    async def knowledge_search(
        query: str,
        kb_id: str = "",
        tool_call_id: Annotated[str, InjectedToolCallId] = "",
        config: RunnableConfig = None,  # type: ignore[assignment]
    ) -> tuple[str, Optional[dict]]:
        """在知识库中检索并基于证据作答。当问题需要事实/文档依据时使用。

        kb_id 通常无需填写：系统会自动定位当前用户的知识库（上传的文档都在其中）。
        """
        # 安全：config（servicer 注入的 owner kb）优先于 LLM 填的入参——kb_id 是模型
        # 可见参数，被提示注入/幻觉填成他人 kb 也不能越权检索；无 config 时（离线
        # 测试/脚本直调）才用入参。
        kb = _kb_id_from_config(config) or kb_id
        result = await subgraph.ainvoke({"query": query, "kb_id": kb})
        answer = str(result.get("answer", "") or "")
        sources = result.get("sources", []) or []

        run_id = _run_id_from_config(config)
        tcid = tool_call_id or "tc"
        resource_key = f"{run_id}/{tcid}/{_FILE_NAME}"
        body = sources_to_artifact_md(query, answer, sources).encode("utf-8")
        _maybe_upload(settings, resource_key, body, _MIME)

        artifact = {
            "resource_key": resource_key,
            "name": _FILE_NAME,
            "file_name": _FILE_NAME,
            "mime_type": _MIME,
            "size": len(body),
            "download_url": f"/artifacts/{resource_key}",
            "preview_url": f"/artifacts/{resource_key}",
            "missing": False,
        }
        summary = answer + (f"\n（依据 {len(sources)} 条来源，详见 {_FILE_NAME}）" if sources else "")
        return summary, artifact

    tool = StructuredTool.from_function(
        coroutine=knowledge_search,
        name="knowledge_search",
        description="在知识库中做混合检索并基于证据作答（返回答案摘要 + 来源产物）。当问题需要事实/文档依据时使用。",
        response_format="content_and_artifact",
    )
    tool.metadata = {"provider": "local"}
    return tool
