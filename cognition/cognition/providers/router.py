"""最小模型分层路由（seam）。

角色→provider 的映射保留（planner/complex→Claude，simple/summary→DeepSeek），
但 M1 由 env 解析单一 provider（Settings.model_provider）统管所有角色——分支留着，
后续里程碑再真正按角色分流/降级/预算。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional, Sequence

if TYPE_CHECKING:
    from langchain_core.language_models.chat_models import BaseChatModel
    from langchain_core.tools import BaseTool

from cognition.config import Settings, get_settings
from cognition.providers.anthropic_provider import build_anthropic_chat
from cognition.providers.deepseek_provider import build_deepseek_chat

# 角色→首选 provider 的 seam（M2+ 才真正生效）。
ROLE_TO_PROVIDER: dict[str, str] = {
    "planner": "anthropic",
    "complex": "anthropic",
    "simple": "deepseek",
    "summary": "deepseek",
}


def select_model(
    role: str,
    *,
    tools: Optional[Sequence["BaseTool"]] = None,
    settings: Optional[Settings] = None,
) -> "BaseChatModel":
    """按角色选择模型；如给定 tools 则 bind_tools。

    M1：实际 provider 取自 Settings.model_provider（env，默认 anthropic），
    角色映射仅作为未来分流的占位分支。
    """
    settings = settings or get_settings()

    # 角色首选（保留分支，M1 不据此分流）。
    _preferred = ROLE_TO_PROVIDER.get(role, "anthropic")

    # M1：env 决定单一 provider。
    provider = (settings.model_provider or _preferred).lower()
    if provider == "deepseek":
        model = build_deepseek_chat(settings)
    else:
        model = build_anthropic_chat(settings)

    if tools:
        model = model.bind_tools(list(tools))
    return model
