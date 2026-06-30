"""DeepSeek provider 工厂（OpenAI 兼容）。

薄封装 langchain-openai 的 ChatOpenAI，指向 DeepSeek 的 OpenAI 兼容端点。延迟 import。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from langchain_core.language_models.chat_models import BaseChatModel

from cognition.config import Settings, get_settings


def build_deepseek_chat(settings: Settings | None = None, **kwargs: Any) -> "BaseChatModel":
    """构造指向 DeepSeek 的 ChatOpenAI。"""
    from langchain_openai import ChatOpenAI

    settings = settings or get_settings()
    params: dict[str, Any] = {
        "model": settings.deepseek_model,
        "base_url": settings.deepseek_base_url,
    }
    if settings.deepseek_api_key:
        params["api_key"] = settings.deepseek_api_key
    params.update(kwargs)
    return ChatOpenAI(**params)
