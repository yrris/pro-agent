"""Docker 容器脚本运行器（生产默认隔离）。

`docker run --rm --network none -v {skill}:/skill:ro -v {out}:/out:rw` + 内存/CPU/pids 限制
+ 超时杀容器；产物从 /out 扫描后经 report._maybe_upload 上传 MinIO。
不改调用方即可换 gVisor/Firecracker（见 base.ScriptRunner）。CI 默认用 Local 运行器覆盖逻辑，
本类的实机用例以 `@pytest.mark.docker` 标注、默认跳过。
"""

from __future__ import annotations

import asyncio
import logging
import mimetypes
import tempfile
from pathlib import Path
from typing import Optional

from cognition.config import Settings
from cognition.skills.runner.base import ScriptResult
from cognition.skills.runner.request import ScriptRunRequest, scan_artifacts

logger = logging.getLogger(__name__)


class DockerScriptRunner:
    """一次性容器执行脚本，强隔离 + 资源限制。"""

    def __init__(
        self,
        image: str = "my-agent/skill-executor:latest",
        *,
        settings: Optional[Settings] = None,
        memory: str = "512m",
        cpus: str = "1",
        pids_limit: int = 128,
    ) -> None:
        self._image = image
        self._settings = settings
        self._memory = memory
        self._cpus = cpus
        self._pids_limit = pids_limit

    def _docker_argv(self, req: ScriptRunRequest, out_dir: str) -> list[str]:
        # 容器内命令：把 req.cmd 的相对脚本路径挂到 /skill 下执行；产物写 /out。
        interpreter, rel_script, json_args = req.cmd
        return [
            "docker", "run", "--rm",
            "--network", "none",
            "--memory", self._memory,
            "--cpus", self._cpus,
            "--pids-limit", str(self._pids_limit),
            "--read-only",
            "-v", f"{req.workdir}:/skill:ro",
            "-v", f"{out_dir}:/out:rw",
            "-e", "SKILL_OUTPUT_DIR=/out",
            "-w", "/skill",
            self._image,
            interpreter, f"/skill/{rel_script}", json_args,
        ]

    async def run(self, req: ScriptRunRequest, *, run_id: str, tool_call_id: str) -> ScriptResult:
        out_dir = tempfile.mkdtemp(prefix="skill-out-")
        argv = self._docker_argv(req, out_dir)
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
        except FileNotFoundError as exc:
            return ScriptResult(exit_code=127, stdout="", stderr=f"docker 不可用: {exc}")

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
        from cognition.tools.report import _maybe_upload

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
