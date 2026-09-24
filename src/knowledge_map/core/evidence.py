"""Package retained Grounding Evidence for the Chat Agent."""

import json
import logging
from collections.abc import Awaitable, Callable

from pydantic import JsonValue

from knowledge_map.core.audit import observe_audit_metadata
from knowledge_map.schemas.evidence import EvidenceContextLimits
from knowledge_map.schemas.retrieval import (
    AppliedContextLimits,
    CoverageDescription,
    EvidenceAssemblyFailure,
    EvidencePackage,
    EvidencePassage,
    FusedCandidate,
    GroundingEvidence,
    MonthlyCoverage,
    RetrievalExecutionResult,
    SourceArticleEvidence,
)

logger = logging.getLogger(__name__)


class EvidenceHydrationError(RuntimeError):
    """A storage adapter could not load the requested Article Chunk."""


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
    ) -> None:
        self._load_grounding = load_grounding

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
                    "safe_diagnostic": "Grounding Evidence could not be assembled.",
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
            observe_audit_metadata(failure_kind="coverage")
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
        omitted: list[JsonValue] = []
        for index, candidate in enumerate(ordered):
            if selected_passage_count == limits.max_passages:
                omitted.extend(
                    {"chunk_id": remaining.chunk_id, "reason": "passage_limit"}
                    for remaining in ordered[index:]
                )
                break
            try:
                grounding = await self._load_grounding(candidate)
            except (EvidenceHydrationError, LookupError, OSError, ValueError):
                observe_audit_metadata(failure_kind="hydration")
                raise
            if (
                grounding.chunk_id != candidate.chunk_id
                or grounding.citation.source_article_id != candidate.source_article_id
            ):
                observe_audit_metadata(failure_kind="provenance")
                raise ValueError("hydrated evidence belongs to another candidate")
            passage = EvidencePassage(
                source_article_id=candidate.source_article_id,
                text=grounding.text,
                provenance="stored_chunk",
                candidate=candidate,
            )
            previous = sources.get(candidate.source_article_id)
            if previous and previous.citation != grounding.citation:
                observe_audit_metadata(failure_kind="provenance")
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
            else:
                omitted.append(
                    {"chunk_id": candidate.chunk_id, "reason": "character_limit"}
                )
        try:
            context = AppliedContextLimits(
                unit="characters",
                limit=limits.character_limit,
                used=len(render_evidence_context(package)),
                max_passages=limits.max_passages,
                omitted_passages=package.context.omitted_passages,
            )
        except ValueError:
            observe_audit_metadata(failure_kind="budget")
            raise
        result = package.model_copy(update={"context": context})
        observe_audit_metadata(omitted_candidates=omitted)
        return result
