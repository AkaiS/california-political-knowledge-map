"""A completed retrieval run records its Headline Metrics, and compaction keeps them.

Each test runs authored retrieval outputs through the evaluation engine and the
report checkpoint, which compacts every retrieval snapshot, with the task's own
case evaluators and headline definition, then reads the saved Evaluation
Report. No model is called.
"""

from __future__ import annotations

import json

from engine_runs import headline_rows, headline_table
from retrieval_runs import (
    FULL_TEXT,
    POPULATION,
    SETTINGS,
    assembled,
    labels,
    ranked,
    run_retrieval,
)

from knowledge_map.evaluation.tasks.chat import ChatFailure
from knowledge_map.evaluation.tasks.retrieval import RetrievalOutput
from knowledge_map.schemas.retrieval import RetrievalAnswer


def saved_run(directory, cases):
    return json.loads(run_retrieval(directory, cases).read_text())


def test_compacted_run_keeps_fused_recall_at_10_first_with_its_headline_rows(
    tmp_path,
):
    document = saved_run(tmp_path, POPULATION)

    # The checkpoint compacted the saved snapshot.
    assert document["retrieval_report"]["metric_version"] == "unique-chunk-budget-v2"
    assert "fused" not in document["report"]["cases"][0]["output"]
    # Found: fused recall 1 at 5 and 10, rank 1, complete; context has a, b.
    # Partial: fused recall 1/2, rank 2, incomplete; no context.  Nothing
    # retrieved: all zero.  Only Found rendered an answer; the two failed
    # Evidence Assemblies are neither answers nor execution failures.  The
    # table holds outcomes only: no branch rows and no diagnostic rows.
    assert headline_table(document) == [
        ["fused_recall_at_10", "primary", 0.5, 1.5, 3.0, "per_case_mean", 3, 3, None],
        ["completed_answer_rate", "headline", 1 / 3, 1.0, 3.0, "rate", 3, 3, None],
        ["fused_recall_at_5", "headline", 0.5, 1.5, 3.0, "per_case_mean", 3, 3, None],
        [
            "fused_reciprocal_rank",
            "headline",
            0.5,
            1.5,
            3.0,
            "per_case_mean",
            3,
            3,
            None,
        ],
        [
            "fused_complete_evidence_at_10",
            "headline",
            1 / 3,
            1.0,
            3.0,
            "per_case_mean",
            3,
            3,
            None,
        ],
        ["context_recall", "headline", 1 / 3, 1.0, 3.0, "per_case_mean", 3, 3, None],
        [
            "context_complete_evidence",
            "headline",
            1 / 3,
            1.0,
            3.0,
            "per_case_mean",
            3,
            3,
            None,
        ],
        ["execution_failure_rate", "headline", 0.0, 0.0, 3.0, "rate", 3, 3, None],
    ]
    assert document["experiment_metadata"]["headline_version"] == "retrieval-v1"


def failed_at(stage, **fields):
    return RetrievalOutput(
        failure=ChatFailure(
            stage=stage,
            kind="execution",
            exception_type="RuntimeError",
            diagnostic=f"RAG evaluation could not complete {stage}.",
        ),
        **fields,
    )


STARTUP_FAILURE = failed_at("startup")


def test_failed_cases_complete_the_run_and_count_only_in_operational_rows(
    tmp_path,
):
    clean = headline_rows(saved_run(tmp_path / "clean", POPULATION))
    package = assembled("unrendered", ranked(FULL_TEXT, "a"), ())
    document = saved_run(
        tmp_path / "with-failures",
        [
            *POPULATION,
            ("raised", labels("a"), RuntimeError("transport exhausted")),
            ("recorded", labels("a"), STARTUP_FAILURE),
            # The Chat Agent answered, but no Source Guide was rendered.
            (
                "unrendered",
                labels("a"),
                failed_at(
                    "rendering",
                    result=package,
                    answer=RetrievalAnswer(evidence=package, introduction=None),
                    settings=SETTINGS,
                ),
            ),
        ],
    )

    assert document["evaluation_run"]["status"] == "completed"
    # The recorded failure still carries its zero case scores.
    recorded = next(
        case for case in document["report"]["cases"] if case["name"] == "recorded"
    )
    assert recorded["scores"]["fused_recall_at_10"]["value"] == 0
    rows = headline_rows(document)
    operational = {
        "role": "headline",
        "denominator": 6.0,
        "aggregation": "rate",
        "scored_cases": 6,
        "selected_cases": 6,
        "unavailable_reason": None,
    }
    assert rows.pop(("execution_failure_rate", "rate")) == {
        "metric": "execution_failure_rate",
        "value": 3 / 6,
        "numerator": 3.0,
        **operational,
    }
    # Only Found rendered an answer; an answer left unrendered is not one.
    assert rows.pop(("completed_answer_rate", "rate")) == {
        "metric": "completed_answer_rate",
        "value": 1 / 6,
        "numerator": 1.0,
        **operational,
    }
    del clean[("execution_failure_rate", "rate")]
    del clean[("completed_answer_rate", "rate")]
    # Every quality row reads exactly as it did without the failures, over
    # the larger run population.
    assert {key: {**row, "selected_cases": 6} for key, row in clean.items()} == rows


class UnreadableOutput(dict):
    """An output whose recorded failure cannot be read.

    Every retrieval row is a mean of recorded scores, so only reading whether
    a case failed can raise inside the headline evaluator.  It saves as an
    empty output, which compaction reads.
    """

    def get(self, key, default=None):
        raise ValueError(f"unreadable output field {key!r}")


def test_unreadable_output_records_evaluator_errors_the_same_way_on_every_run(
    tmp_path,
):
    cases = [*POPULATION, ("unreadable", labels("a"), UnreadableOutput())]
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
    assert failure["source"] == {
        "name": "HeadlineMetrics",
        "arguments": ["retrieval-v1"],
    }
    assert (
        first["report"]["report_evaluator_failures"]
        == second["report"]["report_evaluator_failures"]
    )
