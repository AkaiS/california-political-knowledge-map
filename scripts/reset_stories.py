#!/usr/bin/env python
"""Send Stories back to UNPROCESSED so the pipeline picks them up again.

Resets the Stories a run leaves stuck -- PROCESSING, claimed and never
released, and FAILED_DLQ, given up on -- so the next run picks them up again.
Asks first, and the prompt defaults to *no*: this rewrites rows in
`document_store.db` and there is no undo, so a bare Return has to be the safe
answer.

Usage:
    uv run scripts/reset_stories.py
    uv run scripts/reset_stories.py --status SYSTEM_ERROR
    uv run scripts/reset_stories.py --dry-run
    uv run scripts/reset_stories.py --yes          # unattended; skips the prompt
"""

import argparse
import sqlite3
import sys

from knowledge_map.adapters.sqlite_db import (
    DEFAULT_DB_PATH,
    RESETTABLE_STORY_STATUSES,
    count_stories_by_status,
    reset_stories_to_unprocessed,
)
from knowledge_map.schemas.pipeline import StoryStatus

_STATUS_NAMES = tuple(status.value for status in StoryStatus)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--status",
        action="append",
        choices=_STATUS_NAMES,
        metavar="STATUS",
        help=(
            "Status to reset; repeatable.  "
            f"Defaults to {' and '.join(RESETTABLE_STORY_STATUSES)}.  "
            f"One of: {', '.join(_STATUS_NAMES)}"
        ),
    )
    parser.add_argument(
        "--db",
        default=DEFAULT_DB_PATH,
        help=f"SQLite database to reset (default: {DEFAULT_DB_PATH})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be reset and change nothing",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip the confirmation prompt.  Required when stdin is not a terminal.",
    )
    return parser.parse_args(argv)


def _confirm(statuses: list[str], counts: dict[str, int], db_path: str) -> bool:
    """Ask whether to go ahead.  Anything but an explicit yes means no."""

    total = sum(counts.values())
    print(f"About to reset {total} Stor{'y' if total == 1 else 'ies'} to UNPROCESSED")
    print(f"  database  {db_path}")
    for status in statuses:
        print(f"  {status:<13} {counts[status]}")
    print("  completed_at is cleared on every row touched.")

    try:
        answer = input("Reset them? [y/N] ")
    except EOFError:
        # A closed stdin is not consent.
        return False
    return answer.strip().lower() in {"y", "yes"}


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    # `dict.fromkeys` rather than `set` so a repeated --status collapses without
    # scrambling the order the statuses are reported in.
    statuses = list(dict.fromkeys(args.status or RESETTABLE_STORY_STATUSES))

    try:
        counts = count_stories_by_status(statuses, db_path=args.db)
    except (sqlite3.Error, OSError) as error:
        print(f"Could not read {args.db}: {error}", file=sys.stderr)
        return 1

    total = sum(counts.values())
    if total == 0:
        print(f"No Stories at {', '.join(statuses)}. Nothing to reset.")
        return 0

    if args.dry_run:
        print(f"Would reset {total} Stor{'y' if total == 1 else 'ies'} in {args.db}:")
        for status in statuses:
            print(f"  {status:<13} {counts[status]}")
        return 0

    if not args.yes:
        if not sys.stdin.isatty():
            print(
                "Refusing to reset without a terminal to confirm at. "
                "Re-run with --yes if this is deliberate.",
                file=sys.stderr,
            )
            return 1
        if not _confirm(statuses, counts, args.db):
            print("Cancelled. Nothing was changed.")
            return 0

    reset = reset_stories_to_unprocessed(statuses, db_path=args.db)
    moved = sum(reset.values())
    print(f"Reset {moved} Stor{'y' if moved == 1 else 'ies'} to UNPROCESSED:")
    for status in statuses:
        print(f"  {status:<13} {reset[status]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
