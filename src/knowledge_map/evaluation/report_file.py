"""Write one Evaluation Run's report to a committed JSON file.

Records the commit a run ran at and the model it ran against.  Commit the
report; an uncommitted run did not happen — see ADR 0017.
"""

from __future__ import annotations

import dataclasses
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic_core import to_jsonable_python
from pydantic_evals.reporting import EvaluationReport


def report_path(
    task: str, *, model: str, ran_at: datetime, root: Path | None = None
) -> Path:
    """Name a report file so `ls` sorts one task's runs by commit and date."""
    stamp = ran_at.strftime("%Y%m%dT%H%M%SZ")
    return (root or Path("evals/reports")) / task / f"{stamp}-{_commit()}-{_slug(model)}.json"


def write_report(
    report: EvaluationReport[Any, Any, Any],
    *,
    task: str,
    model: str,
    gold_set_path: Path | str,
    split: str | None = None,
    root: Path | None = None,
) -> Path:
    """Serialize ``report`` with its provenance and return where it landed."""
    ran_at = datetime.now(UTC)
    path = report_path(task, model=model, ran_at=ran_at, root=root)
    path.parent.mkdir(parents=True, exist_ok=True)
    document = {
        "task": task,
        "model": model,
        "commit": _commit(),
        "dirty": _worktree_is_dirty(),
        "gold_set": str(gold_set_path),
        "split": split,
        "ran_at": ran_at.isoformat(),
        "report": to_jsonable_python(dataclasses.asdict(report), fallback=str),
    }
    path.write_text(json.dumps(document, indent=2, sort_keys=True, default=str) + "\n")
    return path


def _commit() -> str:
    """Return the short commit the run executed at, or `nogit`."""
    return _git("rev-parse", "--short", "HEAD") or "nogit"


def _worktree_is_dirty() -> bool:
    """Report whether uncommitted changes make the commit an incomplete record."""
    return bool(_git("status", "--porcelain"))


def _git(*arguments: str) -> str:
    try:
        completed = subprocess.run(
            ("git", *arguments), capture_output=True, text=True, check=True
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""
    return completed.stdout.strip()


def _slug(value: str) -> str:
    return "".join(character if character.isalnum() else "-" for character in value).strip("-")
