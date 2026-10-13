"""Release data copies must preserve reader content and leave private source data intact."""

import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from deployment_inventory import readonly_sqlite, sha256_file, sqlite_inventory
from export_deployment_corpus import export_corpus


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "source.db"
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.executescript("""
            CREATE TABLE publications(id TEXT PRIMARY KEY, name TEXT, base_url TEXT);
            CREATE TABLE stories(id INTEGER PRIMARY KEY, url TEXT, publication_id TEXT,
                status TEXT, content TEXT);
            CREATE TABLE story_links(story_id INTEGER REFERENCES stories(id), url TEXT, text TEXT);
            CREATE TABLE source_guides(guide_id TEXT PRIMARY KEY, question TEXT, owner_id TEXT);
            CREATE TABLE source_guide_attempts(attempt_id TEXT PRIMARY KEY,
                guide_id TEXT REFERENCES source_guides(guide_id), outcome_json TEXT);
            CREATE TABLE public_daily_admissions(day TEXT PRIMARY KEY, submissions INTEGER NOT NULL);
            INSERT INTO publications VALUES('pub', 'California publication', 'https://example.org');
            INSERT INTO stories VALUES(1, 'https://example.org/article', 'pub', 'COMPLETED', 'Article text');
            INSERT INTO story_links VALUES(1, 'https://example.org/article#section', 'Section link');
            INSERT INTO source_guides VALUES('guide', 'PRIVATE_QUESTION_ONLY', 'PRIVATE_VISITOR_HASH');
            INSERT INTO source_guide_attempts VALUES('attempt', 'guide', 'PRIVATE_RESULT_ONLY');
            INSERT INTO public_daily_admissions VALUES('2026-10-12', 5);
        """)
    return path


def test_export_keeps_reader_content_and_scrubs_private_bytes_only_in_copy(source, tmp_path):
    original_hash = sha256_file(source)
    release = export_corpus(source, tmp_path / "exports", "release-1")
    exported = release / "document_store.db"
    with closing(readonly_sqlite(exported)) as connection:
        assert connection.execute("SELECT name FROM publications").fetchone()[0] == "California publication"
        assert connection.execute("SELECT content FROM stories").fetchone()[0] == "Article text"
        assert connection.execute("SELECT url FROM story_links").fetchone()[0].endswith("#section")
        for name in ("source_guides", "source_guide_attempts", "public_daily_admissions"):
            assert connection.execute(f"SELECT count(*) FROM {name}").fetchone()[0] == 0
        assert "owner_id" in [row[1] for row in connection.execute("PRAGMA table_info(source_guides)")]
    for private_bytes in (b"PRIVATE_QUESTION_ONLY", b"PRIVATE_VISITOR_HASH", b"PRIVATE_RESULT_ONLY"):
        assert private_bytes not in exported.read_bytes()
    assert sha256_file(source) == original_hash
    with closing(readonly_sqlite(source)) as connection:
        assert connection.execute("SELECT question FROM source_guides").fetchone()[0] == "PRIVATE_QUESTION_ONLY"
    manifest = json.loads((release / "manifest.json").read_text())
    assert manifest["source"]["files_unchanged_during_export"] is True
    assert manifest["sqlite"]["sha256"] == sha256_file(exported)
    assert manifest["sqlite"]["preserved_tables"]["stories"]["rows"] == 1
    assert manifest["sqlite"]["removed_private_rows"] == {
        "source_guide_attempts": 1, "source_guides": 1, "public_daily_admissions": 1,
    }
    assert manifest["deployable"] is False
    assert manifest["graph"]["filename"] is None


def test_backup_includes_committed_wal_content(source, tmp_path):
    with closing(sqlite3.connect(source)) as writer:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("INSERT INTO stories VALUES(2, 'wal-story', 'pub', 'COMPLETED', 'WAL only')")
        writer.commit()
        assert Path(str(source) + "-wal").stat().st_size > 0
        release = export_corpus(source, tmp_path / "exports", "wal-release")
        with closing(readonly_sqlite(release / "document_store.db")) as copy:
            assert copy.execute("SELECT content FROM stories WHERE id=2").fetchone()[0] == "WAL only"


def test_existing_release_cannot_be_overwritten(source, tmp_path):
    root = tmp_path / "exports"
    release = export_corpus(source, root, "immutable")
    manifest = (release / "manifest.json").read_bytes()
    with pytest.raises(FileExistsError):
        export_corpus(source, root, "immutable")
    assert (release / "manifest.json").read_bytes() == manifest


def test_unknown_private_table_fails_closed_and_cleans_failed_copy(source, tmp_path):
    with closing(sqlite3.connect(source)) as connection, connection:
        connection.execute("CREATE TABLE new_private_table(secret TEXT)")
        connection.execute("INSERT INTO new_private_table VALUES('secret')")
    before = sha256_file(source)
    with pytest.raises(ValueError, match="Unclassified tables"):
        export_corpus(source, tmp_path / "exports", "unsafe")
    assert not (tmp_path / "exports" / "unsafe").exists()
    assert sha256_file(source) == before


def test_invalid_foreign_keys_block_release(source, tmp_path):
    with closing(sqlite3.connect(source)) as connection, connection:
        connection.execute("INSERT INTO story_links VALUES(999, 'orphan', 'Broken')")
    with pytest.raises(ValueError, match="foreign-key"):
        export_corpus(source, tmp_path / "exports", "broken")
    assert not (tmp_path / "exports" / "broken").exists()


@pytest.mark.parametrize("release", ["../source", "/absolute", "nested/name", "", "."])
def test_release_names_cannot_escape_output_root(source, tmp_path, release):
    with pytest.raises(ValueError, match="directory name"):
        export_corpus(source, tmp_path / "exports", release)


def test_inventory_has_schemas_and_counts_without_private_values(source):
    result = sqlite_inventory(source)
    assert result["tables"]["source_guides"]["rows"] == 1
    assert result["publications"] == [{"name": "California publication", "base_url": "https://example.org"}]
    assert "PRIVATE_" not in json.dumps(result)
    with closing(readonly_sqlite(source)) as connection, pytest.raises(sqlite3.OperationalError, match="readonly"):
        connection.execute("DELETE FROM source_guides")
