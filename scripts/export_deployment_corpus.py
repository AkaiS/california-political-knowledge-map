"""Back up and sanitize a release copy without writing to the source database."""

import argparse
import hashlib
import json
import re
import shutil
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from deployment_inventory import quote_identifier, readonly_sqlite, sha256_file

CORPUS_TABLES = frozenset({
    "stories", "publications", "story_links", "publication_selectors",
    "publication_discovery_state", "selector_proposals", "scraped_html_cache",
})
PRIVATE_TABLES = (
    "source_guide_attempts", "source_guides", "public_daily_admissions",
)


def table_fingerprint(connection: sqlite3.Connection, name: str) -> dict:
    """Hash row contents independent of query order, including binary values."""
    hashes = []
    for row in connection.execute(f"SELECT * FROM {quote_identifier(name)}"):
        values = [{"bytes_hex": value.hex()} if isinstance(value, bytes) else value for value in row]
        encoded = json.dumps(values, ensure_ascii=False, separators=(",", ":")).encode()
        hashes.append(hashlib.sha256(encoded).hexdigest())
    digest = hashlib.sha256("\n".join(sorted(hashes)).encode()).hexdigest()
    return {"rows": len(hashes), "content_sha256": digest}


def source_file_hashes(path: Path) -> dict:
    # WAL belongs to the active source; SQLite's backup API incorporates it.
    return {
        suffix or "main": sha256_file(candidate)
        for suffix in ("", "-wal")
        if (candidate := Path(str(path) + suffix)).is_file()
    }


def export_corpus(source: Path, output_root: Path, release: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", release):
        raise ValueError("Release must be a simple immutable directory name")
    source = source.resolve(strict=True)
    output_root = output_root.resolve()
    destination = output_root / release
    if source == destination / "document_store.db":
        raise ValueError("Export destination must differ from the source")
    output_root.mkdir(parents=True, exist_ok=True)
    destination.mkdir()  # Never replace an existing release.
    try:
        original_hashes = source_file_hashes(source)
        exported = destination / "document_store.db"
        with closing(readonly_sqlite(source)) as original, closing(sqlite3.connect(exported)) as copy:
            original.backup(copy)
            tables = {row[0] for row in copy.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )}
            unknown = tables - CORPUS_TABLES - set(PRIVATE_TABLES)
            if unknown:
                raise ValueError("Unclassified tables require privacy review: " + ", ".join(sorted(unknown)))
            missing = {"stories", "publications", "story_links"} - tables
            if missing:
                raise ValueError("Required reader corpus tables missing: " + ", ".join(sorted(missing)))
            preserved = {name: table_fingerprint(copy, name) for name in sorted(tables & CORPUS_TABLES)}
            removed = {
                name: copy.execute(f"SELECT count(*) FROM {quote_identifier(name)}").fetchone()[0]
                for name in PRIVATE_TABLES if name in tables
            }
            copy.execute("PRAGMA foreign_keys = ON")
            with copy:
                for name in PRIVATE_TABLES:
                    if name in tables:
                        copy.execute(f"DELETE FROM {quote_identifier(name)}")
            # DELETE alone leaves private questions and identities in free pages.
            copy.execute("VACUUM")
            after = {name: table_fingerprint(copy, name) for name in preserved}
            if after != preserved:
                raise ValueError("Sanitization changed reader corpus rows")
            if copy.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("Export failed SQLite integrity verification")
            foreign_key_errors = copy.execute("PRAGMA foreign_key_check").fetchall()
            if foreign_key_errors:
                raise ValueError("Export contains invalid foreign-key references")
            for name in removed:
                if copy.execute(f"SELECT count(*) FROM {quote_identifier(name)}").fetchone()[0]:
                    raise ValueError("Private deployment rows remain")
        final_source_hashes = source_file_hashes(source)
        manifest = {
            "format_version": 1,
            "release": release,
            "created_at": datetime.now(UTC).isoformat(),
            "sqlite": {
                "filename": exported.name,
                "bytes": exported.stat().st_size,
                "sha256": sha256_file(exported),
                "preserved_tables": preserved,
                "removed_private_rows": removed,
                "integrity": "ok",
                "foreign_key_errors": 0,
                "freed_private_pages_removed": True,
            },
            "source": {
                "opened_read_only": True,
                "before_sha256": original_hashes,
                "after_sha256": final_source_hashes,
                "files_unchanged_during_export": original_hashes == final_source_hashes,
            },
            "graph": {
                "filename": None,
                "sha256": None,
                "state": "pending explicitly approved offline dump and disposable recovery rehearsal",
                "neo4j_version": "2026.07.1",
            },
            "deployable": False,
            "remaining": [
                "Pair with same-corpus Neo4j offline dump, embedding checksum and application release",
                "Restore into disposable Neo4j and verify indexes and Story alignment",
                "Verify Publication labels and section links through real HTTP service",
            ],
        }
        (destination / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        return destination
    except Exception:
        # Only remove the newly created export directory, never a previous release.
        shutil.rmtree(destination)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("document_store.db"))
    parser.add_argument("--output-root", type=Path, default=Path(".scratch/deployment-corpus"))
    parser.add_argument("--release", default=datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ"))
    args = parser.parse_args()
    print(export_corpus(args.source, args.output_root, args.release))


if __name__ == "__main__":
    main()
