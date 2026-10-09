"""Saved search limits and reader disclosures at the public HTTP boundary."""

import pytest
from test_chat_web import completed_guide, guide_client, stored_article, submit_guide
from test_retrieval import COVERAGE, Branch

from knowledge_map.schemas.retrieval import FailedBranch, RetrievalBranch


class FailedSearch:
    def __init__(self, branch=RetrievalBranch.DENSE):
        self.branch = branch

    async def retrieve(self, request, **kwargs):
        return FailedBranch(branch=self.branch)


def test_unmatched_portion_and_partial_search_keep_supported_reading_after_restart(
    tmp_path,
):
    db_path = tmp_path / "guides.db"
    branches = {branch: Branch(branch) for branch in RetrievalBranch}
    branches[RetrievalBranch.DENSE] = FailedSearch()
    with guide_client(
        db_path=db_path,
        branches=branches,
        load_grounding=stored_article,
        guidance={
            "source_notes": [
                {
                    "source_article_id": "https://example.com/full_text",
                    "note": "Read the housing grant eligibility section.",
                }
            ],
            "unmatched_requests": [
                {
                    "request_portion": "rural transit grants <img src=x>",
                    "explanation": "The selected reporting does not address this part of your question.",
                }
            ],
            "introduction": "UNSTRUCTURED_DIAGNOSTIC_MUST_NOT_BE_DISPLAYED",
        },
    ) as (client, _, _):
        response = submit_guide(
            client,
            json={
                "question": "Where can I read about housing and rural transit grants?"
            },
        )
        guide = response.json()
        assert guide["status"] == "completed"
        assert len(guide["articles"]) == 1
        assert {item["kind"] for item in guide["disclosures"]} == {
            "unmatched_request",
            "partial_search",
        }
        unmatched = next(
            item for item in guide["disclosures"] if item["kind"] == "unmatched_request"
        )
        assert unmatched["request_portion"] == "rural transit grants <img src=x>"
        assert guide["search_details"]["completion"] == "partial"
        assert guide["search_details"]["included_articles"] == 1
        for hidden in (
            "UNSTRUCTURED_DIAGNOSTIC",
            "Dense retrieval",
            "Graph connections",
            "PRIVATE_CHUNK",
            "chunk_id",
            "routes",
            "ranking",
        ):
            assert hidden not in response.text
    with guide_client(db_path=db_path) as (client, _, _):
        assert client.get(f"/api/guides/{guide['guide_id']}").json() == guide


def test_failed_update_keeps_saved_disclosures_separate_from_latest_attempt(tmp_path):
    from knowledge_map.schemas.evidence import EvidenceContextLimits

    db_path = tmp_path / "guides.db"
    with guide_client(
        db_path=db_path,
        context_limits=EvidenceContextLimits(max_passages=1),
        guidance={
            "source_notes": [],
            "unmatched_requests": [
                {
                    "request_portion": "transit grants",
                    "explanation": "No selected reading supports this requested portion.",
                }
            ],
        },
    ) as (client, _, _):
        saved = submit_guide(
            client,
            json={"question": "Where should I read about housing and transit grants?"},
        ).json()
        assert saved["search_details"]["selection_limited"] is True
    changed = COVERAGE.model_validate(
        {"entries": [{**COVERAGE.entries[0].model_dump(), "name": "New collection"}]}
    )
    with guide_client(
        db_path=db_path, coverage=changed, guidance=RuntimeError("PRIVATE_FAILURE")
    ) as (client, _, _):
        guide = completed_guide(
            client, client.post(f"/api/guides/{saved['guide_id']}/update", json={})
        ).json()
        assert guide["search_details"] == saved["search_details"]
        assert guide["disclosures"] == saved["disclosures"]
        assert guide["last_retrieved_at"] == saved["last_retrieved_at"]
        assert (
            guide["latest_attempt"]["search_details"]["collections"][0]["name"]
            == "New collection"
        )
        assert guide["latest_attempt"]["search_details"]["completion"] == "failed"
        assert guide["latest_attempt"]["disclosures"][0]["kind"] == "guidance_failed"


@pytest.mark.parametrize(
    "condition, outcome, disclosure, completion",
    [
        ("empty", "empty", "no_matches", "completed"),
        ("irrelevant", "empty", "irrelevant_candidates", "completed"),
        ("failed", "retrieval_failed", "retrieval_failed", "failed"),
        ("guidance", "guidance_failed", "guidance_failed", "failed"),
        ("declined", "declined", "declined", "not_searched"),
        ("deferred", "empty", "deferred", "completed"),
    ],
)
def test_search_explanations_follow_typed_outcomes_and_survive_restart(
    tmp_path, condition, outcome, disclosure, completion
):
    options = {}
    if condition == "empty":
        options["branches"] = {
            branch: Branch(branch, candidates=()) for branch in RetrievalBranch
        }
    elif condition == "failed":
        options["branches"] = {
            branch: FailedSearch(branch) for branch in RetrievalBranch
        }
    elif condition == "guidance":
        options["guidance"] = RuntimeError("PRIVATE_PROVIDER_DETAILS")
    elif condition in {"declined", "deferred"}:
        options["assessment"] = {
            "status": condition,
            "explanation": "No results is wording, not the state.",
        }
        if condition == "deferred":
            options["assessment"]["recoverable_portion"] = (
                "Reporting about votes may be searched."
            )
    else:
        options["guidance"] = {
            "source_notes": [],
            "introduction": "declined deferred failed no results",
        }
    db_path = tmp_path / "guides.db"
    with guide_client(db_path=db_path, **options) as (client, _, _):
        response = submit_guide(
            client, json={"question": "Where can I read about AB 1?"}
        )
        guide = response.json()
        assert guide["status"] == outcome
        assert disclosure in {item["kind"] for item in guide["disclosures"]}
        assert guide["search_details"]["completion"] == completion
        assert guide["latest_attempt"]["disclosures"] == guide["disclosures"]
        assert "PRIVATE_" not in response.text
        if condition in {"empty", "irrelevant"}:
            assert "does not establish" in guide["message"]
    with guide_client(db_path=db_path) as (client, _, _):
        assert client.get(f"/api/guides/{guide['guide_id']}").json() == guide


def test_search_scope_is_visible_and_saved_even_when_assessment_fails(tmp_path):
    coverage = COVERAGE.model_validate(
        {
            "entries": [
                {
                    **COVERAGE.entries[0].model_dump(),
                    "name": "California reporting",
                    "earliest_date": "2020-01-01",
                    "latest_date": "2025-12-31",
                }
            ]
        }
    )
    db_path = tmp_path / "guides.db"
    with guide_client(
        db_path=db_path, coverage=coverage, assessment=RuntimeError("PRIVATE_FAILURE")
    ) as (client, _, _):
        available = client.get("/api/coverage").json()["entries"]
        guide = submit_guide(
            client, json={"question": "Who supported AB 1 in 2025?"}
        ).json()
        assert guide["search_details"]["collections"] == available
        assert guide["search_details"]["completion"] == "failed"
        assert available[0]["name"] == "California reporting"
        assert available[0]["earliest_date"] == "2020-01-01"
        assert available[0]["latest_date"] == "2025-12-31"
        assert "availability" not in available[0]
        assert "collection_id" not in available[0]
    with guide_client(db_path=db_path) as (client, prompts, _):
        assert client.get(f"/api/guides/{guide['guide_id']}").json() == guide
        assert client.get("/api/coverage").json()["entries"] != available
        assert prompts == []


def test_article_publication_comes_only_from_its_registered_source_and_is_saved(
    tmp_path,
):
    from knowledge_map.adapters import sqlite_db

    db_path = str(tmp_path / "guides.db")
    sqlite_db.init_db(db_path)
    sqlite_db.register_publication(
        "reporting",
        "California Ledger <img src=x>",
        "https://example.com",
        db_path=db_path,
    )
    sqlite_db.cache_scraped_html(
        "https://example.com/dense", "reporting", None, db_path=db_path
    )
    with guide_client(
        db_path=db_path,
        load_grounding=stored_article,
        guidance={
            "source_notes": [
                {
                    "source_article_id": "https://example.com/dense",
                    "note": "Read the grant eligibility section.",
                },
                {
                    "source_article_id": "https://example.com/structural",
                    "note": "Read the CalMatters budget discussion.",
                },
            ]
        },
    ) as (client, _, _):
        guide = submit_guide(
            client, json={"question": "Where should I read about grants?"}
        ).json()
        assert guide["articles"][0]["publication"] == "California Ledger <img src=x>"
        assert guide["articles"][0]["citation"]["published_date"] == "2025-03-01"
        assert "publication" not in guide["articles"][1]
        assert "published_date" not in guide["articles"][1]["citation"]
    sqlite_db.update_publication(
        "reporting", name="Changed Publication", db_path=db_path
    )
    with guide_client(db_path=db_path) as (client, _, _):
        assert client.get(f"/api/guides/{guide['guide_id']}").json() == guide


def test_guidance_failure_retains_the_existing_deferred_explanation(tmp_path):
    with guide_client(
        db_path=tmp_path / "guides.db",
        assessment={
            "status": "deferred",
            "explanation": "Complete roll calls are unavailable.",
            "recoverable_portion": "Search reporting about the requested bill.",
        },
        guidance=RuntimeError("PRIVATE_FAILURE"),
    ) as (client, _, _):
        guide = submit_guide(
            client, json={"question": "Where can I read every AB 1 roll call?"}
        ).json()
    assert guide["status"] == "guidance_failed"
    assert {item["kind"] for item in guide["disclosures"]} == {
        "guidance_failed",
        "deferred",
    }
    assert "Complete roll calls are unavailable." in guide["message"]
    assert "Search reporting about the requested bill." in guide["message"]
