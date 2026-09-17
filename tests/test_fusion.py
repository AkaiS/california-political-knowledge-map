"""Ranking behavior at the execution-to-fused-candidates boundary."""

import pytest
from pydantic import ValidationError

from knowledge_map.core.fusion import fuse_candidates
from knowledge_map.schemas.fusion import FusionConfig
from knowledge_map.schemas.query_preparation import QueryRewrite, QuestionAssessment
from knowledge_map.schemas.retrieval import (
    BranchCandidate,
    BranchRanking,
    BranchScore,
    FailedBranch,
    FusedCandidate,
    GraphNodeReference,
    RetrievalBranch,
    RetrievalExecutionResult,
    RetrievalRequest,
    RetrievalRoute,
    SkippedBranch,
    SuccessfulBranch,
)


def candidate(branch: RetrievalBranch, chunk: str, rank: int, score: float = 0.5):
    kind, matched_field = {
        RetrievalBranch.FULL_TEXT: ("chunk_text", "text"),
        RetrievalBranch.DENSE: ("chunk_embedding", "embedding"),
        RetrievalBranch.STRUCTURAL: ("typed_traversal", None),
    }[branch]
    return BranchCandidate(
        chunk_id=chunk,
        source_article_id="article-a",
        ranking=BranchRanking(branch=branch, rank=rank, score=BranchScore(score)),
        routes=(
            RetrievalRoute.model_validate(
                {
                    "kind": kind,
                    "matched_field": matched_field,
                    "entry_node": GraphNodeReference(
                        id="entity-a", label="Organization"
                    ),
                }
            ),
        ),
    )


def execution(*candidates: BranchCandidate):
    return RetrievalExecutionResult(
        request=RetrievalRequest(
            rewrite=QueryRewrite(
                question="Which organizations lobbied for AB 186?",
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


def test_structural_priority_keeps_text_only_chunks_in_the_candidate_union():
    result = fuse_candidates(
        execution(
            candidate(RetrievalBranch.FULL_TEXT, "a-full-text-only", 1, 9000.0),
            candidate(RetrievalBranch.DENSE, "b-dense-only", 1, 0.99),
            candidate(RetrievalBranch.STRUCTURAL, "c-graph-only", 1, -100.0),
        )
    )

    assert [(c.chunk_id, c.rank) for c in result] == [
        ("c-graph-only", 1),
        ("a-full-text-only", 2),
        ("b-dense-only", 3),
    ]
    assert [c.fusion_score for c in result] == pytest.approx(
        [0.03278688524590164, 0.01639344262295082, 0.01639344262295082]
    )


def test_a_chunk_accumulates_each_branch_once_at_its_best_pre_fusion_rank():
    full_text = candidate(RetrievalBranch.FULL_TEXT, "shared-chunk", 2, 9000.0)
    second_route = candidate(RetrievalBranch.FULL_TEXT, "shared-chunk", 4, 12000.0)
    dense = candidate(RetrievalBranch.DENSE, "shared-chunk", 3, 0.9)
    structural = candidate(RetrievalBranch.STRUCTURAL, "shared-chunk", 5, -100.0)
    graph_only = candidate(RetrievalBranch.STRUCTURAL, "graph-only", 1)
    retained = execution(second_route, full_text, dense, structural, graph_only)
    original = retained.model_dump_json()

    result = fuse_candidates(retained)

    assert [c.chunk_id for c in result] == ["shared-chunk", "graph-only"]
    assert result[0].fusion_score == pytest.approx(0.06277127890031116)
    assert result[0].contributions == (second_route, full_text, dense, structural)
    assert retained.model_dump_json() == original


def test_replacement_weights_and_rank_constant_change_ranking_without_code_changes():
    retained = execution(
        candidate(RetrievalBranch.FULL_TEXT, "a-text", 1),
        candidate(RetrievalBranch.STRUCTURAL, "b-graph", 3),
        candidate(RetrievalBranch.DENSE, "c-dense", 1),
    )
    config = FusionConfig(
        full_text_weight=2, dense_weight=4, structural_weight=5, rank_constant=0
    )

    result = fuse_candidates(retained, config=config)

    assert [c.chunk_id for c in result] == ["c-dense", "a-text", "b-graph"]
    assert [c.fusion_score for c in result] == pytest.approx(
        [4.0, 2.0, 1.6666666666666667]
    )
    assert [c.chunk_id for c in fuse_candidates(retained)] == [
        "b-graph",
        "a-text",
        "c-dense",
    ]
    assert FusionConfig.model_validate_json(config.model_dump_json()) == config


@pytest.mark.parametrize(
    "replacement",
    [
        {"structural_weight": 1},
        {"structural_weight": 0.5},
        {"full_text_weight": 2},
        {"dense_weight": 2},
        {"full_text_weight": 0},
        {"dense_weight": -1},
        {"structural_weight": float("inf")},
        {"full_text_weight": float("nan")},
        {"dense_weight": True},
        {"rank_constant": -1},
        {"rank_constant": float("inf")},
        {"rank_constant": float("nan")},
        {"rank_constant": True},
    ],
)
def test_configuration_rejects_invalid_weights_and_rank_constants(replacement):
    with pytest.raises(ValidationError):
        FusionConfig.model_validate(replacement)


def test_limits_nominate_unique_chunks_and_keep_all_routes_for_admitted_chunks():
    full_text_a = candidate(RetrievalBranch.FULL_TEXT, "a", 1)
    full_text_a_again = candidate(RetrievalBranch.FULL_TEXT, "a", 2)
    full_text_b = candidate(RetrievalBranch.FULL_TEXT, "b", 3)
    dense_a = candidate(RetrievalBranch.DENSE, "a", 2)
    structural_b = candidate(RetrievalBranch.STRUCTURAL, "b", 3)
    retained = execution(
        full_text_a,
        full_text_a_again,
        full_text_b,
        candidate(RetrievalBranch.FULL_TEXT, "c", 4),
        candidate(RetrievalBranch.DENSE, "d", 1),
        dense_a,
        candidate(RetrievalBranch.DENSE, "e", 3),
        candidate(RetrievalBranch.STRUCTURAL, "f", 1),
        candidate(RetrievalBranch.STRUCTURAL, "g", 2),
        structural_b,
    )
    original = retained.model_dump_json()
    config = FusionConfig(
        full_text_candidate_limit=2,
        dense_candidate_limit=1,
        structural_candidate_limit=1,
        fused_candidate_limit=3,
    )

    result = fuse_candidates(retained, config=config)

    assert [(c.chunk_id, c.rank) for c in result] == [("b", 1), ("f", 2), ("a", 3)]
    assert result[0].fusion_score == pytest.approx(0.047619047619047616)
    assert result[0].contributions == (full_text_b, structural_b)
    assert result[2].contributions == (full_text_a, full_text_a_again, dense_a)
    assert retained.model_dump_json() == original


def test_unweighted_measurement_baseline_uses_equal_branch_contributions():
    retained = execution(
        candidate(RetrievalBranch.FULL_TEXT, "a-text", 1),
        candidate(RetrievalBranch.STRUCTURAL, "b-graph", 2),
        candidate(RetrievalBranch.DENSE, "c-dense", 3),
    )
    config = FusionConfig(
        full_text_weight=2, dense_weight=3, structural_weight=5, rank_constant=1
    )

    baseline = fuse_candidates(retained, config=config, unweighted_baseline=True)

    assert [c.chunk_id for c in baseline] == ["a-text", "b-graph", "c-dense"]
    assert [c.fusion_score for c in baseline] == pytest.approx(
        [0.5, 0.3333333333333333, 0.25]
    )
    assert [c.chunk_id for c in fuse_candidates(retained, config=config)] == [
        "b-graph",
        "a-text",
        "c-dense",
    ]
    assert config.structural_weight == 5


@pytest.mark.parametrize(
    "field",
    [
        "full_text_candidate_limit",
        "dense_candidate_limit",
        "structural_candidate_limit",
        "fused_candidate_limit",
    ],
)
@pytest.mark.parametrize("value", [0, -1, 1.5, True, "2"])
def test_candidate_limits_require_positive_integer_counts(field, value):
    with pytest.raises(ValidationError):
        FusionConfig.model_validate({field: value})


def test_defaults_expose_the_documented_initial_configuration():
    assert FusionConfig().model_dump() == {
        "full_text_weight": 1.0,
        "dense_weight": 1.0,
        "structural_weight": 2.0,
        "rank_constant": 60.0,
        "full_text_candidate_limit": 50,
        "dense_candidate_limit": 50,
        "structural_candidate_limit": 50,
        "fused_candidate_limit": 100,
    }


def test_rank_ties_and_cutoffs_use_chunk_identity_independent_of_input_order():
    a = candidate(RetrievalBranch.FULL_TEXT, "a", 1, -1000)
    b = candidate(RetrievalBranch.FULL_TEXT, "b", 1, 1000)
    c = candidate(RetrievalBranch.STRUCTURAL, "c", 62, 9000)
    config = FusionConfig(full_text_candidate_limit=1)
    retained = execution(b, a, c)
    reversed_branches = RetrievalExecutionResult(
        request=retained.request,
        outcomes=tuple(reversed(execution(a, b, c).outcomes)),
    )

    first = fuse_candidates(retained, config=config)
    second = fuse_candidates(reversed_branches, config=config)

    assert first == second
    assert [(c.chunk_id, c.rank) for c in first] == [("a", 1), ("c", 2)]
    assert first[0].fusion_score == first[1].fusion_score


def test_fusion_retains_matched_fields_graph_claims_and_ambiguous_node_identities():
    base = candidate(RetrievalBranch.STRUCTURAL, "shared", 1)
    graphs = tuple(
        BranchCandidate.model_validate(
            {
                **base.model_dump(),
                "ranking": {"branch": "structural", "rank": rank, "score": None},
                "routes": [
                    {
                        "kind": "typed_traversal",
                        "matched_field": None,
                        "entry_node": {
                            "id": "org-a",
                            "label": "Organization",
                            "element_id": element,
                        },
                        "graph_claims": [
                            {
                                "source": {
                                    "id": "org-a",
                                    "label": "Organization",
                                    "element_id": element,
                                },
                                "target": {"id": "bill-a", "label": "Bill"},
                                "relationship_type": "LOBBIED_FOR",
                                "claim_key": {},
                                "chunk_ids": ["shared"],
                                "needs_review": True,
                            }
                        ],
                    }
                ],
            }
        )
        for rank, element in enumerate(("node:17", "node:18"), start=1)
    )
    full_text = BranchCandidate.model_validate(
        {
            **candidate(RetrievalBranch.FULL_TEXT, "shared", 2, 17.5).model_dump(),
            "routes": [
                {
                    "kind": "entity_name",
                    "matched_field": "name",
                    "entry_node": {
                        "id": "org-a",
                        "label": "Organization",
                        "element_id": "node:17",
                    },
                },
                {
                    "kind": "article_title",
                    "matched_field": "title",
                    "entry_node": {"id": "article-a", "label": "NewsArticle"},
                },
            ],
        }
    )
    other_chunk = candidate(RetrievalBranch.DENSE, "different-chunk", 1)

    result = fuse_candidates(execution(*graphs, full_text, other_chunk))

    assert [c.chunk_id for c in result] == ["shared", "different-chunk"]
    restored = FusedCandidate.model_validate_json(result[0].model_dump_json())
    assert restored.contributions == (full_text, *graphs)
    assert [c.routes[0].entry_node.element_id for c in restored.contributions[1:]] == [
        "node:17",
        "node:18",
    ]
    assert restored.fusion_score == pytest.approx(0.0489159175039651)


@pytest.mark.parametrize("relational", [True, False])
def test_failed_or_skipped_branches_leave_successful_evidence_eligible(relational):
    dense = candidate(RetrievalBranch.DENSE, "text-only", 1)
    retained = RetrievalExecutionResult(
        request=RetrievalRequest(
            rewrite=QueryRewrite(
                question="Which organizations lobbied for AB 186?",
                relational=relational,
                assessment=QuestionAssessment(status="allowed"),
            )
        ),
        outcomes=(
            FailedBranch(branch=RetrievalBranch.FULL_TEXT),
            SuccessfulBranch(branch=RetrievalBranch.DENSE, candidates=(dense,)),
            FailedBranch(branch=RetrievalBranch.STRUCTURAL)
            if relational
            else SkippedBranch(),
        ),
    )

    result = fuse_candidates(retained)

    assert len(result) == 1
    assert result[0].contributions == (dense,)
    assert retained.failed_branches == (
        (RetrievalBranch.FULL_TEXT, RetrievalBranch.STRUCTURAL)
        if relational
        else (RetrievalBranch.FULL_TEXT,)
    )


def test_successful_empty_branches_produce_no_fused_candidates():
    assert fuse_candidates(execution()) == ()
