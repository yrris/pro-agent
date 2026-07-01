"""knowledge_search 工具形状 + 经 EventMapper 映射为 artifact_refs（坐实 proto/Go 零改）。"""

from __future__ import annotations

from types import SimpleNamespace

from qdrant_client import QdrantClient

from cognition.config import Settings
from cognition.events.mapper import EventMapper
from cognition.events.schema import EventType
from cognition.rag.embeddings import FakeEmbedder
from cognition.rag.graph import build_rag_subgraph
from cognition.rag.ingest import ingest
from cognition.rag.reranker import FakeReranker
from cognition.rag.retriever import Retriever
from cognition.rag.sparse import FakeSparseEmbedder
from cognition.rag.store import QdrantStore
from cognition.tools.knowledge_search import build_knowledge_search_tool

DIM = 64


class _FakeModel:
    def invoke(self, prompt: str):
        if "只回答 YES 或 NO" in prompt:
            return SimpleNamespace(content="YES")
        if "拆解成" in prompt:
            return SimpleNamespace(content="混合检索")
        if "是否足够" in prompt:
            return SimpleNamespace(content='{"is_answer": true, "rewrite_query": ""}')
        return SimpleNamespace(content="混合检索结合稠密与稀疏向量〔1〕。")


def _tool():
    store = QdrantStore(QdrantClient(location=":memory:"), "docs", DIM)
    emb, sp = FakeEmbedder(DIM), FakeSparseEmbedder()
    ingest([{"text": "混合检索用稠密+稀疏向量并 RRF 融合。", "file_name": "h.md"}],
           kb_id="kb1", store=store, embedder=emb, sparse=sp)
    settings = Settings(rag_enabled=True, rerank_enabled=True, embedding_dimension=DIM)
    sub = build_rag_subgraph(settings, model=_FakeModel(),
                             retriever=Retriever(store, emb, sp, top_k=5), reranker=FakeReranker())
    return build_knowledge_search_tool(sub, settings)


async def test_tool_returns_content_and_artifact():
    tool = _tool()
    msg = await tool.ainvoke(
        {"args": {"query": "什么是混合检索", "kb_id": "kb1"},
         "id": "call-1", "name": "knowledge_search", "type": "tool_call"}
    )
    assert "混合检索" in msg.content
    art = msg.artifact
    assert art["file_name"] == "search-results.md"
    assert art["download_url"] == "/artifacts/run/call-1/search-results.md"
    assert art["mime_type"] == "text/markdown"
    assert art["size"] > 0 and art["missing"] is False
    assert tool.metadata["provider"] == "local"


async def test_tool_result_maps_to_artifact_refs():
    tool = _tool()
    msg = await tool.ainvoke(
        {"args": {"query": "什么是混合检索", "kb_id": "kb1"},
         "id": "c9", "name": "knowledge_search", "type": "tool_call"}
    )
    # 喂给 EventMapper._on_tool_end（复用现有 tool_result 通路，无需新事件类型）
    mapper = EventMapper("run-x")
    out = SimpleNamespace(tool_call_id="c9", name="knowledge_search",
                          content=msg.content, status="success", artifact=msg.artifact)
    events = mapper._on_tool_end({"data": {"output": out}}, "")
    tool_results = [e for e in events if e.type is EventType.TOOL_RESULT]
    assert tool_results
    refs = tool_results[0].tool_result.artifact_refs
    assert refs and refs[0].file_name == "search-results.md"
    assert tool_results[0].tool_result.tool_provider == "local"
