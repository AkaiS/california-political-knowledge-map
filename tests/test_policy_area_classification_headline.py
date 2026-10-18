"""A completed Policy Area Classification run records its Headline Metrics.

Each test runs authored outputs through the evaluation engine and the report
checkpoint with the task's own case evaluators and headline definition, then
reads the saved Evaluation Report. No model is called.
"""

from __future__ import annotations

import json

import pytest
from engine_runs import headline_rows, headline_table, run_task

from knowledge_map.evaluation import LabelQuality
from knowledge_map.evaluation.tasks.policy_area_classification import (
    ClassificationExpectation,
    ClassificationInput,
    ClassificationOutput,
)

NO_DENOMINATOR = "no case contributed to the denominator"

HEALTH = "Health"
HOUSING = "Housing & Community Development"
LABOR = "Labor & Employment"


@pytest.fixture(autouse=True)
def disable_telemetry(monkeypatch):
    monkeypatch.setattr("knowledge_map.evaluation.engine.setup_telemetry", lambda: None)


def article(case_id, silver, returned):
    return (
        case_id,
        ClassificationExpectation(policy_areas=list(silver)),
        ClassificationOutput(policy_areas=list(returned)),
    )


def saved_run(directory, cases):
    path = run_task(
        directory,
        "policy_area_classification",
        cases,
        task_input=lambda case_id: ClassificationInput(
            url=case_id, title=case_id, resolved_text=case_id
        ),
        label_quality=LabelQuality.SILVER,
    )
    return json.loads(path.read_text())


# Health is common and always found; Labor is rare and missed; Housing is only
# ever predicted.  Pooled F1 is carried by Health, while the label-macro F1
# weighs Health and Labor once each and leaves Housing out.
EXACT = article("exact", [HEALTH], [HEALTH])
EXTRA = article("extra", [HEALTH], [HEALTH, HOUSING])
MISSED = article("missed", [HEALTH, LABOR], [HEALTH])
BOTH_EMPTY = article("both-empty", [], [])
POPULATION = [EXACT, EXTRA, MISSED, BOTH_EMPTY]


def test_completed_run_records_pooled_policy_area_f1_first_and_a_label_macro_f1(
    tmp_path,
):
    document = saved_run(tmp_path, POPULATION)

    # Pooled: 3 matched, 4 found, 4 expected.  Per area, Health matched 3 of
    # 3 found and 3 expected (F1 1) and Labor 0 of 0 found and 1 expected
    # (F1 0), so the label-macro F1 is 1/2.  Per case: exact 1, extra 2/3,
    # missed 2/3, both-empty passes at 1.
    assert headline_table(document) == [
        ["policy_area_f1", "primary", 6 / 8, 6.0, 8.0, "pooled", 4, 4, None],
        ["policy_area_precision", "headline", 3 / 4, 3.0, 4.0, "pooled", 4, 4, None],
        ["policy_area_recall", "headline", 3 / 4, 3.0, 4.0, "pooled", 4, 4, None],
        ["policy_area_macro_f1", "headline", 1 / 2, 1.0, 2.0, "pooled", 4, 4, None],
        [
            "policy_area_f1",
            "headline",
            pytest.approx((1 + 2 / 3 + 2 / 3 + 1) / 4),
            pytest.approx(1 + 2 / 3 + 2 / 3 + 1),
            4.0,
            "per_case_mean",
            4,
            4,
            None,
        ],
        ["execution_failure_rate", "headline", 0.0, 0.0, 4.0, "rate", 4, 4, None],
        [
            f"policy_area_precision[{HEALTH}]",
            "diagnostic",
            1.0,
            3.0,
            3.0,
            "pooled",
            4,
            4,
            None,
        ],
        [
            f"policy_area_recall[{HEALTH}]",
            "diagnostic",
            1.0,
            3.0,
            3.0,
            "pooled",
            4,
            4,
            None,
        ],
        [
            f"policy_area_f1[{HEALTH}]",
            "diagnostic",
            1.0,
            6.0,
            6.0,
            "pooled",
            4,
            4,
            None,
        ],
        [
            f"policy_area_precision[{HOUSING}]",
            "diagnostic",
            0.0,
            0.0,
            1.0,
            "pooled",
            4,
            4,
            None,
        ],
        [
            f"policy_area_recall[{HOUSING}]",
            "diagnostic",
            None,
            0.0,
            0.0,
            "pooled",
            4,
            4,
            NO_DENOMINATOR,
        ],
        [
            f"policy_area_f1[{HOUSING}]",
            "diagnostic",
            0.0,
            0.0,
            1.0,
            "pooled",
            4,
            4,
            None,
        ],
        [
            f"policy_area_precision[{LABOR}]",
            "diagnostic",
            None,
            0.0,
            0.0,
            "pooled",
            4,
            4,
            NO_DENOMINATOR,
        ],
        [
            f"policy_area_recall[{LABOR}]",
            "diagnostic",
            0.0,
            0.0,
            1.0,
            "pooled",
            4,
            4,
            None,
        ],
        [f"policy_area_f1[{LABOR}]", "diagnostic", 0.0, 0.0, 1.0, "pooled", 4, 4, None],
    ]
    assert (
        document["experiment_metadata"]["headline_version"]
        == "policy_area_classification-v1"
    )


def test_an_article_both_sides_left_empty_adds_nothing_pooled_but_passes_per_case(
    tmp_path,
):
    document = saved_run(tmp_path, [BOTH_EMPTY])

    # No area was named on either side, so no per-area row exists and the
    # label-macro F1 has no area to average over.
    assert headline_table(document) == [
        ["policy_area_f1", "primary", None, 0.0, 0.0, "pooled", 1, 1, NO_DENOMINATOR],
        [
            "policy_area_precision",
            "headline",
            None,
            0.0,
            0.0,
            "pooled",
            1,
            1,
            NO_DENOMINATOR,
        ],
        [
            "policy_area_recall",
            "headline",
            None,
            0.0,
            0.0,
            "pooled",
            1,
            1,
            NO_DENOMINATOR,
        ],
        [
            "policy_area_macro_f1",
            "headline",
            None,
            0.0,
            0.0,
            "pooled",
            1,
            1,
            NO_DENOMINATOR,
        ],
        ["policy_area_f1", "headline", 1.0, 1.0, 1.0, "per_case_mean", 1, 1, None],
        ["execution_failure_rate", "headline", 0.0, 0.0, 1.0, "rate", 1, 1, None],
    ]


def test_failed_cases_complete_the_run_and_count_only_toward_execution_failures(
    tmp_path,
):
    clean = headline_rows(saved_run(tmp_path / "clean", POPULATION))
    document = saved_run(
        tmp_path / "with-failures",
        [
            *POPULATION,
            # Both fail on areas no succeeded case's silver used, so a failure
            # that leaked into the label-macro F1 would change it.
            (
                "raised",
                ClassificationExpectation(policy_areas=[LABOR, HOUSING]),
                RuntimeError("transport exhausted"),
            ),
            (
                "recorded",
                ClassificationExpectation(policy_areas=[HOUSING]),
                ClassificationOutput(
                    policy_areas=[HOUSING], failure_type="output_validation"
                ),
            ),
        ],
    )

    assert document["evaluation_run"]["status"] == "completed"
    rows = headline_rows(document)
    assert rows.pop(("execution_failure_rate", "rate")) == {
        "metric": "execution_failure_rate",
        "role": "headline",
        "value": 2 / 6,
        "numerator": 2.0,
        "denominator": 6.0,
        "aggregation": "rate",
        "scored_cases": 6,
        "selected_cases": 6,
        "unavailable_reason": None,
    }
    del clean[("execution_failure_rate", "rate")]
    # Every quality row reads exactly as it did without the failures, over
    # the larger run population.
    assert {key: {**row, "selected_cases": 6} for key, row in clean.items()} == rows


def test_unreadable_output_records_evaluator_errors_the_same_way_on_every_run(
    tmp_path,
):
    cases = [*POPULATION, ("unreadable", ClassificationExpectation(), None)]
    first = saved_run(tmp_path / "first", cases)
    second = saved_run(tmp_path / "second", cases)

    for document in (first, second):
        assert document["evaluation_run"]["status"] == "completed"
        assert document["report"]["analyses"] == []
    (failure,) = first["report"]["report_evaluator_failures"]
    assert failure["source"] == {
        "name": "HeadlineMetrics",
        "arguments": ["policy_area_classification-v1"],
    }
    assert (
        first["report"]["report_evaluator_failures"]
        == second["report"]["report_evaluator_failures"]
    )
