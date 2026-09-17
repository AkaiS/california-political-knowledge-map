"""Approved questions retain branch evidence through the retrieval handoff."""

import asyncio
import logging

import pytest
from pydantic_ai.usage import RunUsage

from knowledge_map.core.retrieval import RetrievalCoordinator
from knowledge_map.schemas.fusion import FusionConfig
from knowledge_map.schemas.query_preparation import QueryRewrite, QuestionAssessment
from knowledge_map.schemas.retrieval import (
    BranchCandidate,
    BranchRanking,
    CoverageAvailability,
    CoverageDescription,
    CoverageEntry,
    EvidenceAssemblyFailure,
    EvidencePackage,
    GraphNodeReference,
    GroundingEvidence,
    RetrievalBranch,
    RetrievalRoute,
    SourceArticleCitation,
    SuccessfulBranch,
)
from knowledge_map.schemas.stories import Story


def rewrite(relational=False):
    return QueryRewrite(
        question="Which organizations support AB 1?",
        relational=relational,
        assessment=QuestionAssessment(status="allowed"),
    )


COVERAGE = CoverageDescription(
    entries=(
        CoverageEntry(
            collection_id="reporting",
            name="Reporting",
            kind="publication",
            description="California political reporting.",
            availability=CoverageAvailability(available_count=3),
            date_basis="publication_date",
        ),
    )
)


def candidate(branch, chunk=None, rank=1):
    chunk = chunk or branch.value
    kind, field = {
        RetrievalBranch.FULL_TEXT: ("chunk_text", "text"),
        RetrievalBranch.DENSE: ("chunk_embedding", "embedding"),
        RetrievalBranch.STRUCTURAL: ("typed_traversal", None),
    }[branch]
    return BranchCandidate(
        chunk_id=chunk,
        source_article_id=f"https://example.com/{chunk}",
        ranking=BranchRanking(branch=branch, rank=rank, score=None),
        routes=(
            RetrievalRoute.model_validate(
                {
                    "kind": kind,
                    "matched_field": field,
                    "entry_node": GraphNodeReference(id=chunk, label="Chunk"),
                }
            ),
        ),
    )


class Branch:
    def __init__(self, branch, candidates=None):
        self.branch = branch
        self.candidates = (candidate(branch),) if candidates is None else candidates
        self.requests = []
        self.keywords = None

    async def retrieve(self, request, *, deadline, keywords=None, usage=None):
        self.requests.append((request, deadline))
        self.keywords = keywords
        return SuccessfulBranch(branch=self.branch, candidates=self.candidates)


async def load_grounding(fused):
    return GroundingEvidence(
        chunk_id=fused.chunk_id,
        text="The union supports AB 1.",
        citation=SourceArticleCitation(
            source_article_id=fused.source_article_id,
            title="Union supports bill",
            url=fused.source_article_id,
        ),
    )


async def load_story(citation):
    return Story(
        title=citation.title,
        url=str(citation.url),
        content="The union supports AB 1.",
    )


def coordinator(branches=None, **kwargs):
    branches = branches or {branch: Branch(branch) for branch in RetrievalBranch}
    return RetrievalCoordinator(
        full_text=branches[RetrievalBranch.FULL_TEXT],
        dense=branches[RetrievalBranch.DENSE],
        structural=branches[RetrievalBranch.STRUCTURAL],
        load_grounding=kwargs.pop("load_grounding", load_grounding),
        load_story=kwargs.pop("load_story", load_story),
        **kwargs,
    )


def retrieve(runner, approved=None):
    return asyncio.run(
        runner.run(
            approved or rewrite(),
            coverage=COVERAGE,
            relevant_collection_ids=("reporting",),
        )
    )


def test_non_relational_approval_returns_verified_evidence_from_both_text_branches():
    branches = {branch: Branch(branch) for branch in RetrievalBranch}
    approved = rewrite()
    result = retrieve(coordinator(branches), approved)

    assert isinstance(result, EvidencePackage)
    assert result.execution.expected_branches == ("full_text", "dense")
    assert result.execution.outcomes[-1].status == "skipped"
    assert {source.citation.source_article_id for source in result.sources} == {
        "https://example.com/full_text",
        "https://example.com/dense",
    }
    for branch in (RetrievalBranch.FULL_TEXT, RetrievalBranch.DENSE):
        assert [request.rewrite for request, _ in branches[branch].requests] == [
            approved
        ]
    assert branches[RetrievalBranch.STRUCTURAL].requests == []
    assert branches[RetrievalBranch.FULL_TEXT].keywords == (
        "organizations",
        "support",
        "ab",
        "1",
    )
    assert result.sources[0].passages[0].verification == "original_story"


def test_relational_branches_make_progress_together_before_graph_prioritized_fusion():
    async def exercise():
        started = set()
        ready = asyncio.Event()

        class ConcurrentBranch(Branch):
            async def retrieve(self, request, **kwargs):
                started.add(self.branch)
                if len(started) == 3:
                    ready.set()
                await ready.wait()
                return await super().retrieve(request, **kwargs)

        branches = {branch: ConcurrentBranch(branch) for branch in RetrievalBranch}
        approved = rewrite(relational=True)
        result = await asyncio.wait_for(
            coordinator(branches).run(
                approved, coverage=COVERAGE, relevant_collection_ids=("reporting",)
            ),
            timeout=0.2,
        )
        assert isinstance(result, EvidencePackage)
        assert result.execution.expected_branches == (
            "full_text",
            "dense",
            "structural",
        )
        assert result.sources[0].passages[0].candidate.chunk_id == "structural"
        assert all(
            branch.requests[0][0].rewrite == approved for branch in branches.values()
        )
        assert len({branch.requests[0][1] for branch in branches.values()}) == 1

    asyncio.run(exercise())


def test_concrete_retrievers_share_the_coordinator_contract_and_record_total_usage(
    caplog,
):
    from unittest.mock import AsyncMock, MagicMock

    from neo4j import AsyncDriver
    from structural_support import scripted_agents
    from test_dense_retrieval import driver_for as dense_driver
    from test_dense_retrieval import embedder_for
    from test_full_text_retrieval import online_indexes
    from test_structural_retrieval import driver_for as structural_driver

    from knowledge_map.adapters.dense import Neo4jDenseRetriever
    from knowledge_map.adapters.full_text import Neo4jFullTextRetriever
    from knowledge_map.adapters.structural import Neo4jStructuralRetriever

    full_text_driver = MagicMock(spec=AsyncDriver)
    index_result, empty_result = AsyncMock(), AsyncMock()
    index_result.data.return_value = online_indexes()
    empty_result.data.return_value = []
    full_text_driver.session.return_value.__aenter__.return_value.run = AsyncMock(
        side_effect=[index_result, empty_result, empty_result, empty_result]
    )
    total = RunUsage()

    async def exercise():
        runner = coordinator(
            {
                RetrievalBranch.FULL_TEXT: Neo4jFullTextRetriever(full_text_driver),
                RetrievalBranch.DENSE: Neo4jDenseRetriever(
                    dense_driver(), embedder_for(), candidate_limit=50
                ),
                RetrievalBranch.STRUCTURAL: Neo4jStructuralRetriever(
                    structural_driver(), agents=scripted_agents()
                ),
            }
        )
        return await runner.run(
            rewrite(relational=True),
            coverage=COVERAGE,
            relevant_collection_ids=("reporting",),
            usage=total,
        )

    with caplog.at_level(logging.INFO):
        result = asyncio.run(exercise())
    assert isinstance(result, EvidencePackage)
    assert result.failed_branches == ()
    assert result.sources == ()
    assert total.requests == 5
    assert total.input_tokens > 8
    assert total.output_tokens > 0
    (record,) = [
        record
        for record in caplog.records
        if getattr(record, "event", None) == "retrieval_total_usage"
    ]
    assert (record.requests, record.input_tokens, record.output_tokens) == (
        total.requests,
        total.input_tokens,
        total.output_tokens,
    )


@pytest.mark.parametrize("failed_count", [1, 2, 3])
def test_branch_exceptions_preserve_every_other_branch_and_disclose_all_failures(
    failed_count,
):
    failed = tuple(RetrievalBranch)[:failed_count]

    class BrokenBranch(Branch):
        async def retrieve(self, request, **kwargs):
            raise RuntimeError("private database detail")

    branches = {
        branch: BrokenBranch(branch) if branch in failed else Branch(branch)
        for branch in RetrievalBranch
    }
    result = retrieve(coordinator(branches), rewrite(relational=True))

    assert isinstance(result, EvidencePackage)
    assert result.failed_branches == failed
    assert len(result.failure_disclosures) == failed_count
    assert {
        passage.candidate.chunk_id
        for source in result.sources
        for passage in source.passages
    } == {branch.value for branch in RetrievalBranch if branch not in failed}
    assert "private database detail" not in result.model_dump_json()
    if failed_count == 3:
        assert (
            result.failure_disclosures[0]
            == "Graph connections matching the question could not be searched."
        )


@pytest.mark.parametrize("unfinished_count", [1, 2, 3])
def test_one_deadline_retains_completed_candidates_and_fails_every_unfinished_branch(
    unfinished_count, caplog
):
    async def exercise():
        unfinished = tuple(RetrievalBranch)[-unfinished_count:]
        cancelled = set()

        class StalledBranch(Branch):
            async def retrieve(self, request, **kwargs):
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.add(self.branch)

        branches = {
            branch: StalledBranch(branch) if branch in unfinished else Branch(branch)
            for branch in RetrievalBranch
        }
        result = await asyncio.wait_for(
            coordinator(branches, deadline_seconds=0.01).run(
                rewrite(relational=True),
                coverage=COVERAGE,
                relevant_collection_ids=("reporting",),
            ),
            timeout=0.5,
        )
        assert isinstance(result, EvidenceAssemblyFailure)
        assert result.execution.failed_branches == unfinished
        assert set(result.execution.evidence_by_branch) == set(RetrievalBranch) - set(
            unfinished
        )
        assert cancelled == set(unfinished)
        deadlines = [
            record
            for record in caplog.records
            if getattr(record, "stage", None) == "deadline"
        ]
        assert {record.branch for record in deadlines} == set(unfinished)
        assert all(record.deadline_exhausted for record in deadlines)

    asyncio.run(exercise())


def test_preparation_consumes_the_same_deadline_without_starting_expired_branches():
    times = iter([100.0, 101.0])
    branches = {branch: Branch(branch) for branch in RetrievalBranch}
    result = retrieve(
        coordinator(branches, deadline_seconds=0.5, clock=lambda: next(times, 101.0))
    )
    assert isinstance(result, EvidenceAssemblyFailure)
    assert result.execution.failed_branches == ("full_text", "dense")
    assert all(branch.requests == [] for branch in branches.values())


def test_fusion_must_finish_before_the_shared_deadline(monkeypatch):
    import knowledge_map.core.retrieval as retrieval_module

    now = [100.0]
    original_fusion = retrieval_module.fuse_candidates

    def late_fusion(*args, **kwargs):
        result = original_fusion(*args, **kwargs)
        now[0] = 102.0
        return result

    monkeypatch.setattr(retrieval_module, "fuse_candidates", late_fusion)
    result = retrieve(
        coordinator(deadline_seconds=1, clock=lambda: now[0]),
    )

    assert isinstance(result, EvidenceAssemblyFailure)
    assert set(result.execution.evidence_by_branch) == {"full_text", "dense"}


@pytest.mark.parametrize("seconds", [0, -1, float("inf"), float("nan"), True])
def test_deadline_configuration_requires_a_finite_positive_duration(seconds):
    with pytest.raises(ValueError):
        coordinator(deadline_seconds=seconds)


def test_configured_fusion_limits_preserve_all_routes_and_the_pre_fusion_audit():
    branches = {
        branch: Branch(
            branch,
            (candidate(branch, "shared"), candidate(branch, branch.value, rank=2)),
        )
        for branch in RetrievalBranch
    }
    result = retrieve(
        coordinator(
            branches,
            fusion_config=FusionConfig(
                structural_weight=3,
                full_text_candidate_limit=1,
                dense_candidate_limit=1,
                structural_candidate_limit=1,
                fused_candidate_limit=1,
            ),
        ),
        rewrite(relational=True),
    )
    assert isinstance(result, EvidencePackage)
    assert len(result.sources) == 1
    selected = result.sources[0].passages[0].candidate
    assert selected.chunk_id == "shared"
    assert selected.fusion_score == pytest.approx(5 / 61)
    assert {
        contribution.ranking.branch for contribution in selected.contributions
    } == set(RetrievalBranch)
    assert all(
        len(candidates) == 2
        for candidates in result.execution.evidence_by_branch.values()
    )


@pytest.mark.parametrize("stage", ["load_grounding", "load_story"])
def test_hydration_is_inside_the_same_deadline_and_does_not_relabel_successful_branches(
    stage,
):
    cancelled = []

    async def stalled(value):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.append(stage)

    result = retrieve(coordinator(deadline_seconds=0.01, **{stage: stalled}))
    assert isinstance(result, EvidenceAssemblyFailure)
    assert result.execution.failed_branches == ()
    assert set(result.execution.evidence_by_branch) == {"full_text", "dense"}
    assert cancelled == [stage]


def test_caller_cancellation_stops_all_branches_without_becoming_a_search_failure():
    async def exercise():
        started, stopped = set(), set()
        ready = asyncio.Event()

        class StalledBranch(Branch):
            async def retrieve(self, request, **kwargs):
                started.add(self.branch)
                if len(started) == 3:
                    ready.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    stopped.add(self.branch)

        task = asyncio.create_task(
            coordinator(
                {branch: StalledBranch(branch) for branch in RetrievalBranch}
            ).run(
                rewrite(relational=True),
                coverage=COVERAGE,
                relevant_collection_ids=("reporting",),
            )
        )
        await asyncio.wait_for(ready.wait(), timeout=0.5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert stopped == set(RetrievalBranch)

    asyncio.run(exercise())
