"""工具注册表。

`get_local_tools()` 返回本阶段的本地工具集合。这里是 toolProvider="local" 概念上
被打标的地方——后续接 MCP / Skill 工具时，在此聚合并标注各自的 provider。

M2：calculator（无副作用计算）+ write_report（产物落 MinIO，登记 artifact）。
"""

from __future__ import annotations

from langchain_core.tools import BaseTool

from cognition.tools.calculator import calculator
from cognition.tools.report import write_report

# 工具提供方标记（事件契约里 tool_provider 字段的来源）。本阶段恒为 "local"。
LOCAL_PROVIDER = "local"


def get_local_tools() -> list[BaseTool]:
    """返回本地工具列表（M2：calculator + write_report）。"""
    return [calculator, write_report]
