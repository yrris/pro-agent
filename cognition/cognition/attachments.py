"""附件处理（M8）：上传附件 → 多模态消息构造与入模型前展开。

设计要点（docs/08 §4）：
- **checkpoint 防膨胀**：state 里的 HumanMessage 只存自定义 `pro_attachment` 引用块
  （resource_key + 元信息），绝不存 base64；think 节点入模型前经 `expand_attachment_blocks`
  第三道投影（repair → history 裁剪 → expand）按需下载展开。
- **全量替换不变量**：expand 之后消息里不得残留任何 pro_attachment 块——provider
  对未知块类型直接 400（Anthropic），且残留会随 checkpoint 污染后续轮。
- **vision 门控**：仅 vision provider（anthropic）把图片展开为 base64 image 块；
  DeepSeek 等纯文本模型降级为文本占位。图片尺寸闸 4.5MB（Claude 单图 ~5MB 上限，
  与上传 20MB 上限不是一回事）。
- 下载走认知面自持的 MinIO 凭据（M4 起已有），带受限 LRU（小对象才缓存）。
"""

from __future__ import annotations

import base64
import logging
from collections import OrderedDict
from typing import Any, Callable, Iterable, Optional, Sequence

from langchain_core.messages import AnyMessage, HumanMessage

from cognition.config import Settings, get_settings

logger = logging.getLogger(__name__)

# 自定义引用块类型（只存在于 checkpoint/state，永不直达 provider）。
ATTACHMENT_BLOCK_TYPE = "pro_attachment"

# 支持图像理解的 provider（能力表；M9 扩 provider 时在此登记）。
VISION_PROVIDERS = {"anthropic"}

# 展开期单图字节上限（Claude 单图 ~5MB，留余量）。
MAX_IMAGE_BYTES = int(4.5 * 1024 * 1024)

# 下载 LRU：最多 8 项、单对象 ≤6MB 才缓存（防大图吃内存）。
_CACHE_MAX_ITEMS = 8
_CACHE_MAX_BYTES = 6 * 1024 * 1024


def supports_vision(provider: str) -> bool:
    """该 provider 是否支持图像理解（executor 角色 resolved provider）。"""
    return (provider or "").lower() in VISION_PROVIDERS


def is_image(mime: str) -> bool:
    return (mime or "").lower().startswith("image/")


def normalize_attachments(attachments: Iterable[Any]) -> list[dict[str, Any]]:
    """proto Attachment / dict → 统一 dict（后续全链路只认这个形状）。"""
    out: list[dict[str, Any]] = []
    for a in attachments or []:
        if isinstance(a, dict):
            rk = str(a.get("resource_key", "") or "")
            fn = str(a.get("file_name", "") or "")
            mt = str(a.get("mime_type", "") or "")
            size = int(a.get("size", 0) or 0)
        else:
            rk = str(getattr(a, "resource_key", "") or "")
            fn = str(getattr(a, "file_name", "") or "")
            mt = str(getattr(a, "mime_type", "") or "")
            size = int(getattr(a, "size", 0) or 0)
        if rk:
            out.append({"resource_key": rk, "file_name": fn or rk.rsplit("/", 1)[-1], "mime_type": mt, "size": size})
    return out


def _human_size(n: int) -> str:
    if n < 1024:
        return f"{n}B"
    if n < 1024 * 1024:
        return f"{n / 1024:.0f}KB"
    return f"{n / 1024 / 1024:.1f}MB"


def attachment_note(attachments: Sequence[dict], ingested_names: Sequence[str] = ()) -> str:
    """附件清单注记（进消息文本，模型据此知道有什么、去哪找）。"""
    if not attachments:
        return ""
    items = "、".join(f"{a['file_name']}（{a['mime_type'] or '未知类型'}, {_human_size(a['size'])}）" for a in attachments)
    note = f"〔用户上传附件：{items}〕"
    if ingested_names:
        note += f"\n〔其中 {'、'.join(ingested_names)} 的内容已存入你的知识库，可用 knowledge_search 工具检索引用〕"
    return note


def build_attachment_message(
    query: str, attachments: Sequence[dict], ingested_names: Sequence[str] = ()
) -> HumanMessage:
    """构造带附件的用户消息：文本块（query+清单注记）+ 图片的 pro_attachment 引用块。

    非图片附件不产块（内容经知识库/引用块路径供给）；无图片时退化为纯文本 content
    （不走块路径，减少不必要的多模态分支）。
    """
    text = query if not attachments else f"{query}\n\n{attachment_note(attachments, ingested_names)}"
    image_atts = [a for a in attachments if is_image(a["mime_type"])]
    if not image_atts:
        return HumanMessage(content=text)
    blocks: list[Any] = [{"type": "text", "text": text}]
    for a in image_atts:
        blocks.append(
            {
                "type": ATTACHMENT_BLOCK_TYPE,
                "resource_key": a["resource_key"],
                "file_name": a["file_name"],
                "mime_type": a["mime_type"],
                "size": a["size"],
            }
        )
    return HumanMessage(content=blocks)


class MinioDownloader:
    """按 resource_key 读对象字节（惰性 import + 受限 LRU）。失败抛异常由调用方降级。"""

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self._settings = settings or get_settings()
        self._client: Any = None
        self._cache: OrderedDict[str, bytes] = OrderedDict()

    def _get_client(self):
        if self._client is None:
            from minio import Minio  # 惰性：离线单测不需要该依赖

            s = self._settings
            self._client = Minio(
                s.minio_endpoint, access_key=s.minio_access_key,
                secret_key=s.minio_secret_key, secure=s.minio_secure,
            )
        return self._client

    def __call__(self, resource_key: str) -> bytes:
        cached = self._cache.get(resource_key)
        if cached is not None:
            self._cache.move_to_end(resource_key)
            return cached
        resp = self._get_client().get_object(self._settings.minio_bucket, resource_key)
        try:
            data = resp.read()
        finally:
            resp.close()
            resp.release_conn()
        if len(data) <= _CACHE_MAX_BYTES:
            self._cache[resource_key] = data
            while len(self._cache) > _CACHE_MAX_ITEMS:
                self._cache.popitem(last=False)
        return data


# —— 上传附件 → 知识库（run 前同步入库，read-your-writes）——

# 文本类判定（进知识库的内容源）：mime 前缀/精确匹配 + 扩展名兜底（浏览器对 md/csv
# 的 mime 报告不稳定）。
_TEXT_MIME_EXACT = {"application/json", "application/x-ndjson", "application/xml"}
_TEXT_EXTS = {".txt", ".md", ".markdown", ".csv", ".json", ".log", ".xml", ".yaml", ".yml"}
PDF_MIME = "application/pdf"

# 单文件入库文本上限（约 200k 字符）：防超大文档拖慢 run 启动；超限截断并注记。
MAX_INGEST_CHARS = 200_000


def is_text_like(mime: str, file_name: str = "") -> bool:
    m = (mime or "").lower()
    if m.startswith("text/") or m in _TEXT_MIME_EXACT:
        return True
    name = (file_name or "").lower()
    return any(name.endswith(ext) for ext in _TEXT_EXTS)


def is_pdf(mime: str, file_name: str = "") -> bool:
    return (mime or "").lower() == PDF_MIME or (file_name or "").lower().endswith(".pdf")


def extract_text(data: bytes, mime: str, file_name: str = "") -> Optional[str]:
    """从附件字节提取纯文本；不可提取/失败返回 None（调用方跳过，不炸 run）。"""
    if is_pdf(mime, file_name):
        try:
            import io

            from pypdf import PdfReader  # 惰性：未装/损坏 pdf 都降级

            reader = PdfReader(io.BytesIO(data))
            pages = [(p.extract_text() or "") for p in reader.pages]
            text = "\n".join(pages).strip()
            return text or None
        except Exception as exc:  # noqa: BLE001 — pdf 解析失败降级跳过
            logger.warning("pdf text extract failed for %s: %s", file_name, exc)
            return None
    if is_text_like(mime, file_name):
        try:
            return data.decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            return None
    return None


def build_ingestor(
    settings: Optional[Settings] = None,
    *,
    downloader: Optional[Callable[[str], bytes]] = None,
    store: Any = None,
    embedder: Any = None,
    sparse: Any = None,
) -> Callable[[list[dict], str], list[str]]:
    """构建附件入库器（装配期一次；I/O 依赖可注入供离线测试）。

    返回同步可调用 `(att_dicts, kb_id) -> 入库文件名列表`——servicer 在 Run 里经
    `asyncio.to_thread` 调用（embedder/下载同步阻塞，绝不能在 grpc.aio 事件循环上裸跑）。
    幂等：`ingest(stable_ids=True)` 内容寻址，同文件重传/重试不重复入库。
    """
    settings = settings or get_settings()
    if store is None or embedder is None or sparse is None:
        from cognition.rag.factory import build_embedder, build_sparse, build_store

        store = store or build_store(settings)
        embedder = embedder or build_embedder(settings)
        sparse = sparse or build_sparse(settings)
    dl = downloader or MinioDownloader(settings)

    def _ingest_attachments(attachments: list[dict], kb_id: str) -> list[str]:
        from cognition.rag.ingest import ingest

        if not kb_id:
            return []  # kb_id 空=无隔离全库，宁可不入
        docs: list[dict] = []
        names: list[str] = []
        for a in attachments or []:
            mime, fname = a.get("mime_type", ""), a.get("file_name", "")
            if not (is_text_like(mime, fname) or is_pdf(mime, fname)):
                continue  # 图片等非文本：走多模态/占位路径，不进知识库
            try:
                data = dl(a["resource_key"])
            except Exception as exc:  # noqa: BLE001 — 单文件失败不拖垮其余
                logger.warning("attachment download failed for ingest %s: %s", a.get("resource_key"), exc)
                continue
            text = extract_text(data, mime, fname)
            if not text or not text.strip():
                continue
            if len(text) > MAX_INGEST_CHARS:
                text = text[:MAX_INGEST_CHARS] + "\n…（超长截断）"
            docs.append({"text": text, "file_name": fname, "source_id": a["resource_key"]})
            names.append(fname)
        if docs:
            ingest(docs, kb_id, store=store, embedder=embedder, sparse=sparse, stable_ids=True)
        return names

    return _ingest_attachments


def _placeholder_block(file_name: str, reason: str) -> dict:
    return {"type": "text", "text": f"[图片附件 {file_name}（{reason}，未注入图像内容）]"}


def expand_attachment_blocks(
    messages: list[AnyMessage],
    *,
    downloader: Callable[[str], bytes],
    vision: bool,
    max_image_bytes: int = MAX_IMAGE_BYTES,
) -> list[AnyMessage]:
    """把消息里的 pro_attachment 引用块展开为真实内容（入模型前最后一道投影）。

    vision provider：下载 → base64 image 块（LangChain 标准块，ChatAnthropic 原生消费）；
    非 vision / 下载失败 / 超尺寸：降级文本占位。**保证输出不残留任何 pro_attachment 块**。
    只读投影：不回写 state/checkpoint。
    """
    out: list[AnyMessage] = []
    for m in messages:
        content = getattr(m, "content", None)
        if not isinstance(content, list) or not any(
            isinstance(b, dict) and b.get("type") == ATTACHMENT_BLOCK_TYPE for b in content
        ):
            out.append(m)
            continue
        new_blocks: list[Any] = []
        for b in content:
            if not (isinstance(b, dict) and b.get("type") == ATTACHMENT_BLOCK_TYPE):
                new_blocks.append(b)
                continue
            fname = str(b.get("file_name", "附件"))
            mime = str(b.get("mime_type", ""))
            key = str(b.get("resource_key", ""))
            if not vision or not is_image(mime):
                new_blocks.append(_placeholder_block(fname, "当前模型不支持图像理解"))
                continue
            try:
                data = downloader(key)
            except Exception as exc:  # noqa: BLE001 — 读取失败降级占位，不炸 run
                logger.warning("attachment download failed for %s: %s", key, exc)
                new_blocks.append(_placeholder_block(fname, "图片读取失败"))
                continue
            if len(data) > max_image_bytes:
                new_blocks.append(_placeholder_block(fname, f"图片超过 {_human_size(max_image_bytes)} 模型上限"))
                continue
            new_blocks.append(
                {
                    "type": "image",
                    "source_type": "base64",
                    "data": base64.b64encode(data).decode("ascii"),
                    "mime_type": mime,
                }
            )
        out.append(m.model_copy(update={"content": new_blocks}))
    return out
