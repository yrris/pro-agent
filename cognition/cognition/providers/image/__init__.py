"""图像生成 provider（M9 线 B 生成侧）。

协议：`generate(prompt, images=None, size, n) -> list[bytes]`（PNG/JPEG 原始字节）。
实现：fake（确定性，测试/离线）| ark（火山方舟豆包，同步 b64）| wanx（通义万相，
异步任务轮询）。生图 key 缺省时不注册 image_generate 工具（registry 门控）。
"""

from __future__ import annotations

from typing import Any

from cognition.providers.image.base import ImageGenProvider


def build_image_provider(settings: Any) -> ImageGenProvider:
    """按 settings 构建图像 provider（镜像 rag/factory 的集中选择模式）。"""
    provider = getattr(settings, "image_gen_provider", "") or ""
    if provider == "ark":
        from cognition.providers.image.ark import ArkImageProvider

        return ArkImageProvider(
            api_key=getattr(settings, "image_gen_api_key", "") or "",
            model=getattr(settings, "image_gen_model", "") or "doubao-seedream-3-0-t2i-250415",
            base_url=getattr(settings, "image_gen_base_url", "") or "https://ark.cn-beijing.volces.com/api/v3",
        )
    if provider == "wanx":
        from cognition.providers.image.wanx import WanxImageProvider

        return WanxImageProvider(
            api_key=getattr(settings, "image_gen_api_key", "") or "",
            model=getattr(settings, "image_gen_model", "") or "wanx2.1-t2i-turbo",
            base_url=getattr(settings, "image_gen_base_url", "") or "https://dashscope.aliyuncs.com",
        )
    from cognition.providers.image.fake import FakeImageProvider

    return FakeImageProvider()
