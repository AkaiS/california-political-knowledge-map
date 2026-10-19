"""A scorecard compares a report against an explicit or automatic baseline.

Every test saves Evaluation Reports through an engine run, varies a saved
copy's metadata where a condition needs it, builds a ``Scorecard`` from
``ReportDocument.load`` and reads only its JSON and exit code.
"""

from __future__ import annotations

import json

import pytest
from engine_runs import run_task
from relevance_runs import CONFUSION_CASES, IRRELEVANT, run_relevance

from knowledge_map.evaluation import LabelQuality
from knowledge_map.evaluation.run_report import ReportDocument, Scorecard
from knowledge_map.evaluation.tasks.extraction import (
    ExtractionExpectation,
    ExtractionInput,
    ExtractionOutput,
)


@pytest.fixture(autouse=True)
def disable_telemetry(monkeypatch):
    monkeypatch.setattr("knowledge_map.evaluation.engine.setup_telemetry", lambda: None)


def with_fp_output(output):
    """The confusion cases with the "fp" case's output replaced by ``output``."""

    return [
        (case_id, expected, output(expected) if case_id == "fp" else recorded)
        for case_id, expected, recorded in CONFUSION_CASES
    ]


# The baseline run classifies "fp" correctly: 2 TP, 0 FP, 1 FN, 2 TN.
BETTER_CASES = with_fp_output(lambda expected: expected)


def varied(path, **fields):
    """Save ``path`` again with the given top-level report fields overwritten."""

    document = json.loads(path.read_text())
    document.update(fields)
    path.write_text(json.dumps(document))
    return path


def run(directory, cases=CONFUSION_CASES, **fields):
    """A saved relevance run; its worktree is clean unless ``fields`` says so.

    The report checkpoint records this checkout's real worktree state, so each
    run pins it.
    """

    return varied(run_relevance(directory, cases), **{"dirty": False, **fields})


def compared(current, baseline):
    return Scorecard.build([ReportDocument.load(current)], baseline=baseline).to_json()[
        "comparison"
    ]


def test_comparable_baseline_states_each_primary_and_headline_change(tmp_path):
    baseline = run(tmp_path / "baseline", BETTER_CASES)
    current = run(tmp_path / "current")

    comparison = compared(current, baseline)

    assert comparison["baseline"] == str(baseline.resolve())
    assert comparison["status"] == "comparable"
    assert comparison["failed_conditions"] == []
    assert comparison["dirty_worktree"] == []
    changes = {change["metric"]: change for change in comparison["changes"]}
    assert changes["relevant_f1"] == {
        "metric": "relevant_f1",
        "aggregation": "pooled",
        "value": pytest.approx(2 / 3),
        "baseline_value": pytest.approx(0.8),
        "baseline_numerator": 4,
        "baseline_denominator": 5,
        "change": pytest.approx(2 / 3 - 0.8),
    }
    assert changes["relevant_precision"]["change"] == pytest.approx(2 / 3 - 1)
    assert changes["accuracy"]["change"] == pytest.approx(3 / 5 - 4 / 5)
    assert changes["false_positives"]["change"] == pytest.approx(1 / 5)
    assert changes["execution_failure_rate"]["change"] == 0
    assert comparison["changes"][0]["metric"] == "relevant_f1"
    assert len(changes) == 9


def without_selection_manifest(path):
    document = json.loads(path.read_text())
    del document["evaluation_run"]["selected_case_ids"]
    path.write_text(json.dumps(document))
    return path


INTERRUPTED_AT_FP = with_fp_output(lambda _: KeyboardInterrupt("operator"))
UNREADABLE_FP = with_fp_output(lambda _: None)


@pytest.mark.parametrize(
    ("make_baseline", "make_current", "condition"),
    [
        (
            lambda d: run(d, task="coreference"),
            lambda d: run(d),
            "task",
        ),
        (
            lambda d: run(d, data_set_sha256="0" * 64),
            lambda d: run(d),
            "data_set_revision",
        ),
        (
            lambda d: run(d, CONFUSION_CASES[:4]),
            lambda d: run(d),
            "selected_case_ids",
        ),
        (
            lambda d: run(d, experiment_metadata={"headline_version": "relevance-v0"}),
            lambda d: run(d),
            "headline_version",
        ),
        (
            lambda d: run(d, INTERRUPTED_AT_FP),
            lambda d: run(d),
            "completed_baseline_with_headline_table",
        ),
        (
            lambda d: run(d, UNREADABLE_FP),
            lambda d: run(d),
            "completed_baseline_with_headline_table",
        ),
        (
            lambda d: without_selection_manifest(run(d)),
            lambda d: run(d),
            "selection_manifest_on_both_sides",
        ),
        (
            lambda d: run(d),
            lambda d: without_selection_manifest(run(d)),
            "selection_manifest_on_both_sides",
        ),
    ],
    ids=[
        "task",
        "data-set-revision",
        "selected-case-ids",
        "headline-version",
        "interrupted-baseline",
        "baseline-without-table",
        "baseline-without-manifest",
        "current-without-manifest",
    ],
)
def test_explicit_baseline_failing_one_condition_is_not_comparable_and_has_no_changes(
    tmp_path, make_baseline, make_current, condition
):
    baseline = make_baseline(tmp_path / "baseline")
    current = make_current(tmp_path / "current")

    card = Scorecard.build([ReportDocument.load(current)], baseline=baseline)
    comparison = card.to_json()["comparison"]

    assert comparison["baseline"] == str(baseline.resolve())
    assert comparison["status"] == "not_comparable"
    assert comparison["failed_conditions"] == [condition]
    assert comparison["changes"] == []
    assert card.exit_code == 0


def test_every_failed_condition_is_listed(tmp_path):
    baseline = without_selection_manifest(
        run(
            tmp_path / "baseline",
            INTERRUPTED_AT_FP[:4],
            task="coreference",
            data_set_sha256="0" * 64,
            experiment_metadata={"headline_version": "relevance-v0"},
            dirty=True,
        )
    )

    comparison = compared(run(tmp_path / "current"), baseline)

    assert comparison["status"] == "not_comparable"
    assert comparison["failed_conditions"] == [
        "task",
        "data_set_revision",
        "selected_case_ids",
        "headline_version",
        "completed_baseline_with_headline_table",
        "selection_manifest_on_both_sides",
    ]
    assert comparison["dirty_worktree"] == ["baseline"]
    assert comparison["changes"] == []


def test_incomplete_current_run_against_a_comparable_run_has_no_changes(tmp_path):
    # A Comparable Run is a property of the baseline; the current run's own
    # incompleteness is reported by its population and exit code.
    baseline = run(tmp_path / "baseline")
    current = run(tmp_path / "current", INTERRUPTED_AT_FP)

    card = Scorecard.build([ReportDocument.load(current)], baseline=baseline)
    summary = card.to_json()

    assert summary["status"] == "incomplete"
    assert summary["comparison"]["status"] == "comparable"
    assert summary["comparison"]["changes"] == []
    assert card.exit_code == 1


def test_system_under_test_may_differ_between_comparable_runs(tmp_path):
    baseline = run(
        tmp_path / "baseline",
        BETTER_CASES,
        commit="0000000",
        deployment={"kind": "openrouter", "model": "other/model"},
        model="other/model",
        experiment_metadata={
            "headline_version": "relevance-v1",
            "prompts": {"relevance": "1" * 64},
        },
    )
    current = run(
        tmp_path / "current",
        experiment_metadata={
            "headline_version": "relevance-v1",
            "prompts": {"relevance": "2" * 64},
        },
    )

    comparison = compared(current, baseline)

    assert comparison["status"] == "comparable"
    assert comparison["failed_conditions"] == []
    assert comparison["changes"][0]["change"] == pytest.approx(2 / 3 - 0.8)


@pytest.mark.parametrize(
    ("current_dirty", "baseline_dirty", "named"),
    [
        (True, False, ["current"]),
        (False, True, ["baseline"]),
        (True, True, ["current", "baseline"]),
    ],
)
def test_dirty_worktree_is_a_caveat_that_names_its_side(
    tmp_path, current_dirty, baseline_dirty, named
):
    baseline = run(tmp_path / "baseline", BETTER_CASES, dirty=baseline_dirty)
    current = run(tmp_path / "current", dirty=current_dirty)

    comparison = compared(current, baseline)

    assert comparison["status"] == "comparable_with_caveat"
    assert comparison["failed_conditions"] == []
    assert comparison["dirty_worktree"] == named
    assert comparison["changes"][0]["change"] == pytest.approx(2 / 3 - 0.8)


# Nothing predicted RELEVANT, so RELEVANT precision has no denominator.
NOTHING_RELEVANT = [
    (case_id, expected, IRRELEVANT) for case_id, expected, _ in CONFUSION_CASES
]


@pytest.mark.parametrize(
    ("baseline_cases", "current_cases"),
    [(NOTHING_RELEVANT, CONFUSION_CASES), (CONFUSION_CASES, NOTHING_RELEVANT)],
    ids=["baseline-null", "current-null"],
)
def test_change_is_null_when_either_value_is_null(
    tmp_path, baseline_cases, current_cases
):
    baseline = run(tmp_path / "baseline", baseline_cases)
    current = run(tmp_path / "current", current_cases)

    changes = {
        change["metric"]: change for change in compared(current, baseline)["changes"]
    }

    precision = changes["relevant_precision"]
    assert None in (precision["value"], precision["baseline_value"])
    assert precision["value"] != precision["baseline_value"]
    assert precision["change"] is None
    assert changes["accuracy"]["change"] == pytest.approx(
        0.6 - 0.4 if current_cases is CONFUSION_CASES else 0.4 - 0.6
    )


def test_diagnostic_rows_have_no_change(tmp_path):
    def extraction_run(directory):
        empty = ExtractionOutput(nodes=[], relationships=[])
        path = run_task(
            directory,
            "extraction",
            [("chunk", ExtractionExpectation(nodes=[], relationships=[]), empty)],
            task_input=lambda case_id: ExtractionInput(
                url=case_id, title=case_id, chunk_index=0, text=case_id
            ),
            label_quality=LabelQuality.SILVER,
        )
        return varied(path, dirty=False)

    baseline = extraction_run(tmp_path / "baseline")
    current = extraction_run(tmp_path / "current")

    summary = Scorecard.build(
        [ReportDocument.load(current)], baseline=baseline
    ).to_json()

    assert summary["comparison"]["status"] == "comparable"
    rows = summary["headline"]["rows"]
    assert {row["role"] for row in rows} == {"primary", "headline", "diagnostic"}
    assert [
        (change["metric"], change["aggregation"])
        for change in summary["comparison"]["changes"]
    ] == [
        (row["metric"], row["aggregation"])
        for row in rows
        if row["role"] != "diagnostic"
    ]


def on_day(directory, day, cases=CONFUSION_CASES, **fields):
    """A saved relevance run in ``directory`` that ran on October ``day``."""

    return run(directory, cases, ran_at=f"2026-10-{day:02d}T12:00:00+00:00", **fields)


def automatic(current):
    return compared(current, "auto")


def test_auto_prefers_a_newer_dirty_comparable_run_over_an_older_clean_one(
    tmp_path,
):
    on_day(tmp_path, 1, BETTER_CASES)
    newer_dirty = on_day(tmp_path, 2, NOTHING_RELEVANT, dirty=True)
    current = on_day(tmp_path, 3)

    comparison = automatic(current)

    assert comparison["baseline"] == str(newer_dirty.resolve())
    assert comparison["status"] == "comparable_with_caveat"
    assert comparison["dirty_worktree"] == ["baseline"]
    assert comparison["changes"][0]["baseline_value"] == 0


def test_auto_never_chooses_a_later_report(tmp_path):
    earlier = on_day(tmp_path, 1, BETTER_CASES)
    current = on_day(tmp_path, 2)
    on_day(tmp_path, 3)

    comparison = automatic(current)

    assert comparison["baseline"] == str(earlier.resolve())
    assert comparison["status"] == "comparable"


def test_auto_skips_a_newer_run_that_is_not_comparable(tmp_path):
    comparable = on_day(tmp_path, 1, BETTER_CASES)
    on_day(tmp_path, 2, data_set_sha256="0" * 64)
    current = on_day(tmp_path, 3)

    comparison = automatic(current)

    assert comparison["baseline"] == str(comparable.resolve())
    assert comparison["status"] == "comparable"


def test_without_a_comparable_run_auto_carries_the_newest_runs_failed_conditions(
    tmp_path,
):
    on_day(tmp_path, 1, CONFUSION_CASES[:4])
    newest = on_day(tmp_path, 2, data_set_sha256="0" * 64, dirty=True)
    current = on_day(tmp_path, 3)

    comparison = automatic(current)

    assert comparison == {
        "baseline": str(newest.resolve()),
        "status": "not_comparable",
        "failed_conditions": ["data_set_revision"],
        "dirty_worktree": ["baseline"],
        "changes": [],
    }


def test_auto_without_an_earlier_run_says_so(tmp_path):
    current = on_day(tmp_path, 2)
    on_day(tmp_path, 3)

    assert automatic(current) == {
        "baseline": None,
        "status": "no_earlier_run",
        "failed_conditions": [],
        "dirty_worktree": [],
        "changes": [],
    }


def test_auto_ignores_reports_of_other_tasks_beside_the_current_one(tmp_path):
    same_task = on_day(tmp_path, 1, data_set_sha256="0" * 64)
    on_day(tmp_path, 2, task="coreference")
    current = on_day(tmp_path, 3)

    comparison = automatic(current)

    assert comparison["baseline"] == str(same_task.resolve())
    assert comparison["failed_conditions"] == ["data_set_revision"]


def test_no_baseline_requests_no_comparison(tmp_path):
    summary = Scorecard.build(
        [ReportDocument.load(run(tmp_path / "current"))], baseline="none"
    ).to_json()

    assert summary["comparison"] == {
        "baseline": None,
        "status": "not_requested",
        "failed_conditions": [],
        "dirty_worktree": [],
        "changes": [],
    }
