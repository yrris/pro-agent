"""运行配置（pydantic-settings，从环境变量读取）。

M1 范围：模型 provider + id、Anthropic/DeepSeek key、Postgres DSN、
ReAct 步数上限、gRPC 监听端口。所有字段都有默认值，因此纯逻辑测试无需任何环境变量。

环境变量约定：
- 业务配置使用 `COGNITION_` 前缀（如 COGNITION_MODEL_PROVIDER / COGNITION_GRPC_PORT）。
- 密钥沿用各家 SDK 的惯用名（ANTHROPIC_API_KEY / DEEPSEEK_API_KEY），同时接受带前缀写法。
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """认知面运行配置（单一事实源）。"""

    model_config = SettingsConfigDict(
        env_prefix="COGNITION_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        # 字段以 model_ 开头会触发 pydantic 的保护命名空间告警，这里关闭。
        protected_namespaces=(),
        populate_by_name=True,
    )

    # —— 模型路由 ——
    # M1：单一 provider 由 env 解析（默认 anthropic）；role→provider 分支保留在 router 中。
    model_provider: str = Field(default="anthropic")  # "anthropic" | "deepseek"
    anthropic_model: str = Field(default="claude-opus-4-8")
    deepseek_model: str = Field(default="deepseek-chat")

    anthropic_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("COGNITION_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY"),
    )
    deepseek_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("COGNITION_DEEPSEEK_API_KEY", "DEEPSEEK_API_KEY"),
    )
    deepseek_base_url: str = Field(default="https://api.deepseek.com")

    # —— Checkpoint（可恢复执行状态）——
    pg_dsn: str | None = Field(
        default=None,
        validation_alias=AliasChoices("COGNITION_PG_DSN", "DATABASE_URL"),
    )

    # —— ReAct ——
    max_steps: int = Field(default=40, ge=1)

    # 确定性脚本化模型开关：无需真实 LLM key 即可端到端验证（见 providers/fake.py）。
    fake_model: bool = Field(default=False)

    # —— gRPC 服务 ——
    grpc_host: str = Field(default="0.0.0.0")
    grpc_port: int = Field(default=50051, ge=1, le=65535)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """进程级单例配置。"""
    return Settings()
