"""A completed Relevance Evaluation Run records its Headline Metrics.

Each test runs authored outputs through the evaluation engine and the report
checkpoint with Relevance's own case evaluators and headline definition, then
reads the saved Evaluation Report.
"""

from __future__ import annotations

import json

import pytest
from relevance_runs import CONFUSION_CASES, RELEVANT, run_relevance

COLUMNS = [
    "metric",
    "role",
    "value",
    "numerator",
    "denominator",
    "aggregation",
    "scored_cases",
    "selected_cases",
    "unavailable_reason",
]


@pytest.fixture(autouse=True)
def disable_telemetry(monkeypatch):
    monkeypatch.setattr("knowledge_map.evaluation.engine.setup_telemetry", lambda: None)


def saved_run(directory, cases):
    return json.loads(run_relevance(directory, cases).read_text())


def headline_table(document):
    tables = [
        analysis
        for analysis in document["report"]["analyses"]
        if analysis.get("title") == "Headline metrics"
    ]
    assert len(tables) == 1
    assert tables[0]["type"] == "table"
    assert tables[0]["columns"] == COLUMNS
    return tables[0]["rows"]


def test_completed_run_records_pooled_relevant_f1_first_with_its_headline_rows(
    tmp_path,
):
    document = saved_run(tmp_path, CONFUSION_CASES)

    assert headline_table(document) == [
        ["relevant_f1", "primary", 4 / 6, 4.0, 6.0, "pooled", 5, 5, None],
        ["relevant_precision", "headline", 2 / 3, 2.0, 3.0, "pooled", 5, 5, None],
        ["relevant_recall", "headline", 2 / 3, 2.0, 3.0, "pooled", 5, 5, None],
        ["accuracy", "headline", 3 / 5, 3.0, 5.0, "rate", 5, 5, None],
        ["true_positives", "headline", 2 / 5, 2.0, 5.0, "rate", 5, 5, None],
        ["false_positives", "headline", 1 / 5, 1.0, 5.0, "rate", 5, 5, None],
        ["false_negatives", "headline", 1 / 5, 1.0, 5.0, "rate", 5, 5, None],
        ["true_negatives", "headline", 1 / 5, 1.0, 5.0, "rate", 5, 5, None],
        ["execution_failure_rate", "headline", 0.0, 0.0, 5.0, "rate", 5, 5, None],
    ]


def test_failed_cases_complete_the_run_and_count_only_toward_execution_failures(
    tmp_path,
):
    document = saved_run(
        tmp_path,
        [
            *CONFUSION_CASES,
            ("raised", RELEVANT, RuntimeError("transport exhausted")),
            ("recorded", RELEVANT, {"failure": {"stage": "classification"}}),
        ],
    )

    assert document["evaluation_run"]["status"] == "completed"
    assert headline_table(document) == [
        ["relevant_f1", "primary", 4 / 6, 4.0, 6.0, "pooled", 5, 7, None],
        ["relevant_precision", "headline", 2 / 3, 2.0, 3.0, "pooled", 5, 7, None],
        ["relevant_recall", "headline", 2 / 3, 2.0, 3.0, "pooled", 5, 7, None],
        ["accuracy", "headline", 3 / 5, 3.0, 5.0, "rate", 5, 7, None],
        ["true_positives", "headline", 2 / 5, 2.0, 5.0, "rate", 5, 7, None],
        ["false_positives", "headline", 1 / 5, 1.0, 5.0, "rate", 5, 7, None],
        ["false_negatives", "headline", 1 / 5, 1.0, 5.0, "rate", 5, 7, None],
        ["true_negatives", "headline", 1 / 5, 1.0, 5.0, "rate", 5, 7, None],
        ["execution_failure_rate", "headline", 2 / 7, 2.0, 7.0, "rate", 7, 7, None],
    ]


def test_a_run_of_only_failures_keeps_quality_rows_null_with_a_reason(tmp_path):
    document = saved_run(
        tmp_path, [("raised", RELEVANT, RuntimeError("transport exhausted"))]
    )

    rows = {row[0]: row for row in headline_table(document)}
    reason = "no case contributed to the denominator"
    assert rows["relevant_f1"] == [
        "relevant_f1",
        "primary",
        None,
        0.0,
        0.0,
        "pooled",
        0,
        1,
        reason,
    ]
    assert rows["accuracy"] == [
        "accuracy",
        "headline",
        None,
        0.0,
        0.0,
        "rate",
        0,
        1,
        reason,
    ]
    assert rows["execution_failure_rate"][2:5] == [1.0, 1.0, 1.0]


def test_unreadable_output_records_evaluator_errors_the_same_way_on_every_run(
    tmp_path,
):
    cases = [*CONFUSION_CASES, ("unreadable", RELEVANT, None)]
    first = saved_run(tmp_path / "first", cases)
    second = saved_run(tmp_path / "second", cases)

    for document in (first, second):
        assert document["evaluation_run"]["status"] == "completed"
        assert document["report"]["analyses"] == []
        unreadable = next(
            case for case in document["report"]["cases"] if case["name"] == "unreadable"
        )
        assert unreadable["evaluator_failures"]
    (failure,) = first["report"]["report_evaluator_failures"]
    assert failure["name"] == "HeadlineMetrics"
    assert failure["source"] == {
        "name": "HeadlineMetrics",
        "arguments": ["relevance-v1"],
    }
    assert (
        first["report"]["report_evaluator_failures"]
        == second["report"]["report_evaluator_failures"]
    )
