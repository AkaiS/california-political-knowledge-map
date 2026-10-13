"""Freeze checksums after a compatible graph dump and sanitized SQLite export."""

import argparse
import json
from pathlib import Path

from knowledge_map.cloud_runtime import (
    ARTIFACTS,
    EMBEDDING_SHA256,
    CloudConfigurationError,
    sha256,
    validate_sqlite,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("seed", type=Path)
    parser.add_argument("--corpus-id", required=True)
    parser.add_argument("--application-revision", required=True)
    parser.add_argument("--sqlite-export-manifest", type=Path, required=True)
    args = parser.parse_args()
    seed = args.seed.resolve(strict=True)
    target = seed / "release.json"
    if target.exists():
        raise CloudConfigurationError("An existing release manifest is immutable")
    validate_sqlite(seed / "document_store.db", sanitized=True)
    checksums = {name: sha256(seed / name) for name in ARTIFACTS}
    exported = json.loads(args.sqlite_export_manifest.read_text())
    sqlite_export = exported.get("sqlite", {})
    if (
        sqlite_export.get("filename") != "document_store.db"
        or sqlite_export.get("sha256") != checksums["document_store.db"]
        or not sqlite_export.get("freed_private_pages_removed")
    ):
        raise CloudConfigurationError("SQLite must match its sanitized export manifest")
    if checksums[ARTIFACTS[2]] != EMBEDDING_SHA256:
        raise CloudConfigurationError("Use the frozen EmbeddingGemma artifact")
    with target.open("x") as output:
        json.dump(
            {
                "corpus_id": args.corpus_id,
                "application_revision": args.application_revision,
                "neo4j_version": "2026.07.1",
                "sha256": checksums,
                "sqlite_export": sqlite_export,
            },
            output,
            indent=2,
        )
        output.write("\n")


if __name__ == "__main__":
    main()
