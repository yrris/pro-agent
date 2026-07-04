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


def build_openai_edit_form(model: str, prompt: str, size: str, quality: str, n: int) -> dict[str, str]:
    """/images/edits 的表单字段（纯函数，可测）。**不含 response_format（gpt-image 默认
    b64_json）、不含 input_fidelity（gpt-image-2 不支持）**；图片走 multipart files 的
    可重复字段 image[]，不在此。size 非法回落 auto。"""
    sz = size.replace("*", "x")
    if sz not in _VALID_SIZES:
        sz = "auto"
    return {
        "model": model,
        "prompt": prompt,
        "size": sz,
        "quality": quality or "low",
        "n": str(max(1, min(int(n), 4))),
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
        images: Optional[list[bytes]] = None,  # 传了→图生图走 /images/edits(multipart)
        size: str = "1024x1024",
        n: int = 1,
    ) -> list[bytes]:
        headers = {"Authorization": f"Bearer {self._api_key}"}
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            if images:
                # 图生图：multipart，图片用可重复字段名 image[]（OpenAI 契约），其余走表单。
                files = [("image[]", (f"src-{i}.png", buf, "image/png")) for i, buf in enumerate(images)]
                resp = await client.post(
                    f"{self._base}/images/edits",
                    headers=headers,
                    data=build_openai_edit_form(self._model, prompt, size, self._quality, n),
                    files=files,
                )
            else:
                resp = await client.post(
                    f"{self._base}/images/generations",
                    headers=headers,
                    json=build_openai_image_payload(self._model, prompt, size, self._quality, n),
                )
            resp.raise_for_status()
            return parse_openai_images(resp.json())
