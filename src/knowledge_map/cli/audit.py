"""Read saved trails without initializing chat or operational telemetry."""

import argparse
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

from knowledge_map.adapters.audit import SQLiteAuditStore, audit_database_path
from knowledge_map.schemas.audit import AuditStageRecord


def _timestamp(value: str) -> datetime:
    try:
        timestamp = datetime.fromisoformat(value)
        if timestamp.tzinfo is not None:
            return timestamp
    except ValueError:
        pass
    raise argparse.ArgumentTypeError("Use an ISO 8601 timestamp with a timezone.")


def _deployment(value: str) -> tuple[str, str]:
    kind, separator, model = value.partition(":")
    if kind not in {"local", "openrouter"} or not separator or not model:
        raise argparse.ArgumentTypeError("Use local:MODEL or openrouter:MODEL.")
    return kind, model


def add_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "audit", help="Inspect saved Chat Session Audit Trails"
    )
    commands = parser.add_subparsers(dest="audit_action", required=True)
    listing = commands.add_parser("list", help="List saved trails by observation time")
    listing.add_argument("--db", type=Path, default=audit_database_path())
    listing.add_argument(
        "--since", type=_timestamp, help="First observation at or after this timestamp"
    )
    listing.add_argument(
        "--until", type=_timestamp, help="First observation at or before this timestamp"
    )
    listing.add_argument(
        "--has-answer",
        choices=("yes", "no"),
        help="Whether a Retrieval Answer record was saved",
    )
    listing.add_argument("--code-revision", help="Exact saved code commit")
    listing.add_argument(
        "--model-deployment",
        type=_deployment,
        metavar="KIND:MODEL",
        help="Exact saved deployment kind and model in any role",
    )
    listing.add_argument(
        "--failed-stage", help="Exact saved stage name with a failed result"
    )
    show = commands.add_parser("show", help="Show one trail's saved stages")
    show.add_argument("session_id")
    show.add_argument("--db", type=Path, default=audit_database_path())
    export = commands.add_parser(
        "export", help="Export one trail's saved stages as JSON to stdout"
    )
    export.add_argument("session_id")
    export.add_argument("--db", type=Path, default=audit_database_path())


def _matches(records: tuple[AuditStageRecord, ...], args: argparse.Namespace) -> bool:
    observed_at = records[0].started_at
    if args.code_revision is not None:
        codes = (
            record.metadata.get("code")
            for record in records
            if record.name == "session_start"
        )
        if not any(
            isinstance(code, dict) and code.get("commit") == args.code_revision
            for code in codes
        ):
            return False
    if args.model_deployment is not None:
        deployments = (
            record.metadata.get("deployments")
            for record in records
            if record.name == "session_start"
        )
        if not any(
            isinstance(deployment, dict)
            and (deployment.get("kind"), deployment.get("model"))
            == args.model_deployment
            for roles in deployments
            if isinstance(roles, dict)
            for deployment in roles.values()
        ):
            return False
    return not (
        (args.since is not None and observed_at < args.since)
        or (args.until is not None and observed_at > args.until)
        or (
            args.has_answer is not None
            and any(record.name == "retrieval_answer" for record in records)
            != (args.has_answer == "yes")
        )
        or (
            args.failed_stage is not None
            and not any(
                record.name == args.failed_stage and record.status == "failed"
                for record in records
            )
        )
    )


def dispatch(args: argparse.Namespace) -> None:
    try:
        store = SQLiteAuditStore(args.db)
        if args.audit_action == "list":
            trails = store.read_trails()
            result = {
                "sessions": [
                    {
                        "session_id": session_id,
                        "observed_at": records[0].model_dump(mode="json")["started_at"],
                        "has_retrieval_answer": any(
                            record.name == "retrieval_answer" for record in records
                        ),
                    }
                    for session_id, records in trails.items()
                    if _matches(records, args)
                ]
            }
        else:
            records = store.read_trail(args.session_id)
            if not records:
                print("No saved stages for this audit ID.", file=sys.stderr)
                raise SystemExit(1)
            result = {
                "session_id": args.session_id,
                "stages": [record.model_dump(mode="json") for record in records],
            }
    except (OSError, sqlite3.Error, ValueError):
        print("The audit database could not be read.", file=sys.stderr)
        raise SystemExit(1) from None
    print(
        json.dumps(
            result,
            indent=2,
            ensure_ascii=False,
        )
    )
