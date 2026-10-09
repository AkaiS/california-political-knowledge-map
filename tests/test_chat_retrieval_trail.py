"""Retrieval branch observations through the real chat ASGI interface."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from neo4j import AsyncDriver
from starlette.testclient import TestClient
from structural_support import entity_outputs, scripted_agents
from test_chat_preparation_trail import scripted_model
from test_chat_session_trail import chat_capture as chat_capture  # noqa: PLC0414
from test_chat_web import (
    events,
    guide_async_client,
    no_dependencies,
    question_request,
    submit_guide,
    submit_guide_async,
)
from test_dense_retrieval import driver_for as dense_driver
from test_dense_retrieval import embedder_for, online_index
from test_full_text_retrieval import online_indexes
from test_query_preparation import rewriter_agent
from test_retrieval import COVERAGE, Branch, candidate, coordinator
from test_structural_retrieval import driver_for as structural_driver

from knowledge_map.adapters.dense import Neo4jDenseRetriever
from knowledge_map.adapters.full_text import Neo4jFullTextRetriever
from knowledge_map.adapters.structural import Neo4jStructuralRetriever
from knowledge_map.core.chat import ChatSession, get_chat_agent
from knowledge_map.core.retrieval import FullTextRetriever, ModelRetriever
from knowledge_map.schemas.retrieval import FailedBranch, RetrievalBranch
from knowledge_map.web import create_app


def chat_app(
    branches,
    *,
    relational=True,
    rewritten_question="Which organizations support AB 1?",
    **retrieval_options,
):
    agent = get_chat_agent()
    agent.model = scripted_model(
        [{"status": "allowed"}, {"introduction": "Read the available reporting."}]
    )
    rewriter = rewriter_agent()
    rewriter.model = scripted_model(
        [{"question": rewritten_question, "relational": relational}]
    )

    def session_factory(question, dependencies):
        return ChatSession(
            question,
            chat_agent=agent,
            rewriter=rewriter,
            retrieval=coordinator(branches, **retrieval_options),
            coverage=COVERAGE,
            relevant_collection_ids=("reporting",),
        )

    return create_app(startup=no_dependencies, session_factory=session_factory)


def branch_observations(capture):
    return {
        span["attributes"]["branch"]: span
        for span in capture.exported_spans_as_dict(parse_json_attributes=True)
        if span["name"] == "chat_session.retrieval_branch"
    }


@pytest.mark.parametrize(
    "completion_order",
    [
        (RetrievalBranch.DENSE, RetrievalBranch.STRUCTURAL, RetrievalBranch.FULL_TEXT),
        (RetrievalBranch.FULL_TEXT, RetrievalBranch.STRUCTURAL, RetrievalBranch.DENSE),
    ],
)
def test_concurrent_branch_spans_match_successful_and_empty_results(
    chat_capture, completion_order
):
    async def exercise():
        entered = {branch: asyncio.Event() for branch in RetrievalBranch}
        release = {branch: asyncio.Event() for branch in RetrievalBranch}
        finished = {branch: asyncio.Event() for branch in RetrievalBranch}

        class ConcurrentBranch(Branch):
            async def retrieve(self, request, **kwargs):
                entered[self.branch].set()
                await release[self.branch].wait()
                result = await super().retrieve(request, **kwargs)
                finished[self.branch].set()
                return result

        branches = {
            branch: ConcurrentBranch(
                branch,
                tuple(
                    candidate(branch, f"{branch}-{number}", rank=number)
                    for number in range(1, count + 1)
                ),
            )
            for branch, count in zip(RetrievalBranch, (2, 0, 1), strict=True)
        }
        async with guide_async_client(
            transport=httpx.ASGITransport(app=chat_app(branches)),
            base_url="http://localhost",
        ) as client:
            payload = question_request("Who backed AB 1?")
            approval = asyncio.create_task(submit_guide_async(client, json=payload))
            try:
                await asyncio.wait_for(
                    asyncio.gather(*(event.wait() for event in entered.values())), 2
                )
                for branch in completion_order:
                    release[branch].set()
                    await asyncio.wait_for(finished[branch].wait(), 2)
                completed = events(await approval)
            finally:
                for event in release.values():
                    event.set()
                await approval
        assert len({branch.requests[0][1] for branch in branches.values()}) == 1
        return completed

    completed = asyncio.run(exercise())
    details = completed
    assert details["status"] == "empty"
    spans = branch_observations(chat_capture)
    assert set(spans) == {"full_text", "dense", "structural"}
    assert {
        branch: span["attributes"]["candidate_count"] for branch, span in spans.items()
    } == {
        "full_text": 2,
        "dense": 0,
        "structural": 1,
    }
    for span in spans.values():
        attributes = span["attributes"]
        assert attributes["status"] == "succeeded"
        assert attributes["audit_schema_version"] == 1
        assert (
            not {"candidates", "routes", "scores", "embedding", "sequence"}
            & attributes.keys()
        )
    all_spans = chat_capture.exported_spans_as_dict(parse_json_attributes=True)
    approval = next(s for s in all_spans if s["name"] == "chat_session.submit")
    assert len({s["context"]["span_id"] for s in spans.values()}) == 3
    for span in spans.values():
        assert (
            span["attributes"]["chat_session_id"]
            == approval["attributes"]["chat_session_id"]
        )
        assert span["parent"]["span_id"] == approval["context"]["span_id"]
        assert span["context"]["trace_id"] == approval["context"]["trace_id"]
        assert (
            approval["start_time"]
            <= span["start_time"]
            < span["end_time"]
            <= approval["end_time"]
        )
    assert max(s["start_time"] for s in spans.values()) < min(
        s["end_time"] for s in spans.values()
    )


@pytest.mark.parametrize("failure", ["exception", "returned"])
def test_failed_branch_records_a_safe_cause_and_preserves_sibling_results(
    chat_capture, failure
):
    class BrokenBranch(Branch):
        async def retrieve(self, request, **kwargs):
            if failure == "exception":
                raise RuntimeError("private database credential")
            return FailedBranch(branch=self.branch)

    branches = {branch: Branch(branch) for branch in RetrievalBranch}
    branches[RetrievalBranch.DENSE] = BrokenBranch(RetrievalBranch.DENSE)
    with TestClient(chat_app(branches), base_url="http://localhost") as client:
        payload = question_request("Who backed AB 1?")
        completed = events(submit_guide(client, json=payload))
    details = completed
    assert details["status"] == "empty"
    spans = branch_observations(chat_capture)
    failed = spans["dense"]["attributes"]
    assert failed["status"] == "failed"
    assert failed["candidate_count"] == 0
    assert failed["failure_stage"] == (
        "execution" if failure == "exception" else "unavailable"
    )
    assert failed["failure_kind"] == (
        "unexpected" if failure == "exception" else "unspecified"
    )
    assert failed["diagnostic"] == (
        "The retrieval branch could not complete."
        if failure == "exception"
        else "The retriever returned a failure without a diagnostic."
    )
    assert "private database credential" not in json.dumps(
        [s["attributes"] for s in spans.values()]
    )
    for branch, span in spans.items():
        attributes = span["attributes"]
        assert attributes["status"] in {"succeeded", "failed"}
        assert attributes["candidate_count"] == (
            0 if attributes["status"] == "failed" else 1
        )
        if branch != "dense":
            assert attributes["candidate_count"] == 1
            assert "failure_kind" not in attributes


@pytest.mark.parametrize("failed_branch", list(RetrievalBranch))
def test_retriever_diagnostics_retain_the_observed_failure_stage(
    chat_capture, failed_branch
):
    branches: dict[RetrievalBranch, FullTextRetriever | ModelRetriever] = {
        branch: Branch(branch) for branch in RetrievalBranch
    }
    if failed_branch == RetrievalBranch.FULL_TEXT:
        driver = MagicMock(spec=AsyncDriver)
        result = AsyncMock()
        result.data.return_value = []
        driver.session.return_value.__aenter__.return_value.run = AsyncMock(
            return_value=result
        )
        branches[failed_branch] = Neo4jFullTextRetriever(driver)
        stage, kind = "index", "index_unavailable"
        diagnostic = "A required full-text index is missing, offline, or incompatible."
    elif failed_branch == RetrievalBranch.DENSE:
        branches[failed_branch] = Neo4jDenseRetriever(
            dense_driver(indexes=[]), embedder_for(), candidate_limit=5
        )
        stage, kind = "index", "index_unavailable"
        diagnostic = (
            "The Article Chunk vector index is missing, offline, or incompatible."
        )
    else:
        outputs = entity_outputs()
        outputs[0] = httpx.ConnectError("private provider credential")
        branches[failed_branch] = Neo4jStructuralRetriever(
            structural_driver(), agents=scripted_agents(outputs)
        )
        stage, kind = "schema_filtering", "transport"
        diagnostic = "Structural retrieval could not complete this stage."
    with TestClient(chat_app(branches), base_url="http://localhost") as client:
        payload = question_request("Who backed AB 1?")
        completed = events(submit_guide(client, json=payload))
    spans = branch_observations(chat_capture)
    attributes = spans[failed_branch]["attributes"]
    assert attributes["status"] == "failed"
    assert attributes["failure_stage"] == stage
    assert attributes["failure_kind"] == kind
    assert attributes["diagnostic"] == diagnostic
    assert attributes["candidate_count"] == 0
    details = completed
    assert details["status"] == "empty"
    for branch, span in spans.items():
        assert span["attributes"]["status"]
        if branch != failed_branch:
            assert span["attributes"]["candidate_count"] == 1
            assert "failure_kind" not in span["attributes"]
    assert "private provider credential" not in json.dumps(
        [s["attributes"] for s in spans.values()]
    )


@pytest.mark.parametrize("index_state", ["ONLINE", "POPULATING", None])
def test_index_observations_reuse_existing_lookups_without_candidate_payloads(
    chat_capture, index_state
):
    full_indexes = online_indexes()
    full_indexes[-1]["state"] = index_state
    dense_index = online_index()
    dense_index["state"] = index_state
    if index_state is None:
        full_indexes.pop()
    row = {
        "chunk_id": "private-candidate-id",
        "source_article_id": "https://example.com/private-candidate-id",
        "entry_id": "private-route-id",
        "labels": ["Bill", "NewsArticle", "Chunk"],
        "element_id": "private-element-id",
        "score": 0.987654321,
    }
    full_driver = MagicMock(spec=AsyncDriver)
    index_result, search_result = AsyncMock(), AsyncMock()
    index_result.data.return_value = full_indexes
    search_result.data.return_value = [row]
    full_run = full_driver.session.return_value.__aenter__.return_value.run
    full_run.side_effect = [index_result, search_result, search_result, search_result]
    vector_driver = dense_driver(
        indexes=[] if index_state is None else [dense_index], rows=[row]
    )
    branches = {
        RetrievalBranch.FULL_TEXT: Neo4jFullTextRetriever(
            full_driver, database="reporting"
        ),
        RetrievalBranch.DENSE: Neo4jDenseRetriever(
            vector_driver, embedder_for(), candidate_limit=5, database="reporting"
        ),
        RetrievalBranch.STRUCTURAL: Branch(RetrievalBranch.STRUCTURAL),
    }
    with TestClient(
        chat_app(branches, relational=False), base_url="http://localhost"
    ) as client:
        payload = question_request("Who backed AB 1?")
        completed = events(submit_guide(client, json=payload))
    spans = branch_observations(chat_capture)
    assert completed["status"] == "empty"
    assert spans["full_text"]["attributes"]["indexes"] == {
        "entity_name_fulltext_index": "ONLINE",
        "article_title_fulltext_index": "ONLINE",
        "chunk_text_fulltext_index": index_state,
    }
    assert spans["dense"]["attributes"]["indexes"] == {
        "chunk_vector_index": index_state
    }
    for branch in ("full_text", "dense"):
        assert spans[branch]["attributes"]["database"] == "reporting"
    expected_status = "succeeded" if index_state == "ONLINE" else "failed"
    for branch in ("full_text", "dense"):
        attributes = spans[branch]["attributes"]
        assert attributes["status"] == expected_status
        assert attributes["candidate_count"] == (
            0 if index_state != "ONLINE" else 3 if branch == "full_text" else 1
        )
    assert full_run.await_count == (4 if index_state == "ONLINE" else 1)
    assert (
        vector_driver.session.return_value.__aenter__.return_value.run.await_count
        == (2 if index_state == "ONLINE" else 1)
    )
    attributes_json = json.dumps([span["attributes"] for span in spans.values()])
    for excluded in (
        "private-candidate-id",
        "private-route-id",
        "private-element-id",
        "0.987654321",
        "embeddings",
        "candidates",
        "routes",
    ):
        assert excluded not in attributes_json


def test_prepared_search_terms_retain_legislative_session_wording(chat_capture):
    branches = {branch: Branch(branch) for branch in RetrievalBranch}
    with TestClient(
        chat_app(
            branches,
            rewritten_question="Which organizations support AB 1 in the 2025-2026 session?",
        ),
        base_url="http://localhost",
    ) as client:
        payload = question_request(
            "Which organizations support AB 1 in the 2025-2026 session?"
        )
        events(submit_guide(client, json=payload))
    assert branch_observations(chat_capture)["full_text"]["attributes"][
        "search_terms"
    ] == [
        "organizations",
        "support",
        "ab",
        "1",
        "2025",
        "2026",
        "session",
    ]


def test_shared_deadline_records_late_failure_and_keeps_completed_siblings(
    chat_capture,
):
    async def exercise():
        now = 100.0
        completed = {branch: asyncio.Event() for branch in RetrievalBranch}

        class DeadlineBranch(Branch):
            async def retrieve(self, request, **kwargs):
                nonlocal now
                result = await super().retrieve(request, **kwargs)
                if self.branch == RetrievalBranch.DENSE:
                    await completed[RetrievalBranch.FULL_TEXT].wait()
                    await completed[RetrievalBranch.STRUCTURAL].wait()
                    now = kwargs["deadline"]
                completed[self.branch].set()
                return result

        branches = {branch: DeadlineBranch(branch) for branch in RetrievalBranch}
        async with guide_async_client(
            transport=httpx.ASGITransport(app=chat_app(branches, clock=lambda: now)),
            base_url="http://localhost",
        ) as client:
            payload = question_request("Who backed AB 1?")
            response = await asyncio.wait_for(
                submit_guide_async(client, json=payload), 2
            )
        assert all(branch.requests[0][1] == 160.0 for branch in branches.values())
        return events(response)

    completed = asyncio.run(exercise())
    details = completed
    assert details["status"] == "assembly_failed"
    spans = branch_observations(chat_capture)
    failed = spans["dense"]["attributes"]
    assert failed["status"] == "failed"
    assert failed["failure_stage"] == "deadline"
    assert failed["failure_kind"] == "deadline_exhausted"
    assert (
        failed["diagnostic"]
        == "The retrieval deadline expired before this branch completed."
    )
    assert failed["candidate_count"] == 0
    for branch, span in spans.items():
        attributes = span["attributes"]
        assert attributes["status"] in {"succeeded", "failed"}
        assert attributes["candidate_count"] == (
            0 if attributes["status"] == "failed" else 1
        )
        if branch != "dense":
            assert attributes["status"] == "succeeded"
            assert attributes["candidate_count"] == 1
            assert "failure_kind" not in attributes
