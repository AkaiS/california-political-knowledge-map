"""Insert and inspect Chat Session observations in a separate local database."""

import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path

from knowledge_map.schemas.audit import AuditStageRecord


def audit_database_path() -> Path:
    return Path(os.environ.get("CHAT_AUDIT_DB_PATH", "chat_audit.db"))


class SQLiteAuditStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def initialize(self) -> None:
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS audit_stages (
                    stage_id TEXT PRIMARY KEY NOT NULL,
                    session_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    ended_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    schema_version INTEGER NOT NULL,
                    metadata TEXT NOT NULL
                )"""
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS audit_session_time "
                "ON audit_stages (session_id, started_at)"
            )

    def insert(self, record: AuditStageRecord) -> None:
        values = record.model_dump(mode="json")
        values["metadata"] = json.dumps(values["metadata"], ensure_ascii=False)
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute(
                "INSERT INTO audit_stages VALUES "
                "(:stage_id, :session_id, :name, :started_at, :ended_at, "
                ":status, :schema_version, :metadata)",
                values,
            )

    def read_trail(self, session_id: str) -> tuple[AuditStageRecord, ...]:
        uri = self.path.resolve().as_uri() + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True)) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                "SELECT * FROM audit_stages WHERE session_id = ? "
                "ORDER BY started_at, stage_id",
                (session_id,),
            ).fetchall()
        return tuple(
            AuditStageRecord.model_validate(
                {**dict(row), "metadata": json.loads(row["metadata"])}
            )
            for row in rows
        )
