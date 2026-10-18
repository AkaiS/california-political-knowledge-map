"""A completed Topic Assignment run records its Headline Metrics.

Each test runs authored outputs through the evaluation engine and the report
checkpoint with the task's own case evaluators and headline definition, then
reads the saved Evaluation Report. No model is called.
"""

from __future__ import annotations

import json

import pytest
from engine_runs import headline_rows, headline_table, run_task

from knowledge_map.evaluation import LabelQuality
from knowledge_map.evaluation.tasks.topic_assignment import (
    AssignmentExpectation,
    AssignmentInput,
    AssignmentOutput,
    SilverTopicAssignment,
)
from knowledge_map.schemas import TopicAssignment

NO_DENOMINATOR = "no case contributed to the denominator"

HEALTH = "Health"
HOUSING = "Housing & Community Development"
LABOR = "Labor & Employment"


@pytest.fixture(autouse=True)
def disable_telemetry(monkeypatch):
    monkeypatch.setattr("knowledge_map.evaluation.engine.setup_telemetry", lambda: None)


def silver(*pairs):
    return AssignmentExpectation(
        assignments=[
            SilverTopicAssignment(
                measure_name=name, measure_label="Bill", policy_area=area
            )
            for name, area in pairs
        ]
    )


def assigned(*pairs, failure_type=None):
    return AssignmentOutput(
        assignments=[
            TopicAssignment(measure_name=name, measure_label="Bill", policy_area=area)
            for name, area in pairs
        ],
        failure_type=failure_type,
    )


def saved_run(directory, cases):
    path = run_task(
        directory,
        "topic_assignment",
        cases,
        task_input=lambda case_id: AssignmentInput(
            url=case_id, title=case_id, resolved_text=case_id
        ),
        label_quality=LabelQuality.SILVER,
    )
    return json.loads(path.read_text())


# One large article the model mostly got right, one small article it got
# wrong, and one article both sides left empty.  Pooled F1 weighs the large
# article's many pairs; the per-case mean weighs each article once.
LARGE = (
    "large",
    silver(
        ("SB 9", HOUSING),
        ("SB 10", HOUSING),
        ("AB 5", LABOR),
        ("AB 1", HEALTH),
        ("AB 2", HEALTH),
        ("AB 3", HEALTH),
    ),
    # Case and spacing are folded as the write path folds them.
    assigned(
        ("sb  9", HOUSING),
        ("SB 10", HOUSING),
        ("AB 5", LABOR),
        ("AB 1", HEALTH),
        ("AB 2", HEALTH),
    ),
)
SMALL = (
    "small",
    silver(("SB 1", HEALTH)),
    assigned(("SB 1", LABOR)),
)
BOTH_EMPTY = ("both-empty", silver(), assigned())
POPULATION = [LARGE, SMALL, BOTH_EMPTY]


def test_completed_run_records_pooled_assignment_f1_first_with_its_headline_rows(
    tmp_path,
):
    document = saved_run(tmp_path, POPULATION)

    # Large matched 5 of 5 found and 6 expected (F1 10/11); small matched 0 of
    # 1 and 1 (F1 0); both-empty adds nothing and passes at 1.  Pooled: 5
    # matched, 6 found, 7 expected.  Per case: (10/11 + 0 + 1) / 3.
    assert headline_table(document) == [
        ["assignment_f1", "primary", 10 / 13, 10.0, 13.0, "pooled", 3, 3, None],
        ["assignment_precision", "headline", 5 / 6, 5.0, 6.0, "pooled", 3, 3, None],
        ["assignment_recall", "headline", 5 / 7, 5.0, 7.0, "pooled", 3, 3, None],
        [
            "assignment_f1",
            "headline",
            pytest.approx((10 / 11 + 0 + 1) / 3),
            pytest.approx(10 / 11 + 0 + 1),
            3.0,
            "per_case_mean",
            3,
            3,
            None,
        ],
        ["execution_failure_rate", "headline", 0.0, 0.0, 3.0, "rate", 3, 3, None],
    ]
    assert document["experiment_metadata"]["headline_version"] == "topic_assignment-v1"


def test_an_article_both_sides_left_empty_adds_nothing_pooled_but_passes_per_case(
    tmp_path,
):
    rows = headline_rows(saved_run(tmp_path, [BOTH_EMPTY]))

    for metric in ("assignment_f1", "assignment_precision", "assignment_recall"):
        assert rows[(metric, "pooled")] == {
            "metric": metric,
            "role": "primary" if metric == "assignment_f1" else "headline",
            "value": None,
            "numerator": 0.0,
            "denominator": 0.0,
            "aggregation": "pooled",
            "scored_cases": 1,
            "selected_cases": 1,
            "unavailable_reason": NO_DENOMINATOR,
        }
    per_case = rows[("assignment_f1", "per_case_mean")]
    assert (per_case["value"], per_case["numerator"], per_case["denominator"]) == (
        1.0,
        1.0,
        1.0,
    )


def test_failed_cases_complete_the_run_and_count_only_toward_execution_failures(
    tmp_path,
):
    clean = headline_rows(saved_run(tmp_path / "clean", POPULATION))
    document = saved_run(
        tmp_path / "with-failures",
        [
            *POPULATION,
            ("raised", LARGE[1], RuntimeError("transport exhausted")),
            ("recorded", LARGE[1], assigned(failure_type="output_validation")),
        ],
    )

    assert document["evaluation_run"]["status"] == "completed"
    rows = headline_rows(document)
    assert rows.pop(("execution_failure_rate", "rate")) == {
        "metric": "execution_failure_rate",
        "role": "headline",
        "value": 2 / 5,
        "numerator": 2.0,
        "denominator": 5.0,
        "aggregation": "rate",
        "scored_cases": 5,
        "selected_cases": 5,
        "unavailable_reason": None,
    }
    del clean[("execution_failure_rate", "rate")]
    # Every quality row reads exactly as it did without the failures, over
    # the larger run population.
    assert {key: {**row, "selected_cases": 5} for key, row in clean.items()} == rows


def test_unreadable_output_records_evaluator_errors_the_same_way_on_every_run(
    tmp_path,
):
    cases = [*POPULATION, ("unreadable", LARGE[1], None)]
    first = saved_run(tmp_path / "first", cases)
    second = saved_run(tmp_path / "second", cases)

    for document in (first, second):
        assert document["evaluation_run"]["status"] == "completed"
        assert document["report"]["analyses"] == []
    (failure,) = first["report"]["report_evaluator_failures"]
    assert failure["source"] == {
        "name": "HeadlineMetrics",
        "arguments": ["topic_assignment-v1"],
    }
    assert (
        first["report"]["report_evaluator_failures"]
        == second["report"]["report_evaluator_failures"]
    )
