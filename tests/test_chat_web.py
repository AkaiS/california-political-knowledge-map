"""Source Guides through the FastAPI boundary with controlled model and store IO."""

import json
from contextlib import asynccontextmanager, contextmanager
from time import monotonic
from types import SimpleNamespace

import httpx
import pytest
from anyio.lowlevel import checkpoint
from pydantic_ai import Agent
from pydantic_ai.messages import ModelResponse, ToolCallPart, UserPromptPart
from pydantic_ai.models.function import FunctionModel
from starlette.testclient import TestClient
from test_retrieval import COVERAGE, Branch, coordinator

from knowledge_map.core.chat import CHAT_INSTRUCTIONS, ChatSession
from knowledge_map.schemas.query_preparation import QuestionAssessment
from knowledge_map.schemas.retrieval import (
    FailedBranch,
    GroundingEvidence,
    RetrievalBranch,
    SourceArticleCitation,
)
from knowledge_map.web import create_app


def completed_guide(client, response):
    """Follow the accepted guide through the same persisted reads as the reader."""
    assert response.status_code == 202
    deadline = monotonic() + 5
    while response.json()["latest_attempt"]["status"] == "running":
        assert monotonic() < deadline, "Source Guide did not complete"
        response = client.get(f"/api/guides/{response.json()['guide_id']}")
    return response


async def completed_guide_async(client, response):
    assert response.status_code in {200, 202}
    deadline = monotonic() + 5
    while response.json()["latest_attempt"]["status"] == "running":
        assert monotonic() < deadline, "Source Guide did not complete"
        await checkpoint()
        response = await client.get(f"/api/guides/{response.json()['guide_id']}")
    return response


def submit_guide(client, **kwargs):
    return completed_guide(client, client.post("/api/questions", **kwargs))


async def submit_guide_async(client, **kwargs):
    return await completed_guide_async(
        client, await client.post("/api/questions", **kwargs)
    )


@asynccontextmanager
async def guide_async_client(*, transport, **kwargs):
    app = transport.app
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=transport, **kwargs) as client,
    ):
        yield client


@contextmanager
def guide_client(
    *,
    assessment=None,
    guidance=None,
    branches=None,
    db_path=None,
    coverage=COVERAGE,
    **retrieval_options,
):
    prompts = []
    branches = branches or {branch: Branch(branch) for branch in RetrievalBranch}

    def respond(messages, info):
        prompts.append(
            [
                part.content
                for message in messages
                for part in message.parts
                if isinstance(part, UserPromptPart)
            ]
        )
        output = (
            assessment or {"status": "allowed"}
            if "question_policy" in json.loads(prompts[-1][-1])
            else guidance or {"source_notes": []}
        )
        if isinstance(output, Exception):
            raise output
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, output)])

    agent = Agent(
        FunctionModel(respond),
        output_type=QuestionAssessment,
        instructions=CHAT_INSTRUCTIONS,
        retries=0,
    )

    @asynccontextmanager
    async def startup():
        yield SimpleNamespace(coverage=coverage)

    def session_factory(question, dependencies):
        return ChatSession(
            question,
            chat_agent=agent,
            retrieval=coordinator(
                branches, structural_reporting=True, **retrieval_options
            ),
            coverage=coverage,
            relevant_collection_ids=("reporting",),
        )

    with TestClient(
        create_app(
            startup=startup, session_factory=session_factory, guide_db_path=db_path
        ),
        base_url="http://localhost",
    ) as client:
        yield client, prompts, branches


def test_completed_guide_reopens_after_restart_without_current_sources_or_models(
    tmp_path,
):
    db_path = tmp_path / "document_store.db"
    question = "What should I read about AB 1's housing provisions in 2025?"
    with guide_client(
        db_path=db_path,
        assessment={
            "status": "deferred",
            "explanation": "Complete roll calls are unavailable.",
            "recoverable_portion": "Reporting can identify some votes.",
        },
        guidance={
            "source_notes": [
                {
                    "source_article_id": "https://example.com/dense",
                    "note": "Read the section on AB 1's housing provisions.",
                }
            ]
        },
        load_grounding=stored_article,
    ) as (client, _, _):
        submitted = submit_guide(client, json={"question": question}).json()
        guide_id = submitted["guide_id"]
        reopened = client.get(f"/api/guides/{guide_id}")
        assert reopened.json() == submitted
    with guide_client(
        db_path=db_path, assessment=RuntimeError("No model available after restart")
    ) as (client, prompts, branches):
        reopened = client.get(f"/api/guides/{guide_id}")
        saved = client.get("/api/guides").json()["guides"]
        assert reopened.json() == submitted
        assert saved[0]["guide_id"] == guide_id
        assert saved[0]["question"] == question
        assert saved[0]["status"] == "completed"
        assert prompts == []
        assert all(not branch.requests for branch in branches.values())
    guide = reopened.json()
    assert (
        guide["articles"][0]["reading_direction"]
        == "Read the section on AB 1's housing provisions."
    )
    assert guide["articles"][0]["citation"]["published_date"] == "2025-03-01"
    assert guide["latest_attempt"]["status"] == "completed"
    assert guide["latest_attempt"]["outcome"] == "completed"
    assert guide["assessment"]["status"] == "deferred"
    assert "Complete roll calls are unavailable." in guide["message"]
    assert "Reporting can identify some votes." in guide["message"]
    assert guide["created_at"] <= guide["latest_attempt"]["started_at"]
    assert guide["last_retrieved_at"] == guide["latest_attempt"]["finished_at"]
    assert "PRIVATE_CHUNK_SENTINEL" not in reopened.text


def test_failure_to_start_execution_leaves_a_saved_failed_question(tmp_path):
    db_path = tmp_path / "document_store.db"

    def unavailable(question, dependencies):
        raise RuntimeError("PRIVATE_STARTUP_FAILURE")

    with TestClient(
        create_app(
            startup=no_dependencies, session_factory=unavailable, guide_db_path=db_path
        ),
        base_url="http://localhost",
        raise_server_exceptions=False,
    ) as client:
        response = submit_guide(client, json={"question": "Who supported AB 1?"})
        assert response.status_code == 200
        guide = response.json()
        assert guide["status"] == "assessment_failed"
        assert guide["latest_attempt"]["status"] == "failed"
        assert "last_retrieved_at" not in guide
    with guide_client(db_path=db_path) as (client, prompts, _):
        assert client.get(f"/api/guides/{guide['guide_id']}").json() == guide
        assert prompts == []
        assert "PRIVATE_" not in client.get("/api/guides").text


@pytest.mark.parametrize(
    "assessment,guidance,outcome,state,retrieved",
    [
        (
            {"status": "needs_edit", "explanation": "Name the bill."},
            None,
            "needs_edit",
            "completed",
            False,
        ),
        (
            {
                "status": "declined",
                "explanation": "Predictions are outside the question policy.",
            },
            None,
            "declined",
            "completed",
            False,
        ),
        (
            {
                "status": "deferred",
                "explanation": "Complete roll calls are unavailable.",
                "recoverable_portion": "Reporting can identify some votes.",
            },
            None,
            "empty",
            "empty",
            True,
        ),
        ({"status": "allowed"}, None, "empty", "empty", True),
        (
            RuntimeError("PRIVATE_ASSESSMENT_FAILURE"),
            None,
            "assessment_failed",
            "failed",
            False,
        ),
        (
            {"status": "allowed"},
            RuntimeError("PRIVATE_GUIDANCE_FAILURE"),
            "guidance_failed",
            "failed",
            False,
        ),
    ],
)
def test_unsuccessful_and_empty_guides_restore_their_outcome_after_restart(
    tmp_path, assessment, guidance, outcome, state, retrieved
):
    db_path = tmp_path / "document_store.db"
    with guide_client(db_path=db_path, assessment=assessment, guidance=guidance) as (
        client,
        _,
        _,
    ):
        guide = submit_guide(client, json={"question": "Who backed that bill?"}).json()
    with guide_client(db_path=db_path, assessment=RuntimeError("Must not execute")) as (
        client,
        prompts,
        branches,
    ):
        reopened = client.get(f"/api/guides/{guide['guide_id']}")
        assert reopened.json() == guide
        assert guide["question"] == "Who backed that bill?"
        assert guide["status"] == outcome
        assert guide["latest_attempt"]["outcome"] == outcome
        assert guide["latest_attempt"]["status"] == state
        assert guide["latest_attempt"]["finished_at"]
        assert ("last_retrieved_at" in guide) == retrieved
        listing = client.get("/api/guides").json()["guides"]
        assert len(listing) == 1
        assert listing[0]["status"] == outcome
        if isinstance(assessment, dict):
            assert listing[0]["assessment"]["status"] == assessment["status"]
        assert prompts == []
        assert all(not branch.requests for branch in branches.values())
        assert "PRIVATE_" not in reopened.text


def test_saved_guide_navigation_handles_an_empty_store_and_unknown_identity():
    with guide_client() as (client, prompts, _):
        assert client.get("/api/guides").json() == {"guides": []}
        assert client.get("/api/guides/missing").status_code == 404
        assert prompts == []


def test_submission_searches_the_complete_question_without_rewriting_or_approval():
    question = (
        "Which organizations supported Senator Smith's AB 1 between 2024-01-01 "
        "and 2025-12-31? Find at most 5 reports, oldest publication first."
    )
    with guide_client() as (client, prompts, branches):
        response = submit_guide(client, json={"question": question})
    assert response.status_code == 200
    assert response.json()["question"] == question
    assert json.loads(prompts[0][0])["question"] == question
    assert prompts[1][1] == question
    for branch in branches.values():
        assert [request.rewrite.question for request, _ in branch.requests] == [
            question
        ]
    assert "approval" not in response.text


@pytest.mark.parametrize(
    "question, assessment, expected",
    [
        (
            "What is happening with housing in California?",
            {"status": "allowed"},
            "empty",
        ),
        (
            "Who supported that bill?",
            {
                "status": "needs_edit",
                "explanation": "Edit the complete question to name the bill.",
            },
            "needs_edit",
        ),
        (
            "Who will win the election?",
            {
                "status": "declined",
                "explanation": "Predictions are outside the question policy.",
            },
            "declined",
        ),
    ],
)
def test_assessment_preserves_broad_questions_and_requests_explicit_referents(
    question, assessment, expected
):
    with guide_client(assessment=assessment) as (client, _, branches):
        response = submit_guide(client, json={"question": question})
    assert response.status_code == 200
    guide = response.json()
    assert guide["status"] == expected
    assert guide["question"] == question
    assert guide["assessment"]["status"] == assessment["status"]
    assert all(
        bool(branch.requests) == (expected == "empty") for branch in branches.values()
    )
    if expected != "empty":
        assert guide["message"] == assessment["explanation"]


async def stored_article(candidate):
    return GroundingEvidence(
        chunk_id=candidate.chunk_id,
        text="PRIVATE_CHUNK_SENTINEL: the article's conclusions.",
        citation=SourceArticleCitation(
            source_article_id=candidate.source_article_id,
            title=f"Reporting {candidate.chunk_id}",
            url=candidate.source_article_id,
            published_date={"dense": "2025-03-01", "full_text": "2024-01-01"}.get(
                candidate.chunk_id
            ),
        ),
    )


def test_only_articles_with_reading_directions_are_public_in_relevance_order():
    with guide_client(
        guidance={
            "source_notes": [
                {
                    "source_article_id": "https://example.com/dense",
                    "note": "Read the section on AB 1's housing provisions.",
                },
                {
                    "source_article_id": "https://example.com/full_text",
                    "note": "Look for the discussion comparing organizations' concerns about AB 1.",
                },
            ]
        },
        load_grounding=stored_article,
    ) as (client, _, _):
        response = submit_guide(
            client,
            json={"question": "What are organizations saying about AB 1?"},
        )
    guide = response.json()
    assert guide["status"] == "completed"
    assert [article["citation"]["url"] for article in guide["articles"]] == [
        "https://example.com/dense",
        "https://example.com/full_text",
    ]
    assert (
        guide["articles"][0]["reading_direction"]
        == "Read the section on AB 1's housing provisions."
    )
    assert guide["articles"][1]["citation"]["published_date"] == "2024-01-01"
    for hidden in (
        "PRIVATE_CHUNK_SENTINEL",
        "structural",
        "passages",
        "execution",
        "chunk_id",
    ):
        assert hidden not in response.text


@pytest.mark.parametrize(
    "guidance",
    [
        {"source_notes": [{"source_article_id": "invented", "note": "Read this."}]},
        {
            "source_notes": [
                {"source_article_id": "https://example.com/dense", "note": "Read this."}
            ]
            * 2
        },
        {
            "source_notes": [
                {"source_article_id": "https://example.com/dense", "note": "   "}
            ]
        },
        RuntimeError("PRIVATE_PROVIDER_FAILURE"),
    ],
)
def test_invalid_or_unavailable_guidance_is_a_failure_not_an_empty_guide(guidance):
    with guide_client(guidance=guidance, load_grounding=stored_article) as (
        client,
        _,
        _,
    ):
        response = submit_guide(client, json={"question": "Who supported AB 1?"})
    assert response.status_code == 200
    assert response.json()["status"] == "guidance_failed"
    assert response.json()["articles"] == []
    assert "PRIVATE_" not in response.text


@pytest.mark.parametrize(
    "failure", ["assessment", "assembly", "all_branches", "one_branch"]
)
def test_failures_stay_typed_and_useful_sibling_sources_remain(failure, tmp_path):
    class Failed(Branch):
        async def retrieve(self, request, **kwargs):
            return FailedBranch(branch=self.branch)

    async def unavailable(candidate):
        raise OSError("PRIVATE_STORE_FAILURE")

    branches = {
        branch: (
            Failed(branch)
            if failure == "all_branches"
            or failure == "one_branch"
            and branch == RetrievalBranch.DENSE
            else Branch(branch)
        )
        for branch in RetrievalBranch
    }
    with guide_client(
        db_path=tmp_path / "guides.db",
        assessment=RuntimeError("PRIVATE_MODEL_FAILURE")
        if failure == "assessment"
        else {
            "status": "deferred",
            "explanation": "Complete roll calls are unavailable.",
            "recoverable_portion": "Reporting can identify some votes.",
        },
        guidance={
            "source_notes": []
            if failure == "all_branches"
            else [
                {
                    "source_article_id": "https://example.com/full_text",
                    "note": "Look for the section on recorded votes on AB 1.",
                }
            ]
        },
        branches=branches,
        load_grounding=unavailable if failure == "assembly" else stored_article,
    ) as (client, _, _):
        response = submit_guide(
            client, json={"question": "How did everyone vote on AB 1?"}
        )
    guide = response.json()
    with guide_client(db_path=tmp_path / "guides.db") as (client, prompts, _):
        assert client.get(f"/api/guides/{guide['guide_id']}").json() == guide
        assert prompts == []
    assert (
        guide["status"]
        == {
            "assessment": "assessment_failed",
            "assembly": "assembly_failed",
            "all_branches": "retrieval_failed",
            "one_branch": "completed",
        }[failure]
    )
    if failure == "one_branch":
        assert len(guide["articles"]) == 1
        assert guide["partial"] is True
        assert "Part of this search failed." in guide["message"]
        assert "Complete roll calls are unavailable." in guide["message"]
    assert "PRIVATE_" not in response.text


@pytest.mark.parametrize(
    "order, expected",
    [
        ("publication_asc", ["full_text", "dense", "structural"]),
        ("publication_desc", ["dense", "full_text", "structural"]),
    ],
)
def test_requested_publication_chronology_orders_all_included_articles_and_omits_missing_dates(
    order, expected
):
    with guide_client(
        assessment={"status": "allowed", "reading_order": order},
        guidance={
            "source_notes": [
                {
                    "source_article_id": f"https://example.com/{name}",
                    "note": "Read the section on AB 1's housing provisions.",
                }
                for name in ["structural", "dense", "full_text"]
            ]
        },
        load_grounding=stored_article,
    ) as (client, _, _):
        response = submit_guide(
            client,
            json={"question": "Find reporting on AB 1 in publication order."},
        )
    articles = response.json()["articles"]
    assert [article["citation"]["url"] for article in articles] == [
        f"https://example.com/{name}" for name in expected
    ]
    assert "published_date" not in articles[-1]["citation"]


def test_reader_page_serves_submission_and_editing_controls_without_external_assets():
    with guide_client() as (client, _, _):
        page = client.get("/")
        script = client.get("/guide.js")
        coverage = client.get("/api/coverage")
    assert page.status_code == 200
    assert "Source Guides" in page.text
    assert "Complete question" in page.text
    assert "Edit question" in page.text
    assert "New question" in page.text
    assert "Content-Security-Policy" in page.headers
    assert script.status_code == 200
    assert coverage.json() == {
        "entries": [{"name": "Reporting", "date_basis": "publication_date"}]
    }


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/guide.js",
        "/api/coverage",
        "/api/questions",
        "/api/guides",
        "/api/guides/saved",
        "/api/chat",
        "/docs",
    ],
)
def test_reader_routes_reject_nonlocal_host(path):
    with guide_client() as (client, _, _):
        response = client.get(path, headers={"Host": "attacker.example"})
    assert response.status_code == 421


@pytest.mark.parametrize(
    "payload",
    [
        {"question": " "},
        {"question": "AB 1", "model": "other"},
        {"question": "AB 1", "builtinTools": ["web"]},
    ],
)
def test_invalid_submissions_cannot_select_runtime_models_or_tools(payload):
    with guide_client() as (client, prompts, _):
        response = client.post("/api/questions", json=payload)
        simple_post = client.post(
            "/api/questions",
            content="question=AB+1",
            headers={"Content-Type": "text/plain"},
        )
    assert response.status_code == 422
    assert simple_post.status_code == 415
    assert prompts == []


@asynccontextmanager
async def no_dependencies():
    yield None


def question_request(question: str, conversation_id: str = "unused") -> dict:
    return {"question": question}


def events(response) -> dict:
    assert response.status_code == 200
    return response.json()
