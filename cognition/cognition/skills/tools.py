"""Skill 工具（I/O）：把渐进式披露与脚本执行暴露成 LangChain 工具。

- `skill(name)`：L2——返回 SKILL.md 正文 + 脚本摘要（工具 description 里带 L1 目录）。
- `skill_list` / `skill_read` / `skill_glob` / `skill_grep`：L3——按需读 references，全部经 sandbox 校验。
- `script_runner(skill, script, args, timeout)`：经注入的 ScriptRunner 执行脚本，返回
  (stdout 摘要, artifact)（`content_and_artifact`，复用 Go /artifacts 代理与 ArtifactRef 形状）。

全部工具 metadata.provider="skill"，供装配期构建 provider_map。
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Optional

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, InjectedToolCallId, StructuredTool

from cognition.config import Settings
from cognition.skills import SkillSandboxError
from cognition.skills.disclosure import body, catalog
from cognition.skills.registry import SkillRegistry
from cognition.skills.runner.base import ScriptRunner
from cognition.skills.runner.request import build_request
from cognition.skills.sandbox import assert_path_allowed
from cognition.tools.report import _run_id_from_config

_SKILL_PROVIDER = "skill"
_MAX_READ_CHARS = 20000


def build_skill_tools(
    registry: SkillRegistry,
    runner: ScriptRunner,
    *,
    settings: Optional[Settings] = None,
    max_body_chars: int = 8000,
    default_timeout: float = 120.0,
) -> list[BaseTool]:
    """构建一组 skill 工具（闭包持有 registry/runner）。目录随装配期快照。"""

    def _bases() -> list[Path]:
        return registry.base_paths

    def skill(name: str) -> str:
        """展开某个 skill 的说明与可用脚本（渐进式披露 L2）。"""
        sk = registry.get(name)
        if sk is None:
            return f"未找到 skill「{name}」。可用: {[s.name for s in registry.list()]}"
        return body(sk, registry.scripts_of(sk), max_body_chars)

    def skill_list(path: str = "") -> str:
        """列目录：留空列出全部 skill；给相对/绝对路径则列该目录（沙箱内）。"""
        if not path:
            return catalog(registry.list())
        try:
            target = assert_path_allowed(path, _bases())
        except SkillSandboxError as exc:
            return f"拒绝: {exc}"
        if not target.is_dir():
            return f"不是目录: {path}"
        return "\n".join(sorted(p.name + ("/" if p.is_dir() else "") for p in target.iterdir()))

    def skill_read(path: str) -> str:
        """读取 skill 目录内的文件（渐进式披露 L3，沙箱内，超长截断）。"""
        try:
            target = assert_path_allowed(path, _bases())
        except SkillSandboxError as exc:
            return f"拒绝: {exc}"
        if not target.is_file():
            return f"文件不存在: {path}"
        text = target.read_text(encoding="utf-8", errors="replace")
        if len(text) > _MAX_READ_CHARS:
            return text[:_MAX_READ_CHARS] + f"\n…（已截断，原文 {len(text)} 字符）"
        return text

    def skill_glob(pattern: str) -> str:
        """在所有 skill 目录内按通配符查找文件（沙箱内）。"""
        hits: list[str] = []
        for base in _bases():
            for p in sorted(base.glob(pattern)):
                try:
                    assert_path_allowed(p, _bases())
                except SkillSandboxError:
                    continue
                hits.append(str(p))
        return "\n".join(hits) if hits else f"无匹配: {pattern}"

    def skill_grep(pattern: str, path: str = "") -> str:
        """在 skill 目录内按子串搜索（沙箱内，返回命中行）。"""
        roots = [assert_path_allowed(path, _bases())] if path else _bases()
        out: list[str] = []
        for root in roots:
            files = [root] if root.is_file() else [p for p in root.rglob("*") if p.is_file()]
            for f in files:
                try:
                    for i, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                        if pattern in line:
                            out.append(f"{f}:{i}: {line.strip()}")
                            if len(out) >= 100:
                                return "\n".join(out)
                except OSError:
                    continue
        return "\n".join(out) if out else f"无匹配: {pattern}"

    async def script_runner(
        skill: str,
        script: str,
        script_args: Optional[dict] = None,
        timeout: Optional[float] = None,
        tool_call_id: Annotated[str, InjectedToolCallId] = "",
        config: RunnableConfig = None,  # type: ignore[assignment]
    ) -> tuple[str, Optional[dict]]:
        """执行某个 skill 的脚本（容器隔离），返回输出摘要并登记产物。

        script_args 会作为单个 JSON 参数传给脚本。
        """
        sk = registry.get(skill)
        if sk is None:
            return (f"未找到 skill「{skill}」。", None)
        req = build_request(sk, script, script_args, default_timeout=default_timeout, requested_timeout=timeout)
        run_id = _run_id_from_config(config)
        result = await runner.run(req, run_id=run_id, tool_call_id=tool_call_id or "tc")
        head = "脚本执行完成" if result.ok else f"脚本执行失败(exit={result.exit_code}, timeout={result.timed_out})"
        summary = f"{head}。stdout: {result.stdout[:800]}"
        if result.stderr.strip():
            summary += f"\nstderr: {result.stderr[:400]}"
        if result.artifacts:
            summary += f"\n登记产物 {len(result.artifacts)} 个。"
        # 回传全部产物（此前只回 artifacts[0]，多产物技能如 chart 的 PNG+JSON 会丢件；
        # EventMapper._coerce_artifacts 本就接受列表）。
        artifact = list(result.artifacts) if result.artifacts else None
        return (summary, artifact)

    catalog_desc = "展开某个 skill 的说明与脚本（渐进式披露）。\n" + catalog(registry.list())

    tools: list[BaseTool] = [
        StructuredTool.from_function(func=skill, name="skill", description=catalog_desc),
        StructuredTool.from_function(func=skill_list, name="skill_list"),
        StructuredTool.from_function(func=skill_read, name="skill_read"),
        StructuredTool.from_function(func=skill_glob, name="skill_glob"),
        StructuredTool.from_function(func=skill_grep, name="skill_grep"),
        StructuredTool.from_function(
            coroutine=script_runner,
            name="script_runner",
            description="执行某个 skill 的脚本（容器隔离），返回输出摘要并登记可下载产物。",
            response_format="content_and_artifact",
        ),
    ]
    for t in tools:
        t.metadata = {"provider": _SKILL_PROVIDER}
    return tools
