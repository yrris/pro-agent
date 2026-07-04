"""M12 工具缺口：web_fetch（SSRF 防护/正文抽取）、code_interpreter（沙箱执行）、
docx/xlsx 文本提取。"""

from __future__ import annotations

import asyncio
import io

from cognition.attachments import extract_text, is_docx, is_xlsx
from cognition.config import Settings
from cognition.tools.code_interpreter import build_code_interpreter_tool
from cognition.tools.web_fetch import html_to_text, is_private_host, validate_fetch_url


# —— web_fetch 纯逻辑 ——

def test_html_to_text_strips_noise():
    title, text = html_to_text(
        "<html><head><title>标题X</title><style>.a{}</style></head>"
        "<body><script>evil()</script><h1>正文一</h1><p>段落 <b>加粗</b></p></body></html>"
    )
    assert title == "标题X"
    assert "正文一" in text and "段落" in text and "加粗" in text
    assert "evil" not in text and ".a{}" not in text


def test_ssrf_guard_matrix():
    # 私网/环回/元数据/link-local 全拒。
    for host in ("127.0.0.1", "localhost", "10.0.0.8", "192.168.1.1", "169.254.169.254", "0.0.0.0"):
        assert is_private_host(host) is True, host
    # URL 层：scheme 与主机校验。
    assert validate_fetch_url("ftp://example.com") is not None
    assert validate_fetch_url("http://127.0.0.1:8080/healthz") is not None
    assert validate_fetch_url("http://localhost:6333/dashboard") is not None
    assert validate_fetch_url("not a url") is not None
    # 公网域名放行（DNS 依赖：github.com 恒公网；离线环境解析失败=拒绝也安全）。
    # 不强断言放行，避免离线 CI 抖动。


# —— code_interpreter ——

def _ci(settings=None):
    return build_code_interpreter_tool(settings or Settings(code_interpreter_enabled=True))


async def _run_ci(code: str, timeout: float | None = None):
    tool = _ci()
    args = {"code": code}
    if timeout is not None:
        args["timeout"] = timeout
    return await tool.ainvoke(
        {"args": args, "id": "ci1", "name": "code_interpreter", "type": "tool_call"},
        config={"metadata": {"request_id": "run-ci"}},
    )


def test_code_interpreter_stdout_and_artifact():
    msg = asyncio.run(_run_ci(
        "import os\n"
        "print('结果=' + str(2**10))\n"
        "with open(os.path.join(os.environ['SKILL_OUTPUT_DIR'], 'out.txt'), 'w') as f: f.write('hello')\n"
    ))
    assert "执行成功" in msg.content and "结果=1024" in msg.content
    assert msg.artifact and msg.artifact[0]["file_name"] == "out.txt"
    assert msg.artifact[0]["download_url"] == "/artifacts/run-ci/ci1/out.txt"


def test_code_interpreter_error_and_timeout():
    msg = asyncio.run(_run_ci("raise ValueError('炸')"))
    assert "执行失败" in msg.content and "ValueError" in msg.content
    msg2 = asyncio.run(_run_ci("import time; time.sleep(30)", timeout=2))
    assert "超时" in msg2.content


def test_code_interpreter_empty():
    msg = asyncio.run(_run_ci("   "))
    assert "代码为空" in msg.content


# —— docx / xlsx 提取 ——

def test_docx_extract():
    import pytest

    docx = pytest.importorskip("docx")
    buf = io.BytesIO()
    d = docx.Document()
    d.add_paragraph("第一段内容")
    t = d.add_table(rows=1, cols=2)
    t.rows[0].cells[0].text = "甲"
    t.rows[0].cells[1].text = "乙"
    d.save(buf)
    data = buf.getvalue()
    assert is_docx("", "报告.docx")
    text = extract_text(data, "", "报告.docx")
    assert "第一段内容" in text and "甲 | 乙" in text


def test_xlsx_extract():
    import pytest

    openpyxl = pytest.importorskip("openpyxl")
    buf = io.BytesIO()
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "销售"
    ws.append(["月份", "金额"])
    ws.append(["1月", 120])
    wb.save(buf)
    assert is_xlsx("", "table.xlsx")
    text = extract_text(buf.getvalue(), "", "table.xlsx")
    assert "工作表: 销售" in text and "月份,金额" in text and "1月,120" in text


def test_corrupt_office_degrades_none():
    assert extract_text(b"not a real docx", "", "x.docx") is None
    assert extract_text(b"not a real xlsx", "", "x.xlsx") is None


def test_new_skills_load_and_render_page():
    """M12：github-deep-research（纯提示词）与 frontend-design（render_page.py）注册与执行。"""
    from pathlib import Path

    from cognition.skills.registry import SkillRegistry
    from cognition.skills.runner.local import LocalSubprocessScriptRunner
    from cognition.skills.tools import build_skill_tools

    skill_dir = Path(__file__).resolve().parents[1] / "runtime" / "skills"
    reg = SkillRegistry()
    reg.refresh([str(skill_dir)])
    names = {s.name for s in reg.list()}
    assert {"github-deep-research", "frontend-design"} <= names

    tools = {t.name: t for t in build_skill_tools(reg, LocalSubprocessScriptRunner())}
    # L2 展开含调研流程/设计准则关键词。
    assert "web_fetch" in tools["skill"].invoke({"name": "github-deep-research"})
    assert "自包含" in tools["skill"].invoke({"name": "frontend-design"})

    async def run():
        return await tools["script_runner"].ainvoke(
            {"args": {"skill": "frontend-design", "script": "render_page.py",
                      "script_args": {"title": "测试页", "html": "<h1>你好</h1>"}},
             "id": "fd1", "name": "script_runner", "type": "tool_call"},
            config={"metadata": {"request_id": "r1"}},
        )

    msg = asyncio.run(run())
    assert "已生成 site.html" in msg.content
    assert msg.artifact and msg.artifact[0]["file_name"] == "site.html"


def test_code_interpreter_env_isolation():
    """密钥隔离：用户代码读不到认知面进程的 API key 等环境变量。"""
    import os

    os.environ["FAKE_SECRET_FOR_TEST"] = "leak-me"
    try:
        msg = asyncio.run(_run_ci(
            "import os\n"
            "print('SECRET=' + os.environ.get('FAKE_SECRET_FOR_TEST', 'ABSENT'))\n"
            "print('KEYS=' + str(sorted(k for k in os.environ if 'KEY' in k or 'SECRET' in k)))\n"
        ))
    finally:
        del os.environ["FAKE_SECRET_FOR_TEST"]
    assert "SECRET=ABSENT" in msg.content  # 不继承任意变量
    assert "leak-me" not in msg.content


def test_code_interpreter_default_off_and_gated_registration():
    """评审#1：code_interpreter 默认关闭（危险原语 opt-in）。"""
    async def names(settings):
        from cognition.tools.registry import build_tool_suite

        tools, _, closers = await build_tool_suite(settings)
        for c in closers:
            await c()
        return {t.name for t in tools}

    off = asyncio.run(names(Settings(mcp_enabled=False, skills_enabled=False)))
    assert "code_interpreter" not in off  # 默认不注册
    assert "web_fetch" in off  # web_fetch 默认开（有 SSRF 防护）
    on = asyncio.run(names(Settings(mcp_enabled=False, skills_enabled=False, code_interpreter_enabled=True)))
    assert "code_interpreter" in on


def test_office_zip_bomb_guard():
    """评审#4/#8：伪造成超大解压比的 office zip 被拒（不进解析）。"""
    import io
    import zipfile

    from cognition.attachments import _office_zip_safe

    # 正常小 zip 放行。
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("word/document.xml", "<xml>hi</xml>")
    assert _office_zip_safe(buf.getvalue()) is True
    # 高压缩比炸弹：0 字节压成的 200MB 全零。
    bomb = io.BytesIO()
    with zipfile.ZipFile(bomb, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("big.xml", b"\x00" * (200 * 1024 * 1024))
    assert _office_zip_safe(bomb.getvalue()) is False


def test_openai_alias_does_not_steal_ark(monkeypatch):
    """评审#20：环境里有 OPENAI_API_KEY 时，ark 配置（ARK_API_KEY）不被抢。"""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
    monkeypatch.setenv("ARK_API_KEY", "ark-key")
    s = Settings(image_gen_provider="ark")
    assert s.image_gen_api_key == "ark-key"  # ARK 在 OPENAI 之前命中
