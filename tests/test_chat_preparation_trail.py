"""Preparation and approval observations through the real chat ASGI interface."""

import json
from contextlib import asynccontextmanager

import httpx
import pytest
from pydantic_ai.exceptions import ModelHTTPError, UnexpectedModelBehavior
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel
from starlette.testclient import TestClient
from test_chat_session_trail import chat_capture as chat_capture  # noqa: PLC0414
from test_chat_startup import (
    startup_dependencies as startup_dependencies,  # noqa: PLC0414
)
from test_chat_web import events, question_request
from test_chat_web_answers import approval_request
from test_chat_web_corrections import correction_request, rejection_request

from knowledge_map.chat_startup import chat_dependencies
from knowledge_map.web import create_app


def observations(capture):
    return [
        span
        for span in capture.exported_spans_as_dict(parse_json_attributes=True)
        if span["name"].startswith("chat_session.")
    ]


def test_proposal_and_deferred_assessment_record_the_question_before_approval(
    startup_dependencies, chat_capture
):
    with TestClient(create_app(), base_url="http://localhost") as client:
        prepared = events(
            client.post("/api/chat", json=question_request("Who backed AB 1?"))
        )
        spans = observations(chat_capture)
        proposal = next(s for s in spans if s["name"] == "chat_session.query_rewrite")
        assessment = next(
            s for s in spans if s["name"] == "chat_session.question_assessment"
        )
        operation = next(s for s in spans if s["name"] == "chat_session.prepare")
        assert proposal["attributes"]["proposal_attempt"] == 1
        assert proposal["attributes"]["status"] == "proposed"
        assert (
            proposal["attributes"]["question"] == "Which organizations supported AB 1?"
        )
        assert proposal["attributes"]["relational"] is True
        assert assessment["attributes"]["proposal_attempt"] == 1
        assert assessment["attributes"]["status"] == "deferred"
        assert (
            assessment["attributes"]["explanation"]
            == "Complete lobbying records are unavailable."
        )
        assert (
            assessment["attributes"]["recoverable_portion"]
            == "CalMatters has 2 available articles."
        )
        assert len({s["attributes"]["chat_session_id"] for s in spans}) == 1
        assert all(s["attributes"]["audit_schema_version"] == 1 for s in spans)
        for stage in (proposal, assessment):
            assert stage["parent"]["span_id"] == operation["context"]["span_id"]
            assert stage["end_time"] <= operation["end_time"]
        assert "proposal_attempt" not in operation["attributes"]
        assert any(event["type"] == "tool-approval-request" for event in prepared)
        assert "Complete lobbying records are unavailable." in json.dumps(prepared)
        assert "relational" not in json.dumps(prepared)


def scripted_model(outputs):
    outputs = iter(outputs)

    def respond(messages, info):
        return ModelResponse(
            parts=[ToolCallPart(info.output_tools[0].name, next(outputs))]
        )

    return FunctionModel(respond)


def test_correction_and_approval_refer_to_the_proposal_used_by_retrieval(
    startup_dependencies, chat_capture
):
    _, _, _, _, requests, _, _, _ = startup_dependencies

    @asynccontextmanager
    async def startup():
        async with chat_dependencies() as dependencies:
            dependencies.rewriter.model = scripted_model(
                [
                    {
                        "question": "Which organizations supported AB 1?",
                        "relational": True,
                    },
                    {
                        "question": "Which articles discuss AB 1 in the 2025-2026 term?",
                        "relational": False,
                    },
                ]
            )
            dependencies.chat_agent.model = scripted_model(
                [
                    {"status": "allowed"},
                    {"status": "allowed"},
                    {"introduction": "Read the available reporting."},
                ]
            )
            yield dependencies

    with TestClient(create_app(startup=startup), base_url="http://localhost") as client:
        first = events(
            client.post("/api/chat", json=question_request("Who backed AB 1?"))
        )
        assert not any(request.method == "POST" for request in requests)
        rejected = events(client.post("/api/chat", json=rejection_request(first)))
        assert any(event["type"] == "tool-output-denied" for event in rejected)
        assert not any(
            s["name"] == "chat_session.approve" for s in observations(chat_capture)
        )
        revised = events(
            client.post(
                "/api/chat",
                json=correction_request(
                    first, "Find articles about the 2025-2026 term instead."
                ),
            )
        )
        assert "Which articles discuss AB 1 in the 2025-2026 term?" in json.dumps(
            revised
        )
        assert client.post("/api/chat", json=approval_request(first)).status_code == 409
        answered = events(client.post("/api/chat", json=approval_request(revised)))
    assert "Read the available reporting." in json.dumps(answered)
    embedding = next(
        request
        for request in requests
        if request.url.host == "unavailable-embedding.test"
    )
    assert json.loads(embedding.content)["input"] == [
        "Which articles discuss AB 1 in the 2025-2026 term?"
    ]
    spans = observations(chat_capture)
    proposals = [s for s in spans if s["name"] == "chat_session.query_rewrite"]
    assert [s["attributes"]["proposal_attempt"] for s in proposals] == [1, 2]
    assert [s["attributes"]["relational"] for s in proposals] == [True, False]
    assert (
        proposals[1]["attributes"]["question"]
        == "Which articles discuss AB 1 in the 2025-2026 term?"
    )
    correction = next(s for s in spans if s["name"] == "chat_session.rewrite_corrected")
    assert correction["attributes"]["proposal_attempt"] == 1
    assert (
        correction["attributes"]["correction"]
        == "Find articles about the 2025-2026 term instead."
    )
    approved = next(s for s in spans if s["name"] == "chat_session.rewrite_approved")
    assert approved["attributes"]["proposal_attempt"] == 2
    assert (
        approved["attributes"]["approved_question"]
        == "Which articles discuss AB 1 in the 2025-2026 term?"
    )
    assert approved["attributes"]["relational"] is False
    assessments = [s for s in spans if s["name"] == "chat_session.question_assessment"]
    assert [s["attributes"]["proposal_attempt"] for s in assessments] == [1, 2]
    assert [s["attributes"]["status"] for s in assessments] == ["allowed", "allowed"]
    roots = [
        s
        for s in spans
        if s["name"]
        in {"chat_session.prepare", "chat_session.correct", "chat_session.approve"}
    ]
    assert [s["name"] for s in roots] == [
        "chat_session.prepare",
        "chat_session.correct",
        "chat_session.approve",
    ]
    assert len({s["attributes"]["chat_session_id"] for s in spans}) == 1
    assert len({s["context"]["trace_id"] for s in roots}) == 3
    assert all(s["attributes"]["audit_schema_version"] == 1 for s in spans)
    assert all("proposal_attempt" not in s["attributes"] for s in roots)
    assert roots[0]["end_time"] < roots[1]["start_time"]
    assert roots[1]["end_time"] < roots[2]["start_time"]
    assert correction["parent"]["span_id"] == roots[1]["context"]["span_id"]
    assert approved["parent"]["span_id"] == roots[2]["context"]["span_id"]
    all_spans = chat_capture.exported_spans_as_dict(parse_json_attributes=True)
    by_id = {s["context"]["span_id"]: s for s in all_spans}
    agents = [
        s
        for s in all_spans
        if s["attributes"].get("gen_ai.operation.name") == "invoke_agent"
    ]
    assert len(agents) == 5
    for agent in agents:
        parent = by_id[agent["parent"]["span_id"]]
        assert parent["name"] in {
            "chat_session.query_rewrite",
            "chat_session.question_assessment",
            "chat_session.guidance",
        }
        assert (
            parent["start_time"]
            <= agent["start_time"]
            < agent["end_time"]
            <= parent["end_time"]
        )


def test_returned_rewrite_unavailability_records_its_safe_cause_without_approval(
    startup_dependencies, chat_capture
):
    _, _, _, _, _, failures, _, _ = startup_dependencies
    with TestClient(create_app(), base_url="http://localhost") as client:
        failures.add("rewriter.test")
        prepared = events(
            client.post("/api/chat", json=question_request("Who backed AB 1?"))
        )
    text = "".join(
        event["delta"] for event in prepared if event["type"] == "text-delta"
    )
    assert text == (
        "A temporary network problem prevented rewriting your question. "
        "The question cannot be answered right now. Please try again later."
    )
    assert not any(event["type"] == "tool-approval-request" for event in prepared)
    spans = observations(chat_capture)
    assert {span["name"] for span in spans} == {
        "chat_session.started",
        "chat_session.prepare",
        "chat_session.query_rewrite",
    }
    proposal = next(s for s in spans if s["name"] == "chat_session.query_rewrite")
    assert proposal["attributes"]["proposal_attempt"] == 1
    assert proposal["attributes"]["status"] == "unavailable"
    assert proposal["attributes"]["failure_kind"] == "transport"
    assert proposal["attributes"]["diagnostic"] == text
    assert "question" not in proposal["attributes"]
    assert "relational" not in proposal["attributes"]
    assert "private diagnostic" not in json.dumps([s["attributes"] for s in spans])


def test_declined_assessment_keeps_its_explanation_and_never_offers_approval(
    startup_dependencies, chat_capture
):
    @asynccontextmanager
    async def startup():
        async with chat_dependencies() as dependencies:
            dependencies.chat_agent.model = scripted_model(
                [
                    {
                        "status": "declined",
                        "explanation": "Predictions about the next legislative session are outside question policy.",
                    },
                ]
            )
            yield dependencies

    with TestClient(create_app(startup=startup), base_url="http://localhost") as client:
        declined = events(
            client.post("/api/chat", json=question_request("Who backed AB 1?"))
        )
        assert (
            client.post(
                "/api/chat", json=question_request("Another question")
            ).status_code
            == 409
        )
    assert [event["delta"] for event in declined if event["type"] == "text-delta"] == [
        "Predictions about the next legislative session are outside question policy."
    ]
    assert not any(event["type"] == "tool-approval-request" for event in declined)
    spans = observations(chat_capture)
    assert {s["name"] for s in spans} == {
        "chat_session.started",
        "chat_session.prepare",
        "chat_session.query_rewrite",
        "chat_session.question_assessment",
    }
    assessment = next(
        s for s in spans if s["name"] == "chat_session.question_assessment"
    )
    assert assessment["attributes"]["proposal_attempt"] == 1
    assert assessment["attributes"]["status"] == "declined"
    assert assessment["attributes"]["explanation"] == "[Scrubbed due to 'session']"
    assert "recoverable_portion" not in assessment["attributes"]
    assert "failure_kind" not in assessment["attributes"]


@pytest.mark.parametrize("reject_before_leaving", [False, True])
def test_leaving_before_approval_preserves_only_the_observed_preparation(
    startup_dependencies, chat_capture, reject_before_leaving
):
    with TestClient(create_app(), base_url="http://localhost") as client:
        prepared = events(
            client.post("/api/chat", json=question_request("Who backed AB 1?"))
        )
        assert any(event["type"] == "tool-approval-request" for event in prepared)
        before_leaving = observations(chat_capture)
        assert {s["name"] for s in before_leaving} == {
            "chat_session.started",
            "chat_session.prepare",
            "chat_session.query_rewrite",
            "chat_session.question_assessment",
        }
        assert all(s["end_time"] >= s["start_time"] for s in before_leaving)
        if reject_before_leaving:
            rejected = events(
                client.post("/api/chat", json=rejection_request(prepared))
            )
            assert any(event["type"] == "tool-output-denied" for event in rejected)
    assert observations(chat_capture) == before_leaving


@pytest.mark.parametrize(
    "stage, error, failure_kind",
    [
        (
            "query_rewrite",
            ModelHTTPError(401, "test-model", "private diagnostic"),
            "provider",
        ),
        (
            "query_rewrite",
            UnexpectedModelBehavior("private diagnostic"),
            "model_output",
        ),
        ("question_assessment", httpx.ConnectError("private diagnostic"), "transport"),
        (
            "question_assessment",
            ModelHTTPError(401, "test-model", "private diagnostic"),
            "provider",
        ),
        (
            "question_assessment",
            UnexpectedModelBehavior("private diagnostic"),
            "model_output",
        ),
        ("question_assessment", RuntimeError("private diagnostic"), "unexpected"),
    ],
)
def test_failed_preparation_stage_records_a_safe_kind_and_the_browser_stops(
    startup_dependencies, chat_capture, stage, error, failure_kind
):
    def fail(messages, info):
        raise error

    @asynccontextmanager
    async def startup():
        async with chat_dependencies() as dependencies:
            agent = (
                dependencies.rewriter
                if stage == "query_rewrite"
                else dependencies.chat_agent
            )
            agent.model = FunctionModel(fail)
            yield dependencies

    with TestClient(create_app(startup=startup), base_url="http://localhost") as client:
        failed = events(
            client.post("/api/chat", json=question_request("Who backed AB 1?"))
        )
        assert (
            client.post("/api/chat", json=question_request("Try again")).status_code
            == 409
        )
    assert [event["errorText"] for event in failed if event["type"] == "error"] == [
        "This question could not be completed. Start a new chat to ask a question."
    ]
    assert not any(event["type"] == "tool-approval-request" for event in failed)
    all_spans = chat_capture.exported_spans_as_dict(parse_json_attributes=True)
    spans = [s for s in all_spans if s["name"].startswith("chat_session.")]
    expected_names = {
        "chat_session.started",
        "chat_session.prepare",
        "chat_session.query_rewrite",
    }
    if stage == "question_assessment":
        expected_names.add("chat_session.question_assessment")
    assert {s["name"] for s in spans} == expected_names
    failure = next(s for s in spans if s["name"] == f"chat_session.{stage}")
    assert failure["attributes"]["proposal_attempt"] == 1
    assert failure["attributes"]["status"] == "failed"
    assert failure["attributes"]["failure_kind"] == failure_kind
    assert failure["attributes"]["diagnostic"] == (
        "The Query Rewriter could not prepare a proposal."
        if stage == "query_rewrite"
        else "The Chat Agent could not assess question policy and coverage."
    )
    assert "private diagnostic" not in json.dumps([s["attributes"] for s in all_spans])
    assert not any(
        event.name == "exception"
        for span in chat_capture.exported_spans
        for event in span.events
    )
    assert "private diagnostic" not in json.dumps(failed)
    for span in spans:
        assert not (
            {
                "gen_ai.input.messages",
                "gen_ai.output.messages",
                "input_tokens",
                "output_tokens",
                "retries",
            }
            & span["attributes"].keys()
        )
