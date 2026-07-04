"""运行级生成图暂存区（B.1：让生成的图能内联进 frontend-design 的网页）。

问题：生图工具把图存进 MinIO 的 run/tc/ 下（run 产物），但技能沙箱 --network none、
输入只从附件白名单落地，够不到 run 产物——所以"生成图 + 做成网页"里网页嵌不进那张图。

方案：一个**按 run_id 键控的本地暂存目录**。image_generate 生图后把副本写进这里；
script_runner 跑技能时若该 run 有暂存图，就把此目录**只读**挂进沙箱（SKILL_GENERATED_DIR），
render_page.py 据此把 src="generated/xxx" 的引用替换成 data-URI 内联。

安全：只读挂载，不改 --network none / --read-only 语义；路径在进程本机 tmp（docker 挂宿主路径，
与 out_dir/in_dir 同机制）。清理：随 OS tmp 回收（单用户 dev 可接受，见 docs/10）。
"""

from __future__ import annotations

import os
import re
import tempfile

_BASE = os.path.join(tempfile.gettempdir(), "pro-agent-generated")
_SAFE = re.compile(r"[^A-Za-z0-9_.-]")


def _safe(seg: str) -> str:
    return _SAFE.sub("_", seg or "unknown")[:120]


def run_generated_dir(run_id: str, *, create: bool = False) -> str:
    """返回某 run 的生成图暂存目录路径；create=True 时确保存在。"""
    path = os.path.join(_BASE, _safe(run_id))
    if create:
        os.makedirs(path, exist_ok=True)
    return path


def stash_generated(run_id: str, file_name: str, data: bytes) -> None:
    """把一张生成图写进该 run 的暂存区（best-effort，失败不抛——不阻断生图主流程）。"""
    try:
        d = run_generated_dir(run_id, create=True)
        with open(os.path.join(d, _safe(file_name)), "wb") as f:
            f.write(data)
    except OSError:
        pass


def has_generated(run_id: str) -> bool:
    """该 run 是否有暂存的生成图（决定要不要给沙箱挂载 SKILL_GENERATED_DIR）。"""
    d = run_generated_dir(run_id)
    try:
        return os.path.isdir(d) and any(os.scandir(d))
    except OSError:
        return False
