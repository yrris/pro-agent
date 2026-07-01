"""本地子进程运行器（dev/CI 用，无隔离）。

行为与 Docker 运行器一致（同样的产物约定），但直接在宿主子进程里跑——用于单测覆盖
"请求构造→执行→产物扫描→（可选）上传"的整条逻辑，不依赖 docker daemon。
脚本约定：把产物写入环境变量 `SKILL_OUTPUT_DIR` 指向的目录；args 作为 argv[1]（JSON）。
"""

from __future__ import annotations

import asyncio
import logging
import mimetypes
import os
import tempfile
from pathlib import Path
from typing import Optional

from cognition.config import Settings
from cognition.skills.runner.base import ScriptResult
from cognition.skills.runner.request import ScriptRunRequest, scan_artifacts

logger = logging.getLogger(__name__)


class LocalSubprocessScriptRunner:
    """在宿主子进程执行脚本（无隔离）。生产用 DockerScriptRunner。"""

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self._settings = settings

    async def run(self, req: ScriptRunRequest, *, run_id: str, tool_call_id: str) -> ScriptResult:
        out_dir = tempfile.mkdtemp(prefix="skill-out-")
        env = {**os.environ, "SKILL_OUTPUT_DIR": out_dir, "SKILL_ARGS": req.cmd[-1]}
        try:
            proc = await asyncio.create_subprocess_exec(
                *req.cmd,
                cwd=req.workdir,
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            return ScriptResult(exit_code=127, stdout="", stderr=f"运行器无法启动: {exc}")

        timed_out = False
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=req.timeout_s)
        except asyncio.TimeoutError:
            timed_out = True
            proc.kill()
            out, err = await proc.communicate()

        files = [
            (p.name, p.stat().st_size) for p in sorted(Path(out_dir).glob("*")) if p.is_file()
        ]
        artifacts = scan_artifacts(files, run_id=run_id, tool_call_id=tool_call_id)
        self._maybe_upload(out_dir, run_id, tool_call_id)

        return ScriptResult(
            exit_code=proc.returncode if proc.returncode is not None else -1,
            stdout=(out or b"").decode("utf-8", errors="replace"),
            stderr=(err or b"").decode("utf-8", errors="replace"),
            artifacts=artifacts,
            timed_out=timed_out,
        )

    def _maybe_upload(self, out_dir: str, run_id: str, tool_call_id: str) -> None:
        if self._settings is None or not self._settings.minio_upload_enabled:
            return
        from cognition.tools.report import _maybe_upload  # 复用惰性可降级上传

        for p in sorted(Path(out_dir).glob("*")):
            if not p.is_file():
                continue
            mime, _ = mimetypes.guess_type(p.name)
            _maybe_upload(
                self._settings,
                f"{run_id}/{tool_call_id}/{p.name}",
                p.read_bytes(),
                mime or "application/octet-stream",
            )
