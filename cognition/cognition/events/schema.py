"""共享事件契约 v1 的 pydantic 镜像（与 proto/agent/v1/agent.proto 一致）。

类型：tool_thought | tool_call | tool_result | result。
不变量：finish 仅 RESULT 为 true（整 run 终态，恰好一次）；is_final 是单条消息终态。
`Event.to_proto()` 转换为生成的 proto 消息——在方法内**延迟** import 生成模块，
以便纯逻辑测试无需 genproto。
"""

from __future__ import annotations

import time
from enum import Enum
from typing import TYPE_CHECKING, Any, Optional

from pydantic import BaseModel, Field, model_validator

if TYPE_CHECKING:  # 仅类型提示
    from cognition._genproto import agent_pb2


def now_unix_ms() -> int:
    """当前时间（毫秒）。"""
    return int(time.time() * 1000)


class EventType(str, Enum):
    """事件消息类型。"""

    TOOL_THOUGHT = "tool_thought"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    RESULT = "result"


class ToolCallStatus(str, Enum):
    """工具调用生命周期状态。"""

    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


class ArtifactRef(BaseModel):
    """产物引用（沿用原项目 8 字段形状）。"""

    resource_key: str = ""
    name: str = ""
    preview_url: str = ""
    download_url: str = ""
    file_name: str = ""
    mime_type: str = ""
    size: int = 0
    missing: bool = False


class ThoughtPayload(BaseModel):
    """tool_thought 载荷。"""

    text: str = ""


class ToolPayload(BaseModel):
    """tool_call / tool_result 复用的载荷。"""

    tool_call_id: str = ""
    tool_name: str = ""
    tool_provider: str = "local"
    status: Optional[ToolCallStatus] = None  # tool_result 不带 status
    dispatch_index: int = 0
    input: dict[str, Any] = Field(default_factory=dict)
    tool_result: str = ""  # observation 文本（tool_result 用）
    summary: str = ""
    error_msg: str = ""
    artifact_refs: list[ArtifactRef] = Field(default_factory=list)


class ResultPayload(BaseModel):
    """result 载荷。"""

    text: str = ""
    artifact_refs: list[ArtifactRef] = Field(default_factory=list)


class Event(BaseModel):
    """流出的领域事件（信封 + oneof 载荷）。"""

    seq: int = Field(ge=1)         # 每 run 单调、无空洞、从 1
    run_id: str
    message_id: str               # 原位更新键；TOOL_CALL 时 == tool_call_id
    type: EventType
    ts_unix_ms: int = Field(default_factory=now_unix_ms)
    is_final: bool = False        # 本条消息终态
    finish: bool = False          # 整个 run 终态；仅 RESULT 为 true
    step: str = ""                # ReAct 步序/节点名（可观测）

    # oneof payload —— 按 type 设置其一
    tool_thought: Optional[ThoughtPayload] = None
    tool_call: Optional[ToolPayload] = None
    tool_result: Optional[ToolPayload] = None
    result: Optional[ResultPayload] = None

    @model_validator(mode="after")
    def _check_invariants(self) -> "Event":
        # finish 只允许出现在 RESULT 上。
        if self.finish and self.type is not EventType.RESULT:
            raise ValueError("finish=True is only allowed on RESULT events")
        # 对应 type 的载荷必须存在（结构完整性）。
        expected = {
            EventType.TOOL_THOUGHT: self.tool_thought,
            EventType.TOOL_CALL: self.tool_call,
            EventType.TOOL_RESULT: self.tool_result,
            EventType.RESULT: self.result,
        }[self.type]
        if expected is None:
            raise ValueError(f"event type {self.type.value} requires its matching payload")
        return self

    # ——————————————————————————————————————————————————————————————
    # proto 转换（延迟 import 生成模块；纯逻辑测试不会触发）
    # ——————————————————————————————————————————————————————————————
    def to_proto(self) -> "agent_pb2.Event":
        """转换为生成的 proto Event。"""
        from cognition._genproto import agent_pb2 as pb

        type_map = {
            EventType.TOOL_THOUGHT: pb.EVENT_TYPE_TOOL_THOUGHT,
            EventType.TOOL_CALL: pb.EVENT_TYPE_TOOL_CALL,
            EventType.TOOL_RESULT: pb.EVENT_TYPE_TOOL_RESULT,
            EventType.RESULT: pb.EVENT_TYPE_RESULT,
        }

        proto = pb.Event(
            seq=self.seq,
            run_id=self.run_id,
            message_id=self.message_id,
            type=type_map[self.type],
            ts_unix_ms=self.ts_unix_ms,
            is_final=self.is_final,
            finish=self.finish,
            step=self.step,
        )

        if self.type is EventType.TOOL_THOUGHT and self.tool_thought is not None:
            proto.tool_thought.CopyFrom(pb.ThoughtPayload(text=self.tool_thought.text))
        elif self.type is EventType.TOOL_CALL and self.tool_call is not None:
            proto.tool_call.CopyFrom(_tool_payload_to_proto(self.tool_call, pb))
        elif self.type is EventType.TOOL_RESULT and self.tool_result is not None:
            proto.tool_result.CopyFrom(_tool_payload_to_proto(self.tool_result, pb))
        elif self.type is EventType.RESULT and self.result is not None:
            proto.result.CopyFrom(
                pb.ResultPayload(
                    text=self.result.text,
                    artifact_refs=[_artifact_to_proto(a, pb) for a in self.result.artifact_refs],
                )
            )
        return proto


def _artifact_to_proto(a: ArtifactRef, pb: Any) -> Any:
    return pb.ArtifactRef(
        resource_key=a.resource_key,
        name=a.name,
        preview_url=a.preview_url,
        download_url=a.download_url,
        file_name=a.file_name,
        mime_type=a.mime_type,
        size=a.size,
        missing=a.missing,
    )


def _tool_payload_to_proto(p: ToolPayload, pb: Any) -> Any:
    status_map = {
        ToolCallStatus.RUNNING: pb.TOOL_CALL_STATUS_RUNNING,
        ToolCallStatus.SUCCESS: pb.TOOL_CALL_STATUS_SUCCESS,
        ToolCallStatus.FAILED: pb.TOOL_CALL_STATUS_FAILED,
    }
    tp = pb.ToolPayload(
        tool_call_id=p.tool_call_id,
        tool_name=p.tool_name,
        tool_provider=p.tool_provider,
        status=status_map.get(p.status, pb.TOOL_CALL_STATUS_UNSPECIFIED),
        dispatch_index=p.dispatch_index,
        tool_result=p.tool_result,
        summary=p.summary,
        error_msg=p.error_msg,
        artifact_refs=[_artifact_to_proto(a, pb) for a in p.artifact_refs],
    )
    # google.protobuf.Struct：用 update 填充解析后的参数对象（非字符串）。
    if p.input:
        tp.input.update(p.input)
    return tp
