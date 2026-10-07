"""Run an approved question through retrieval, fusion, and Evidence Assembly."""

import asyncio
import logging
import math
from collections.abc import Awaitable, Callable
from contextlib import nullcontext
from functools import partial
from typing import Protocol

import logfire
from pydantic_ai.usage import RunUsage

from knowledge_map.adapters.full_text import extract_full_text_keywords
from knowledge_map.core.evidence import EvidenceAssembler
from knowledge_map.core.fusion import fuse_candidates
from knowledge_map.retrieval_telemetry import (
    active_branch_span,
    record_branch_failure,
    selection_stage,
)
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
    SuccessfulBranch,
)

logger = logging.getLogger(__name__)


def _failed(diagnostic: RetrievalFailureLog) -> FailedBranch:
    record_branch_failure(diagnostic)
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


async def _trace_branch(
    branch: RetrievalBranch,
    call: Callable[[], Awaitable[SuccessfulBranch | FailedBranch]],
    deadline: float,
    clock: Callable[[], float],
    chat_session_id: str | None,
    keywords: tuple[str, ...],
) -> SuccessfulBranch | FailedBranch:
    with (
        logfire.span(
            "chat_session.retrieval_branch",
            chat_session_id=chat_session_id,
            audit_schema_version=1,
            branch=branch.value,
        )
        if chat_session_id is not None
        else nullcontext()
    ) as span:
        if span is not None and branch == RetrievalBranch.FULL_TEXT:
            span.set_attribute("search_terms", keywords)
        with active_branch_span(span):
            outcome = await _run_branch(branch, call, deadline, clock)
        if span is not None:
            if isinstance(outcome, FailedBranch) and "failure_kind" not in (
                span.attributes or {}
            ):
                span.set_attributes(
                    {
                        "failure_stage": "unavailable",
                        "failure_kind": "unspecified",
                        "diagnostic": "The retriever returned a failure without a diagnostic.",
                    }
                )
            span.set_attributes(
                {
                    "status": outcome.status,
                    "candidate_count": len(outcome.candidates)
                    if isinstance(outcome, SuccessfulBranch)
                    else 0,
                }
            )
        return outcome


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
        fusion_config: FusionConfig | None = None,
        context_limits: EvidenceContextLimits | None = None,
        deadline_seconds: float = 60,
        clock: Callable[[], float] | None = None,
        structural_reporting: bool = False,
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
        self._assembler = EvidenceAssembler(load_grounding=load_grounding)
        self._fusion_config = fusion_config or FusionConfig()
        self._context_limits = context_limits or EvidenceContextLimits()
        self._deadline_seconds = deadline_seconds
        self._clock = clock
        self._structural_reporting = structural_reporting

    async def run(
        self,
        rewrite: QueryRewrite,
        *,
        coverage: CoverageDescription,
        relevant_collection_ids: tuple[str, ...],
        monthly_coverage: tuple[MonthlyCoverage, ...] = (),
        usage: RunUsage | None = None,
        chat_session_id: str | None = None,
    ) -> EvidencePackage | EvidenceAssemblyFailure:
        clock = self._clock or asyncio.get_running_loop().time
        deadline = clock() + self._deadline_seconds
        request = RetrievalRequest(
            rewrite=rewrite, structural_reporting=self._structural_reporting
        )
        keywords = extract_full_text_keywords(rewrite)
        run_usage = RunUsage()
        calls = [
            partial(
                self._full_text.retrieve, request, deadline=deadline, keywords=keywords
            ),
            partial(self._dense.retrieve, request, deadline=deadline, usage=run_usage),
        ]
        if RetrievalBranch.STRUCTURAL in request.expected_branches:
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
                        _trace_branch(
                            branch, call, deadline, clock, chat_session_id, keywords
                        )
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
        if RetrievalBranch.STRUCTURAL not in request.expected_branches:
            skipped = SkippedBranch()
            outcomes.append(skipped)
            if chat_session_id is not None:
                logfire.info(
                    "chat_session.retrieval_branch",
                    chat_session_id=chat_session_id,
                    audit_schema_version=1,
                    candidate_count=0,
                    **skipped.model_dump(mode="json"),
                )
        execution = RetrievalExecutionResult(request=request, outcomes=tuple(outcomes))
        try:
            with selection_stage("fusion", chat_session_id):
                if clock() >= deadline:
                    raise TimeoutError
                fused = fuse_candidates(execution, config=self._fusion_config)
                if clock() >= deadline:
                    raise TimeoutError
            with selection_stage("evidence_assembly", chat_session_id):
                async with asyncio.timeout(deadline - clock()):
                    result = await self._assembler.assemble(
                        execution,
                        fused,
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
