"""Original Story evidence returned at the assembly boundary."""

import asyncio
import json

import pytest
from pydantic import HttpUrl, ValidationError

from knowledge_map.core.evidence import (
    EvidenceAssembler,
    EvidenceHydrationError,
    render_evidence_context,
)
from knowledge_map.core.fusion import fuse_candidates
from knowledge_map.schemas.evidence import EvidenceContextLimits
from knowledge_map.schemas.query_preparation import QueryRewrite, QuestionAssessment
from knowledge_map.schemas.retrieval import (
    BranchCandidate,
    BranchRanking,
    CoverageAvailability,
    CoverageDescription,
    CoverageEntry,
    EvidenceAssemblyFailure,
    EvidencePackage,
    FailedBranch,
    GraphClaim,
    GraphNodeReference,
    GroundingEvidence,
    MonthlyCoverage,
    RetrievalBranch,
    RetrievalExecutionResult,
    RetrievalRequest,
    RetrievalRoute,
    SourceArticleCitation,
    SuccessfulBranch,
)
from knowledge_map.schemas.stories import Story


def candidate(chunk="a", article="https://example.com/a", rank=1):
    return BranchCandidate(
        chunk_id=chunk,
        source_article_id=article,
        ranking=BranchRanking(branch=RetrievalBranch.FULL_TEXT, rank=rank, score=None),
        routes=(
            RetrievalRoute(
                kind="chunk_text",
                matched_field="text",
                entry_node=GraphNodeReference(id=chunk, label="Chunk"),
            ),
        ),
    )


def execution(*candidates):
    return RetrievalExecutionResult(
        request=RetrievalRequest(
            rewrite=QueryRewrite(
                question="Which organizations support AB 1?",
                relational=True,
                assessment=QuestionAssessment(status="allowed"),
            )
        ),
        outcomes=tuple(
            SuccessfulBranch(
                branch=branch,
                candidates=tuple(c for c in candidates if c.ranking.branch == branch),
            )
            for branch in RetrievalBranch
        ),
    )


class EvidenceStore:
    def __init__(self, rows):
        self.rows = rows

    async def load_grounding(self, candidate):
        text, _ = self.rows[candidate.chunk_id]
        return GroundingEvidence(
            chunk_id=candidate.chunk_id,
            text=text,
            citation=SourceArticleCitation(
                source_article_id=candidate.source_article_id,
                title="Original reporting",
                url=HttpUrl(candidate.source_article_id),
                published_date="2026-09-01",
            ),
        )

    async def load_story(self, citation):
        return self.rows[
            next(
                chunk
                for chunk, (_, story) in self.rows.items()
                if story.url == str(citation.url)
            )
        ][1]


def assemble(store, retained, *, coverage=None, relevant_collection_ids=(), **kwargs):
    return asyncio.run(
        EvidenceAssembler(
            load_grounding=store.load_grounding,
            load_story=store.load_story,
        ).assemble(
            retained,
            fuse_candidates(retained),
            coverage=coverage or CoverageDescription(entries=()),
            relevant_collection_ids=relevant_collection_ids,
            **kwargs,
        )
    )


def test_selected_wording_is_verified_against_the_original_story():
    story = Story(
        url="https://example.com/a",
        title="Original reporting",
        content="Introduction. The union supports AB 1. More reporting.",
    )
    retained = execution(candidate())

    result = assemble(
        EvidenceStore({"a": ("The union supports AB 1.", story)}), retained
    )

    assert isinstance(result, EvidencePackage)
    passage = result.sources[0].passages[0]
    assert (passage.text, passage.start, passage.end, passage.verification) == (
        "The union supports AB 1.",
        14,
        38,
        "original_story",
    )
    assert result.sources[0].citation.url == HttpUrl(story.url)
    assert (
        passage.candidate.contributions
        == retained.evidence_by_branch[RetrievalBranch.FULL_TEXT]
    )


@pytest.mark.parametrize("body", ["She supports AB 1.", None, ""])
def test_unverifiable_wording_is_an_assembly_failure_without_changing_branches(body):
    story = Story(url="https://example.com/a", title="Original reporting", content=body)
    retained = execution(candidate())

    result = assemble(
        EvidenceStore({"a": ("Senator Smith supports AB 1.", story)}), retained
    )

    assert isinstance(result, EvidenceAssemblyFailure)
    assert result.execution == retained
    assert result.execution.failed_branches == ()
    assert result.model_dump()["outcome"] == "assembly_failed"


def test_passages_group_by_source_without_losing_distant_passages_or_graph_routes():
    article_a = "https://example.com/a"
    article_b = "https://example.com/b"
    story_a = Story(
        url=article_a,
        title="Original reporting",
        content="First passage. Other context. Last passage.",
    )
    story_b = Story(url=article_b, title="Other reporting", content="Another article.")
    first = candidate("a-first", article_a, 1)
    claim = GraphClaim(
        source=GraphNodeReference(
            id="union", label="Organization", element_id="entity-1"
        ),
        target=GraphNodeReference(id="AB 1", label="Bill", element_id="entity-2"),
        relationship_type="SUPPORTS",
        claim_key={},
        chunk_ids=("a-first",),
    )
    structural = BranchCandidate(
        chunk_id="a-first",
        source_article_id=article_a,
        ranking=BranchRanking(branch=RetrievalBranch.STRUCTURAL, rank=1, score=None),
        routes=(
            RetrievalRoute(
                kind="typed_traversal",
                matched_field=None,
                entry_node=claim.source,
                graph_claims=(claim,),
            ),
        ),
    )
    retained = execution(
        first,
        candidate("b", article_b, 2),
        candidate("a-last", article_a, 3),
        structural,
    )
    store = EvidenceStore(
        {
            "a-first": ("First passage.", story_a),
            "b": ("Another article.", story_b),
            "a-last": ("Last passage.", story_a),
        }
    )

    result = assemble(store, retained)

    assert isinstance(result, EvidencePackage)
    assert [
        (source.citation.source_article_id, [p.text for p in source.passages])
        for source in result.sources
    ] == [
        (article_a, ["First passage.", "Last passage."]),
        (article_b, ["Another article."]),
    ]
    restored = EvidencePackage.model_validate_json(result.model_dump_json())
    assert restored.sources[0].passages[0].candidate.contributions == (
        first,
        structural,
    )
    assert restored.execution == retained


def coverage_entry(collection_id):
    return CoverageEntry(
        collection_id=collection_id,
        name=collection_id,
        kind="publication",
        description="Reporting about California politics.",
        limitations=("Publication dates do not establish event dates.",),
        availability=CoverageAvailability(available_count=20),
        date_basis="publication_date",
    )


def test_only_relevant_coverage_and_requested_monthly_detail_accompany_empty_evidence():
    relevant = coverage_entry("relevant")
    unrelated = coverage_entry("unrelated")
    month = MonthlyCoverage(
        collection_id="relevant",
        month="2026-09",
        availability=CoverageAvailability(available_count=2),
    )
    other_month = MonthlyCoverage(
        collection_id="unrelated",
        month="2026-08",
        availability=CoverageAvailability(available_count=3),
    )

    result = assemble(
        EvidenceStore({}),
        execution(),
        coverage=CoverageDescription(entries=(unrelated, relevant)),
        relevant_collection_ids=("relevant",),
        monthly_coverage=(other_month, month),
    )

    assert isinstance(result, EvidencePackage)
    assert result.sources == ()
    assert result.coverage.entries == (relevant,)
    assert result.monthly_coverage == (month,)


def test_passage_limit_keeps_the_highest_rank_and_measures_the_rendered_context():
    story = Story(
        url="https://example.com/a",
        title="Original reporting",
        content="First passage. Last passage.",
    )
    retained = execution(candidate("last", rank=2), candidate("first", rank=1))

    result = assemble(
        EvidenceStore(
            {"first": ("First passage.", story), "last": ("Last passage.", story)}
        ),
        retained,
        limits=EvidenceContextLimits(character_limit=24000, max_passages=1),
    )

    assert isinstance(result, EvidencePackage)
    assert [p.text for s in result.sources for p in s.passages] == ["First passage."]
    assert result.context.max_passages == 1
    assert result.context.omitted_passages == 1
    context = render_evidence_context(result)
    assert result.context.unit == "characters"
    assert result.context.used == len(context)
    rendered = json.loads(context)
    assert rendered["sources"][0]["citation"]["url"] == story.url
    assert rendered["sources"][0]["passages"][0]["text"] == "First passage."
    assert "Last passage." not in context
    assert "execution" not in rendered
    assert rendered["omitted_passages"] == 1


def test_character_budget_skips_an_oversized_passage_and_keeps_later_evidence():
    story = Story(
        url="https://example.com/a",
        title="Original reporting",
        content="Long reporting. " * 1000 + "Short passage.",
    )
    retained = execution(candidate("large", rank=1), candidate("small", rank=2))
    store = EvidenceStore(
        {
            "large": ("Long reporting. " * 1000, story),
            "small": ("Short passage.", story),
        }
    )

    result = assemble(
        store, retained, limits=EvidenceContextLimits(character_limit=2000)
    )

    assert isinstance(result, EvidencePackage)
    assert [p.text for s in result.sources for p in s.passages] == ["Short passage."]
    assert result.context.omitted_passages == 1
    assert 14 < result.context.used <= 2000
    assert result.context.used == len(render_evidence_context(result))
    assert result.execution == retained
    repeated = assemble(
        store, retained, limits=EvidenceContextLimits(character_limit=2000)
    )
    assert result == repeated


@pytest.mark.parametrize(
    "problem", ["missing", "wrong_chunk", "wrong_source", "wrong_story", "lost_route"]
)
def test_failed_hydration_never_misattributes_evidence_or_changes_failed_branches(
    problem,
):
    class BrokenStore(EvidenceStore):
        async def load_grounding(self, candidate):
            if problem == "missing":
                raise EvidenceHydrationError("Private database location")
            grounding = await super().load_grounding(candidate)
            if problem == "wrong_chunk":
                return grounding.model_copy(update={"chunk_id": "some-other-chunk"})
            if problem == "wrong_source":
                return grounding.model_copy(
                    update={
                        "citation": grounding.citation.model_copy(
                            update={"source_article_id": "some-other-source"}
                        )
                    }
                )
            return grounding

        async def load_story(self, citation):
            story = await super().load_story(citation)
            if problem == "wrong_story":
                return story.model_copy(
                    update={"url": "https://unrelated.example/story"}
                )
            return story

    story = Story(
        url="https://example.com/a", title="Original reporting", content="Verbatim."
    )
    retained = execution(candidate())
    retained = RetrievalExecutionResult(
        request=retained.request,
        outcomes=(
            *retained.outcomes[:2],
            FailedBranch(branch=RetrievalBranch.STRUCTURAL),
        ),
    )
    fused = fuse_candidates(retained)
    if problem == "lost_route":
        changed = (
            fused[0]
            .contributions[0]
            .model_copy(
                update={
                    "ranking": BranchRanking(
                        branch=RetrievalBranch.FULL_TEXT, rank=9, score=None
                    )
                }
            )
        )
        fused = (fused[0].model_copy(update={"contributions": (changed,)}),)
    store = BrokenStore({"a": ("Verbatim.", story)})

    result = asyncio.run(
        EvidenceAssembler(
            load_grounding=store.load_grounding,
            load_story=store.load_story,
        ).assemble(
            retained,
            fused,
            coverage=CoverageDescription(entries=()),
            relevant_collection_ids=(),
        )
    )

    assert isinstance(result, EvidenceAssemblyFailure)
    assert result.execution == retained
    assert result.execution.failed_branches == (RetrievalBranch.STRUCTURAL,)
    assert "Private database" not in result.model_dump_json()


@pytest.mark.parametrize(
    "entries,ids",
    [
        ((), ("missing",)),
        ((coverage_entry("relevant"), coverage_entry("relevant")), ("relevant",)),
    ],
)
def test_requested_coverage_must_be_available_and_unambiguous(entries, ids):
    result = assemble(
        EvidenceStore({}),
        execution(),
        coverage=CoverageDescription(entries=entries),
        relevant_collection_ids=ids,
    )

    assert isinstance(result, EvidenceAssemblyFailure)


def test_relevant_coverage_and_months_have_a_stable_order():
    coverage = CoverageDescription(entries=(coverage_entry("z"), coverage_entry("a")))
    months = tuple(
        MonthlyCoverage(
            collection_id=collection,
            month=month,
            availability=CoverageAvailability(available_count=1),
        )
        for collection, month in [("z", "2026-08"), ("a", "2026-09"), ("a", "2026-08")]
    )
    result = assemble(
        EvidenceStore({}),
        execution(),
        coverage=coverage,
        relevant_collection_ids=("z", "a"),
        monthly_coverage=months,
    )

    assert isinstance(result, EvidencePackage)
    assert [entry.collection_id for entry in result.coverage.entries] == ["a", "z"]
    assert [
        (month.collection_id, month.month) for month in result.monthly_coverage
    ] == [
        ("a", "2026-08"),
        ("a", "2026-09"),
        ("z", "2026-08"),
    ]


def test_conflicting_citations_cannot_overwrite_the_first_passages_source():
    class ConflictingStore(EvidenceStore):
        async def load_grounding(self, candidate):
            grounding = await super().load_grounding(candidate)
            if candidate.chunk_id == "last":
                return grounding.model_copy(
                    update={
                        "citation": grounding.citation.model_copy(
                            update={"title": "A different article"}
                        )
                    }
                )
            return grounding

    story = Story(
        url="https://example.com/a", title="Original reporting", content="First. Last."
    )
    result = assemble(
        ConflictingStore({"first": ("First.", story), "last": ("Last.", story)}),
        execution(candidate("first", rank=1), candidate("last", rank=2)),
    )

    assert isinstance(result, EvidenceAssemblyFailure)


def test_duplicate_fused_chunks_are_an_assembly_failure():
    story = Story(
        url="https://example.com/a", title="Original reporting", content="Verbatim."
    )
    store = EvidenceStore({"a": ("Verbatim.", story)})
    retained = execution(candidate())
    fused = fuse_candidates(retained)

    result = asyncio.run(
        EvidenceAssembler(
            load_grounding=store.load_grounding,
            load_story=store.load_story,
        ).assemble(
            retained,
            (*fused, *fused),
            coverage=CoverageDescription(entries=()),
            relevant_collection_ids=(),
        )
    )

    assert isinstance(result, EvidenceAssemblyFailure)


def test_budget_includes_coverage_disclosures_and_citations_at_the_exact_boundary():
    story = Story(
        url="https://example.com/a", title="Original reporting", content="Verbatim."
    )
    store = EvidenceStore({"a": ("Verbatim.", story)})
    retained = execution(candidate())
    retained = RetrievalExecutionResult(
        request=retained.request,
        outcomes=(
            *retained.outcomes[:2],
            FailedBranch(branch=RetrievalBranch.STRUCTURAL),
        ),
    )
    options = {
        "coverage": CoverageDescription(entries=(coverage_entry("relevant"),)),
        "relevant_collection_ids": ("relevant",),
    }
    unbounded = assemble(store, retained, **options)
    assert isinstance(unbounded, EvidencePackage)
    boundary = len(render_evidence_context(unbounded))

    exact = assemble(
        store,
        retained,
        **options,
        limits=EvidenceContextLimits(character_limit=boundary),
    )
    too_small = assemble(
        store,
        retained,
        **options,
        limits=EvidenceContextLimits(character_limit=boundary - 1),
    )

    assert isinstance(exact, EvidencePackage)
    assert exact.sources == unbounded.sources
    assert exact.context.used == boundary
    assert isinstance(too_small, EvidencePackage)
    assert too_small.sources == ()
    assert too_small.context.omitted_passages == 1
    assert too_small.coverage == unbounded.coverage
    assert too_small.failure_disclosures == (
        "Graph connections matching the question could not be searched.",
    )


def test_coverage_that_exceeds_the_whole_budget_fails_without_dropping_its_limit():
    retained = execution()
    result = assemble(
        EvidenceStore({}),
        retained,
        coverage=CoverageDescription(entries=(coverage_entry("relevant"),)),
        relevant_collection_ids=("relevant",),
        limits=EvidenceContextLimits(character_limit=10),
    )

    assert result == EvidenceAssemblyFailure(execution=retained)


def test_rendered_context_excludes_unverified_chunk_wording_but_retains_routes():
    story = Story(
        url="https://example.com/a",
        title="Original reporting",
        content="She supports AB 1.",
    )
    stored = GroundingEvidence(
        chunk_id="a",
        text="Senator Smith supports AB 1.",
        citation=SourceArticleCitation(
            source_article_id=story.url, title=story.title, url=HttpUrl(story.url)
        ),
    )
    retained = execution(candidate().model_copy(update={"grounding": stored}))
    result = assemble(EvidenceStore({"a": ("She supports AB 1.", story)}), retained)

    assert isinstance(result, EvidencePackage)
    context = render_evidence_context(result)
    assert "Senator Smith supports AB 1." not in context
    assert "She supports AB 1." in context
    assert (
        json.loads(context)["sources"][0]["passages"][0]["candidate"]["contributions"][
            0
        ]["routes"][0]["kind"]
        == "chunk_text"
    )
    assert (
        result.execution.evidence_by_branch[RetrievalBranch.FULL_TEXT][0].grounding
        == stored
    )


def test_rendered_context_distinguishes_empty_search_failure_and_budget_omission():
    story = Story(
        url="https://example.com/a", title="Original reporting", content="Verbatim."
    )
    retained = execution(candidate())
    retained = RetrievalExecutionResult(
        request=retained.request,
        outcomes=(
            retained.outcomes[0],
            FailedBranch(branch=RetrievalBranch.DENSE),
            retained.outcomes[2],
        ),
    )
    result = assemble(
        EvidenceStore({"a": ("Verbatim.", story)}),
        retained,
        limits=EvidenceContextLimits(character_limit=600),
    )

    assert isinstance(result, EvidencePackage)
    rendered = json.loads(render_evidence_context(result))
    assert rendered["sources"] == []
    assert rendered["branches"] == [
        {"branch": "full_text", "status": "succeeded", "candidate_count": 1},
        {"branch": "dense", "status": "failed"},
        {"branch": "structural", "status": "succeeded", "candidate_count": 0},
    ]
    assert rendered["failure_disclosures"] == [
        "Dense retrieval could not be completed."
    ]


@pytest.mark.parametrize("field", ["character_limit", "max_passages"])
@pytest.mark.parametrize("value", [0, -1, True, 1.5, "12"])
def test_context_limits_require_positive_integer_counts(field, value):
    with pytest.raises(ValidationError):
        EvidenceContextLimits.model_validate({field: value})
