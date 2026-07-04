"""图像生成（M9 B7）：provider 抽象 + image_generate 工具 + 门控注册。"""

from __future__ import annotations

import asyncio

from cognition.config import Settings
from cognition.providers.image import build_image_provider
from cognition.providers.image.ark import build_ark_payload, parse_ark_response
from cognition.providers.image.fake import FakeImageProvider
from cognition.providers.image.wanx import build_wanx_payload, parse_wanx_task_status
from cognition.tools.image_generate import build_image_generate_tool

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def test_fake_provider_deterministic_and_distinct():
    p = FakeImageProvider()
    a1 = asyncio.run(p.generate("一只橘猫"))
    a2 = asyncio.run(p.generate("一只橘猫"))
    b = asyncio.run(p.generate("赛博朋克城市", n=2))
    assert a1 == a2  # 同 prompt 确定性
    assert a1[0].startswith(PNG_MAGIC)
    assert len(b) == 2 and b[0] != b[1]  # n 张互不相同
    assert a1[0] != b[0]  # 不同 prompt 可区分


def test_provider_factory_selection():
    assert isinstance(build_image_provider(Settings(image_gen_provider="fake")), FakeImageProvider)
    ark = build_image_provider(Settings(image_gen_provider="ark", image_gen_api_key="k"))
    wanx = build_image_provider(Settings(image_gen_provider="wanx", image_gen_api_key="k"))
    assert type(ark).__name__ == "ArkImageProvider"
    assert type(wanx).__name__ == "WanxImageProvider"


def test_payload_builders_and_parsers():
    p = build_ark_payload("m1", "猫", "1024*1024")
    assert p["size"] == "1024x1024" and p["response_format"] == "b64_json" and "image" not in p
    p2 = build_ark_payload("m1", "猫", "1024x1024", image_b64="QUJD")
    assert p2["image"].startswith("data:image/png;base64,")
    import base64

    assert parse_ark_response({"data": [{"b64_json": base64.b64encode(b"IMG").decode()}]}) == b"IMG"

    w = build_wanx_payload("m2", "狗", "1024x1024", 2)
    assert w["parameters"]["size"] == "1024*1024" and w["parameters"]["n"] == 2
    st, urls = parse_wanx_task_status(
        {"output": {"task_status": "SUCCEEDED", "results": [{"url": "http://x/1.png"}]}}
    )
    assert st == "SUCCEEDED" and urls == ["http://x/1.png"]


def test_tool_multi_image_artifacts():
    tool = build_image_generate_tool(FakeImageProvider(), Settings())

    async def run():
        return await tool.ainvoke(
            {"args": {"prompt": "水墨山水", "n": 2}, "id": "img1",
             "name": "image_generate", "type": "tool_call"},
            config={"metadata": {"request_id": "run9"}},
        )

    msg = asyncio.run(run())
    assert "已生成 2 张图片" in msg.content
    assert isinstance(msg.artifact, list) and len(msg.artifact) == 2
    a = msg.artifact[0]
    assert a["mime_type"] == "image/png" and a["download_url"] == "/artifacts/run9/img1/image-1.png"
    assert {x["file_name"] for x in msg.artifact} == {"image-1.png", "image-2.png"}


def test_tool_provider_failure_degrades_to_text():
    class Boom:
        async def generate(self, prompt, *, images=None, size="1024x1024", n=1):
            raise RuntimeError("quota exceeded")

    tool = build_image_generate_tool(Boom(), Settings())

    async def run():
        return await tool.ainvoke(
            {"args": {"prompt": "x"}, "id": "img2", "name": "image_generate", "type": "tool_call"},
            config={"metadata": {"request_id": "r"}},
        )

    msg = asyncio.run(run())
    assert "图像生成失败" in msg.content and msg.artifact is None


def test_registry_gating():
    from cognition.tools.registry import build_tool_suite

    async def names(settings):
        tools, provider_map, closers = await build_tool_suite(settings)
        for c in closers:
            await c()
        return {t.name for t in tools}, provider_map

    off, _ = asyncio.run(names(Settings(image_gen_provider="", mcp_enabled=False, skills_enabled=False)))
    on, pm = asyncio.run(names(Settings(image_gen_provider="fake", mcp_enabled=False, skills_enabled=False)))
    assert "image_generate" not in off
    assert "image_generate" in on and pm["image_generate"] == "local"


def test_openai_payload_and_parse():
    """M12：OpenAI gpt-image provider——quality 默认 low、尺寸回落 auto、b64 解析。"""
    from cognition.providers.image.openai import build_openai_image_payload, parse_openai_images

    p = build_openai_image_payload("gpt-image-2", "猫", "1024x1024", "low", 2)
    assert p["quality"] == "low" and p["n"] == 2 and p["size"] == "1024x1024"
    assert build_openai_image_payload("m", "x", "512x512", "", 9)["size"] == "auto"  # 非法尺寸回落
    assert build_openai_image_payload("m", "x", "512x512", "", 9)["n"] == 4  # n 夹取
    import base64 as b64

    assert parse_openai_images({"data": [{"b64_json": b64.b64encode(b"IMG").decode()}]}) == [b"IMG"]


def test_openai_factory_selection():
    p = build_image_provider(Settings(image_gen_provider="openai", image_gen_api_key="k"))
    assert type(p).__name__ == "OpenAIImageProvider"


def test_openai_edit_form_no_forbidden_fields():
    """Y2：/images/edits 表单——不含 response_format/input_fidelity（gpt-image-2 会 400）；
    尺寸回落 auto；n 夹取。图片走 multipart files 不在此。"""
    from cognition.providers.image.openai import build_openai_edit_form

    f = build_openai_edit_form("gpt-image-2", "把猫变成橘色", "1024x1024", "low", 9)
    assert f["prompt"] == "把猫变成橘色" and f["quality"] == "low"
    assert f["n"] == "4" and f["size"] == "1024x1024"
    assert "response_format" not in f and "input_fidelity" not in f
    assert build_openai_edit_form("m", "x", "512x512", "", 1)["size"] == "auto"


def test_image_generate_source_images_whitelist_and_mode():
    """Y2：source_images 按本 run 附件白名单解析；未知名回工具文本自纠；传了走图生图。"""
    import asyncio as _a

    class SpyProvider:
        def __init__(self):
            self.got_images = None

        async def generate(self, prompt, *, images=None, size="1024x1024", n=1):
            self.got_images = images
            return [b"\x89PNG\r\n\x1a\n"]  # 单张假 PNG

    prov = SpyProvider()
    tool = build_image_generate_tool(prov, Settings())
    meta = {"request_id": "run-e",
            "attachments": '[{"resource_key":"uploads/u/s/aa-cat.png","file_name":"cat.png"}]'}

    # 未知文件名 → 工具文本自纠，不调 provider。
    msg_bad = _a.run(tool.ainvoke(
        {"args": {"prompt": "改色", "source_images": ["ghost.png"]}, "id": "i1",
         "name": "image_generate", "type": "tool_call"},
        config={"metadata": meta}))
    assert "不存在" in msg_bad.content and prov.got_images is None

    # 白名单命中 → 走图生图（provider 收到 bytes；下载器需 mock）。
    from cognition import attachments as _att

    orig = _att.MinioDownloader
    _att.MinioDownloader = lambda settings: (lambda key: b"SRCBYTES")  # noqa: E731
    try:
        msg_ok = _a.run(tool.ainvoke(
            {"args": {"prompt": "把猫变橘色", "source_images": ["cat.png"]}, "id": "i2",
             "name": "image_generate", "type": "tool_call"},
            config={"metadata": meta}))
    finally:
        _att.MinioDownloader = orig
    assert "图生图" in msg_ok.content
    assert prov.got_images == [b"SRCBYTES"]


def test_image_generate_text_to_image_no_sources():
    """无 source_images → 文生图（provider images=None）。"""
    import asyncio as _a

    class Spy:
        def __init__(self):
            self.images = "unset"

        async def generate(self, prompt, *, images=None, size="1024x1024", n=1):
            self.images = images
            return [b"\x89PNG\r\n\x1a\n"]

    s = Spy()
    tool = build_image_generate_tool(s, Settings())
    msg = _a.run(tool.ainvoke(
        {"args": {"prompt": "水墨山水"}, "id": "i3", "name": "image_generate", "type": "tool_call"},
        config={"metadata": {"request_id": "r"}}))
    assert "文生图" in msg.content and s.images is None
