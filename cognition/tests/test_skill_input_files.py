"""脚本输入文件管道（M9 B2）：文件名白名单解析 + staging + runner/工具接线。

安全不变量：LLM 只能用**文件名**引用本 run 附件（白名单来自 config.metadata，key 已过
Go 归属闸）——名字不在白名单/歧义返回工具文本自纠，绝不能让模型指定任意对象 key。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from cognition.skills.registry import SkillRegistry
from cognition.skills.runner.local import LocalSubprocessScriptRunner
from cognition.skills.runner.request import resolve_input_files
from cognition.skills.runner.staging import stage_inputs
from cognition.skills.tools import build_skill_tools

ATTS = [
    {"resource_key": "uploads/u1/s1/aa-data.csv", "file_name": "data.csv", "mime_type": "text/csv", "size": 10},
    {"resource_key": "uploads/u1/s1/bb-dup.txt", "file_name": "dup.txt", "mime_type": "text/plain", "size": 1},
    {"resource_key": "uploads/u1/s2/cc-dup.txt", "file_name": "dup.txt", "mime_type": "text/plain", "size": 1},
]


def test_resolve_input_files_matrix():
    ok, problems = resolve_input_files(["data.csv"], ATTS)
    assert ok == [("uploads/u1/s1/aa-data.csv", "data.csv")] and not problems
    # 不存在 → 报错行含可用清单。
    _, p2 = resolve_input_files(["ghost.csv"], ATTS)
    assert p2 and "ghost.csv" in p2[0] and "data.csv" in p2[0]
    # 同名歧义 → 确定性报错。
    _, p3 = resolve_input_files(["dup.txt"], ATTS)
    assert p3 and "同名" in p3[0]
    # 带路径的请求名清洗为 basename 后匹配失败（白名单键是纯文件名）。
    _, p4 = resolve_input_files(["../etc/data.csv"], ATTS)
    assert p4  # "../etc/data.csv" 不在白名单
    assert resolve_input_files([], ATTS) == ([], [])


def test_stage_inputs_writes_and_raises(tmp_path):
    objs = {"uploads/u1/s1/aa-data.csv": b"a,b\n1,2\n"}
    staged = stage_inputs([("uploads/u1/s1/aa-data.csv", "data.csv")], objs.__getitem__, str(tmp_path))
    assert staged == ["data.csv"]
    assert (tmp_path / "data.csv").read_bytes() == b"a,b\n1,2\n"
    try:
        stage_inputs([("nope", "x")], objs.__getitem__, str(tmp_path))
        raise AssertionError("should raise")
    except KeyError:
        pass


_SKILL_MD = """---
name: reader
description: 读输入文件测试
---
读取 $SKILL_INPUT_DIR 下的文件。
"""

_READ_PY = """
import json, os, sys
in_dir = os.environ.get("SKILL_INPUT_DIR", "")
args = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
name = args.get("file", "data.csv")
with open(os.path.join(in_dir, name), encoding="utf-8") as f:
    content = f.read()
out = os.environ.get("SKILL_OUTPUT_DIR", ".")
with open(os.path.join(out, "echo.txt"), "w", encoding="utf-8") as f:
    f.write(content.upper())
print(f"read {name}: {len(content)} chars")
"""


def _skill_dir(tmp_path) -> Path:
    d = tmp_path / "reader"
    (d / "scripts").mkdir(parents=True)
    (d / "SKILL.md").write_text(_SKILL_MD, encoding="utf-8")
    (d / "scripts" / "read.py").write_text(_READ_PY, encoding="utf-8")
    return d


def _tools(tmp_path, downloader):
    reg = SkillRegistry()
    reg.refresh([tmp_path])
    tools = build_skill_tools(reg, LocalSubprocessScriptRunner(downloader=downloader))
    return {t.name: t for t in tools}


def test_local_runner_end_to_end_reads_staged_input(tmp_path):
    objs = {"uploads/u1/s1/aa-data.csv": "名字,分数\n甲,90\n".encode()}
    _skill_dir(tmp_path)
    tools = _tools(tmp_path, objs.__getitem__)

    async def run():
        return await tools["script_runner"].ainvoke(
            {"args": {"skill": "reader", "script": "read.py",
                      "script_args": {"file": "data.csv"}, "input_files": ["data.csv"]},
             "id": "c1", "name": "script_runner", "type": "tool_call"},
            config={"metadata": {"request_id": "r1",
                                 "attachments": '[{"resource_key":"uploads/u1/s1/aa-data.csv","file_name":"data.csv"}]'}},
        )

    msg = asyncio.run(run())
    assert "read data.csv" in msg.content
    assert msg.artifact and msg.artifact[0]["file_name"] == "echo.txt"


def test_tool_rejects_non_whitelisted_name(tmp_path):
    _skill_dir(tmp_path)
    tools = _tools(tmp_path, lambda k: b"")

    async def run():
        return await tools["script_runner"].ainvoke(
            {"args": {"skill": "reader", "script": "read.py", "input_files": ["秘密.txt"]},
             "id": "c2", "name": "script_runner", "type": "tool_call"},
            config={"metadata": {"request_id": "r1", "attachments": "[]"}},
        )

    msg = asyncio.run(run())
    assert "不存在" in msg.content and msg.artifact is None


def test_download_failure_is_deterministic_precondition_failure(tmp_path):
    def boom(key: str) -> bytes:
        raise RuntimeError("minio down")

    _skill_dir(tmp_path)
    tools = _tools(tmp_path, boom)

    async def run():
        return await tools["script_runner"].ainvoke(
            {"args": {"skill": "reader", "script": "read.py", "input_files": ["data.csv"]},
             "id": "c3", "name": "script_runner", "type": "tool_call"},
            config={"metadata": {"request_id": "r1",
                                 "attachments": '[{"resource_key":"uploads/u1/s1/aa-data.csv","file_name":"data.csv"}]'}},
        )

    msg = asyncio.run(run())
    assert "输入文件下载失败" in msg.content  # exit=126 stderr 进摘要，脚本未运行
