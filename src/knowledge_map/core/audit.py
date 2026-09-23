"""Dispatch independent best-effort inserts without gating a Chat Session."""

import asyncio
import logging
import subprocess
from pathlib import Path

from pydantic import JsonValue

from knowledge_map.adapters.audit import SQLiteAuditStore
from knowledge_map.schemas.audit import AuditStageRecord

logger = logging.getLogger(__name__)


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
