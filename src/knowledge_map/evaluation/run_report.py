"""Read saved Evaluation Reports into scorecards (ADR 0024, ADR 0026).

The one reader of saved reports: it classifies each report, accounts for its
population, and renders the result.  A report's run-level result comes only
from its frozen headline table; everything else here is the population and
diagnostic output that explains it.
"""

from __future__ import annotations

import json
import shlex
from collections import Counter, defaultdict
from collections.abc import Sequence
from pathlib import Path
from statistics import fmean
from typing import Any, Literal
from urllib.parse import quote

from pydantic import BaseModel

from .headline import Aggregation, Headline, is_failed_outcome
from .rag_review import project_report

BRANCHES = ("full_text", "dense", "structural")
REVIEWER_SCRIPT = (
    Path(__file__).resolve().parents[3] / "scripts" / "review_chat_eval.py"
)
DEFAULT_REVIEWER_PORT = 8766


class NoHeadline(BaseModel, frozen=True):
    """Why a report carries no Headline Metrics."""

    reason: Literal[
        "predates_headline_metrics", "incomplete_run", "headline_evaluator_failed"
    ]


class ReportDocument:
    """One saved Evaluation Report, in any historical shape."""

    def __init__(self, path: Path, content: dict[str, Any]) -> None:
        self.path = path
        self.content = content

    @classmethod
    def load(cls, path: Path) -> ReportDocument:
        """Read ``path``; raise when it is not a readable Evaluation Report."""

        content = json.loads(Path(path).read_text())
        if (
            not isinstance(content, dict)
            or not isinstance(content.get("task"), str)
            or not isinstance(content.get("report"), dict)
        ):
            raise ValueError(f"{path} is not an Evaluation Report")  # noqa: TRY004 -- callers report unreadable files as one ValueError
        return cls(Path(path), content)


class Axis(BaseModel, frozen=True):
    """One report's result: its headline or why it has none, and its summary."""

    headline_version: str | None
    headline: Headline | NoHeadline
    summary: dict[str, Any]

    @property
    def failed(self) -> bool:
        counts = self.summary["counts"]
        return bool(
            self.summary["status"] not in ("completed", "historical_selection_unknown")
            or counts["execution_failures"]
            or counts["evaluator_errors"]
            or isinstance(self.headline, NoHeadline)
            and self.headline.reason != "predates_headline_metrics"
        )

    def to_json(self) -> dict[str, Any]:
        headline = self.headline
        return {
            **self.summary,
            "headline": {
                "version": self.headline_version,
                "no_headline_reason": headline.reason
                if isinstance(headline, NoHeadline)
                else None,
                "rows": []
                if isinstance(headline, NoHeadline)
                else [row.model_dump(mode="json") for row in headline.rows],
            },
            "comparison": {"baseline": None, "status": "not_requested"},
        }


class Scorecard(BaseModel, frozen=True):
    """One axis per report, in argument order, and never an overall score."""

    axes: tuple[Axis, ...]

    @classmethod
    def build(
        cls,
        documents: Sequence[ReportDocument],
        baseline: Literal["none"],
        *,
        reviewer_port: int = DEFAULT_REVIEWER_PORT,
    ) -> Scorecard:
        if baseline != "none":
            raise ValueError(f"unsupported baseline {baseline!r}")
        if not 1 <= reviewer_port <= 65535:
            raise ValueError("Reviewer port must be between 1 and 65535")
        return cls(axes=tuple(_axis(document, reviewer_port) for document in documents))

    def to_json(self) -> dict[str, Any]:
        """The one axis's summary, or every axis's in argument order."""

        if len(self.axes) == 1:
            return self.axes[0].to_json()
        return {"axes": [axis.to_json() for axis in self.axes]}

    @property
    def exit_code(self) -> int:
        """Nonzero when any axis is incomplete or has failures or evaluator errors."""

        return 1 if any(axis.failed for axis in self.axes) else 0


def _axis(document: ReportDocument, reviewer_port: int) -> Axis:
    content = document.content
    summary = _summary(document.path, content, reviewer_port=reviewer_port)
    version = summary["provenance"]["headline_version"]
    headline: Headline | NoHeadline
    if not version:
        headline = NoHeadline(reason="predates_headline_metrics")
    elif summary["status"] != "completed":
        headline = NoHeadline(reason="incomplete_run")
    else:
        headline = Headline.from_analyses(
            content["report"].get("analyses") or []
        ) or NoHeadline(reason="headline_evaluator_failed")
    # The task's headline evaluator owns the completed-answer and decline
    # rules; a report without its table has no such counts.
    if isinstance(headline, Headline):
        summary["counts"]["completed_answers"] = _recorded_count(
            headline, "completed_answer_rate"
        )
        summary["counts"]["declined"] = _recorded_count(headline, "declined_rate")
    return Axis(headline_version=version, headline=headline, summary=summary)


def _recorded_count(headline: Headline, metric: str) -> int | None:
    row = headline.row(metric, Aggregation.RATE)
    return None if row is None or row.numerator is None else int(row.numerator)


def _metric_names(document: dict[str, Any], selected: list[dict]) -> set[str]:
    names = {
        name
        for case in document["report"].get("cases", [])
        for name in case.get("scores", {})
    }
    if document.get("task") == "retrieval":
        from knowledge_map.evaluation.tasks.retrieval import (
            RetrievalExpectation,
            retrieval_scores,
        )

        expected = next(
            (
                case.get("expected_output")
                for case in selected
                if case.get("expected_output")
            ),
            None,
        )
        if expected:
            labels = RetrievalExpectation.model_validate(expected)
            for branch in (*BRANCHES, "fused"):
                names.update(
                    retrieval_scores((), labels, prefix=branch, ks=(1, 5, 10, 50))
                )
            names.update(("context_recall", "context_complete_evidence"))
        for branch in (*BRANCHES, "fused"):
            names.update(f"{branch}_ndcg_at_{k}" for k in (1, 5, 10, 50))
    return names


def _summary(
    path: Path,
    document: dict[str, Any],
    *,
    reviewer_port: int,
) -> dict[str, Any]:
    """Keep missing measurements visible instead of shrinking their populations."""
    report = document["report"]
    run = document.get("evaluation_run", {})
    cases = report.get("cases", [])
    failures = report.get("failures", [])
    selected = run.get("selected_cases", [])
    recorded_ids = run.get("selected_case_ids")
    experiment = (
        document.get("experiment_metadata") or report.get("experiment_metadata") or {}
    )
    selection = experiment.get("selection", {})
    # A planned run records the population it asked for; the report's own
    # manifest and outcomes must match it.
    expected_ids = selection.get("case_ids")
    selected_ids = list(expected_ids) if expected_ids is not None else recorded_ids
    if selected_ids is None:
        # Historical reports have no selection manifest; the reported cases
        # are known outcomes, not evidence that the entire file was selected.
        selected_ids = [case["name"] for case in cases + failures]
    outcomes = cases + failures
    counts = Counter(case["name"] for case in outcomes)
    expected_set = set(selected_ids)
    extra = sorted(set(counts) - expected_set)
    duplicate = sorted(name for name, count in counts.items() if count != 1)
    mismatch = (
        recorded_ids is not None
        and expected_ids is not None
        and set(recorded_ids) != expected_set
    )
    unresolved = [case_id for case_id in selected_ids if case_id not in counts]
    stage_failures: Counter[str] = Counter()
    branches: dict[str, Counter] = {name: Counter() for name in BRANCHES}
    for case in cases:
        output = case.get("output")
        output = output if isinstance(output, dict) else {}
        if is_failed_outcome(case):
            failure = output.get("failure")
            stage_failures[
                failure.get("stage", "unknown")
                if isinstance(failure, dict)
                else f"task:{output.get('failure_type')}"
            ] += 1
        answer = output.get("answer") or {}
        outcomes = output.get("branches")
        if outcomes is None:
            evidence = (
                answer.get("evidence")
                or output.get("retrieval")
                or output.get("result")
                or {}
            )
            outcomes = evidence.get("execution", {}).get("outcomes", [])
        for branch in outcomes:
            if branch.get("branch") in branches:
                branches[branch["branch"]][branch.get("status", "unknown")] += 1
    if failures:
        stage_failures["framework"] = len(failures)
    metric_values: dict[str, list[float]] = defaultdict(list)
    metric_reasons: dict[str, set[str]] = defaultdict(set)
    for case in cases:
        for name, score in case.get("scores", {}).items():
            value = score.get("value") if isinstance(score, dict) else score
            if isinstance(value, (float, int)):
                metric_values[name].append(float(value))
            elif isinstance(score, dict) and score.get("reason"):
                metric_reasons[name].add(score["reason"])
    metrics = {}
    for name in sorted(_metric_names(document, selected or cases)):
        values = metric_values[name]
        reason = None
        if not values:
            if "ndcg" in name:
                reason = "NDCG is not computed by the established evaluator; the RAG references have no relevance grades."
            elif document.get("label_quality") == "unlabeled":
                reason = "This Data Set has no reference judgments."
            else:
                reason = (
                    "; ".join(sorted(metric_reasons[name]))
                    or "No selected case recorded this measurement; inspect failures and evaluator errors."
                )
        metrics[name] = {
            "mean": fmean(values) if values else None,
            "scored_cases": len(values),
            "selected_cases": len(selected_ids),
            "missing_cases": max(0, len(selected_ids) - len(values)),
            "inclusion_policy": "Unweighted mean of recorded numeric case scores. Unscored failures and unresolved cases are missing, never silently counted as successes or zero.",
            "unavailable_reason": reason,
        }
    if document["task"] in ("retrieval", "chat"):
        projection = project_report(document)
        for row in projection["metrics"]:
            name = row["score"]
            existing = metrics.get(name, {})
            metrics[name] = {
                **existing,
                "mean": row["value"],
                "scored_cases": row["scored_cases"],
                "applicable_cases": row["applicable_cases"],
                "selected_cases": len(selected_ids),
                "missing_cases": max(0, len(selected_ids) - row["scored_cases"]),
                "inclusion_policy": "Existing RAG reviewer measurement rules; the headline table's per-case mean, which leaves out failed cases, where the table holds the measurement, otherwise the unweighted mean of recorded or exactly replayed case scores. Unresolved measurements remain missing.",
                "unavailable_reason": row["reason"] if row["value"] is None else None,
            }
    integrity_errors = {
        "unexpected_case_ids": extra,
        "duplicate_case_ids": duplicate,
        "selection_manifest_mismatch": mismatch,
    }
    status = run.get("status", "historical_selection_unknown")
    if extra or duplicate or mismatch or unresolved:
        status = "incomplete"
    started = run.get("started_case_ids", [])
    assertions = {}
    assertion_names = {name for case in cases for name in case.get("assertions", {})}
    for name in sorted(assertion_names):
        values = [
            case["assertions"][name]["value"]
            for case in cases
            if isinstance(case.get("assertions", {}).get(name), dict)
            and isinstance(case["assertions"][name].get("value"), bool)
        ]
        assertions[name] = {
            "passed": sum(values),
            "failed": len(values) - sum(values),
            "scored_cases": len(values),
            "selected_cases": len(selected_ids),
            "missing_cases": max(0, len(selected_ids) - len(values)),
            "pass_rate": fmean(values) if values else None,
            "inclusion_policy": "Recorded boolean evaluator assertions only; missing, failed execution, and unresolved measurements remain explicit.",
        }
    reports_dir = (
        path.resolve().parent.parent if path.parent.name == document["task"] else None
    )
    reviewable = document["task"] in ("retrieval", "chat") and reports_dir is not None
    reviewer_command = (
        shlex.join(
            [
                "uv",
                "run",
                str(REVIEWER_SCRIPT),
                "--mode",
                "rag",
                "--reports-dir",
                str(reports_dir),
                "--port",
                str(reviewer_port),
            ]
        )
        if reviewable
        else None
    )
    summary = {
        "task": document["task"],
        "scope": selection.get("scope", "unknown"),
        "status": status,
        "recorded_status": run.get("status"),
        "interruption_reason": run.get("interruption_reason"),
        "counts": {
            "selected": len(selected_ids),
            "attempted": len(set(started) | set(counts)),
            "terminal": len(expected_set & set(counts)),
            "completed_answers": None,
            "declined": None,
            "execution_failures": sum(stage_failures.values()),
            "unresolved": len(unresolved),
            "evaluator_errors": sum(len(c.get("evaluator_failures", [])) for c in cases)
            + len(report.get("report_evaluator_failures", [])),
        },
        "failures_by_stage": dict(sorted(stage_failures.items())),
        "unresolved_case_ids": unresolved,
        "integrity": integrity_errors,
        "case_ids": selected_ids,
        "branch_completion": {
            name: {
                **dict(sorted(count.items())),
                "selected_cases": len(selected_ids),
                "unrecorded": len(selected_ids) - sum(count.values()),
                "inclusion_policy": "Recorded branch outcomes / selected cases; declines and earlier failures have unrecorded branches.",
            }
            for name, count in branches.items()
        }
        if document["task"] in ("retrieval", "chat")
        else {},
        "metrics": metrics,
        "assertions": assertions,
        "metric_population_note": "Scores use the existing evaluator's reference and slot denominators; this summary reports the case population used in each mean.",
        "metrics_unavailable_reason": "This Data Set has no reference judgments."
        if all(metric["mean"] is None for metric in metrics.values())
        and document.get("label_quality") == "unlabeled"
        else None,
        "provenance": {
            key: document.get(key)
            for key in (
                "data_set",
                "data_set_sha256",
                "deployment",
                "commit",
                "dirty",
                "label_quality",
                "ran_at",
            )
        }
        | {
            "headline_version": experiment.get("headline_version"),
            "experiment_metadata": experiment,
            "retrieval_settings": document.get("retrieval_report", {}).get(
                "configurations"
            ),
        },
        "report_path": str(path.resolve()),
        "reviewer_url": f"http://127.0.0.1:{reviewer_port}/runs/{quote(document['task'] + '--' + path.stem)}"
        if reviewable
        else None,
        "reviewer_command": reviewer_command,
        "reviewer_reports_dir": str(reports_dir) if reviewable else None,
        "reviewer_status": "unverified; run the reviewer command or verify the existing server serves this exact reports directory"
        if reviewable
        else "unavailable; reviewer supports chat/retrieval reports in TASK/*.json layout",
        "trace_url": document.get("trace_url"),
    }
    return summary
