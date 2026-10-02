"""Retained ranks explain bounded metrics and reproduce production fusion."""

import copy
import json
import runpy
from types import SimpleNamespace

import pytest
from test_retrieval import candidate, rewrite
from test_retrieval_eval_task import evaluate, expectation

from knowledge_map.core.fusion import fuse_candidates
from knowledge_map.evaluation.retrieval_report import (
    METRIC_VERSION,
    compact_branches,
    compact_retrieval_report,
    replay_fusion,
)
from knowledge_map.evaluation.tasks.retrieval import (
    RetrievalOutput,
    RetrievedReferenceEvidence,
)
from knowledge_map.schemas.fusion import FusionConfig
from knowledge_map.schemas.retrieval import (
    EvidenceAssemblyFailure,
    RetrievalBranch,
    RetrievalExecutionResult,
    RetrievalRequest,
    SkippedBranch,
    SuccessfulBranch,
)


def execution(full_text, dense=()):
    return RetrievalExecutionResult(
        request=RetrievalRequest(rewrite=rewrite()),
        outcomes=(
            SuccessfulBranch(branch=RetrievalBranch.FULL_TEXT, candidates=full_text),
            SuccessfulBranch(branch=RetrievalBranch.DENSE, candidates=dense),
            SkippedBranch(),
        ),
    )


def raw_document(result, expected, *, settings=None):
    return {
        "task": "retrieval",
        "report": {
            "cases": [
                {
                    "name": "case",
                    "expected_output": expected.model_dump(mode="json"),
                    "attributes": {},
                    "scores": {},
                    "output": {
                        "settings": settings
                        or {"fusion_settings": FusionConfig().model_dump()},
                        "result": {
                            "execution": result.model_dump(mode="json"),
                            "sources": [],
                        },
                        "messages": [],
                    },
                }
            ],
        },
    }


@pytest.mark.parametrize("limit", [2, 50, 75])
def test_compact_ranks_reproduce_fusion_with_cross_branch_tail_and_ties(limit):
    ft = RetrievalBranch.FULL_TEXT
    dense = RetrievalBranch.DENSE
    result = execution(
        tuple(
            candidate(ft, chunk=f"ft-{rank:04}", rank=rank) for rank in range(1, 2001)
        )
        + (
            candidate(ft, chunk="ft-0001", rank=2001),
            candidate(ft, chunk="cross", rank=2002),
        ),
        (
            candidate(dense, chunk="cross", rank=1),
            candidate(dense, chunk="ft-0001", rank=90),
        ),
    )
    config = FusionConfig(full_text_candidate_limit=limit, dense_candidate_limit=limit)
    compact = compact_branches(result.model_dump(mode="json")["outcomes"], config)
    replay = replay_fusion(compact, config)
    actual = fuse_candidates(result, config=config)
    assert [(c["chunk_id"], c["rank"], c["fusion_score"]) for c in replay] == [
        (c.chunk_id, c.rank, c.fusion_score) for c in actual
    ]
    assert len(compact[0]["candidates"]) == 50
    extras = compact[0]["extra_fusion_ranks"]
    assert next(r for r in extras if r["chunk_id"] == "cross")["rank"] == 2002
    assert all(
        r["chunk_id"] == "cross" or int(r["chunk_id"].split("-")[1]) <= limit
        for r in extras
    )
    assert compact[0]["retrieved_count"] == 2002
    assert compact[0]["unique_chunk_count"] == 2001
    assert "routes" not in json.dumps(compact)


def test_article_recall_and_reciprocal_rank_use_the_unique_chunk_budget():
    ft = RetrievalBranch.FULL_TEXT
    first_article = tuple(
        candidate(ft, chunk=f"same-{rank}", rank=rank).model_copy(
            update={"source_article_id": "same"}
        )
        for rank in range(1, 51)
    )
    result = execution(
        first_article
        + (
            candidate(ft, chunk="target", rank=51).model_copy(
                update={"source_article_id": "target"}
            ),
        )
    )
    output = RetrievalOutput(
        result=EvidenceAssemblyFailure(execution=result), fused=fuse_candidates(result)
    )
    scores = evaluate(output, expectation(("same", "target"), grain="source_article"))
    assert scores["full_text_recall_at_50"] == 0.5
    assert scores["full_text_complete_evidence_at_50"] == 0
    scores = evaluate(output, expectation(("target",), grain="source_article"))
    assert scores["full_text_reciprocal_rank"] == 0
    assert scores["fused_reciprocal_rank"] == 0
    document = raw_document(result, expectation(("target",), grain="source_article"))
    compact_retrieval_report(document, rescore=True)
    saved = document["report"]["cases"][0]["scores"]
    assert saved["full_text_recall_at_50"]["value"] == 0
    assert saved["full_text_reciprocal_rank"]["value"] == 0


def test_live_and_saved_scores_match_and_configuration_is_stored_once():
    result = execution((candidate(RetrievalBranch.FULL_TEXT, chunk="a", rank=1),))
    expected = expectation(("a", "missing"))
    output = RetrievalOutput(
        result=EvidenceAssemblyFailure(execution=result), fused=fuse_candidates(result)
    )
    live = RetrievedReferenceEvidence().evaluate(
        SimpleNamespace(inputs=rewrite(), output=output, expected_output=expected)
    )
    document = raw_document(result, expected)
    case = document["report"]["cases"][0]
    case["scores"]["full_text_recall_at_50"] = {
        "value": live["full_text_recall_at_50"].value,
        "reason": "old",
        "name": "full_text_recall_at_50",
        "source": "RetrievedReferenceEvidence",
    }
    document["report"]["cases"].append(copy.deepcopy(case))
    compact_retrieval_report(document)
    assert len(document["retrieval_report"]["configurations"]) == 1
    assert document["retrieval_report"]["metric_version"] == METRIC_VERSION
    for case in document["report"]["cases"]:
        assert case["output"]["configuration_index"] == 0
        assert "settings" not in case["output"]
        assert "fused" not in case["output"]
        for name, score in case["scores"].items():
            assert score["value"] == live[name].value
        assert (
            case["scores"]["full_text_recall_at_50"]["source"]
            == "RetrievedReferenceEvidence"
        )
    before = copy.deepcopy(document)
    assert compact_retrieval_report(document) == before


def test_selected_text_citations_and_specific_corrections_survive_without_catalogs():
    result = execution((candidate(RetrievalBranch.FULL_TEXT, chunk="a", rank=1),))
    document = raw_document(result, expectation(("a",)))
    case = document["report"]["cases"][0]
    case["output"]["result"]["sources"] = [
        {
            "citation": {
                "source_article_id": "article",
                "title": "Article",
                "url": "https://example.org/",
            },
            "passages": [
                {
                    "text": "Exact wording",
                    "provenance": "stored_chunk",
                    "candidate": {"chunk_id": "a", "contributions": ["discard"]},
                }
            ],
        }
    ]
    case["attributes"]["stage_observations"] = [
        {
            "name": "chat_session.structural_stage",
            "attributes": {
                "status": "succeeded",
                "stage": "cypher_execution",
                "row_count": 7319,
                "catalog": "discard",
            },
        },
        {
            "name": "chat_session.structural_stage",
            "attributes": {
                "status": "failed",
                "stage": "validation",
                "diagnostic": "wire distinct roles",
                "catalog": "discard",
            },
        },
        {
            "name": "chat_session.retrieval_branch",
            "attributes": {
                "status": "succeeded",
                "branch": "structural",
                "catalog": "discard",
            },
        },
    ]
    case["output"]["messages"] = [
        {
            "component": "selector",
            "status": "succeeded",
            "request_index": 1,
            "request_parameters": {"catalog": "discard"},
            "messages": [
                {
                    "kind": "request",
                    "parts": [
                        {"part_kind": "user-prompt", "content": "catalog discard"}
                    ],
                },
                {
                    "kind": "response",
                    "parts": [{"part_kind": "text", "content": '{"invalid": true}'}],
                },
            ],
        },
        {
            "component": "selector",
            "status": "succeeded",
            "request_index": 2,
            "messages": [
                {
                    "kind": "request",
                    "parts": [
                        {"part_kind": "user-prompt", "content": "catalog discard"}
                    ],
                },
                {
                    "kind": "request",
                    "parts": [
                        {"part_kind": "retry-prompt", "content": "wire distinct roles"}
                    ],
                },
                {
                    "kind": "response",
                    "parts": [{"part_kind": "text", "content": '{"valid": true}'}],
                },
            ],
        },
    ]
    compact_retrieval_report(document)
    output = case["output"]
    assert output["evidence"]["sources"][0]["passages"] == [
        {"chunk_id": "a", "text": "Exact wording", "provenance": "stored_chunk"}
    ]
    assert output["evidence"]["sources"][0]["citation"]["title"] == "Article"
    assert output["model_corrections"][1]["feedback"] == ["wire distinct roles"]
    assert output["model_corrections"][0]["response"] == ['{"invalid": true}']
    assert case["attributes"]["retrieval_diagnostics"][0]["row_count"] == 7319
    assert not any(
        d["terminal_branch_failure"]
        for d in case["attributes"]["retrieval_diagnostics"]
    )
    assert "discard" not in json.dumps(document)


def test_migration_rescores_preserves_original_and_is_idempotent(tmp_path):
    result = execution(
        tuple(
            candidate(RetrievalBranch.FULL_TEXT, chunk=f"c-{i}", rank=i).model_copy(
                update={"source_article_id": "same" if i <= 50 else "target"}
            )
            for i in range(1, 52)
        )
    )
    document = raw_document(
        result, expectation(("same", "target"), grain="source_article")
    )
    document["report"]["cases"][0]["scores"]["full_text_recall_at_50"] = {
        "value": 1,
        "reason": "old",
        "source": "RetrievedReferenceEvidence",
    }
    path = tmp_path / "report.json"
    original = json.dumps(document).encode()
    path.write_bytes(original)
    compact_file = runpy.run_path("scripts/compact_retrieval_reports.py")[
        "compact_file"
    ]
    compact_file(path, backup_dir=tmp_path / "backups")
    assert (tmp_path / "backups" / path.name).read_bytes() == original
    saved = json.loads(path.read_text())
    case = saved["report"]["cases"][0]
    assert case["scores"]["full_text_recall_at_50"]["value"] == 0.5
    assert (
        case["attributes"]["legacy_identity_budget_scores"]["full_text_recall_at_50"]
        == 1
    )
    assert saved["retrieval_report"]["migration"]["rescored"]
    compacted = path.read_bytes()
    compact_file(path, backup_dir=tmp_path / "backups")
    assert path.read_bytes() == compacted
    assert (tmp_path / "backups" / path.name).read_bytes() == original


def test_missing_recorded_configuration_cannot_claim_exact_fusion_replay():
    result = execution((candidate(RetrievalBranch.FULL_TEXT, chunk="a", rank=1),))
    document = raw_document(result, expectation(("a",)))
    document["report"]["cases"][0]["output"]["settings"] = {}
    with pytest.raises(ValueError, match="recorded fusion settings"):
        compact_retrieval_report(document)
