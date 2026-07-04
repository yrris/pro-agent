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


def sniff_image_type(data: bytes) -> tuple[str, str]:
    """按魔数嗅探图片真实类型，返回 (扩展名, content-type)（纯函数，可测）。

    /images/edits 是 multipart：字段的文件名扩展名与 content-type 必须与真实字节匹配，
    否则用户上传的 jpg/webp 照片被标成 png 可能被 OpenAI 拒（400）。默认回落 png。
    """
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png", "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "jpg", "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp", "image/webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif", "image/gif"
    return "png", "image/png"


def parse_openai_images(data: dict[str, Any]) -> list[bytes]:
    """响应 → 图片字节列表（纯函数，可测）；形状异常抛 ValueError。"""
    items = data.get("data") or []
    out = [base64.b64decode(it["b64_json"]) for it in items if isinstance(it, dict) and it.get("b64_json")]
    if not out:
        raise ValueError(f"openai 响应缺少图像数据: {list(data)}")
    return out


class OpenAIImageProvider:
    # 是否真正把源图送去生成（供 image_generate 措辞判断，不谎称图生图）。
    supports_image_to_image = True
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
                # 文件名扩展名/content-type 按真实字节嗅探（jpg/webp 照片不能标成 png）。
                files = []
                for i, buf in enumerate(images):
                    ext, ctype = sniff_image_type(buf)
                    files.append(("image[]", (f"src-{i}.{ext}", buf, ctype)))
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
