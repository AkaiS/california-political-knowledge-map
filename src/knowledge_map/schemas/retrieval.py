"""Typed retrieval handoffs consumed by branches, fusion, and the Chat Agent."""

from datetime import date
from enum import StrEnum
from typing import Annotated, Any, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    FiniteFloat,
    HttpUrl,
    RootModel,
    StringConstraints,
    model_validator,
)

from knowledge_map.schemas.query_preparation import QueryRewrite, ReadingOrder

type NonemptyText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1)
]
type Rank = Annotated[int, Field(strict=True, ge=1)]
type Count = Annotated[int, Field(strict=True, ge=0)]


class RetrievalValue(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class BranchScore(RootModel[FiniteFloat]):
    """An opaque branch-local score that has no cross-branch ordering."""

    model_config = ConfigDict(frozen=True)


class RetrievalBranch(StrEnum):
    FULL_TEXT = "full_text"
    DENSE = "dense"
    STRUCTURAL = "structural"


class RetrievalRequest(RetrievalValue):
    rewrite: QueryRewrite
    structural_reporting: bool = False

    @model_validator(mode="after")
    def require_retrievable_question(self) -> Self:
        if self.rewrite.assessment.status in {"declined", "needs_edit"}:
            raise ValueError("a Declined or unresolved question cannot enter retrieval")
        return self

    @property
    def expected_branches(self) -> tuple[RetrievalBranch, ...]:
        branches = (RetrievalBranch.FULL_TEXT, RetrievalBranch.DENSE)
        if self.rewrite.relational or self.structural_reporting:
            return (*branches, RetrievalBranch.STRUCTURAL)
        return branches


class GraphNodeReference(RetrievalValue):
    id: NonemptyText
    label: NonemptyText
    element_id: NonemptyText | None = None


class GraphClaim(RetrievalValue):
    source: GraphNodeReference
    target: GraphNodeReference
    relationship_type: NonemptyText
    claim_key: dict[str, str | int | FiniteFloat | bool | None]
    chunk_ids: tuple[NonemptyText, ...] = ()
    source_article_ids: tuple[NonemptyText, ...] = ()
    needs_review: bool = False

    @model_validator(mode="after")
    def require_provenance_at_the_claims_decision_grain(self) -> Self:
        article_level = self.relationship_type in {
            "ABOUT_TOPIC",
            "DISCUSSES_TOPIC",
        }
        if article_level:
            if not self.source_article_ids or self.chunk_ids:
                raise ValueError(
                    "an article-level topic claim must name only its asserting Source Articles"
                )
        elif not self.chunk_ids or self.source_article_ids:
            raise ValueError(
                "a chunk-level claim must name only its asserting Article Chunks"
            )
        return self


class RetrievalRoute(RetrievalValue):
    kind: Literal[
        "entity_name",
        "article_title",
        "chunk_text",
        "chunk_embedding",
        "typed_traversal",
    ]
    matched_field: Literal["name", "title", "text", "embedding"] | None
    entry_node: GraphNodeReference
    graph_claims: tuple[GraphClaim, ...] = ()


class BranchRanking(RetrievalValue):
    """A score has meaning only with its originating branch and ordinal rank."""

    branch: RetrievalBranch
    rank: Rank
    score: BranchScore | None


class BranchCandidate(RetrievalValue):
    chunk_id: NonemptyText
    source_article_id: NonemptyText
    ranking: BranchRanking
    routes: Annotated[tuple[RetrievalRoute, ...], Field(min_length=1)]
    grounding: "GroundingEvidence | None" = None

    @model_validator(mode="after")
    def routes_belong_to_branch(self) -> Self:
        if self.grounding is not None and (
            self.grounding.chunk_id != self.chunk_id
            or self.grounding.citation.source_article_id != self.source_article_id
        ):
            raise ValueError("Grounding Evidence must belong to the candidate")
        matches = {
            "entity_name": (RetrievalBranch.FULL_TEXT, "name"),
            "article_title": (RetrievalBranch.FULL_TEXT, "title"),
            "chunk_text": (RetrievalBranch.FULL_TEXT, "text"),
            "chunk_embedding": (RetrievalBranch.DENSE, "embedding"),
            "typed_traversal": (RetrievalBranch.STRUCTURAL, None),
        }
        for route in self.routes:
            if matches[route.kind] != (self.ranking.branch, route.matched_field):
                raise ValueError(
                    "route and matched field must belong to the scored branch"
                )
        return self


class FusedCandidate(RetrievalValue):
    chunk_id: NonemptyText
    rank: Rank
    fusion_score: Annotated[FiniteFloat, Field(ge=0)]
    contributions: Annotated[tuple[BranchCandidate, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def contributions_refer_to_one_chunk(self) -> Self:
        if any(candidate.chunk_id != self.chunk_id for candidate in self.contributions):
            raise ValueError("all contributions must refer to the same Article Chunk")
        if len({candidate.source_article_id for candidate in self.contributions}) != 1:
            raise ValueError("all contributions must refer to the same Source Article")
        return self

    @property
    def source_article_id(self) -> str:
        return self.contributions[0].source_article_id


class SuccessfulBranch(RetrievalValue):
    branch: RetrievalBranch
    status: Literal["succeeded"] = "succeeded"
    candidates: tuple[BranchCandidate, ...]
    construction: dict[str, Any] | None = None
    semantic_results: tuple[dict[str, Any], ...] = ()

    @model_validator(mode="after")
    def rankings_belong_to_branch(self) -> Self:
        if any(
            candidate.ranking.branch != self.branch for candidate in self.candidates
        ):
            raise ValueError("candidate scores and ranks must belong to their branch")
        return self


class FailedBranch(RetrievalValue):
    branch: RetrievalBranch
    status: Literal["failed"] = "failed"
    construction: dict[str, Any] | None = None


class SkippedBranch(RetrievalValue):
    branch: Literal[RetrievalBranch.STRUCTURAL] = RetrievalBranch.STRUCTURAL
    status: Literal["skipped"] = "skipped"
    reason: Literal["non_relational"] = "non_relational"


type BranchOutcome = Annotated[
    SuccessfulBranch | FailedBranch | SkippedBranch, Field(discriminator="status")
]


class RetrievalExecutionResult(RetrievalValue):
    request: RetrievalRequest
    expected_branches: tuple[RetrievalBranch, ...] = Field(
        default_factory=lambda data: data["request"].expected_branches
    )
    outcomes: tuple[BranchOutcome, ...]

    @model_validator(mode="after")
    def account_for_every_branch(self) -> Self:
        if self.expected_branches != self.request.expected_branches:
            raise ValueError("expected branches must follow the approved Query Rewrite")
        branches = [outcome.branch for outcome in self.outcomes]
        if len(branches) != len(RetrievalBranch) or set(branches) != set(
            RetrievalBranch
        ):
            raise ValueError("record exactly one outcome for every retrieval branch")
        for outcome in self.outcomes:
            expected = outcome.branch in self.expected_branches
            if expected == (outcome.status == "skipped"):
                raise ValueError("only an unexpected structural branch may be skipped")
        return self

    @property
    def failed_branches(self) -> tuple[RetrievalBranch, ...]:
        return tuple(
            outcome.branch for outcome in self.outcomes if outcome.status == "failed"
        )

    @property
    def evidence_by_branch(self) -> dict[RetrievalBranch, tuple[BranchCandidate, ...]]:
        return {
            outcome.branch: outcome.candidates
            for outcome in self.outcomes
            if outcome.status == "succeeded"
        }

    @property
    def failure_disclosures(self) -> tuple[str, ...]:
        messages = {
            RetrievalBranch.STRUCTURAL: "Graph connections matching the question could not be searched.",
            RetrievalBranch.FULL_TEXT: "Full-text retrieval could not be completed.",
            RetrievalBranch.DENSE: "Dense retrieval could not be completed.",
        }
        return tuple(
            message
            for branch, message in messages.items()
            if branch in self.failed_branches
        )

    @property
    def structural_empty_disclosure(self) -> str | None:
        structural = self.evidence_by_branch.get(RetrievalBranch.STRUCTURAL)
        if structural == ():
            return "No matching graph connections were found in the available graph."
        return None


class RetrievalFailureLog(RetrievalValue):
    """Operational detail for structured logs, never nested in an answer value."""

    branch: RetrievalBranch
    stage: Literal[
        "preparation",
        "index",
        "execution",
        "schema_filtering",
        "typed_selection",
        "wiring",
        "binding",
        "validation",
        "hop_bound",
        "cypher_execution",
        "hydration",
        "deadline",
    ]
    failure_kind: Literal[
        "transport",
        "model_output",
        "validation",
        "attempts_exhausted",
        "hop_bound_exhausted",
        "index_unavailable",
        "database",
        "hydration",
        "deadline_exhausted",
        "unexpected",
    ]
    attempts_consumed: Count
    safe_diagnostic: NonemptyText

    @property
    def deadline_exhausted(self) -> bool:
        return self.failure_kind == "deadline_exhausted"


class CoverageAvailability(RetrievalValue):
    available_count: Count
    expected_count: Count | None = None

    @model_validator(mode="after")
    def known_total_bounds_available_material(self) -> Self:
        if (
            self.expected_count is not None
            and self.available_count > self.expected_count
        ):
            raise ValueError("available material cannot exceed the known expected set")
        return self

    @property
    def percentage(self) -> float | None:
        if not self.expected_count:
            return None
        return 100 * self.available_count / self.expected_count


class CoverageEntry(RetrievalValue):
    collection_id: NonemptyText
    name: NonemptyText
    kind: Literal["publication", "public_record"]
    description: NonemptyText
    limitations: tuple[NonemptyText, ...] = ()
    availability: CoverageAvailability
    date_basis: Literal["publication_date", "event_date"]
    earliest_date: date | None = None
    latest_date: date | None = None

    @model_validator(mode="after")
    def news_dates_describe_publication(self) -> Self:
        if self.kind == "publication" and self.date_basis != "publication_date":
            raise ValueError("news coverage dates must be Story publication dates")
        if (
            self.earliest_date
            and self.latest_date
            and self.earliest_date > self.latest_date
        ):
            raise ValueError("coverage dates must be chronological")
        return self


class CoverageDescription(RetrievalValue):
    entries: tuple[CoverageEntry, ...]


class MonthlyCoverage(RetrievalValue):
    """Separate, on-demand detail with this month's own expected denominator."""

    collection_id: NonemptyText
    month: Annotated[str, StringConstraints(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")]
    availability: CoverageAvailability


class SourceArticleCitation(RetrievalValue):
    source_article_id: NonemptyText
    title: NonemptyText
    url: HttpUrl
    published_date: NonemptyText | None = None


class GroundingEvidence(RetrievalValue):
    """Stored chunk wording and its Source Article citation."""

    chunk_id: NonemptyText
    text: Annotated[str, Field(min_length=1)]
    citation: SourceArticleCitation


class EvidencePassage(RetrievalValue):
    """Stored Article Chunk wording selected by Evidence Assembly."""

    source_article_id: NonemptyText
    text: Annotated[str, Field(min_length=1)]
    provenance: Literal["stored_chunk"]
    candidate: FusedCandidate


class SourceArticleEvidence(RetrievalValue):
    citation: SourceArticleCitation
    passages: Annotated[tuple[EvidencePassage, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def passages_belong_to_cited_source(self) -> Self:
        if any(
            passage.source_article_id != self.citation.source_article_id
            for passage in self.passages
        ):
            raise ValueError("every passage must belong to its cited Source Article")
        if any(
            passage.candidate.source_article_id != self.citation.source_article_id
            for passage in self.passages
        ):
            raise ValueError(
                "every passage candidate must come from its cited Source Article"
            )
        return self


class AppliedContextLimits(RetrievalValue):
    unit: Literal["characters", "tokens"]
    limit: Rank
    used: Count
    max_passages: Rank
    omitted_passages: Count

    @model_validator(mode="after")
    def measured_context_fits_limit(self) -> Self:
        if self.used > self.limit:
            raise ValueError("measured context usage exceeds the applied limit")
        return self


class EvidencePackage(RetrievalValue):
    execution: RetrievalExecutionResult
    sources: tuple[SourceArticleEvidence, ...]
    coverage: CoverageDescription
    monthly_coverage: tuple[MonthlyCoverage, ...] = ()
    context: AppliedContextLimits

    @model_validator(mode="after")
    def evidence_retains_provenance_within_limits(self) -> Self:
        collections = {entry.collection_id for entry in self.coverage.entries}
        if any(
            month.collection_id not in collections for month in self.monthly_coverage
        ):
            raise ValueError("monthly coverage must belong to a relevant collection")
        ids = [source.citation.source_article_id for source in self.sources]
        if len(ids) != len(set(ids)):
            raise ValueError("present each Source Article once, grouping its passages")
        passages = [passage for source in self.sources for passage in source.passages]
        if len(passages) > self.context.max_passages:
            raise ValueError("passages exceed the applied context limit")
        candidates = [
            candidate
            for branch_candidates in self.execution.evidence_by_branch.values()
            for candidate in branch_candidates
        ]
        for passage in passages:
            contributions = passage.candidate.contributions
            expected = [
                candidate
                for candidate in candidates
                if candidate.chunk_id == passage.candidate.chunk_id
            ]
            if len(contributions) != len(expected) or any(
                candidate not in contributions for candidate in expected
            ):
                raise ValueError(
                    "a selected passage must retain every recorded candidate contribution"
                )
        return self

    @property
    def failed_branches(self) -> tuple[RetrievalBranch, ...]:
        return self.execution.failed_branches

    @property
    def failure_disclosures(self) -> tuple[str, ...]:
        return self.execution.failure_disclosures


class EvidenceAssemblyFailure(RetrievalValue):
    outcome: Literal["assembly_failed"] = "assembly_failed"
    execution: RetrievalExecutionResult

    @property
    def failure_disclosures(self) -> tuple[str, ...]:
        disclosures = list(self.execution.failure_disclosures)
        structural_empty = self.execution.structural_empty_disclosure
        if structural_empty:
            disclosures.append(structural_empty)
        disclosures.append("Grounding Evidence could not be assembled.")
        return tuple(disclosures)


class SourceRelevanceNote(RetrievalValue):
    source_article_id: NonemptyText
    note: NonemptyText


class SourceDisagreement(RetrievalValue):
    source_article_ids: Annotated[tuple[NonemptyText, ...], Field(min_length=2)]
    description: NonemptyText


class ArticleGroupMember(RetrievalValue):
    source_article_id: NonemptyText
    reading_direction: NonemptyText
    reported_event_date: NonemptyText | None = None


class ArticleGroup(RetrievalValue):
    kind: Literal["contrast", "timeline", "aspect"]
    label: NonemptyText
    members: tuple[ArticleGroupMember, ...]
    order: ReadingOrder = "relevance"

    @model_validator(mode="after")
    def valid_reading_view(self) -> Self:
        if (self.kind == "timeline") != (self.order != "relevance"):
            raise ValueError(
                "only timeline groups have a chronological basis and order"
            )
        return self


class RetrievalAnswer(RetrievalValue):
    guidance_contract: Literal[1, 2, 3] = 1
    evidence: EvidencePackage
    introduction: NonemptyText | None = None
    source_notes: tuple[SourceRelevanceNote, ...] = ()
    disagreements: tuple[SourceDisagreement, ...] = ()
    groups: tuple[ArticleGroup, ...] = ()

    @model_validator(mode="after")
    def guidance_refers_to_selected_sources(self) -> Self:
        selected = {
            source.citation.source_article_id for source in self.evidence.sources
        }
        if any(note.source_article_id not in selected for note in self.source_notes):
            raise ValueError("relevance notes must refer to selected sources")
        if self.guidance_contract >= 2:
            noted = [note.source_article_id for note in self.source_notes]
            if len(noted) != len(set(noted)):
                raise ValueError(
                    "each included article must have one reading direction"
                )
        included = {note.source_article_id for note in self.source_notes}
        if any(
            member.source_article_id not in included
            for group in self.groups
            for member in group.members
        ):
            raise ValueError("group memberships must refer to included articles")
        for disagreement in self.disagreements:
            sources = set(disagreement.source_article_ids)
            if len(sources) < 2 or not sources <= selected:
                raise ValueError(
                    "disagreements must refer to distinct selected sources"
                )
        return self


BranchCandidate.model_rebuild()
