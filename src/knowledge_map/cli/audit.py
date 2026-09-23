"""Read saved trails without initializing chat or operational telemetry."""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from knowledge_map.adapters.audit import SQLiteAuditStore, audit_database_path


def add_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "audit", help="Inspect saved Chat Session Audit Trails"
    )
    commands = parser.add_subparsers(dest="audit_action", required=True)
    show = commands.add_parser("show", help="Show one trail's saved stages")
    show.add_argument("session_id")
    show.add_argument("--db", type=Path, default=audit_database_path())


def dispatch(args: argparse.Namespace) -> None:
    try:
        records = SQLiteAuditStore(args.db).read_trail(args.session_id)
    except (OSError, sqlite3.Error, ValueError):
        print("The audit database could not be read.", file=sys.stderr)
        raise SystemExit(1) from None
    if not records:
        print("No saved stages for this audit ID.", file=sys.stderr)
        raise SystemExit(1)
    print(
        json.dumps(
            {
                "session_id": args.session_id,
                "stages": [record.model_dump(mode="json") for record in records],
            },
            indent=2,
            ensure_ascii=False,
        )
    )
