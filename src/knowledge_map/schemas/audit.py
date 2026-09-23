"""Immutable observations saved in a Chat Session Audit Trail."""

from typing import Literal, Self
from uuid import uuid4

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    model_validator,
)


class AuditStageRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    stage_id: str = Field(default_factory=lambda: str(uuid4()), min_length=1)
    session_id: str = Field(min_length=1)
    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    started_at: AwareDatetime
    ended_at: AwareDatetime
    status: Literal["succeeded", "failed", "skipped"]
    schema_version: Literal[1] = 1
    metadata: dict[str, JsonValue]

    @model_validator(mode="after")
    def require_elapsed_interval(self) -> Self:
        if self.ended_at < self.started_at:
            raise ValueError("stage end cannot precede its start")
        return self
