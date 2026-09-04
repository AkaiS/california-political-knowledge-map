"""Write one Evaluation Run's report to a committed JSON file.

Records the commit, Model Deployment, and model a run used.  Commit the
report; an uncommitted run did not happen — see ADR 0017.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from pydantic_core import to_jsonable_python
from pydantic_evals.reporting import EvaluationReport

from knowledge_map.schemas import DeploymentKind, ModelDeployment
from knowledge_map.utils.telemetry import project_url

from .data_set import LabelQuality


def trace_url(report: EvaluationReport[Any, Any, Any]) -> str | None:
    """Address the trace this run left in Logfire.

    A report already carries the trace id, which is unusable on its own: the
    reader needs the project it belongs to.  Returns ``None`` when the run was
    not attached to a known project, rather than inventing a dead link.
    """

    trace_id = getattr(report, "trace_id", None)
    project = project_url()
    # An all-zero id is OpenTelemetry's way of saying nothing recorded the run,
    # which is the one case a link must not paper over.
    if not trace_id or not project or not trace_id.strip("0"):
        return None
    return f"{project}?q=" + quote(f"trace_id='{trace_id}'")


def report_path(
    task: str,
    *,
    deployment: ModelDeployment | None = None,
    model: str | None = None,
    ran_at: datetime,
    root: Path | None = None,
) -> Path:
    """Name a report file so deployment-specific runs cannot collide."""
    stamp = ran_at.strftime("%Y%m%dT%H%M%SZ")
    selected = _deployment_for_report(deployment, model)
    if deployment is None:
        # Keep the old string-only helper's filename stable for callers that
        # still create historical-style reports.
        filename_slug = _slug(selected.model)
    else:
        filename_slug = _deployment_slug(selected)
    return (root or Path("evals/reports")) / task / f"{stamp}-{run_commit()}-{filename_slug}.json"


def write_report(
    report: EvaluationReport[Any, Any, Any],
    *,
    task: str,
    deployment: ModelDeployment | None = None,
    model: str | None = None,
    data_set_path: Path | str,
    label_quality: LabelQuality,
    split: str | None = None,
    root: Path | None = None,
) -> Path:
    """Serialize ``report`` with its provenance and return where it landed."""
    selected = _deployment_for_report(deployment, model)
    ran_at = datetime.now(UTC)
    path = report_path(
        task,
        deployment=deployment,
        model=model,
        ran_at=ran_at,
        root=root,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized_report = dataclasses.asdict(report)
    document = {
        "task": task,
        "trace_url": trace_url(report),
        "model": selected.model,
        "deployment": selected.model_dump(mode="json"),
        "commit": run_commit(),
        "dirty": _worktree_is_dirty(),
        "data_set": str(data_set_path),
        # Recorded beside the path rather than left to be inferred from it: a
        # score against a model's labels and a score against a person's are
        # not the same measurement, and a reader of an old report has only
        # what the report says.
        "label_quality": label_quality.value,
        "split": split,
        "ran_at": ran_at.isoformat(),
        "report": to_jsonable_python(serialized_report, fallback=str),
    }
    path.write_text(json.dumps(document, indent=2, sort_keys=True, default=str) + "\n")
    return path


def _deployment_for_report(
    deployment: ModelDeployment | None,
    model: str | None,
) -> ModelDeployment:
    if deployment is None:
        if model is None:
            raise TypeError("report provenance requires deployment or model")
        return ModelDeployment(kind=DeploymentKind.LOCAL, model=model)
    if model is not None and model != deployment.model:
        raise ValueError("model must match deployment.model when both are provided")
    return deployment


def _deployment_slug(deployment: ModelDeployment) -> str:
    """Keep a readable slug while preserving the complete identity's uniqueness."""
    readable = _slug(f"{deployment.kind.value}-{deployment.model}")
    readable = readable[:80].rstrip("-") or deployment.kind.value
    identity_digest = hashlib.sha256(
        deployment.model_dump_json().encode("utf-8")
    ).hexdigest()[:12]
    return f"{readable}-{identity_digest}"


def run_commit() -> str:
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
