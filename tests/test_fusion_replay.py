"""Production fusion and retained report ranks preserve one ranking policy."""

import copy
from typing import Any

import pytest
from test_chat_session_trail import chat_capture as chat_capture  # noqa: PLC0414
from test_fusion import candidate, execution

from knowledge_map.core.fusion import fuse_candidates
from knowledge_map.evaluation.retrieval_report import compact_branches, replay_fusion
from knowledge_map.retrieval_telemetry import selection_stage
from knowledge_map.schemas.fusion import FusionConfig
from knowledge_map.schemas.retrieval import RetrievalBranch


@pytest.mark.parametrize("reverse_inputs", [False, True])
def test_production_and_replay_preserve_nondefault_scores_and_final_limit(
    reverse_inputs,
):
    branches: list[dict[str, Any]] = [
        {
            "branch": branch,
            "status": "succeeded",
            "candidates": [
                {
                    "chunk_id": chunk,
                    "source_article_id": f"article-{chunk}",
                    "rank": rank,
                }
                for chunk, rank in records
            ],
            "extra_fusion_ranks": [],
        }
        for branch, records in (
            ("full_text", (("a", 2), ("b", 2), ("shared", 4))),
            ("dense", (("shared", 2), ("a", 10))),
            ("structural", (("graph", 4),)),
        )
    ]
    if reverse_inputs:
        branches.reverse()
    original = copy.deepcopy(branches)
    candidates = tuple(
        candidate(
            RetrievalBranch(branch["branch"]), row["chunk_id"], row["rank"]
        ).model_copy(update={"source_article_id": row["source_article_id"]})
        for branch in branches
        for row in branch["candidates"]
    )
    retained = execution(*(reversed(candidates) if reverse_inputs else candidates))
    original_execution = retained.model_dump_json()
    config = FusionConfig(
        full_text_weight=2,
        dense_weight=4,
        structural_weight=6,
        rank_constant=2,
        full_text_candidate_limit=1,
        dense_candidate_limit=1,
        structural_candidate_limit=1,
        fused_candidate_limit=2,
    )

    expected = [
        {
            "chunk_id": "shared",
            "source_article_id": "article-shared",
            "rank": 1,
            "fusion_score": 1.3333333333333333,
        },
        {
            "chunk_id": "graph",
            "source_article_id": "article-graph",
            "rank": 2,
            "fusion_score": 1.0,
        },
    ]
    assert replay_fusion(branches, config) == expected
    assert [
        {
            "chunk_id": row.chunk_id,
            "source_article_id": row.source_article_id,
            "rank": row.rank,
            "fusion_score": row.fusion_score,
        }
        for row in fuse_candidates(retained, config=config)
    ] == expected
    compact = compact_branches(retained.model_dump(mode="json")["outcomes"], config)
    assert replay_fusion(compact, config) == expected
    assert retained.model_dump_json() == original_execution
    assert branches == original


@pytest.mark.parametrize(
    "eligibility, expected_count, last_score",
    [
        (None, 50, 0.00909090909090909),
        ([], 0, None),
        (list(range(1, 76)), 75, 0.007407407407407408),
    ],
)
def test_replay_uses_recorded_eligibility_and_never_nominates_extra_ranks(
    eligibility, expected_count, last_score
):
    records = [
        {"chunk_id": f"chunk-{rank:02}", "source_article_id": "article", "rank": rank}
        for rank in range(1, 76)
    ]
    branch = {
        "branch": "full_text",
        "status": "succeeded",
        "candidates": records[:50],
        "extra_fusion_ranks": records[50:],
    }
    if eligibility is not None:
        branch["fusion_eligible_chunk_ids"] = [
            f"chunk-{rank:02}" for rank in eligibility
        ]
    original = copy.deepcopy(branch)

    replay = replay_fusion([branch], FusionConfig(full_text_candidate_limit=75))

    assert [row["chunk_id"] for row in replay] == [
        f"chunk-{rank:02}" for rank in range(1, expected_count + 1)
    ]
    if expected_count:
        assert replay[0]["fusion_score"] == 0.01639344262295082
        assert replay[-1] == {
            "chunk_id": f"chunk-{expected_count:02}",
            "source_article_id": "article",
            "rank": expected_count,
            "fusion_score": last_score,
        }
    assert branch == original


def test_replay_leaves_active_production_selection_observations_unchanged(chat_capture):
    with selection_stage("fusion", "production-selection"):
        fuse_candidates(execution(candidate(RetrievalBranch.FULL_TEXT, "live", 1)))
        assert replay_fusion([], FusionConfig()) == []

    span = next(
        span
        for span in chat_capture.exported_spans_as_dict(parse_json_attributes=True)
        if span["name"] == "chat_session.fusion"
    )
    assert span["attributes"]["eligible_branches"] == {
        "full_text": {"count": 1, "chunk_ids": ["live"]},
        "dense": {"count": 0, "chunk_ids": []},
        "structural": {"count": 0, "chunk_ids": []},
    }
    assert span["attributes"]["fused_chunk_ids"] == ["live"]


def test_production_records_nominations_when_fusion_arithmetic_fails(chat_capture):
    retained = execution(
        candidate(RetrievalBranch.FULL_TEXT, "shared", 1),
        candidate(RetrievalBranch.DENSE, "shared", 1),
    )
    config = FusionConfig(
        full_text_weight=1e308,
        dense_weight=1e308,
        structural_weight=1.1e308,
        rank_constant=0,
    )

    with (
        pytest.raises(OverflowError, match="overflow"),
        selection_stage("fusion", "production-selection"),
    ):
        fuse_candidates(retained, config=config)

    span = next(
        span
        for span in chat_capture.exported_spans_as_dict(parse_json_attributes=True)
        if span["name"] == "chat_session.fusion"
    )
    assert span["attributes"]["eligible_branches"] == {
        "full_text": {"count": 1, "chunk_ids": ["shared"]},
        "dense": {"count": 1, "chunk_ids": ["shared"]},
        "structural": {"count": 0, "chunk_ids": []},
    }
    assert span["attributes"]["status"] == "failed"
    assert "fused_chunk_ids" not in span["attributes"]
