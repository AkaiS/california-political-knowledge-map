import hashlib
import json
import sqlite3
import sys
from pathlib import Path

import pytest

from knowledge_map.adapters.source_guides import SQLiteGuideStore
from knowledge_map.schemas.source_guides import SourceGuide

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deployment"))
from backup_sqlite import backup_sqlite


def file_hash(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def test_restore_preserves_owned_guides_attempts_quotas_and_committed_wal(tmp_path):
    source = tmp_path / "cloud.db"
    with sqlite3.connect(source) as writer:
        assert writer.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("CREATE TABLE corpus (id INTEGER PRIMARY KEY, content BLOB)")
        writer.commit()
        store = SQLiteGuideStore(source)
        completed = store.create("Saved public question", owner_id="visitor-one")
        store.finish(
            completed.guide_id,
            completed.latest_attempt.attempt_id,
            SourceGuide(question=completed.question, status="completed"),
        )
        pending = store.create("Unfinished public question", owner_id="visitor-two")
        writer.execute("INSERT INTO corpus VALUES (1, ?)", (b"committed corpus\x00",))
        writer.execute(
            "INSERT INTO public_daily_admissions VALUES ('2026-10-12', 9)"
        )
        writer.commit()
        wal = Path(str(source) + "-wal")
        assert wal.exists() and wal.stat().st_size > 0
        before = (file_hash(source), file_hash(wal))

        snapshot = backup_sqlite(source, tmp_path / "snapshots" / "one")

        assert (file_hash(source), file_hash(wal)) == before
        manifest = json.loads((snapshot / "manifest.json").read_text())
        restored = snapshot / "document_store.db"
        assert manifest["sqlite"]["sha256"] == file_hash(restored)
        assert manifest["source_opened_read_only"] is True
        assert manifest["sanitized"] is False
        with sqlite3.connect(restored) as recovery:
            assert recovery.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert recovery.execute("SELECT content FROM corpus").fetchone()[0] == b"committed corpus\x00"
            assert recovery.execute(
                "SELECT submissions FROM public_daily_admissions WHERE day='2026-10-12'"
            ).fetchone()[0] == 9
            assert recovery.execute("SELECT count(*) FROM source_guide_attempts").fetchone()[0] == 2
        restored_store = SQLiteGuideStore(restored)
        assert restored_store.get(completed.guide_id, owner_id="visitor-one").status == "completed"
        assert restored_store.get(pending.guide_id, owner_id="visitor-two").status == "running"
        with pytest.raises(KeyError):
            restored_store.get(completed.guide_id, owner_id="visitor-two")


def test_existing_snapshot_is_not_replaced(tmp_path):
    source = tmp_path / "cloud.db"
    with sqlite3.connect(source) as connection:
        connection.execute("CREATE TABLE corpus (value TEXT)")
    snapshot = backup_sqlite(source, tmp_path / "one")
    original = {path.name: path.read_bytes() for path in snapshot.iterdir()}

    with pytest.raises(FileExistsError):
        backup_sqlite(source, snapshot)

    assert {path.name: path.read_bytes() for path in snapshot.iterdir()} == original


def test_invalid_foreign_keys_leave_no_completed_or_partial_snapshot(tmp_path):
    source = tmp_path / "cloud.db"
    with sqlite3.connect(source) as connection:
        connection.executescript(
            "CREATE TABLE parent (id INTEGER PRIMARY KEY);"
            "CREATE TABLE child (parent_id INTEGER REFERENCES parent(id));"
            "INSERT INTO child VALUES (99);"
        )
    before = file_hash(source)
    snapshot = tmp_path / "bad-snapshot"

    with pytest.raises(ValueError, match="foreign-key"):
        backup_sqlite(source, snapshot)

    assert not snapshot.exists()
    assert file_hash(source) == before


def test_invalid_database_does_not_leave_snapshot_or_manifest(tmp_path):
    source = tmp_path / "not-a-database"
    source.write_bytes(b"invalid sqlite")
    before = file_hash(source)
    snapshot = tmp_path / "bad-snapshot"

    with pytest.raises(sqlite3.DatabaseError):
        backup_sqlite(source, snapshot)

    assert not snapshot.exists()
    assert file_hash(source) == before
