"""image_generate 本地工具（M9）：文生图 → 多张 PNG 产物。

provider 经装配期注入（fake/ark/wanx 可切换）；图片字节的 MinIO 上传走
asyncio.to_thread（阻塞 I/O 不占 grpc.aio 事件循环——图片是 MB 级，不同于
knowledge_search 的小 md 内联上传）。产物 ArtifactRef 列表复用 Go /artifacts 代理。
"""

from __future__ import annotations

import asyncio
from typing import Annotated, Optional

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, InjectedToolCallId, StructuredTool

from cognition.config import Settings
from cognition.providers.image.base import ImageGenProvider
from cognition.tools.report import _maybe_upload, _run_id_from_config

_MAX_N = 4


def build_image_generate_tool(provider: ImageGenProvider, settings: Settings) -> BaseTool:
    """构造 image_generate 工具（闭包持有 provider/settings）。"""

    async def image_generate(
        prompt: str,
        n: int = 1,
        size: Optional[str] = None,
        tool_call_id: Annotated[str, InjectedToolCallId] = "",
        config: RunnableConfig = None,  # type: ignore[assignment]
    ) -> tuple[str, Optional[list]]:
        """根据文字描述生成图片（1-4 张），产出可下载/预览的 PNG 产物。

        prompt 写清主体/环境/风格/构图/光影（可先看 image-style-library 技能的风格模板）。
        """
        count = max(1, min(int(n), _MAX_N))
        try:
            images = await provider.generate(
                prompt, size=size or settings.image_gen_size, n=count
            )
        except Exception as exc:  # noqa: BLE001 — provider 失败降级为错误文本，模型可复述
            return (f"图像生成失败: {exc}", None)
        if not images:
            return ("图像生成失败: provider 未返回图片", None)

        run_id = _run_id_from_config(config)
        tcid = tool_call_id or "tc"
        artifacts: list[dict] = []
        for i, data in enumerate(images, 1):
            file_name = f"image-{i}.png"
            resource_key = f"{run_id}/{tcid}/{file_name}"
            # 上传阻塞 I/O → to_thread（事件循环红线）；失败不阻断（_maybe_upload 内降级）。
            await asyncio.to_thread(_maybe_upload, settings, resource_key, data, "image/png")
            artifacts.append(
                {
                    "resource_key": resource_key,
                    "name": file_name,
                    "file_name": file_name,
                    "mime_type": "image/png",
                    "size": len(data),
                    "download_url": f"/artifacts/{resource_key}",
                    "preview_url": f"/artifacts/{resource_key}",
                    "missing": False,
                }
            )
        return (f"已生成 {len(artifacts)} 张图片（prompt: {prompt[:80]}）。", artifacts)

    tool = StructuredTool.from_function(
        coroutine=image_generate,
        name="image_generate",
        description="根据文字描述生成图片（文生图）。返回可下载/预览的 PNG 产物；先用 image-style-library 技能确定风格模板效果更好。",
        response_format="content_and_artifact",
    )
    tool.metadata = {"provider": "local"}
    return tool
