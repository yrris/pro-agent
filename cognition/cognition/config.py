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

    # —— 模型分层（M2）——
    # planner / executor 各自的 provider+model；留空则回落到上面的单 provider 设置。
    # 默认 deepseek（性价比）；owner 在最终集成时把 planner 切到 opus。
    planner_provider: str | None = Field(default=None)  # "anthropic" | "deepseek"
    planner_model: str | None = Field(default=None)
    executor_provider: str | None = Field(default=None)
    executor_model: str | None = Field(default=None)

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

    # —— Plan-Execute（M2）——
    # 外层 plan→execute→replan 循环上限（镜像原项目 plannerMaxSteps，默认 5）。
    planner_max_steps: int = Field(default=5, ge=1)
    # 并行子任务宽度上限（镜像 maxParallelTasks，默认 2）。
    max_parallel_tasks: int = Field(default=2, ge=1)
    # 单个并行分支（executor 子图）的超时秒数。
    branch_timeout_seconds: float = Field(default=120.0, gt=0)

    # —— 产物对象存储（MinIO）——
    # 默认与 deploy/.env 的 minio 对齐；上传是惰性/可降级的（无 MinIO 也能跑单测）。
    minio_endpoint: str = Field(
        default="localhost:9000",
        validation_alias=AliasChoices("COGNITION_MINIO_ENDPOINT", "MINIO_ENDPOINT"),
    )
    minio_access_key: str = Field(
        default="minioadmin",
        validation_alias=AliasChoices(
            "COGNITION_MINIO_ACCESS_KEY", "MINIO_ACCESS_KEY", "MINIO_ROOT_USER"
        ),
    )
    minio_secret_key: str = Field(
        default="minioadmin",
        validation_alias=AliasChoices(
            "COGNITION_MINIO_SECRET_KEY", "MINIO_SECRET_KEY", "MINIO_ROOT_PASSWORD"
        ),
    )
    minio_bucket: str = Field(
        default="artifacts",
        validation_alias=AliasChoices("COGNITION_MINIO_BUCKET", "MINIO_BUCKET"),
    )
    minio_secure: bool = Field(default=False)
    # 是否真正上传到 MinIO；默认 False → 单测/无 MinIO 环境只构造 ArtifactRef，不触网。
    minio_upload_enabled: bool = Field(default=False)

    # 确定性脚本化模型开关：无需真实 LLM key 即可端到端验证（见 providers/fake.py）。
    fake_model: bool = Field(default=False)

    # —— gRPC 服务 ——
    grpc_host: str = Field(default="0.0.0.0")
    grpc_port: int = Field(default=50051, ge=1, le=65535)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """进程级单例配置。"""
    return Settings()
