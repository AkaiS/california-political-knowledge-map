"""Verify retained Grounding Evidence against original Stories."""

import json
import logging
from collections.abc import Awaitable, Callable

from pydantic import HttpUrl

from knowledge_map.schemas.evidence import EvidenceContextLimits
from knowledge_map.schemas.retrieval import (
    AppliedContextLimits,
    CoverageDescription,
    EvidenceAssemblyFailure,
    EvidencePackage,
    FusedCandidate,
    GroundingEvidence,
    MonthlyCoverage,
    RetrievalExecutionResult,
    SourceArticleCitation,
    SourceArticleEvidence,
    VerifiedPassage,
)
from knowledge_map.schemas.stories import Story

logger = logging.getLogger(__name__)


class EvidenceHydrationError(RuntimeError):
    """A storage adapter could not load the requested chunk or original Story."""


def render_evidence_context(package: EvidencePackage) -> str:
    """The measured Chat Agent input, without the pre-selection execution audit."""
    return json.dumps(
        {
            "question": package.execution.request.rewrite.question,
            "assessment": package.execution.request.rewrite.assessment.model_dump(
                mode="json"
            ),
            "branches": [
                {
                    "branch": outcome.branch.value,
                    "status": outcome.status,
                    **(
                        {"candidate_count": len(outcome.candidates)}
                        if outcome.status == "succeeded"
                        else {}
                    ),
                }
                for outcome in package.execution.outcomes
            ],
            "failure_disclosures": package.failure_disclosures,
            "sources": [
                source.model_dump(
                    mode="json",
                    exclude={
                        "passages": {
                            "__all__": {
                                "candidate": {
                                    "contributions": {
                                        "__all__": {"grounding"},
                                    }
                                }
                            }
                        },
                    },
                )
                for source in package.sources
            ],
            "coverage": package.coverage.model_dump(mode="json"),
            "monthly_coverage": [
                month.model_dump(mode="json") for month in package.monthly_coverage
            ],
            "omitted_passages": package.context.omitted_passages,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


class EvidenceAssembler:
    def __init__(
        self,
        *,
        load_grounding: Callable[[FusedCandidate], Awaitable[GroundingEvidence]],
        load_story: Callable[[SourceArticleCitation], Awaitable[Story]],
    ) -> None:
        self._load_grounding = load_grounding
        self._load_story = load_story

    async def assemble(
        self,
        execution: RetrievalExecutionResult,
        candidates: tuple[FusedCandidate, ...],
        *,
        coverage: CoverageDescription,
        relevant_collection_ids: tuple[str, ...],
        monthly_coverage: tuple[MonthlyCoverage, ...] = (),
        limits: EvidenceContextLimits | None = None,
    ) -> EvidencePackage | EvidenceAssemblyFailure:
        try:
            return await self._assemble(
                execution,
                candidates,
                coverage=coverage,
                relevant_collection_ids=relevant_collection_ids,
                monthly_coverage=monthly_coverage,
                limits=limits or EvidenceContextLimits(),
            )
        except (EvidenceHydrationError, LookupError, OSError, ValueError):
            logger.warning(
                "evidence_assembly_failed",
                extra={
                    "event": "evidence_assembly_failed",
                    "safe_diagnostic": "Grounding Evidence could not be assembled and verified.",
                },
            )
            return EvidenceAssemblyFailure(execution=execution)

    async def _assemble(
        self,
        execution: RetrievalExecutionResult,
        candidates: tuple[FusedCandidate, ...],
        *,
        coverage: CoverageDescription,
        relevant_collection_ids: tuple[str, ...],
        monthly_coverage: tuple[MonthlyCoverage, ...],
        limits: EvidenceContextLimits,
    ) -> EvidencePackage | EvidenceAssemblyFailure:
        if len({candidate.chunk_id for candidate in candidates}) != len(candidates):
            raise ValueError("fused candidates must identify distinct Article Chunks")
        sources: dict[str, SourceArticleEvidence] = {}
        entries = tuple(
            sorted(
                (
                    entry
                    for entry in coverage.entries
                    if entry.collection_id in relevant_collection_ids
                ),
                key=lambda entry: entry.collection_id,
            )
        )
        if {entry.collection_id for entry in entries} != set(
            relevant_collection_ids
        ) or len(entries) != len(set(relevant_collection_ids)):
            raise ValueError(
                "each relevant collection must have one Coverage Description entry"
            )
        selected_coverage = CoverageDescription(entries=entries)
        selected_months = tuple(
            sorted(
                (
                    month
                    for month in monthly_coverage
                    if month.collection_id in relevant_collection_ids
                ),
                key=lambda month: (month.collection_id, month.month),
            )
        )

        def package_for(
            selected: dict[str, SourceArticleEvidence],
            selected_passage_count: int,
        ) -> EvidencePackage:
            return EvidencePackage(
                execution=execution,
                sources=tuple(selected.values()),
                coverage=selected_coverage,
                monthly_coverage=selected_months,
                context=AppliedContextLimits(
                    unit="characters",
                    limit=limits.character_limit,
                    used=0,
                    max_passages=limits.max_passages,
                    omitted_passages=len(candidates) - selected_passage_count,
                ),
            )

        selected_passage_count = 0
        package = package_for(sources, selected_passage_count)
        ordered = sorted(
            candidates, key=lambda candidate: (candidate.rank, candidate.chunk_id)
        )
        for candidate in ordered:
            if selected_passage_count == limits.max_passages:
                break
            grounding = await self._load_grounding(candidate)
            if (
                grounding.chunk_id != candidate.chunk_id
                or grounding.citation.source_article_id != candidate.source_article_id
            ):
                raise ValueError("hydrated evidence belongs to another candidate")
            story = await self._load_story(grounding.citation)
            if HttpUrl(story.url) != grounding.citation.url:
                raise ValueError("the original Story belongs to another citation")
            if not story.content:
                return EvidenceAssemblyFailure(execution=execution)
            start = story.content.find(grounding.text)
            if start < 0:
                return EvidenceAssemblyFailure(execution=execution)
            passage = VerifiedPassage(
                source_article_id=candidate.source_article_id,
                text=grounding.text,
                start=start,
                end=start + len(grounding.text),
                verification="original_story",
                candidate=candidate,
            )
            previous = sources.get(candidate.source_article_id)
            if previous and previous.citation != grounding.citation:
                raise ValueError("one Source Article has conflicting citations")
            proposed = dict(sources)
            proposed[candidate.source_article_id] = SourceArticleEvidence(
                citation=grounding.citation,
                passages=(*previous.passages, passage) if previous else (passage,),
            )
            proposal = package_for(proposed, selected_passage_count + 1)
            if len(render_evidence_context(proposal)) <= limits.character_limit:
                sources = proposed
                package = proposal
                selected_passage_count += 1
        return package.model_copy(
            update={
                "context": AppliedContextLimits(
                    unit="characters",
                    limit=limits.character_limit,
                    used=len(render_evidence_context(package)),
                    max_passages=limits.max_passages,
                    omitted_passages=package.context.omitted_passages,
                )
            }
        )
