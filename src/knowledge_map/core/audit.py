"""Dispatch independent best-effort inserts without gating a Chat Session."""

import asyncio
import logging
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import JsonValue

from knowledge_map.adapters.audit import SQLiteAuditStore
from knowledge_map.schemas.audit import AuditStageRecord
from knowledge_map.schemas.retrieval import RetrievalFailureLog

logger = logging.getLogger(__name__)


@dataclass
class AuditStage:
    writer: "AuditWriter | None" = None
    session_id: str | None = None
    status: Literal["succeeded", "failed", "skipped"] = "succeeded"
    metadata: dict[str, JsonValue] = field(default_factory=dict)


_current_stage: ContextVar[AuditStage | None] = ContextVar("audit_stage", default=None)


def observe_audit_metadata(**metadata: JsonValue) -> None:
    stage = _current_stage.get()
    if stage is not None:
        stage.metadata.update(metadata)


def observe_retrieval_failure(diagnostic: RetrievalFailureLog) -> None:
    observe_audit_metadata(
        failure_stage=diagnostic.stage,
        failure_kind=diagnostic.failure_kind,
        diagnostic=diagnostic.safe_diagnostic,
    )


def dispatch_audit_stage(
    name: str,
    *,
    started_at: datetime,
    ended_at: datetime,
    status: Literal["succeeded", "failed", "skipped"],
    metadata: dict[str, JsonValue],
) -> None:
    stage = _current_stage.get()
    if stage is None or stage.writer is None or stage.session_id is None:
        return
    try:
        stage.writer.dispatch(
            AuditStageRecord(
                session_id=stage.session_id,
                name=name,
                started_at=started_at,
                ended_at=ended_at,
                status=status,
                metadata=metadata,
            )
        )
    except Exception:
        logger.exception(
            "chat_audit_dispatch_failed",
            extra={"chat_audit_id": stage.session_id, "audit_stage_name": name},
        )


@contextmanager
def audit_stage(
    writer: "AuditWriter | None", session_id: str | None, name: str
) -> Iterator[AuditStage]:
    started_at = datetime.now(UTC)
    stage = AuditStage(writer=writer, session_id=session_id)
    token = _current_stage.set(stage)
    try:
        yield stage
    except BaseException as error:
        stage.status = "failed"
        stage.metadata.setdefault(
            "failure_kind",
            "cancelled" if isinstance(error, asyncio.CancelledError) else "unexpected",
        )
        stage.metadata.setdefault("diagnostic", "The operation did not complete.")
        raise
    finally:
        dispatch_audit_stage(
            name,
            started_at=started_at,
            ended_at=datetime.now(UTC),
            status=stage.status,
            metadata=stage.metadata,
        )
        _current_stage.reset(token)


@contextmanager
def child_audit_stage(name: str) -> Iterator[AuditStage]:
    parent = _current_stage.get()
    with audit_stage(
        parent.writer if parent else None,
        parent.session_id if parent else None,
        name,
    ) as stage:
        yield stage


def code_revision() -> dict[str, JsonValue]:
    try:
        root = Path(__file__).resolve().parents[3]
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return {"commit": None, "dirty": None}
    return {"commit": commit, "dirty": bool(dirty)}


class AuditWriter:
    def __init__(self, store: SQLiteAuditStore) -> None:
        self._store = store
        self._pending: set[asyncio.Task[None]] = set()
        self._available = False

    async def initialize(self) -> None:
        try:
            await asyncio.to_thread(self._store.initialize)
        except Exception:
            logger.exception("chat_audit_initialization_failed")
        else:
            self._available = True

    def dispatch(self, record: AuditStageRecord) -> None:
        if not self._available:
            return
        task = asyncio.create_task(self._insert(record))
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)

    async def _insert(self, record: AuditStageRecord) -> None:
        try:
            await asyncio.to_thread(self._store.insert, record)
        except Exception:
            logger.exception(
                "chat_audit_insert_failed",
                extra={
                    "chat_audit_id": record.session_id,
                    "audit_stage_id": record.stage_id,
                    "audit_stage_name": record.name,
                },
            )

    async def wait_for_writes(self) -> None:
        """Observe completion when explicitly requested, outside the chat path."""
        if self._pending:
            await asyncio.gather(*tuple(self._pending))
