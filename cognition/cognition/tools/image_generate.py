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
from cognition.skills.runner.request import resolve_input_files
from cognition.skills.tools import _attachments_from_config
from cognition.tools.report import _maybe_upload, _run_id_from_config

_MAX_N = 4
_MAX_SOURCE_IMAGES = 4


def build_image_generate_tool(provider: ImageGenProvider, settings: Settings) -> BaseTool:
    """构造 image_generate 工具（闭包持有 provider/settings）。"""

    def _load_sources(source_images, config) -> tuple[list[bytes], Optional[str]]:
        """按文件名从本 run 附件白名单解析源图并下载（图生图）；返回 (bytes 列表, 错误文本)。

        白名单机制同 script_runner 的 input_files：LLM 只能引用本轮消息注记里列出的
        文件名，key 已过 Go 归属闸；未知名回工具文本让模型自纠，绝不触达任意对象。
        """
        all_names = list(source_images or [])
        names = all_names[:_MAX_SOURCE_IMAGES]
        dropped = all_names[_MAX_SOURCE_IMAGES:]  # 超限截断需回信给模型（否则静默丢图）
        warn = (
            f"源图超过 {_MAX_SOURCE_IMAGES} 张，仅取前 {_MAX_SOURCE_IMAGES} 张，忽略：{', '.join(dropped)}。"
            if dropped else ""
        )
        if not names:
            return [], None, ""
        resolved, problems = resolve_input_files(names, _attachments_from_config(config))
        if problems:
            return [], "；".join(problems), ""
        from cognition.attachments import MinioDownloader

        downloader = MinioDownloader(settings)
        out: list[bytes] = []
        for resource_key, _dest in resolved:
            out.append(downloader(resource_key))
        return out, None, warn

    async def image_generate(
        prompt: str,
        n: int = 1,
        size: Optional[str] = None,
        source_images: Optional[list[str]] = None,
        tool_call_id: Annotated[str, InjectedToolCallId] = "",
        config: RunnableConfig = None,  # type: ignore[assignment]
    ) -> tuple[str, Optional[list]]:
        """根据文字描述生成图片（1-4 张），产出可下载/预览的 PNG 产物。

        prompt 写清主体/环境/风格/构图/光影（可先看 image-style-library 技能的风格模板）。
        source_images 填**用户上传附件的图片文件名**（本轮消息注记中列出的）——传了就做
        图生图/编辑（把上传图当底图按 prompt 修改），不传就纯文生图。
        """
        count = max(1, min(int(n), _MAX_N))
        # 源图下载是阻塞 I/O → to_thread（事件循环红线）。
        try:
            sources, src_err, src_warn = await asyncio.to_thread(_load_sources, source_images, config)
        except Exception as exc:  # noqa: BLE001 — 下载失败降级为错误文本
            return (f"源图读取失败: {exc}", None)
        if src_err:
            return (src_err, None)
        try:
            images = await provider.generate(
                prompt, images=sources or None, size=size or settings.image_gen_size, n=count
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
            # B.1：同时把副本落进本 run 的生成图暂存区，供 frontend-design 内联进网页。
            from cognition.skills.runner.scratch import stash_generated

            await asyncio.to_thread(stash_generated, run_id, file_name, data)
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
        # 措辞按是否传入源图 + provider 是否真吃源图：非 openai/ark（如 wanx 文生图）会
        # 忽略源图，此时不谎称"图生图"。provider 经 supports_image_to_image 声明能力。
        used_source = bool(sources) and getattr(provider, "supports_image_to_image", True)
        mode = "图生图" if used_source else ("文生图（注：当前生图后端不支持图生图，已忽略上传图）" if sources else "文生图")
        note = f" {src_warn}" if src_warn else ""
        return (f"已生成 {len(artifacts)} 张图片（{mode}，prompt: {prompt[:80]}）。{note}", artifacts)

    tool = StructuredTool.from_function(
        coroutine=image_generate,
        name="image_generate",
        description=(
            "文生图/图生图：根据文字描述生成图片；若用户上传了图片，把其文件名填入 "
            "source_images 即做图生图/编辑。返回可下载/预览的 PNG 产物；"
            "先用 image-style-library 技能确定风格模板效果更好。"
        ),
        response_format="content_and_artifact",
    )
    tool.metadata = {"provider": "local"}
    return tool
