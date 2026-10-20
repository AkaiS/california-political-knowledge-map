"""Retrieval Evaluation Runs over authored outputs, saved as Evaluation Reports."""

from __future__ import annotations

import asyncio
from pathlib import Path

from engine_runs import run_task
from test_retrieval import COVERAGE, Branch, candidate, coordinator

from knowledge_map.evaluation import LabelQuality
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
    RetrievalAnswer,
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

# Only these questions ask for the structural branch.
RELATIONAL = {"partial"}


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


def answered(package):
    """A rendered Source Guide built on a guidance answer over ``package``."""

    return RetrievalOutput(
        result=package,
        answer=RetrievalAnswer(evidence=package, introduction="Read these first."),
        rendered_text="A rendered Source Guide.",
        fused=fused("a", "b"),
        settings=SETTINGS,
    )


# Fusion found both references first, both reached the final context, and the
# reader was guided to them.
FOUND = (
    "found",
    labels("a", "b"),
    answered(assembled("found", ranked(FULL_TEXT, "a", "b"), ranked(DENSE, "b"))),
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


def run_retrieval(directory: Path, cases) -> Path:
    """Run ``cases`` -- (id, reference labels, authored output) -- on a Silver Set."""

    return run_task(
        directory,
        "retrieval",
        cases,
        task_input=question,
        label_quality=LabelQuality.SILVER,
    )
