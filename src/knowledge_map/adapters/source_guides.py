"""Durable reader content and search attempts in the SQLite document store."""

import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from knowledge_map.adapters import sqlite_db
from knowledge_map.schemas.source_guides import (
    GuideAttempt,
    GuideSearchDetails,
    SavedSourceGuide,
    SourceGuide,
)


class GuideAlreadyRunning(Exception):
    """An explicit update must wait for the guide's active attempt to finish."""


class SQLiteGuideStore:
    def __init__(self, db_path: str | Path | None = None):
        self.db_path = str(
            db_path if db_path is not None else sqlite_db.DEFAULT_DB_PATH
        )
        with closing(sqlite3.connect(self.db_path)) as connection, connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS source_guides (
                    guide_id TEXT PRIMARY KEY,
                    question TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    latest_attempt_id TEXT NOT NULL,
                    content_json TEXT,
                    retrieved_at TEXT
                );
                CREATE TABLE IF NOT EXISTS source_guide_attempts (
                    attempt_id TEXT PRIMARY KEY,
                    guide_id TEXT NOT NULL REFERENCES source_guides(guide_id),
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    status TEXT NOT NULL CHECK(status IN (
                        'running', 'completed', 'empty', 'failed', 'cancelled', 'interrupted'
                    )),
                    outcome_json TEXT
                );
            """)

    def create(
        self, question: str, search_details: GuideSearchDetails | None = None
    ) -> SavedSourceGuide:
        guide_id, attempt_id = str(uuid4()), str(uuid4())
        now = datetime.now(UTC).isoformat()
        with closing(sqlite3.connect(self.db_path)) as connection, connection:
            connection.execute(
                "INSERT INTO source_guides (guide_id, question, created_at, latest_attempt_id) "
                "VALUES (?, ?, ?, ?)",
                (guide_id, question, now, attempt_id),
            )
            connection.execute(
                "INSERT INTO source_guide_attempts (attempt_id, guide_id, started_at, status, outcome_json) "
                "VALUES (?, ?, ?, 'running', ?)",
                (
                    attempt_id,
                    guide_id,
                    now,
                    SourceGuide(
                        question=question,
                        status="running",
                        search_details=search_details,
                    ).model_dump_json(),
                ),
            )
        return self.get(guide_id)

    def interrupt_unfinished(self) -> None:
        for saved in self.list():
            if saved.latest_attempt.status == "running":
                self.finish(
                    saved.guide_id,
                    saved.latest_attempt.attempt_id,
                    SourceGuide(
                        question=saved.question,
                        status="interrupted",
                        message="This search was interrupted before it finished.",
                    ),
                )

    def start_update(
        self, guide_id: str, search_details: GuideSearchDetails | None = None
    ) -> SavedSourceGuide:
        attempt_id = str(uuid4())
        now = datetime.now(UTC).isoformat()
        with closing(sqlite3.connect(self.db_path)) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT a.status, g.question FROM source_guides g JOIN source_guide_attempts a "
                "ON a.attempt_id = g.latest_attempt_id WHERE g.guide_id = ?",
                (guide_id,),
            ).fetchone()
            if row is None:
                raise KeyError(guide_id)
            if row[0] == "running":
                raise GuideAlreadyRunning(guide_id)
            connection.execute(
                "INSERT INTO source_guide_attempts (attempt_id, guide_id, started_at, status, outcome_json) "
                "VALUES (?, ?, ?, 'running', ?)",
                (
                    attempt_id,
                    guide_id,
                    now,
                    SourceGuide(
                        question=row[1], status="running", search_details=search_details
                    ).model_dump_json(),
                ),
            )
            connection.execute(
                "UPDATE source_guides SET latest_attempt_id = ? WHERE guide_id = ?",
                (attempt_id, guide_id),
            )
        return self.get(guide_id)

    def finish(
        self, guide_id: str, attempt_id: str, result: SourceGuide
    ) -> SavedSourceGuide:
        saved = self.get(guide_id)
        details = result.search_details or saved.latest_attempt.search_details
        if details is not None:
            completion = (
                "failed"
                if result.status.endswith("_failed")
                else result.status
                if result.status in {"cancelled", "interrupted"}
                else "not_searched"
                if result.status in {"declined", "needs_edit"}
                else "partial"
                if result.partial
                else "completed"
            )
            result = result.model_copy(
                update={
                    "search_details": details.model_copy(
                        update={"completion": completion}
                    )
                }
            )
        now = datetime.now(UTC).isoformat()
        outcome = result.model_dump_json()
        state = (
            "failed"
            if result.status.endswith("_failed")
            else result.status
            if result.status in {"empty", "cancelled", "interrupted"}
            else "completed"
        )
        with closing(sqlite3.connect(self.db_path)) as connection, connection:
            updated = connection.execute(
                "UPDATE source_guide_attempts SET status = ?, finished_at = ?, outcome_json = ? "
                "WHERE attempt_id = ? AND guide_id = ? AND status = 'running' "
                "AND attempt_id = (SELECT latest_attempt_id FROM source_guides WHERE guide_id = ?)",
                (state, now, outcome, attempt_id, guide_id, guide_id),
            )
            if updated.rowcount and result.status in {"completed", "empty"}:
                connection.execute(
                    "UPDATE source_guides SET content_json = ?, retrieved_at = ? WHERE guide_id = ?",
                    (outcome, now, guide_id),
                )
        return self.get(guide_id)

    def get(self, guide_id: str) -> SavedSourceGuide:
        with closing(sqlite3.connect(self.db_path)) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                "SELECT g.*, a.attempt_id, a.started_at, a.finished_at, a.status, a.outcome_json "
                "FROM source_guides g JOIN source_guide_attempts a ON a.attempt_id = g.latest_attempt_id "
                "WHERE g.guide_id = ?",
                (guide_id,),
            ).fetchone()
        if row is None:
            raise KeyError(guide_id)
        outcome = (
            SourceGuide.model_validate_json(row["outcome_json"])
            if row["outcome_json"]
            else None
        )
        content = (
            SourceGuide.model_validate_json(row["content_json"])
            if row["content_json"]
            else outcome
        )
        values = (
            content.model_dump()
            if content
            else {"question": row["question"], "status": row["status"]}
        )
        return SavedSourceGuide.model_validate(
            {
                **values,
                "guide_id": row["guide_id"],
                "created_at": row["created_at"],
                "last_retrieved_at": row["retrieved_at"],
                "latest_attempt": GuideAttempt.model_validate(
                    {
                        "attempt_id": row["attempt_id"],
                        "started_at": row["started_at"],
                        "finished_at": row["finished_at"],
                        "status": row["status"],
                        "outcome": outcome.status
                        if outcome and outcome.status != "running"
                        else None,
                        "assessment": outcome.assessment if outcome else None,
                        "message": outcome.message if outcome else None,
                        "search_details": outcome.search_details if outcome else None,
                        "disclosures": outcome.disclosures if outcome else (),
                    }
                ),
            }
        )

    def list(self) -> list[SavedSourceGuide]:
        with closing(sqlite3.connect(self.db_path)) as connection:
            identities = connection.execute(
                "SELECT guide_id FROM source_guides ORDER BY created_at DESC, guide_id"
            ).fetchall()
        return [self.get(row[0]) for row in identities]
