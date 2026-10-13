"""Create a consistent recovery snapshot, preserving visitor guides and quotas."""

import argparse
import hashlib
import json
import re
import shutil
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path


def backup_sqlite(source: Path, destination: Path) -> Path:
    """Back up committed WAL data without changing or sanitizing the source."""
    source = source.resolve(strict=True)
    destination = destination.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.mkdir(mode=0o700)  # Never replace an existing private snapshot.
    try:
        database = destination / "document_store.db"
        with (
            closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as original,
            closing(sqlite3.connect(database)) as copy,
        ):
            original.backup(copy, pages=256, sleep=0.05)
            if copy.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise ValueError("Recovery snapshot failed SQLite integrity check")
            if copy.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise ValueError("Recovery snapshot failed SQLite foreign-key check")
        # Close first: WAL-mode copies must have their committed pages in this file.
        with database.open("rb") as stream:
            checksum = hashlib.file_digest(stream, "sha256").hexdigest()
        manifest = {
            "format_version": 1,
            "snapshot": destination.name,
            "created_at": datetime.now(UTC).isoformat(),
            "source_opened_read_only": True,
            "sanitized": False,
            "sqlite": {
                "filename": database.name,
                "bytes": database.stat().st_size,
                "sha256": checksum,
                "integrity": "ok",
                "foreign_key_errors": 0,
            },
        }
        with (destination / "manifest.json").open("x") as output:
            json.dump(manifest, output, indent=2)
            output.write("\n")
        return destination
    except Exception:
        # Only this invocation's new directory is removed; older snapshots survive.
        shutil.rmtree(destination)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument(
        "--snapshot", default=datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    )
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", args.snapshot):
        parser.error("Snapshot must be a simple immutable directory name")
    print(backup_sqlite(args.source, args.output_root / args.snapshot))


if __name__ == "__main__":
    main()
