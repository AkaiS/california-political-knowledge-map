"""Run an approved question through retrieval, fusion, and Evidence Assembly."""

import asyncio
import logging
import math
from collections.abc import Awaitable, Callable
from functools import partial
from typing import Protocol

from pydantic_ai.usage import RunUsage

from knowledge_map.adapters.full_text import extract_full_text_keywords
from knowledge_map.core.evidence import EvidenceAssembler
from knowledge_map.core.fusion import fuse_candidates
from knowledge_map.schemas.evidence import EvidenceContextLimits
from knowledge_map.schemas.fusion import FusionConfig
from knowledge_map.schemas.query_preparation import QueryRewrite
from knowledge_map.schemas.retrieval import (
    BranchOutcome,
    CoverageDescription,
    EvidenceAssemblyFailure,
    EvidencePackage,
    FailedBranch,
    FusedCandidate,
    GroundingEvidence,
    MonthlyCoverage,
    RetrievalBranch,
    RetrievalExecutionResult,
    RetrievalFailureLog,
    RetrievalRequest,
    SkippedBranch,
    SourceArticleCitation,
    SuccessfulBranch,
)
from knowledge_map.schemas.stories import Story

logger = logging.getLogger(__name__)


def _failed(diagnostic: RetrievalFailureLog) -> FailedBranch:
    logger.warning(
        "retrieval_branch_failed",
        extra={
            "event": "retrieval_branch_failed",
            **diagnostic.model_dump(),
            "deadline_exhausted": diagnostic.deadline_exhausted,
        },
    )
    return FailedBranch(branch=diagnostic.branch)


async def _run_branch(
    branch: RetrievalBranch,
    call: Callable[[], Awaitable[SuccessfulBranch | FailedBranch]],
    deadline: float,
    clock: Callable[[], float],
) -> SuccessfulBranch | FailedBranch:
    attempts = 0
    try:
        remaining = deadline - clock()
        if remaining <= 0:
            raise TimeoutError
        async with asyncio.timeout(remaining):
            attempts = 1
            outcome = await call()
        if clock() >= deadline:
            raise TimeoutError
        if outcome.branch != branch:
            raise ValueError("a branch returned another branch's outcome")
        return outcome
    except TimeoutError:
        return _failed(
            RetrievalFailureLog(
                branch=branch,
                stage="deadline",
                failure_kind="deadline_exhausted",
                attempts_consumed=attempts,
                safe_diagnostic="The retrieval deadline expired before this branch completed.",
            )
        )
    except Exception:  # noqa: BLE001 - Preserve sibling evidence on unexpected branch failures.
        return _failed(
            RetrievalFailureLog(
                branch=branch,
                stage="execution",
                failure_kind="unexpected",
                attempts_consumed=1,
                safe_diagnostic="The retrieval branch could not complete.",
            )
        )


class FullTextRetriever(Protocol):
    async def retrieve(
        self,
        request: RetrievalRequest,
        *,
        deadline: float,
        keywords: tuple[str, ...] | None = None,
    ) -> SuccessfulBranch | FailedBranch: ...


class ModelRetriever(Protocol):
    async def retrieve(
        self,
        request: RetrievalRequest,
        *,
        deadline: float,
        usage: RunUsage | None = None,
    ) -> SuccessfulBranch | FailedBranch: ...


class RetrievalCoordinator:
    def __init__(
        self,
        *,
        full_text: FullTextRetriever,
        dense: ModelRetriever,
        structural: ModelRetriever,
        load_grounding: Callable[[FusedCandidate], Awaitable[GroundingEvidence]],
        load_story: Callable[[SourceArticleCitation], Awaitable[Story]],
        fusion_config: FusionConfig | None = None,
        context_limits: EvidenceContextLimits | None = None,
        deadline_seconds: float = 60,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if (
            type(deadline_seconds) not in (int, float)
            or not math.isfinite(deadline_seconds)
            or deadline_seconds <= 0
        ):
            raise ValueError("deadline_seconds must be a finite positive duration")
        self._full_text = full_text
        self._dense = dense
        self._structural = structural
        self._assembler = EvidenceAssembler(
            load_grounding=load_grounding, load_story=load_story
        )
        self._fusion_config = fusion_config or FusionConfig()
        self._context_limits = context_limits or EvidenceContextLimits()
        self._deadline_seconds = deadline_seconds
        self._clock = clock

    async def run(
        self,
        rewrite: QueryRewrite,
        *,
        coverage: CoverageDescription,
        relevant_collection_ids: tuple[str, ...],
        monthly_coverage: tuple[MonthlyCoverage, ...] = (),
        usage: RunUsage | None = None,
    ) -> EvidencePackage | EvidenceAssemblyFailure:
        clock = self._clock or asyncio.get_running_loop().time
        deadline = clock() + self._deadline_seconds
        request = RetrievalRequest(rewrite=rewrite)
        keywords = extract_full_text_keywords(rewrite)
        run_usage = RunUsage()
        calls = [
            partial(
                self._full_text.retrieve, request, deadline=deadline, keywords=keywords
            ),
            partial(self._dense.retrieve, request, deadline=deadline, usage=run_usage),
        ]
        if rewrite.relational:
            calls.append(
                partial(
                    self._structural.retrieve,
                    request,
                    deadline=deadline,
                    usage=run_usage,
                )
            )
        try:
            outcomes: list[BranchOutcome] = list(
                await asyncio.gather(
                    *(
                        _run_branch(branch, call, deadline, clock)
                        for branch, call in zip(
                            request.expected_branches, calls, strict=True
                        )
                    )
                )
            )
        finally:
            if usage is not None:
                usage.incr(run_usage)
            logger.info(
                "retrieval_total_usage",
                extra={
                    "event": "retrieval_total_usage",
                    "requests": run_usage.requests,
                    "input_tokens": run_usage.input_tokens,
                    "output_tokens": run_usage.output_tokens,
                },
            )
        if not rewrite.relational:
            outcomes.append(SkippedBranch())
        execution = RetrievalExecutionResult(request=request, outcomes=tuple(outcomes))
        try:
            if clock() >= deadline:
                raise TimeoutError
            async with asyncio.timeout(deadline - clock()):
                result = await self._assembler.assemble(
                    execution,
                    fuse_candidates(execution, config=self._fusion_config),
                    coverage=coverage,
                    relevant_collection_ids=relevant_collection_ids,
                    monthly_coverage=monthly_coverage,
                    limits=self._context_limits,
                )
            if clock() >= deadline:
                raise TimeoutError
            return result
        except TimeoutError:
            logger.warning(
                "evidence_assembly_deadline",
                extra={
                    "event": "evidence_assembly_failed",
                    "failure_kind": "deadline_exhausted",
                    "safe_diagnostic": "Evidence Assembly could not finish within the retrieval deadline.",
                },
            )
            return EvidenceAssemblyFailure(execution=execution)
