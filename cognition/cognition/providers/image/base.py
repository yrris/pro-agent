"""图像生成 provider 协议（结构化 duck-typing，与 rag 的 provider 协议同风格）。"""

from __future__ import annotations

from typing import Optional, Protocol, runtime_checkable


@runtime_checkable
class ImageGenProvider(Protocol):
    """文生图/图生图统一入口。

    images：可选源图字节（风格化/编辑场景），不支持的实现应忽略而非报错。
    返回原始图片字节（PNG/JPEG），由调用方负责落 MinIO 与 ArtifactRef。
    """

    async def generate(
        self,
        prompt: str,
        *,
        images: Optional[list[bytes]] = None,
        size: str = "1024x1024",
        n: int = 1,
    ) -> list[bytes]: ...
