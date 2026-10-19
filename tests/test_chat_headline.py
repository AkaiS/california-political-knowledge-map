"""A completed chat run records operational Headline Metrics and no quality metric.

Each test runs authored Chat Session outputs through the evaluation engine and
the report checkpoint, with the chat task's own case evaluators and headline
definition, then reads the saved Evaluation Report. No model is called.
"""

from __future__ import annotations

import json

from chat_runs import (
    FRAMEWORK_FAILURE,
    STAGE_FAILURE,
    answered,
    assessed,
    declined_in_preparation,
    run_chat,
)
from engine_runs import headline_rows, headline_table

from knowledge_map.evaluation.tasks.chat import ChatFailure


def saved_run(directory, cases):
    return json.loads(run_chat(directory, cases).read_text())


def test_unlabeled_run_says_it_has_no_quality_metric_and_reports_outcomes(tmp_path):
    document = saved_run(tmp_path, [answered("AB 1")])

    table = headline_table(document)
    assert table[0] == [
        "answer_quality",
        "primary",
        None,
        None,
        None,
        "rate",
        0,
        1,
        "Unlabeled Set: no quality metric",
    ]
    assert [(row[0], row[1], row[5]) for row in table] == [
        ("answer_quality", "primary", "rate"),
        ("completed_answer_rate", "headline", "rate"),
        ("declined_rate", "headline", "rate"),
        ("deferred_rate", "headline", "rate"),
        ("needs_edit_rate", "headline", "rate"),
        ("task_duration_p50", "headline", "quantile"),
        ("task_duration_p95", "headline", "quantile"),
        ("execution_failure_rate", "headline", "rate"),
    ]
    assert document["experiment_metadata"]["headline_version"] == "chat-v1"


def test_completed_answers_include_an_answer_whose_introduction_is_null(tmp_path):
    rows = headline_rows(
        saved_run(
            tmp_path,
            [
                answered("AB 1"),
                answered("AB 2", introduction=None),
                assessed("SB 3", "needs_edit"),
            ],
        )
    )

    assert rows[("completed_answer_rate", "rate")] == {
        "metric": "completed_answer_rate",
        "role": "headline",
        "value": 2 / 3,
        "numerator": 2.0,
        "denominator": 3.0,
        "aggregation": "rate",
        "scored_cases": 3,
        "selected_cases": 3,
        "unavailable_reason": None,
    }


def test_declined_deferred_and_needs_edit_questions_are_separate_rates(tmp_path):
    rows = headline_rows(
        saved_run(
            tmp_path,
            [
                answered("AB 1"),
                assessed("SB 1", "declined"),
                declined_in_preparation("SB 2"),
                assessed(
                    "SB 3", "deferred", recoverable_portion="Reporting since 2024."
                ),
                assessed("SB 4", "needs_edit"),
            ],
        )
    )

    assert {
        metric: (row["role"], row["numerator"], row["denominator"], row["value"])
        for (metric, _), row in rows.items()
        if metric in {"declined_rate", "deferred_rate", "needs_edit_rate"}
    } == {
        "declined_rate": ("headline", 2.0, 5.0, 2 / 5),
        "deferred_rate": ("headline", 1.0, 5.0, 1 / 5),
        "needs_edit_rate": ("headline", 1.0, 5.0, 1 / 5),
    }
    assert rows[("completed_answer_rate", "rate")]["value"] == 1 / 5


def test_task_duration_quantiles_cover_only_cases_that_succeeded(tmp_path):
    rows = headline_rows(
        saved_run(
            tmp_path,
            [
                answered("AB 1"),
                answered("AB 2"),
                assessed("SB 1", "declined"),
                STAGE_FAILURE,
                FRAMEWORK_FAILURE,
            ],
        )
    )

    p50 = rows[("task_duration_p50", "quantile")]
    p95 = rows[("task_duration_p95", "quantile")]
    for row in (p50, p95):
        assert row["role"] == "headline"
        assert row["value"] > 0
        assert row["numerator"] is None
        assert row["denominator"] is None
        assert row["unavailable_reason"] is None
        # The stage failure and the framework failure leave the gap.
        assert (row["scored_cases"], row["selected_cases"]) == (3, 5)
    assert p50["value"] <= p95["value"]


def test_failed_cases_complete_the_run_and_count_only_toward_execution_failures(
    tmp_path,
):
    population = [answered("AB 1"), assessed("SB 1", "declined")]
    clean = headline_rows(saved_run(tmp_path / "clean", population))
    document = saved_run(
        tmp_path / "with-failures", [*population, STAGE_FAILURE, FRAMEWORK_FAILURE]
    )

    assert document["evaluation_run"]["status"] == "completed"
    rows = headline_rows(document)
    assert rows.pop(("execution_failure_rate", "rate")) == {
        "metric": "execution_failure_rate",
        "role": "headline",
        "value": 2 / 4,
        "numerator": 2.0,
        "denominator": 4.0,
        "aggregation": "rate",
        "scored_cases": 4,
        "selected_cases": 4,
        "unavailable_reason": None,
    }
    # No row names the failed stage, and each outcome row counts the same
    # cases as before over the larger run population.
    assert {metric for metric, _ in rows} == {metric for metric, _ in clean} - {
        "execution_failure_rate"
    }
    for metric in (
        "completed_answer_rate",
        "declined_rate",
        "deferred_rate",
        "needs_edit_rate",
    ):
        row = rows[(metric, "rate")]
        assert row["numerator"] == clean[(metric, "rate")]["numerator"]
        assert (row["denominator"], row["selected_cases"]) == (4.0, 4)
    for metric in ("task_duration_p50", "task_duration_p95"):
        row = rows[(metric, "quantile")]
        assert (row["scored_cases"], row["selected_cases"]) == (2, 4)


def test_an_answer_rendered_before_cleanup_failed_still_counts_as_completed(
    tmp_path,
):
    case_id, _, output = answered("AB 1")
    output.failure = ChatFailure(
        stage="cleanup",
        kind="execution",
        exception_type="RuntimeError",
        diagnostic="Chat evaluation could not complete cleanup.",
    )
    rows = headline_rows(
        saved_run(tmp_path, [(case_id, None, output), answered("AB 2")])
    )

    # The reader saw a Source Guide, so the summary's rule counts the answer;
    # the recorded failure counts as an execution failure under no stage name.
    assert rows[("completed_answer_rate", "rate")]["value"] == 1.0
    assert rows[("execution_failure_rate", "rate")]["value"] == 1 / 2
    assert rows[("task_duration_p50", "quantile")]["scored_cases"] == 1


def test_a_run_where_every_case_failed_keeps_its_duration_rows_without_values(
    tmp_path,
):
    rows = headline_rows(saved_run(tmp_path, [STAGE_FAILURE, FRAMEWORK_FAILURE]))

    for metric in ("task_duration_p50", "task_duration_p95"):
        row = rows[(metric, "quantile")]
        assert (row["value"], row["scored_cases"], row["selected_cases"]) == (
            None,
            0,
            2,
        )
        assert row["unavailable_reason"] == "no case succeeded"
    assert rows[("execution_failure_rate", "rate")]["value"] == 1.0


def test_unreadable_output_records_an_evaluator_error_the_same_way_on_every_run(
    tmp_path,
):
    # An output with no Chat Session fields: reading its answer raises inside
    # the headline evaluator.
    cases = [answered("AB 1"), ("AB 2", None, {"question": "Who supported AB 2?"})]
    first = saved_run(tmp_path / "first", cases)
    second = saved_run(tmp_path / "second", cases)

    for document in (first, second):
        assert document["evaluation_run"]["status"] == "completed"
        assert document["report"]["analyses"] == []
    (failure,) = first["report"]["report_evaluator_failures"]
    assert failure["source"] == {"name": "HeadlineMetrics", "arguments": ["chat-v1"]}
    assert (
        first["report"]["report_evaluator_failures"]
        == second["report"]["report_evaluator_failures"]
    )
