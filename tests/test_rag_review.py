"""RAG review exposes only judgment inputs and scoped measurements."""

import copy
import json
import threading
from contextlib import contextmanager
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
from test_chat_eval_review import review_server

from knowledge_map.evaluation.rag_review import (
    AXES,
    project_report,
    required_axes,
    validate_review,
)
from knowledge_map.schemas.fusion import FusionConfig


def report(task="retrieval", *, generation=False):
    evidence = {
        "sources": [
            {
                "citation": {
                    "title": "Source",
                    "source_article_id": "article",
                    "url": "https://example.org",
                },
                "passages": [{"chunk_id": "a", "text": "Bill AB 1 was supported."}],
            }
        ],
        "context": {"used": 40, "limit": 24000},
    }
    output = {
        "evidence": evidence,
        "configuration_index": 0,
        "branches": [
            {
                "branch": "full_text",
                "status": "succeeded",
                "candidates": [
                    {"chunk_id": "a", "source_article_id": "article", "rank": 1}
                ],
                "extra_fusion_ranks": [],
            }
        ],
        "messages": ["secret catalog"],
        "settings": {"internal": "secret"},
    }
    if generation:
        output.update(
            answer={"introduction": "Bill supported", "evidence": evidence},
            rendered_text="**Supported** <script>bad()</script> ![pixel](https://example.org/pixel)",
        )
    return {
        "task": task,
        "commit": "abc",
        "data_set": "evals/silver/retrieval.yaml",
        "label_quality": "silver",
        "split": "training",
        "ran_at": "2026-10-02",
        "model": "model",
        "retrieval_report": {
            "metric_version": "unique-chunk-budget-v2",
            "chunk_budget": 50,
            "configurations": [
                {
                    "fusion_settings": FusionConfig().model_dump(),
                    "evidence_limits": {"character_limit": 24000, "max_passages": 12},
                }
            ],
        },
        "report": {
            "cases": [
                {
                    "name": "case",
                    "inputs": {
                        "question": "Who supports AB 1?",
                        "assessment": "secret",
                    },
                    "attributes": {"stage_observations": ["secret trace"]},
                    "metadata": {"scope_note": "Stored reporting"},
                    "expected_output": {
                        "grain": "article_chunk",
                        "relevant_ids": ["a"],
                        "answers": [
                            {
                                "groups": [
                                    {"kind": "hop-1", "ids": ["a"]},
                                    {"kind": "hop-2", "ids": ["b"]},
                                ]
                            }
                        ],
                    },
                    "scores": {
                        "full_text_recall_at_1": {"value": 0.5},
                        "full_text_reciprocal_rank": {"value": 1},
                    },
                    "output": output,
                }
            ]
        },
    }


def review():
    return {
        key: value
        for axis in AXES
        for key, value in ((axis, None), (f"{axis}_note", ""))
    }


def test_projection_excludes_all_pipeline_internals_and_keeps_exact_selected_text():
    raw = report()
    before = copy.deepcopy(raw)
    projected = project_report(raw)
    assert raw == before
    assert "secret" not in json.dumps(projected)
    case = projected["report"]["cases"][0]
    assert (
        case["output"]["sources"][0]["passages"][0]["text"]
        == "Bill AB 1 was supported."
    )
    assert required_axes(case) == ("context_relevance",)
    assert not case["output"]["has_generation"]
    assert projected["specs"]["label_quality"] == "silver"
    assert (
        projected["specs"]["configurations"][0]["fusion_settings"]["rank_constant"]
        == 60
    )
    precision = [m for m in projected["metrics"] if m["metric"] == "precision"]
    assert all(
        m["value"] is None and "complete relevance judgments" in m["reason"]
        for m in precision
    )
    ndcg = [m for m in projected["metrics"] if m["metric"] == "ndcg"]
    assert all(m["value"] is None and "graded" in m["reason"] for m in ndcg)
    two_hop = next(
        m
        for m in case["metrics"]
        if m["branch"] == "full_text"
        and m["metric"] == "two_hop_recall"
        and m["k"] == 1
    )
    assert two_hop["value"] == 0


def test_two_hop_recall_requires_both_groups_and_reports_its_population():
    raw = report()
    case = raw["report"]["cases"][0]
    case["expected_output"]["answers"][0]["groups"][1]["ids"] = ["a"]
    other = copy.deepcopy(case)
    other["name"] = "one-hop"
    other["expected_output"]["answers"][0]["groups"].pop()
    raw["report"]["cases"].append(other)
    result = project_report(raw)
    row = next(
        m
        for m in result["metrics"]
        if m["metric"] == "two_hop_recall" and m["branch"] == "fused" and m["k"] == 5
    )
    assert row["value"] == 1
    assert row["scored_cases"] == 1
    assert row["applicable_cases"] == 2


def test_chat_review_uses_approved_question_and_same_execution_context():
    raw = report("chat", generation=True)
    c = raw["report"]["cases"][0]
    c["output"]["answer"]["evidence"]["execution"] = {
        "request": {"rewrite": {"question": "Approved scope"}}
    }
    c["output"]["preparation"] = {"message": "secret rewrite"}
    projected = project_report(raw)
    case = projected["report"]["cases"][0]
    assert case["question"] == "Approved scope"
    assert required_axes(case) == AXES
    assert "secret" not in json.dumps(projected)
    rendered = review_server.presentation_for(projected)["html"][
        case["output"]["generation"]
    ]
    assert "<strong>Supported</strong>" in rendered
    assert "<script>" not in rendered
    assert "<img" not in rendered


def test_unavailable_answers_cannot_receive_fabricated_judgments():
    case = project_report(report())["report"]["cases"][0]
    valid = review()
    valid["context_relevance"] = "pass"
    validate_review(valid, case)
    invalid = {**valid, "faithfulness": "pass"}
    with pytest.raises(ValueError, match="cannot be judged"):
        validate_review(invalid, case)
    with pytest.raises(ValueError, match="three RAG"):
        validate_review({"verdict": "pass", "note": "whole trace"}, case)
    case["output"]["sources"] = []
    case["output"]["has_context"] = False
    assert required_axes(case) == ()


@contextmanager
def server(directory):
    handler = review_server.make_handler(directory, b"runs", b"rag", "rag")
    http = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=http.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{http.server_port}"
    finally:
        http.shutdown()
        http.server_close()
        thread.join()


def test_rag_api_round_trip_keeps_reviews_separate_rejects_stale_report_and_preserves_text(
    tmp_path,
):
    directory = tmp_path / "retrieval"
    directory.mkdir()
    path = directory / "run.json"
    path.write_text(json.dumps(report()))
    old_reviews = path.with_suffix(".reviews.json")
    old_reviews.write_text(
        json.dumps({"case": {"verdict": "fail", "note": "End-to-end"}})
    )
    with server(tmp_path) as base:
        runs = json.load(urlopen(f"{base}/api/runs"))
        assert runs[0]["id"] == "retrieval--run"
        api = f"{base}/api/runs/retrieval--run"
        projected = json.load(urlopen(f"{api}/report"))
        assert "secret" not in json.dumps(projected)
        payload = {
            "name": "case",
            "review": review(),
            "review_identity": projected["review_identity"],
        }
        payload["review"]["context_relevance"] = "fail"
        payload["review"]["context_relevance_note"] = "Wrong bill in selected context."

        def post():
            return urlopen(
                Request(
                    f"{api}/reviews",
                    data=json.dumps(payload).encode(),
                    headers={"Content-Type": "application/json"},
                )
            )

        assert post().status == 200
        assert json.load(urlopen(f"{api}/reviews"))["case"] == payload["review"]
        assert path.with_suffix(".rag-reviews.json").exists()
        assert json.loads(old_reviews.read_text())["case"]["note"] == "End-to-end"
        assert json.load(urlopen(f"{base}/api/runs"))[0]["reviewed_count"] == 1
        path.write_text(json.dumps(report()) + "\n")
        with pytest.raises(HTTPError) as stale:
            post()
        assert stale.value.code == 409
        payload["review_identity"] = json.load(urlopen(f"{api}/report"))[
            "review_identity"
        ]
        payload["review"]["faithfulness"] = "pass"
        with pytest.raises(HTTPError) as unavailable:
            post()
        assert unavailable.value.code == 400
        assert (
            urlopen(
                f"{base}/assets/rag_eval_review_model.mjs"
            ).headers.get_content_type()
            == "text/javascript"
        )
        with pytest.raises(HTTPError):
            urlopen(f"{base}/api/runs/../report")


def test_focused_page_contains_axis_rubrics_and_no_pipeline_panels():
    page = Path("scripts/rag_eval_review.html").read_text()
    assert "Retrieval specifications and run metrics" in page
    assert "Selected evidence and citations" in page
    assert "Final generation" in page
    for forbidden in (
        "Question preparation",
        "Application stages",
        "Model messages",
        "Complete case output",
        "Critique or observation",
    ):
        assert forbidden not in page
