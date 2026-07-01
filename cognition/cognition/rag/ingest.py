"""灌库/索引流程（编排）：chunk → dense+sparse embed → upsert 到 Qdrant。

文档可为纯字符串或 {"text","file_name","source_id"}。每块生成 dense+sparse 向量与 payload。
默认 FakeEmbedder + QdrantClient(":memory:") 可离线跑通；生产切真实 provider + Qdrant。
"""

from __future__ import annotations

import hashlib
import re
import time
import uuid
from typing import Any, Union

from qdrant_client import models

from cognition.rag.chunking import split_text
from cognition.rag.embeddings import EmbeddingProvider
from cognition.rag.sparse import SparseProvider
from cognition.rag.store import DENSE_VECTOR, SPARSE_VECTOR, QdrantStore

Doc = Union[str, dict[str, Any]]

_WS = re.compile(r"\s+")


def _norm(text: str) -> str:
    return _WS.sub("", text).lower()


def _dedup_key(text: str) -> str:
    return hashlib.md5(_norm(text).encode("utf-8")).hexdigest()


def ingest(
    docs: list[Doc],
    kb_id: str,
    *,
    store: QdrantStore,
    embedder: EmbeddingProvider,
    sparse: SparseProvider,
    chunk_size: int = 500,
    overlap: int = 100,
) -> int:
    """把 docs 切块+向量化+写入 Qdrant，返回写入的块数。"""
    store.ensure_collection()

    chunks: list[str] = []
    metas: list[dict[str, Any]] = []
    for i, doc in enumerate(docs):
        if isinstance(doc, str):
            text, file_name, source_id = doc, f"doc-{i}", f"doc-{i}"
        else:
            text = str(doc.get("text", ""))
            file_name = str(doc.get("file_name", f"doc-{i}"))
            source_id = str(doc.get("source_id", file_name))
        for ci, ch in enumerate(split_text(text, size=chunk_size, overlap=overlap)):
            chunks.append(ch)
            metas.append({"file_name": file_name, "source_id": source_id, "chunk_index": ci})

    if not chunks:
        return 0

    dense_vecs = embedder.embed(chunks)
    sparse_vecs = sparse.embed(chunks)

    now = int(time.time())
    points: list[models.PointStruct] = []
    for ch, meta, dv, (s_idx, s_val) in zip(chunks, metas, dense_vecs, sparse_vecs):
        points.append(
            models.PointStruct(
                id=uuid.uuid4().hex,
                vector={
                    DENSE_VECTOR: dv,
                    SPARSE_VECTOR: models.SparseVector(indices=s_idx, values=s_val),
                },
                payload={
                    "kb_id": kb_id,
                    "text": ch,
                    "source_id": meta["source_id"],
                    "file_name": meta["file_name"],
                    "chunk_index": meta["chunk_index"],
                    "dedup_key": _dedup_key(ch),
                    "chunk_type": "text",
                    "image_url": None,
                    "created": now,
                },
            )
        )
    store.upsert(points)
    return len(points)
