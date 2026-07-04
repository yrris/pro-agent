"""OpenAI 图像生成（gpt-image 系列）：同步 images API，b64 响应。

对齐原项目取向（DEFAULT_IMAGE_MODEL="gpt-image-2"，OpenAI 兼容端点可换 base_url）。
quality 默认 "low"（成本优先，用户可经 COGNITION_IMAGE_GEN_QUALITY 调 medium/high）；
gpt-image 系列默认返回 b64_json，无需 response_format 参数。
"""

from __future__ import annotations

import base64
from typing import Any, Optional

import httpx

_VALID_SIZES = {"1024x1024", "1536x1024", "1024x1536", "auto"}


def build_openai_image_payload(
    model: str, prompt: str, size: str, quality: str, n: int
) -> dict[str, Any]:
    """请求体构造（纯函数，可测）。size 不合法回落 auto（gpt-image 不吃任意尺寸）。"""
    sz = size.replace("*", "x")
    if sz not in _VALID_SIZES:
        sz = "auto"
    return {
        "model": model,
        "prompt": prompt,
        "size": sz,
        "quality": quality or "low",
        "n": max(1, min(int(n), 4)),
    }


def parse_openai_images(data: dict[str, Any]) -> list[bytes]:
    """响应 → 图片字节列表（纯函数，可测）；形状异常抛 ValueError。"""
    items = data.get("data") or []
    out = [base64.b64decode(it["b64_json"]) for it in items if isinstance(it, dict) and it.get("b64_json")]
    if not out:
        raise ValueError(f"openai 响应缺少图像数据: {list(data)}")
    return out


class OpenAIImageProvider:
    def __init__(
        self, *, api_key: str, model: str, base_url: str, quality: str = "low", timeout: float = 180.0
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._base = base_url.rstrip("/")
        self._quality = quality
        self._timeout = timeout

    async def generate(
        self,
        prompt: str,
        *,
        images: Optional[list[bytes]] = None,  # 图生图（edits 端点）留 seam，v1 忽略
        size: str = "1024x1024",
        n: int = 1,
    ) -> list[bytes]:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(
                f"{self._base}/images/generations",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json=build_openai_image_payload(self._model, prompt, size, self._quality, n),
            )
            resp.raise_for_status()
            return parse_openai_images(resp.json())
