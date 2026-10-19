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
from collections.abc import Callable, Iterable, Sequence
from datetime import datetime
from pathlib import Path
from statistics import fmean
from typing import Any, Literal
from urllib.parse import quote

from pydantic import BaseModel

from .headline import (
    EXECUTION_FAILURE_RATE,
    Aggregation,
    Headline,
    HeadlineRow,
    Role,
    is_failed_outcome,
)
from .rag_review import project_report

BRANCHES = ("full_text", "dense", "structural")
REVIEWER_SCRIPT = (
    Path(__file__).resolve().parents[3] / "scripts" / "review_chat_eval.py"
)
DEFAULT_REVIEWER_PORT = 8766
DIGEST_PREFIX = 12
Baseline = Literal["auto", "none"] | Path


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


class Change(BaseModel, frozen=True):
    """One primary or headline row against the same row of the baseline."""

    metric: str
    aggregation: Aggregation
    value: float | None
    baseline_value: float | None
    baseline_numerator: float | None
    baseline_denominator: float | None
    change: float | None


class Comparison(BaseModel, frozen=True):
    """A report against its baseline: what failed, what caveats, what changed."""

    baseline: str | None = None
    status: Literal[
        "not_requested",
        "no_earlier_run",
        "comparable",
        "comparable_with_caveat",
        "not_comparable",
    ] = "not_requested"
    failed_conditions: tuple[
        Literal[
            "task",
            "data_set_revision",
            "selected_case_ids",
            "headline_version",
            "completed_baseline_with_headline_table",
            "selection_manifest_on_both_sides",
        ],
        ...,
    ] = ()
    dirty_worktree: tuple[Literal["current", "baseline"], ...] = ()
    changes: tuple[Change, ...] = ()

    @classmethod
    def between(
        cls,
        current: ReportDocument,
        current_axis: Axis,
        baseline: ReportDocument,
        baseline_axis: Axis,
    ) -> Comparison:
        """Check every Comparable Run condition; state changes only when all hold."""

        current_summary, baseline_summary = current_axis.summary, baseline_axis.summary
        current_sha = current_summary["provenance"]["data_set_sha256"]
        failed = [
            condition
            for condition, holds in (
                ("task", current_summary["task"] == baseline_summary["task"]),
                (
                    "data_set_revision",
                    current_sha is not None
                    and current_sha
                    == baseline_summary["provenance"]["data_set_sha256"],
                ),
                (
                    "selected_case_ids",
                    set(current_summary["case_ids"])
                    == set(baseline_summary["case_ids"]),
                ),
                (
                    "headline_version",
                    current_axis.headline_version is not None
                    and current_axis.headline_version == baseline_axis.headline_version,
                ),
                (
                    "completed_baseline_with_headline_table",
                    isinstance(baseline_axis.headline, Headline),
                ),
                (
                    "selection_manifest_on_both_sides",
                    _has_selection_manifest(current)
                    and _has_selection_manifest(baseline),
                ),
            )
            if not holds
        ]
        # A commit doesn't record uncommitted changes, so a dirty worktree's
        # system under test is only partly known; the measurement still holds.
        dirty = tuple(
            side
            for side, axis in (("current", current_axis), ("baseline", baseline_axis))
            if axis.summary["provenance"]["dirty"] is True
        )
        if failed:
            status = "not_comparable"
        elif dirty:
            status = "comparable_with_caveat"
        else:
            status = "comparable"
        changes: tuple[Change, ...] = ()
        if not failed and isinstance(current_axis.headline, Headline):
            changes = tuple(
                _change(row, baseline_axis.headline)
                for row in current_axis.headline.rows
                if row.role in (Role.PRIMARY, Role.HEADLINE)
            )
        return cls(
            baseline=str(baseline.path.resolve()),
            status=status,
            failed_conditions=tuple(failed),
            dirty_worktree=dirty,
            changes=changes,
        )


def _has_selection_manifest(document: ReportDocument) -> bool:
    # The report checkpoint records the selected case IDs before any case
    # runs; a report without them can't be shown to match another.
    return isinstance(
        document.content.get("evaluation_run", {}).get("selected_case_ids"), list
    )


def _change(row: HeadlineRow, baseline: Headline) -> Change:
    match = baseline.row(row.metric, row.aggregation)
    baseline_value = None if match is None else match.value
    return Change(
        metric=row.metric,
        aggregation=row.aggregation,
        value=row.value,
        baseline_value=baseline_value,
        baseline_numerator=None if match is None else match.numerator,
        baseline_denominator=None if match is None else match.denominator,
        change=None
        if row.value is None or baseline_value is None
        else row.value - baseline_value,
    )


class Axis(BaseModel, frozen=True):
    """One report's result: its headline or why it has none, and its summary."""

    headline_version: str | None
    headline: Headline | NoHeadline
    summary: dict[str, Any]
    comparison: Comparison = Comparison()

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
            "comparison": self.comparison.model_dump(mode="json"),
        }

    def to_markdown(self) -> str:
        headline, summary = self.headline, self.summary
        counts, provenance = summary["counts"], summary["provenance"]
        changes = self._changes()
        parts = [
            f"## {summary['task']}: {self._result(changes)}",
            (
                f"Population: label quality {provenance['label_quality'] or 'unknown'}, "
                f"selection scope {summary['scope']}; {counts['selected']} selected, "
                f"{counts['scored']} scored, {counts['execution_failures']} failed, "
                f"{counts['unresolved']} unresolved."
            ),
            f"Baseline: {self._baseline()}.",
        ]
        diagnostic: tuple[HeadlineRow, ...] = ()
        if isinstance(headline, NoHeadline):
            parts.append(f"No Headline Metrics: {headline.reason}.")
        else:
            rows = (*headline.by_role(Role.PRIMARY), *headline.by_role(Role.HEADLINE))
            diagnostic = headline.by_role(Role.DIAGNOSTIC)
            parts.append(
                _table(
                    rows,
                    ("baseline value", "change"),
                    lambda row: _change_cells(
                        changes.get((row.metric, row.aggregation))
                    ),
                )
            )
            parts.extend(_unavailable(rows))
        parts.append(f"Provenance: {self._provenance()}.")
        if diagnostic:
            parts.append(
                "\n\n".join(
                    (
                        "<details>\n<summary>Diagnostic rows</summary>",
                        _table(diagnostic),
                        *_unavailable(diagnostic),
                        "</details>",
                    )
                )
            )
        return "\n\n".join(parts) + "\n"

    def _changes(self) -> dict[tuple[str, Aggregation], Change]:
        return {
            (change.metric, change.aggregation): change
            for change in self.comparison.changes
        }

    def _result(self, changes: dict[tuple[str, Aggregation], Change]) -> str:
        headline = self.headline
        if isinstance(headline, NoHeadline):
            return "no Headline Metrics"
        primary = headline.primary
        if primary.value is None:
            # A missing value has no change to report; its reason says why.
            return f"{primary.metric} unavailable ({primary.unavailable_reason})"
        change = changes.get((primary.metric, primary.aggregation))
        against = (
            "no comparable baseline"
            if change is None
            else f"{_number(change.change, signed=True)} against the baseline"
        )
        return f"{primary.metric} {_number(primary.value)} ({against})"

    def _summary_cells(self) -> tuple[str, ...]:
        headline, summary = self.headline, self.summary
        counts = summary["counts"]
        label_quality = summary["provenance"]["label_quality"] or "unknown"
        status = self.comparison.status.replace("_", " ")
        if isinstance(headline, NoHeadline):
            return (
                summary["task"],
                label_quality,
                "-",
                f"no Headline Metrics ({headline.reason})",
                "-",
                f"{counts['scored']}/{counts['selected']}",
                "-",
                status,
            )
        primary = headline.primary
        failures = headline.row(EXECUTION_FAILURE_RATE, Aggregation.RATE)
        change = self._changes().get((primary.metric, primary.aggregation))
        return (
            summary["task"],
            label_quality,
            primary.metric,
            # An Unlabeled Set's primary row says it has no quality metric.
            f"unavailable ({primary.unavailable_reason})"
            if primary.value is None
            else _row_value(primary),
            _change_cells(change)[1],
            f"{primary.scored_cases}/{primary.selected_cases}",
            "-" if failures is None else _row_value(failures),
            status,
        )

    def _baseline(self) -> str:
        comparison = self.comparison
        status = comparison.status.replace("_", " ")
        if comparison.baseline is None:
            return f"none ({status})"
        notes = []
        if comparison.failed_conditions:
            notes.append("failed " + ", ".join(comparison.failed_conditions))
        if comparison.dirty_worktree:
            notes.append(
                "dirty worktree on the "
                + " and ".join(comparison.dirty_worktree)
                + (" sides" if len(comparison.dirty_worktree) > 1 else " side")
            )
        return f"`{comparison.baseline}` ({'; '.join([status, *notes])})"

    def _provenance(self) -> str:
        provenance = self.summary["provenance"]
        dirty = {True: "dirty worktree", False: "clean worktree"}.get(
            provenance["dirty"], "worktree state unknown"
        )
        deployment = provenance["deployment"] or {}
        prompts = provenance["experiment_metadata"].get("prompts") or {}
        sha = provenance["data_set_sha256"]
        trace = self.summary["trace_url"]
        return "; ".join(
            (
                f"commit {provenance['commit'] or 'unknown'} ({dirty})",
                "Model Deployment "
                + (
                    f"{deployment.get('kind')} {deployment.get('model')}"
                    if deployment
                    else "unknown"
                ),
                "prompts "
                + (
                    ", ".join(
                        f"{name} {digest[:DIGEST_PREFIX]}"
                        for name, digest in sorted(prompts.items())
                    )
                    or "none recorded"
                ),
                f"Data Set {sha[:DIGEST_PREFIX] if sha else 'unknown'}",
                f"headline {self.headline_version or 'none'}",
                f"[report]({self.summary['report_path']})",
                f"[trace]({trace})" if trace else "no trace",
            )
        )


def _number(value: float | None, *, signed: bool = False) -> str:
    if value is None:
        return "unavailable"
    return f"{value:+.3f}" if signed else f"{value:.3f}"


def _value(
    aggregation: Aggregation,
    value: float | None,
    numerator: float | None,
    denominator: float | None,
) -> str:
    # A rate alone hides how many cases it rests on; a reader comparing one
    # run with the next needs the count beside it.
    if (
        aggregation not in (Aggregation.RATE, Aggregation.POOLED)
        or numerator is None
        or denominator is None
    ):
        return _number(value)
    return f"{_number(value)} ({_count(numerator)}/{_count(denominator)})"


def _row_value(row: HeadlineRow) -> str:
    return _value(row.aggregation, row.value, row.numerator, row.denominator)


def _count(count: float) -> str:
    return f"{count:.0f}" if count.is_integer() else f"{count:.3f}"


def _change_cells(change: Change | None) -> tuple[str, str]:
    if change is None:
        return ("-", "-")
    return (
        _value(
            change.aggregation,
            change.baseline_value,
            change.baseline_numerator,
            change.baseline_denominator,
        ),
        _number(change.change, signed=True),
    )


def _table(
    rows: Sequence[HeadlineRow],
    extra_columns: tuple[str, ...] = (),
    extra_cells: Callable[[HeadlineRow], tuple[str, ...]] = lambda _: (),
) -> str:
    return _markdown_table(
        ("metric", "value", *extra_columns, "scored / selected", "aggregation"),
        (
            (
                row.metric,
                _row_value(row),
                *extra_cells(row),
                f"{row.scored_cases}/{row.selected_cases}",
                row.aggregation.value,
            )
            for row in rows
        ),
    )


def _markdown_table(columns: Sequence[str], cell_rows: Iterable[Sequence[str]]) -> str:
    return "\n".join(
        (
            "| " + " | ".join(columns) + " |",
            "| " + " | ".join("---" for _ in columns) + " |",
            *("| " + " | ".join(cells) + " |" for cells in cell_rows),
        )
    )


def _unavailable(rows: Sequence[HeadlineRow]) -> list[str]:
    lines = [
        f"- {row.metric} ({row.aggregation.value}) is unavailable: "
        f"{row.unavailable_reason}"
        for row in rows
        if row.value is None
    ]
    return ["\n".join(lines)] if lines else []


class Scorecard(BaseModel, frozen=True):
    """One axis per report, in argument order, and never an overall score."""

    axes: tuple[Axis, ...]

    @classmethod
    def build(
        cls,
        documents: Sequence[ReportDocument],
        baseline: Baseline,
        *,
        reviewer_port: int = DEFAULT_REVIEWER_PORT,
    ) -> Scorecard:
        if not 1 <= reviewer_port <= 65535:
            raise ValueError("Reviewer port must be between 1 and 65535")
        axes = tuple(_axis(document, reviewer_port) for document in documents)
        if baseline == "none":
            return cls(axes=axes)
        if isinstance(baseline, Path):
            baseline_document = ReportDocument.load(baseline)
            baseline_axis = _axis(baseline_document, reviewer_port)

            def compare(document: ReportDocument, axis: Axis) -> Comparison:
                return Comparison.between(
                    document, axis, baseline_document, baseline_axis
                )
        elif baseline == "auto":

            def compare(document: ReportDocument, axis: Axis) -> Comparison:
                return _against_newest_comparable_run(document, axis, reviewer_port)
        else:
            raise ValueError(f"unsupported baseline {baseline!r}")
        return cls(
            axes=tuple(
                axis.model_copy(update={"comparison": compare(document, axis)})
                for document, axis in zip(documents, axes, strict=True)
            )
        )

    def to_json(self) -> dict[str, Any]:
        """The one axis's summary, or every axis's in argument order."""

        if len(self.axes) == 1:
            return self.axes[0].to_json()
        return {"axes": [axis.to_json() for axis in self.axes]}

    def to_markdown(self) -> str:
        """Each axis's one-axis scorecard, in argument order.

        Several axes open with one summary row per axis.
        """

        scorecards = "\n".join(axis.to_markdown() for axis in self.axes)
        if len(self.axes) == 1:
            return scorecards
        summary = _markdown_table(
            (
                "axis",
                "label quality",
                "primary metric",
                "value",
                "change",
                "scored / selected",
                "failure rate",
                "comparison status",
            ),
            (axis._summary_cells() for axis in self.axes),
        )
        return summary + "\n\n" + scorecards

    @property
    def exit_code(self) -> int:
        """Nonzero when any axis is incomplete or has failures or evaluator errors."""

        return 1 if any(axis.failed for axis in self.axes) else 0


def _against_newest_comparable_run(
    document: ReportDocument, axis: Axis, reviewer_port: int
) -> Comparison:
    """Compare against the newest earlier Comparable Run beside ``document``.

    Without one, the newest earlier same-task report's failed conditions say
    why.
    """

    ran_at = _ran_at(document)
    if ran_at is None:
        return Comparison(status="no_earlier_run")
    earlier: list[tuple[datetime, ReportDocument]] = []
    for path in document.path.parent.glob("*.json"):
        try:
            candidate = ReportDocument.load(path)
        except ValueError:
            continue
        when = _ran_at(candidate)
        if (
            candidate.content["task"] == document.content["task"]
            and when is not None
            and when < ran_at
        ):
            earlier.append((when, candidate))
    comparisons = (
        Comparison.between(document, axis, candidate, _axis(candidate, reviewer_port))
        for _, candidate in sorted(earlier, key=lambda pair: pair[0], reverse=True)
    )
    newest = next(comparisons, None)
    if newest is None:
        return Comparison(status="no_earlier_run")
    if newest.status != "not_comparable":
        return newest
    return next(
        (each for each in comparisons if each.status != "not_comparable"), newest
    )


def _ran_at(document: ReportDocument) -> datetime | None:
    try:
        when = datetime.fromisoformat(document.content.get("ran_at"))
    except (TypeError, ValueError):
        return None
    # Every report records an aware UTC time; a naive one can't be ordered
    # against it.
    return when if when.tzinfo is not None else None


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
    summary["counts"]["completed_answers"] = _recorded_count(
        headline, "completed_answer_rate"
    )
    summary["counts"]["declined"] = _recorded_count(headline, "declined_rate")
    return Axis(headline_version=version, headline=headline, summary=summary)


def _recorded_count(headline: Headline | NoHeadline, metric: str) -> int | None:
    if isinstance(headline, NoHeadline):
        return None
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
        outcomes = output.get("branches")
        if outcomes is None:
            answer = output.get("answer") or {}
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
            # A quality measure sees only the selected cases that completed
            # without a recorded failure, so a reader needs that count beside
            # the failed and unresolved ones to know what the values rest on.
            "scored": len(
                {
                    case["name"]
                    for case in cases
                    if case["name"] in expected_set and not is_failed_outcome(case)
                }
            ),
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
