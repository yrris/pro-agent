"""code_interpreter 工具（M12）：模型写 Python → 沙箱执行 → 观察结果 + 文件产物。

执行形态复用技能运行器的约定（$SKILL_OUTPUT_DIR 收产物、stdout/stderr 截断回观察），
但代码是动态的：写入临时工作目录后按 settings.skill_runner 选执行方式——
- local：venv 解释器子进程（dev/CI；无隔离，建议把本工具列入 approval_tools）；
- docker：skill-executor 镜像 `--network none --read-only` 强隔离（生产推荐）。

安全：这是"任意代码执行"原语——生产必须 docker 运行器 + 建议审批门；
超时/输出限幅/产物数量限幅都在本层钉死。
"""

from __future__ import annotations

import asyncio
import mimetypes
import os
import sys
import tempfile
from pathlib import Path
from typing import Annotated, Optional

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, InjectedToolCallId, StructuredTool

from cognition.config import Settings
from cognition.skills.runner.request import scan_artifacts
from cognition.tools.report import _maybe_upload, _run_id_from_config

_TIMEOUT_S = 60.0
_MAX_OUT_CHARS = 4_000
_MAX_ARTIFACTS = 8

_PRELUDE = """\
# pro-agent code interpreter 前导（自动注入）：产物写 OUTPUT_DIR 即成为可下载文件。
import os
OUTPUT_DIR = os.environ.get("SKILL_OUTPUT_DIR", ".")
"""


def build_code_interpreter_tool(settings: Settings) -> BaseTool:
    """构造 code_interpreter 工具（闭包持有 settings 以选运行器/上传产物）。"""

    use_docker = getattr(settings, "skill_runner", "local") == "docker"
    image = getattr(settings, "skill_runner_image", "my-agent/skill-executor:latest")

    async def code_interpreter(
        code: str,
        timeout: Optional[float] = None,
        tool_call_id: Annotated[str, InjectedToolCallId] = "",
        config: RunnableConfig = None,  # type: ignore[assignment]
    ) -> tuple[str, Optional[list]]:
        """执行一段 Python 代码并返回输出；写入 OUTPUT_DIR 的文件会成为可下载产物。

        适用：临时计算/数据变换/画图（matplotlib 可用）/生成文件。代码须自包含；
        网络在生产沙箱中不可用。把结果 print 出来或写文件到 OUTPUT_DIR。
        """
        if not code.strip():
            return ("代码为空。", None)
        t = min(float(timeout or _TIMEOUT_S), 300.0)
        work = tempfile.mkdtemp(prefix="ci-work-")
        out_dir = tempfile.mkdtemp(prefix="ci-out-")
        script = Path(work) / "main.py"
        script.write_text(_PRELUDE + code, encoding="utf-8")

        if use_docker:
            argv = [
                "docker", "run", "--rm", "--network", "none",
                "--memory", "512m", "--cpus", "1", "--pids-limit", "128",
                "--read-only", "--tmpfs", "/tmp", "-e", "MPLCONFIGDIR=/tmp",
                "-v", f"{work}:/work:ro", "-v", f"{out_dir}:/out:rw",
                "-e", "SKILL_OUTPUT_DIR=/out", "-w", "/work",
                image, "python3", "/work/main.py",
            ]
            env = None
        else:
            # 最小化环境：绝不继承进程全量 env——认知面进程持有 LLM/MinIO 等密钥，
            # 任意用户代码 os.environ 一读就泄漏。只给解释器运转所需的白名单变量。
            env = {
                "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                "HOME": out_dir,  # 家目录指向产物目录（pip/matplotlib 等的缓存落这里）
                "LANG": os.environ.get("LANG", "en_US.UTF-8"),
                "SKILL_OUTPUT_DIR": out_dir,
                "MPLCONFIGDIR": out_dir,
            }
            argv = [sys.executable, str(script)]

        try:
            proc = await asyncio.create_subprocess_exec(
                *argv, env=env,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            return (f"解释器不可用: {exc}", None)
        timed_out = False
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=t)
        except asyncio.TimeoutError:
            timed_out = True
            proc.kill()
            out, err = await proc.communicate()

        stdout = (out or b"").decode("utf-8", errors="replace")[:_MAX_OUT_CHARS]
        stderr = (err or b"").decode("utf-8", errors="replace")[:_MAX_OUT_CHARS // 2]

        run_id = _run_id_from_config(config)
        tcid = tool_call_id or "tc"
        files = sorted(p for p in Path(out_dir).glob("*") if p.is_file())[:_MAX_ARTIFACTS]
        artifacts = scan_artifacts(
            [(p.name, p.stat().st_size) for p in files], run_id=run_id, tool_call_id=tcid
        )
        # 上传 best-effort（阻塞 I/O → to_thread；失败不阻断观察结果）。
        for p in files:
            mime, _ = mimetypes.guess_type(p.name)
            await asyncio.to_thread(
                _maybe_upload, settings, f"{run_id}/{tcid}/{p.name}",
                p.read_bytes(), mime or "application/octet-stream",
            )

        if timed_out:
            head = f"执行超时（>{t:.0f}s，已终止）"
        elif proc.returncode == 0:
            head = "执行成功"
        else:
            head = f"执行失败(exit={proc.returncode})"
        summary = f"{head}。stdout:\n{stdout or '（空）'}"
        if stderr.strip():
            summary += f"\nstderr:\n{stderr}"
        if artifacts:
            summary += f"\n产物 {len(artifacts)} 个：{', '.join(a['file_name'] for a in artifacts)}"
        return (summary, artifacts or None)

    tool = StructuredTool.from_function(
        coroutine=code_interpreter,
        name="code_interpreter",
        description="执行 Python 代码（沙箱）：计算/数据变换/matplotlib 画图/生成文件；文件写 OUTPUT_DIR 即成可下载产物。",
        response_format="content_and_artifact",
    )
    tool.metadata = {"provider": "local"}
    return tool
