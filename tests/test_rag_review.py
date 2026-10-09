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
    review_complete,
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


@pytest.mark.parametrize("compacted", [False, True])
def test_review_shows_only_selected_graph_facts_without_jev_construction(compacted):
    raw = report(generation=True)
    evidence = raw["report"]["cases"][0]["output"]["evidence"]
    selected = {"fact": "Bill support", "evidence_chunk_ids": ["a"]}
    branches = [
        {
            "branch": "structural",
            "status": "succeeded",
            "construction": {"catalog": "secret"},
            "semantic_results": [
                selected,
                {"fact": "secret", "evidence_chunk_ids": ["b"]},
            ],
        }
    ]
    if compacted:
        evidence["semantic_context"] = branches
    else:
        evidence["execution"] = {"outcomes": branches}
    projected = project_report(raw)
    output = projected["report"]["cases"][0]["output"]
    assert output["semantic_context"] == [
        {"branch": "structural", "semantic_results": [selected]}
    ]
    assert "secret" not in json.dumps(projected)


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
    assert all(m["value"] is not None for m in precision)
    full_text_precision = next(
        m for m in precision if m["branch"] == "full_text" and m["k"] == 5
    )
    assert full_text_precision["value"] == 0.2
    assert full_text_precision["label"] == "Reference precision@k"
    assert "unlisted chunks may still be useful" in full_text_precision["reason"]
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


@pytest.mark.parametrize("branch", ["full_text", "fused"])
@pytest.mark.parametrize("k", [1, 5, 10, 50])
def test_two_hop_means_include_startup_failures_from_recorded_scores(branch, k):
    raw = report()
    success = raw["report"]["cases"][0]
    success["expected_output"]["answers"][0]["groups"][1]["ids"] = ["a"]
    failure = copy.deepcopy(success)
    failure["name"] = "startup-failure"
    failure["output"].update(branches=[], evidence=None, failure={"stage": "startup"})
    failure["scores"] = {
        f"{branch}_complete_evidence_at_{k}": {
            "value": 0,
            "reason": "No retrieval completed.",
        }
    }
    raw["report"]["cases"].append(failure)
    result = project_report(raw)
    row = next(
        r
        for r in result["metrics"]
        if r["branch"] == branch and r["metric"] == "two_hop_recall" and r["k"] == k
    )
    assert row["value"] == 0.5
    assert row["scored_cases"] == row["applicable_cases"] == 2


@pytest.mark.parametrize("split", ["training", "validation", "test"])
def test_rag_run_cards_keep_the_recorded_dataset_split(tmp_path, split):
    raw = report()
    raw["split"] = split
    path = tmp_path / "run.json"
    path.write_text(json.dumps(raw))
    assert review_server.list_runs(tmp_path, "rag")[0]["split"] == split


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


def test_compact_retrieval_answer_without_introduction_enables_generation_axes():
    raw = report("retrieval", generation=True)
    output = raw["report"]["cases"][0]["output"]
    evidence = output["answer"].pop("evidence")
    output["evidence"] = evidence
    output["answer"]["introduction"] = None
    projected = project_report(raw)
    case = projected["report"]["cases"][0]
    assert required_axes(case) == AXES
    assert case["output"]["generation"] == output["rendered_text"]


def test_generation_failure_exposes_only_answer_diagnostic_and_keeps_context_judgeable():
    raw = report()
    raw["report"]["cases"][0]["output"]["failure"] = {
        "stage": "guidance",
        "exception_type": "ValidationError",
        "diagnostic": "RAG evaluation could not complete guidance.",
        "private": "secret",
    }
    case = project_report(raw)["report"]["cases"][0]
    assert required_axes(case) == ("context_relevance",)
    assert case["output"]["generation_failure"]["stage"] == "guidance"
    assert "secret" not in json.dumps(case)


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


def test_failed_and_unresolved_attempts_remain_visible_and_annotatable():
    raw = report()
    raw["report"]["failures"] = [
        {
            "name": "failed",
            "inputs": {"question": "Failed question"},
            "error_message": "Transport attempts exhausted",
            "error_stacktrace": "private internal stack",
        }
    ]
    raw["evaluation_run"] = {
        "status": "incomplete",
        "selected_count": 3,
        "terminal_count": 2,
        "selected_cases": [
            {"name": "case"},
            {"name": "failed"},
            {"name": "pending", "inputs": {"question": "Pending question"}},
        ],
        "unresolved_case_ids": ["pending"],
    }
    projected = project_report(raw)
    cases = projected["report"]["cases"]
    assert [case["name"] for case in cases] == ["case", "failed", "pending"]
    assert cases[1]["execution"]["status"] == "failed"
    assert cases[2]["execution"]["status"] == "unresolved"
    assert (
        cases[1]["execution"]["failure"]["diagnostic"] == "Transport attempts exhausted"
    )
    assert "private internal stack" not in json.dumps(projected)
    assert projected["evaluation_run"]["status"] == "incomplete"
    for case in cases[1:]:
        note = {**review(), "execution_note": "Inspect this attempt"}
        validate_review(note, case)
        assert review_complete(note, case)
        assert required_axes(case) == ()
        with pytest.raises(ValueError, match="cannot be judged"):
            validate_review({**note, "faithfulness": "fail"}, case)


def test_decline_and_chat_guidance_failures_keep_their_review_material():
    raw = report("chat")
    source = raw["report"]["cases"][0]
    declined = copy.deepcopy(source)
    declined["name"] = "declined"
    declined["output"] = {
        "preparation": {
            "status": "declined",
            "message": "Cannot establish completeness",
        },
        "rendered_text": "Cannot establish completeness",
    }
    source["output"]["failure"] = {
        "stage": "retrieval_and_guidance",
        "exception_type": "ValidationError",
        "diagnostic": "Guidance could not complete",
    }
    raw["report"]["cases"].append(declined)
    projected = project_report(raw)["report"]["cases"]
    assert (
        projected[0]["output"]["generation_failure"]["stage"]
        == "retrieval_and_guidance"
    )
    assert projected[1]["execution"]["message"] == "Cannot establish completeness"
    assert not projected[1]["output"]["has_generation"]


def test_progress_report_failure_notes_save_through_the_reviewer_api(tmp_path):
    raw = report()
    raw["report"]["cases"] = []
    raw["report"]["failures"] = [
        {
            "name": "failed",
            "inputs": {"question": "Question"},
            "error_message": "Failed",
        }
    ]
    raw["evaluation_run"] = {
        "status": "incomplete",
        "selected_cases": [{"name": "failed"}, {"name": "pending"}],
        "selected_count": 2,
        "terminal_count": 1,
    }
    directory = tmp_path / "retrieval"
    directory.mkdir()
    path = directory / "progress.json"
    path.write_text(json.dumps(raw))
    with server(tmp_path) as base:
        api = f"{base}/api/runs/retrieval--progress"
        projected = json.load(urlopen(f"{api}/report"))
        runs = json.load(urlopen(f"{base}/api/runs"))
        assert runs[0]["reviewable_count"] == 2
        assert runs[0]["execution_review_pending_count"] == 2
        assert runs[0]["run_status"] == "incomplete"
        for name in ("failed", "pending"):
            payload = {
                "name": name,
                "review": {**review(), "execution_note": f"Inspect {name}"},
                "review_identity": projected["review_identity"],
            }
            with urlopen(
                Request(
                    f"{api}/reviews",
                    data=json.dumps(payload).encode(),
                    headers={"Content-Type": "application/json"},
                )
            ) as response:
                assert response.status == 200
        finished = json.load(urlopen(f"{base}/api/runs"))[0]
        assert finished["reviewed_count"] == 2
        assert finished["unjudgeable_count"] == 2
        assert finished["execution_review_pending_count"] == 0
    saved = json.loads(path.with_suffix(".rag-reviews.json").read_text())
    assert saved["failed"]["execution_note"] == "Inspect failed"


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


def test_rag_judgments_allow_any_order_and_partial_reviews():
    case = project_report(report("chat", generation=True))["report"]["cases"][0]
    labels = review()
    labels["answer_relevance"] = "fail"
    labels["answer_relevance_note"] = "Answers a different question."
    validate_review(labels, case)
    assert not review_complete(labels, case)
    labels["faithfulness"] = "pass"
    validate_review(labels, case)
    assert labels["context_relevance"] is None
    labels["context_relevance"] = "defer"
    assert not review_complete(labels, case)
    labels["context_relevance"] = "pass"
    assert review_complete(labels, case)


def test_historical_reference_precision_uses_rank_and_article_grain_chunk_slots():
    raw = report()
    case = raw["report"]["cases"][0]
    case["expected_output"]["grain"] = "source_article"
    case["expected_output"]["relevant_ids"] = ["article"]
    case["expected_output"]["answers"] = [{"groups": [{"ids": ["article"]}]}]
    case["output"]["branches"][0]["candidates"] = [
        {"chunk_id": "noise", "source_article_id": "other", "rank": 3},
        {"chunk_id": "b", "source_article_id": "article", "rank": 2},
        {"chunk_id": "a", "source_article_id": "article", "rank": 1},
    ]
    projected = project_report(raw)
    rows = projected["report"]["cases"][0]["metrics"]
    precision = {
        r["k"]: r["value"]
        for r in rows
        if r["branch"] == "full_text" and r["metric"] == "precision"
    }
    assert precision == {1: 1, 5: 0.4, 10: 0.2, 50: 0.04}
    fused = next(
        r
        for r in rows
        if r["branch"] == "fused" and r["metric"] == "precision" and r["k"] == 5
    )
    assert fused["value"] == 0.4
    assert not any("precision" in name for name in case["scores"])


def test_precision_without_references_remains_unavailable_and_recorded_scores_survive():
    raw = report("chat", generation=True)
    case = raw["report"]["cases"][0]
    case.pop("expected_output")
    case["scores"]["full_text_precision_at_5"] = {"value": 0.8, "reason": "Recorded"}
    rows = project_report(raw)["report"]["cases"][0]["metrics"]
    assert (
        next(
            r["value"]
            for r in rows
            if r["branch"] == "full_text" and r["metric"] == "precision" and r["k"] == 5
        )
        == 0.8
    )
    assert (
        next(
            r["value"]
            for r in rows
            if r["branch"] == "dense" and r["metric"] == "precision" and r["k"] == 5
        )
        is None
    )
