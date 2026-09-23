"""Approval and evidence presentation observed through the local chat protocol."""

import asyncio
import json

import httpx
import pytest
from pydantic_ai.messages import ModelResponse, ToolCallPart, UserPromptPart
from pydantic_ai.models.function import FunctionModel
from starlette.testclient import TestClient
from test_chat_web import events, no_dependencies, question_request
from test_query_preparation import rewrite_response, rewriter_agent
from test_retrieval import COVERAGE, coordinator, rewrite

from knowledge_map.core.chat import ChatSession, get_chat_agent
from knowledge_map.schemas.query_preparation import (
    AwaitingQueryApproval,
    QueryApproval,
    QueryRewrite,
    QuestionAssessment,
    RewriteRejection,
)
from knowledge_map.schemas.retrieval import (
    AppliedContextLimits,
    BranchCandidate,
    BranchRanking,
    CoverageAvailability,
    CoverageDescription,
    CoverageEntry,
    EvidenceAssemblyFailure,
    EvidencePackage,
    EvidencePassage,
    FailedBranch,
    FusedCandidate,
    GraphClaim,
    GraphNodeReference,
    GroundingEvidence,
    RetrievalAnswer,
    RetrievalBranch,
    RetrievalExecutionResult,
    RetrievalRequest,
    RetrievalRoute,
    SkippedBranch,
    SourceArticleCitation,
    SourceArticleEvidence,
    SourceDisagreement,
    SourceRelevanceNote,
    SuccessfulBranch,
)
from knowledge_map.web import create_app


def answer(
    *, sources=(), outcomes=None, coverage=None, relational=False, assessment=None
):
    return RetrievalAnswer(
        introduction="Consult the selected reporting.",
        evidence=EvidencePackage(
            execution=RetrievalExecutionResult(
                request=RetrievalRequest(
                    rewrite=QueryRewrite(
                        question="Which organizations supported AB 1?",
                        relational=relational,
                        assessment=assessment or QuestionAssessment(status="allowed"),
                    )
                ),
                outcomes=outcomes
                or (
                    SuccessfulBranch(branch=RetrievalBranch.FULL_TEXT, candidates=()),
                    SuccessfulBranch(branch=RetrievalBranch.DENSE, candidates=()),
                    SkippedBranch(),
                ),
            ),
            sources=sources,
            coverage=coverage or CoverageDescription(entries=()),
            context=AppliedContextLimits(
                unit="characters",
                limit=24000,
                used=0,
                max_passages=12,
                omitted_passages=0,
            ),
        ),
    )


def selected_answer(*, dense_failed=False):
    sources = []
    candidates = []
    for number, title, text in (
        (1, "Union backs AB 1", "The union supported AB 1."),
        (2, "Chamber opposes AB 1", "The chamber opposed AB 1."),
    ):
        citation = SourceArticleCitation(
            source_article_id=f"article-{number}",
            title=title,
            url=f"https://calmatters.org/article-{number}/",
            published_date="2026-09-01",
        )
        candidate = BranchCandidate(
            chunk_id=f"chunk-{number}",
            source_article_id=citation.source_article_id,
            ranking=BranchRanking(
                branch=RetrievalBranch.FULL_TEXT, rank=number, score=None
            ),
            routes=(
                RetrievalRoute(
                    kind="chunk_text",
                    matched_field="text",
                    entry_node=GraphNodeReference(id=f"chunk-{number}", label="Chunk"),
                    graph_claims=(
                        GraphClaim(
                            source=GraphNodeReference(id="union", label="Organization"),
                            target=GraphNodeReference(id="ab-1", label="Bill"),
                            relationship_type="DECLARED_STANCE",
                            claim_key={"alignment": "POSITIVE"},
                            chunk_ids=(f"chunk-{number}",),
                        ),
                    ),
                ),
            ),
            grounding=GroundingEvidence(
                chunk_id=f"chunk-{number}",
                citation=citation,
                text="UNVERIFIED_CANDIDATE_WORDING RAW_EXCEPTION INTERNAL_MODEL_OUTPUT DETAILED_FAILURE_DIAGNOSTIC",
            ),
        )
        candidates.append(candidate)
        sources.append(
            SourceArticleEvidence(
                citation=citation,
                passages=(
                    EvidencePassage(
                        source_article_id=citation.source_article_id,
                        text=text,
                        provenance="stored_chunk",
                        candidate=FusedCandidate(
                            chunk_id=candidate.chunk_id,
                            rank=number,
                            fusion_score=0.02,
                            contributions=(candidate,),
                        ),
                    ),
                ),
            )
        )
    selected = answer(
        sources=tuple(sources),
        coverage=CoverageDescription(
            entries=(
                CoverageEntry(
                    collection_id="calmatters",
                    name="CalMatters",
                    kind="publication",
                    description="California political reporting.",
                    limitations=("Reporting does not include complete roll calls.",),
                    availability=CoverageAvailability(available_count=37),
                    date_basis="publication_date",
                    earliest_date="2024-01-01",
                    latest_date="2026-09-01",
                ),
            )
        ),
        outcomes=(
            SuccessfulBranch(
                branch=RetrievalBranch.FULL_TEXT, candidates=tuple(candidates)
            ),
            FailedBranch(branch=RetrievalBranch.DENSE)
            if dense_failed
            else SuccessfulBranch(branch=RetrievalBranch.DENSE, candidates=()),
            SkippedBranch(),
        ),
    )
    return RetrievalAnswer(
        evidence=selected.evidence,
        introduction=selected.introduction,
        source_notes=(
            SourceRelevanceNote(
                source_article_id="article-1",
                note="This report records the union's position.",
            ),
        ),
        disagreements=(
            SourceDisagreement(
                source_article_ids=("article-1", "article-2"),
                description="These sources report different positions on the measure.",
            ),
        ),
    )


class AnswerSession:
    def __init__(self, outcome=None):
        self.outcome = outcome or answer()
        self.approvals = 0

    async def prepare(self):
        return AwaitingQueryApproval(
            approval=QueryApproval(question="Which organizations supported AB 1?")
        )

    async def approve(self):
        self.approvals += 1
        return self.outcome

    def reject(self, correction=None) -> RewriteRejection:
        pytest.fail("Rejection requires a correction from the composer")


def approval_request(
    preparation, *, question="Who backed AB 1?", conversation_id="conversation-1"
):
    proposal = next(
        event for event in preparation if event["type"] == "tool-input-available"
    )
    request = question_request(question, conversation_id)
    request["messages"].append(
        {
            "id": preparation[0]["messageId"],
            "role": "assistant",
            "parts": [
                {
                    "type": "tool-Query approval",
                    "toolCallId": proposal["toolCallId"],
                    "state": "approval-responded",
                    "input": proposal["input"],
                    "approval": {"id": proposal["toolCallId"], "approved": True},
                }
            ],
        }
    )
    return request


def approve_question(client, question, *, conversation_id="conversation-1"):
    prepared = events(
        client.post("/api/chat", json=question_request(question, conversation_id))
    )
    response = client.post(
        "/api/chat",
        json=approval_request(
            prepared, question=question, conversation_id=conversation_id
        ),
    )
    return response, events(response)


def test_approval_returns_one_answer_and_cannot_be_consumed_again():
    session = AnswerSession()
    with TestClient(
        create_app(startup=no_dependencies, session_factory=lambda *_: session),
        base_url="http://localhost",
    ) as client:
        prepared = events(
            client.post("/api/chat", json=question_request("Who backed AB 1?"))
        )
        payload = approval_request(prepared)
        completed = events(client.post("/api/chat", json=payload))
        repeated = client.post("/api/chat", json=payload)

    assert session.approvals == 1
    assert "Consult the selected reporting." in "".join(
        event["delta"] for event in completed if event["type"] == "text-delta"
    )
    assert repeated.status_code == 409


@pytest.mark.parametrize("changed_field", ["approval_id", "tool_call_id", "message_id"])
def test_unmatched_approval_does_not_consume_the_pending_proposal(changed_field):
    session = AnswerSession()
    with TestClient(
        create_app(startup=no_dependencies, session_factory=lambda *_: session),
        base_url="http://localhost",
    ) as client:
        prepared = events(
            client.post("/api/chat", json=question_request("Who backed AB 1?"))
        )
        invalid = approval_request(prepared)
        message = invalid["messages"][-1]
        part = message["parts"][0]
        if changed_field == "approval_id":
            part["approval"]["id"] = "a-different-approval"
        elif changed_field == "tool_call_id":
            part["toolCallId"] = "a-different-call"
        elif changed_field == "message_id":
            message["id"] = "a-different-message"
        rejected = client.post("/api/chat", json=invalid)
        assert rejected.status_code == 409
        assert session.approvals == 0
        events(client.post("/api/chat", json=approval_request(prepared)))
    assert session.approvals == 1


def test_search_details_remain_browser_presentation_outside_chat_agent_context_and_tools():
    prompts = []
    tools = []

    def respond(messages, info):
        prompts.append(
            [
                part.content
                for message in messages
                for part in message.parts
                if isinstance(part, UserPromptPart)
            ]
        )
        tools.extend(info.function_tools)
        output = (
            {"status": "allowed"}
            if len(prompts) == 1
            else {"introduction": "Read these sources."}
        )
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, output)])

    agent, rewriter = get_chat_agent(), rewriter_agent()

    def session_factory(question, dependencies):
        return ChatSession(
            question,
            chat_agent=agent,
            rewriter=rewriter,
            retrieval=coordinator(),
            coverage=COVERAGE,
            relevant_collection_ids=("reporting",),
        )

    with (
        agent.override(model=FunctionModel(respond)),
        rewriter.override(model=rewrite_response(rewrite().question, False)),
        TestClient(
            create_app(startup=no_dependencies, session_factory=session_factory),
            base_url="http://localhost",
        ) as client,
    ):
        _, completed = approve_question(client, "Who backed AB 1?")

    assert any(event.get("toolName") == "Search details" for event in completed)
    assert len(prompts) == 2
    assert "Search details" not in json.dumps(prompts)
    assert "outcome" not in json.loads(prompts[-1][-1])
    assert tools == []


def test_answer_numbers_source_links_and_shows_only_selected_passages():
    session = AnswerSession(selected_answer(dense_failed=True))
    with TestClient(
        create_app(startup=no_dependencies, session_factory=lambda *_: session),
        base_url="http://localhost",
    ) as client:
        _, completed = approve_question(client, "Who backed AB 1?")

    text = "".join(
        event["delta"] for event in completed if event["type"] == "text-delta"
    )
    assert "1. [Union backs AB 1](<https://calmatters.org/article-1/>)" in text
    assert "2. [Chamber opposes AB 1](<https://calmatters.org/article-2/>)" in text
    assert text.count("Stored Article Chunk:") == 2
    assert "The union supported AB 1." in text
    assert "The chamber opposed AB 1." in text
    assert "> The union supported AB 1." not in text
    assert "This report records the union's position." in text
    assert "These sources report different positions on the measure." in text
    assert "Dense retrieval could not be completed." in text
    assert "UNVERIFIED_CANDIDATE_WORDING" not in text


def test_search_details_include_routes_branch_ranks_graph_claims_and_coverage():
    session = AnswerSession(selected_answer())
    with TestClient(
        create_app(startup=no_dependencies, session_factory=lambda *_: session),
        base_url="http://localhost",
    ) as client:
        response, completed = approve_question(client, "Who backed AB 1?")

    operation = next(
        event for event in completed if event.get("toolName") == "Search details"
    )
    details = next(
        event["output"]
        for event in completed
        if event["type"] == "tool-output-available"
        and event["toolCallId"] == operation["toolCallId"]
    )
    assert details["outcome"] == "retrieval_answer"
    assert [(branch["branch"], branch["status"]) for branch in details["branches"]] == [
        ("full_text", "succeeded"),
        ("dense", "succeeded"),
        ("structural", "skipped"),
    ]
    candidate = details["branches"][0]["candidates"][0]
    assert candidate == {
        "chunk_id": "chunk-1",
        "source_article_id": "article-1",
        "ranking": {"branch": "full_text", "rank": 1, "score": None},
        "routes": [
            {
                "kind": "chunk_text",
                "matched_field": "text",
                "entry_node": {"id": "chunk-1", "label": "Chunk", "element_id": None},
                "graph_claims": [
                    {
                        "source": {
                            "id": "union",
                            "label": "Organization",
                            "element_id": None,
                        },
                        "target": {"id": "ab-1", "label": "Bill", "element_id": None},
                        "relationship_type": "DECLARED_STANCE",
                        "claim_key": {"alignment": "POSITIVE"},
                        "chunk_ids": ["chunk-1"],
                        "source_article_ids": [],
                        "needs_review": False,
                    }
                ],
            }
        ],
    }
    assert details["branches"][2]["reason"] == "non_relational"
    assert details["coverage"]["entries"] == [
        {
            "collection_id": "calmatters",
            "name": "CalMatters",
            "kind": "publication",
            "description": "California political reporting.",
            "limitations": ["Reporting does not include complete roll calls."],
            "availability": {"available_count": 37, "expected_count": None},
            "date_basis": "publication_date",
            "earliest_date": "2024-01-01",
            "latest_date": "2026-09-01",
        }
    ]
    assert "UNVERIFIED_CANDIDATE_WORDING" not in response.text
    assert '"grounding"' not in response.text
    for forbidden in (
        "RAW_EXCEPTION",
        "INTERNAL_MODEL_OUTPUT",
        "DETAILED_FAILURE_DIAGNOSTIC",
    ):
        assert forbidden not in response.text


@pytest.mark.parametrize("failed_count", [0, 1, 2, 3])
def test_main_answer_keeps_deferred_and_every_branch_failure_visible(failed_count):
    failures = (
        (
            RetrievalBranch.STRUCTURAL,
            "Graph connections matching the question could not be searched.",
        ),
        (RetrievalBranch.FULL_TEXT, "Full-text retrieval could not be completed."),
        (RetrievalBranch.DENSE, "Dense retrieval could not be completed."),
    )
    failed = {branch for branch, _ in failures[:failed_count]}
    outcome = answer(
        relational=True,
        assessment=QuestionAssessment(
            status="deferred",
            explanation="Complete roll calls are not available.",
            recoverable_portion="Reporting can identify some votes.",
        ),
        outcomes=tuple(
            FailedBranch(branch=branch)
            if branch in failed
            else SuccessfulBranch(branch=branch, candidates=())
            for branch in RetrievalBranch
        ),
    )
    with TestClient(
        create_app(
            startup=no_dependencies, session_factory=lambda *_: AnswerSession(outcome)
        ),
        base_url="http://localhost",
    ) as client:
        _, completed = approve_question(client, "Who voted yes?")

    text = "".join(
        event["delta"] for event in completed if event["type"] == "text-delta"
    )
    assert "Complete roll calls are not available." in text
    for _, disclosure in failures[:failed_count]:
        assert disclosure in text
    if not failed:
        assert (
            "No matching graph connections were found in the available graph." in text
        )


def test_assembly_failure_discloses_limits_without_presenting_audit_candidates_as_passages():
    selected = selected_answer()
    execution = RetrievalExecutionResult(
        request=RetrievalRequest(
            rewrite=QueryRewrite(
                question="Who voted for AB 1?",
                relational=False,
                assessment=QuestionAssessment(
                    status="deferred",
                    explanation="Complete roll calls are not available.",
                    recoverable_portion="Reporting can identify some votes.",
                ),
            )
        ),
        outcomes=(
            selected.evidence.execution.outcomes[0],
            FailedBranch(branch=RetrievalBranch.DENSE),
            SkippedBranch(),
        ),
    )
    outcome = EvidenceAssemblyFailure(execution=execution)
    with TestClient(
        create_app(
            startup=no_dependencies, session_factory=lambda *_: AnswerSession(outcome)
        ),
        base_url="http://localhost",
    ) as client:
        response, completed = approve_question(client, "Who voted yes?")

    text = "".join(
        event["delta"] for event in completed if event["type"] == "text-delta"
    )
    assert "Grounding Evidence could not be assembled." in text
    assert "Dense retrieval could not be completed." in text
    assert "Complete roll calls are not available." in text
    assert "The union supported AB 1." not in text
    assert "Union backs AB 1" not in text
    assert "https://calmatters.org/article-1/" not in text
    assert "UNVERIFIED_CANDIDATE_WORDING" not in response.text
    details = next(
        event["output"]
        for event in completed
        if event["type"] == "tool-output-available"
        and event["output"].get("outcome") == "assembly_failed"
    )
    assert details["branches"][0]["candidates"][0]["chunk_id"] == "chunk-1"
    assert details["branches"][1] == {"branch": "dense", "status": "failed"}
    assert details["coverage"] is None


def test_search_details_run_while_approval_waits_and_complete_only_after_it_returns():
    async def exercise():
        release = asyncio.Event()
        entered = asyncio.Event()
        running = asyncio.Event()
        delivered = []

        class WaitingSession(AnswerSession):
            async def approve(self):
                entered.set()
                await release.wait()
                return await super().approve()

        session = WaitingSession()
        app = create_app(startup=no_dependencies, session_factory=lambda *_: session)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://localhost"
        ) as client:
            prepared = events(
                await client.post(
                    "/api/chat", json=question_request("Who backed AB 1?")
                )
            )
            payload = approval_request(prepared)

            async def receive():
                return {"type": "http.request", "body": json.dumps(payload).encode()}

            async def send(message):
                if message["type"] != "http.response.body":
                    return
                for line in message.get("body", b"").decode().splitlines():
                    if line.startswith("data: ") and line != "data: [DONE]":
                        event = json.loads(line[6:])
                        delivered.append(event)
                        if event.get("toolName") == "Search details":
                            running.set()

            request = asyncio.create_task(
                app(
                    {
                        "type": "http",
                        "asgi": {"version": "3.0", "spec_version": "2.4"},
                        "http_version": "1.1",
                        "method": "POST",
                        "scheme": "http",
                        "path": "/api/chat",
                        "raw_path": b"/api/chat",
                        "query_string": b"",
                        "root_path": "",
                        "server": ("localhost", 80),
                        "headers": [
                            (b"host", b"localhost"),
                            (b"content-type", b"application/json"),
                        ],
                    },
                    receive,
                    send,
                )
            )
            try:
                await asyncio.wait_for(entered.wait(), timeout=2)
                await asyncio.wait_for(running.wait(), timeout=2)
                operation = next(
                    event
                    for event in delivered
                    if event.get("toolName") == "Search details"
                )
                assert operation["type"] == "tool-input-available"
                assert not any(event["type"] == "text-delta" for event in delivered)
                assert not any(
                    event["type"] == "tool-output-available"
                    and event["toolCallId"] == operation["toolCallId"]
                    for event in delivered
                )
                repeated = await client.post("/api/chat", json=payload)
                assert repeated.status_code == 409
            finally:
                release.set()
                await request

        assert session.approvals == 1
        assert any(event["type"] == "text-delta" for event in delivered)
        assert any(
            event["type"] == "tool-output-available"
            and event["toolCallId"] == operation["toolCallId"]
            for event in delivered
        )

    asyncio.run(exercise())
