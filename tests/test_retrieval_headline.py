"""A completed retrieval run records its Headline Metrics, and compaction keeps them.

Each test runs authored retrieval outputs through the evaluation engine and the
report checkpoint, which compacts every retrieval snapshot, with the task's own
case evaluators and headline definition, then reads the saved Evaluation
Report. No model is called.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from engine_runs import headline_rows, headline_table, run_task
from test_retrieval import COVERAGE, Branch, candidate, coordinator

from knowledge_map.evaluation import LabelQuality
from knowledge_map.evaluation.tasks.chat import ChatFailure
from knowledge_map.evaluation.tasks.retrieval import (
    EvidenceRequirement,
    ReferenceAnswer,
    RetrievalExpectation,
    RetrievalOutput,
)
from knowledge_map.schemas.fusion import FusionConfig
from knowledge_map.schemas.query_preparation import QueryRewrite, QuestionAssessment
from knowledge_map.schemas.retrieval import (
    EvidenceAssemblyFailure,
    FailedBranch,
    FusedCandidate,
    RetrievalBranch,
    RetrievalExecutionResult,
    RetrievalRequest,
    SkippedBranch,
    SuccessfulBranch,
)

FULL_TEXT = RetrievalBranch.FULL_TEXT
DENSE = RetrievalBranch.DENSE
STRUCTURAL = RetrievalBranch.STRUCTURAL
SETTINGS = {"fusion_settings": FusionConfig().model_dump(mode="json")}
NO_DENOMINATOR = "no case contributed to the denominator"

# Only these questions ask for the structural branch.
RELATIONAL = {"partial"}


@pytest.fixture(autouse=True)
def disable_telemetry(monkeypatch):
    monkeypatch.setattr("knowledge_map.evaluation.engine.setup_telemetry", lambda: None)


def question(case_id):
    return QueryRewrite(
        question=f"Which organizations support {case_id}?",
        relational=case_id in RELATIONAL,
        assessment=QuestionAssessment(status="allowed"),
    )


def labels(*ids):
    """Every reference ID is its own required evidence group."""

    return RetrievalExpectation(
        grain="article_chunk",
        relevant_ids=ids,
        answers=(
            ReferenceAnswer(
                groups=tuple(
                    EvidenceRequirement(kind=f"hop-{i}", ids=(id,))
                    for i, id in enumerate(ids)
                )
            ),
        ),
    )


def fused(*chunks):
    return tuple(
        FusedCandidate(
            chunk_id=chunk,
            rank=rank,
            fusion_score=1 / rank,
            contributions=(candidate(FULL_TEXT, chunk=chunk, rank=rank),),
        )
        for rank, chunk in enumerate(chunks, 1)
    )


def ranked(branch, *chunks):
    return tuple(
        candidate(branch, chunk=chunk, rank=rank)
        for rank, chunk in enumerate(chunks, 1)
    )


def assembled(case_id, full_text, dense):
    """An Evidence Package whose selected passages are every branch candidate."""

    branches = {
        FULL_TEXT: Branch(FULL_TEXT, full_text),
        DENSE: Branch(DENSE, dense),
        STRUCTURAL: Branch(STRUCTURAL),
    }
    return asyncio.run(
        coordinator(branches).run(
            question(case_id),
            coverage=COVERAGE,
            relevant_collection_ids=("reporting",),
        )
    )


def unassembled(case_id, *outcomes):
    return EvidenceAssemblyFailure(
        execution=RetrievalExecutionResult(
            request=RetrievalRequest(rewrite=question(case_id)), outcomes=outcomes
        )
    )


# Fusion found both references first, and both reached the final context.
FOUND = (
    "found",
    labels("a", "b"),
    RetrievalOutput(
        result=assembled("found", ranked(FULL_TEXT, "a", "b"), ranked(DENSE, "b")),
        fused=fused("a", "b"),
        settings=SETTINGS,
    ),
)
# A relational question: fusion found one of two references second, and the
# dense and structural branches failed before Evidence Assembly failed.
PARTIAL = (
    "partial",
    labels("c", "d"),
    RetrievalOutput(
        result=unassembled(
            "partial",
            SuccessfulBranch(branch=FULL_TEXT, candidates=ranked(FULL_TEXT, "c")),
            FailedBranch(branch=DENSE),
            FailedBranch(branch=STRUCTURAL),
        ),
        fused=fused("noise", "c"),
        settings=SETTINGS,
    ),
)
# Every branch completed and retrieved nothing.
NOTHING_RETRIEVED = (
    "nothing-retrieved",
    labels("e"),
    RetrievalOutput(
        result=unassembled(
            "nothing-retrieved",
            SuccessfulBranch(branch=FULL_TEXT, candidates=()),
            SuccessfulBranch(branch=DENSE, candidates=()),
            SkippedBranch(),
        ),
        settings=SETTINGS,
    ),
)
POPULATION = [FOUND, PARTIAL, NOTHING_RETRIEVED]


def saved_run(directory, cases):
    path = run_task(
        directory,
        "retrieval",
        cases,
        task_input=question,
        label_quality=LabelQuality.SILVER,
    )
    return json.loads(path.read_text())


def test_compacted_run_keeps_fused_recall_at_10_first_with_its_headline_rows(
    tmp_path,
):
    document = saved_run(tmp_path, POPULATION)

    # The checkpoint compacted the saved snapshot.
    assert document["retrieval_report"]["metric_version"] == "unique-chunk-budget-v2"
    assert "fused" not in document["report"]["cases"][0]["output"]
    # Found: fused recall 1 at 5 and 10, rank 1, complete; context has a, b.
    # Partial: fused recall 1/2, rank 2, incomplete; no context.  Nothing
    # retrieved: all zero.  Only partial asked for the structural branch.
    assert headline_table(document)[:10] == [
        ["fused_recall_at_10", "primary", 0.5, 1.5, 3.0, "per_case_mean", 3, 3, None],
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
        [
            "full_text_completed",
            "headline",
            1.0,
            3.0,
            3.0,
            "per_case_mean",
            3,
            3,
            None,
        ],
        ["dense_completed", "headline", 2 / 3, 2.0, 3.0, "per_case_mean", 3, 3, None],
        [
            "structural_completed",
            "headline",
            0.0,
            0.0,
            1.0,
            "per_case_mean",
            1,
            3,
            None,
        ],
        ["execution_failure_rate", "headline", 0.0, 0.0, 3.0, "rate", 3, 3, None],
    ]
    assert document["experiment_metadata"]["headline_version"] == "retrieval-v1"


def test_diagnostic_rows_hold_each_branch_precision_and_an_unavailable_ndcg(
    tmp_path,
):
    document = saved_run(tmp_path, POPULATION)
    table = headline_table(document)

    diagnostic = [(row[0], row[5]) for row in table if row[1] == "diagnostic"]
    assert diagnostic == [
        *(
            (f"{branch}_{name}", "per_case_mean")
            for branch in ("full_text", "dense", "structural")
            for name in (
                "recall_at_1",
                "recall_at_5",
                "recall_at_10",
                "recall_at_50",
                "reciprocal_rank",
                "complete_evidence_at_5",
                "complete_evidence_at_10",
            )
        ),
        *(
            (f"{ranking}_precision_at_{k}", "per_case_mean")
            for ranking in ("fused", "full_text", "dense", "structural")
            for k in (1, 5, 10, 50)
        ),
        ("fused_ndcg_at_10", "per_case_mean"),
    ]
    rows = headline_rows(document)
    # Full-text ranked a first for found and c first for partial.
    assert rows[("full_text_recall_at_1", "per_case_mean")]["value"] == 1 / 3
    # Two of found's ten fused slots and one of partial's match a reference.
    assert rows[("fused_precision_at_10", "per_case_mean")]["value"] == pytest.approx(
        (2 / 10 + 1 / 10 + 0) / 3
    )
    # Only partial asked for the structural branch, which failed.
    assert rows[("structural_recall_at_10", "per_case_mean")] == {
        "metric": "structural_recall_at_10",
        "role": "diagnostic",
        "value": 0.0,
        "numerator": 0.0,
        "denominator": 1.0,
        "aggregation": "per_case_mean",
        "scored_cases": 1,
        "selected_cases": 3,
        "unavailable_reason": None,
    }
    assert rows[("fused_ndcg_at_10", "per_case_mean")] == {
        "metric": "fused_ndcg_at_10",
        "role": "diagnostic",
        "value": None,
        "numerator": None,
        "denominator": None,
        "aggregation": "per_case_mean",
        "scored_cases": 0,
        "selected_cases": 3,
        "unavailable_reason": "the retrieval references have no relevance grades",
    }


STARTUP_FAILURE = RetrievalOutput(
    failure=ChatFailure(
        stage="startup",
        kind="execution",
        exception_type="RuntimeError",
        diagnostic="RAG evaluation could not complete startup.",
    )
)


def test_failed_cases_complete_the_run_and_count_only_toward_execution_failures(
    tmp_path,
):
    clean = headline_rows(saved_run(tmp_path / "clean", POPULATION))
    document = saved_run(
        tmp_path / "with-failures",
        [
            *POPULATION,
            ("raised", labels("a"), RuntimeError("transport exhausted")),
            ("recorded", labels("a"), STARTUP_FAILURE),
        ],
    )

    assert document["evaluation_run"]["status"] == "completed"
    # The recorded failure still carries its zero case scores.
    recorded = next(
        case for case in document["report"]["cases"] if case["name"] == "recorded"
    )
    assert recorded["scores"]["fused_recall_at_10"]["value"] == 0
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
