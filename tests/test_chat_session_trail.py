"""Chat Session observations captured offline through the ASGI interface."""

import hashlib
import json
import subprocess
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import UUID

import logfire
import pytest
from logfire.testing import TestExporter
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel
from starlette.testclient import TestClient
from test_chat_startup import (
    startup_dependencies as startup_dependencies,  # noqa: PLC0414
)
from test_chat_web import events, question_request

from knowledge_map.chat_startup import chat_dependencies
from knowledge_map.utils.telemetry import scrub_chat_audit_attribute, setup_telemetry
from knowledge_map.web import create_app


@pytest.fixture
def chat_capture():
    # Keep the production instrumentation and scrubbing with an offline exporter.
    setup_telemetry()
    exporter = TestExporter()
    logfire.configure(
        send_to_logfire=False,
        console=False,
        scrubbing=logfire.ScrubbingOptions(callback=scrub_chat_audit_attribute),
        additional_span_processors=[SimpleSpanProcessor(exporter)],
    )
    return exporter


def test_first_question_starts_a_trail_and_closes_preparation_before_approval(
    startup_dependencies, chat_capture
):
    with TestClient(create_app(), base_url="http://localhost") as client:
        prepared = events(
            client.post(
                "/api/chat",
                json=question_request("Who backed AB 1 in the 2025-2026 session?"),
            )
        )
        spans = chat_capture.exported_spans_as_dict(parse_json_attributes=True)
        starts = [span for span in spans if span["name"] == "chat_session.started"]
        assert len(starts) == 1
        start = starts[0]
        session_id = start["attributes"]["chat_session_id"]
        assert UUID(session_id).version == 4
        assert session_id != "conversation-1"
        assert session_id.replace("-", "") != f"{start['context']['trace_id']:032x}"
        assert start["attributes"]["audit_schema_version"] == 1
        assert (
            start["attributes"]["original_question"]
            == "Who backed AB 1 in the 2025-2026 session?"
        )
        preparation = next(
            span for span in spans if span["name"] == "chat_session.prepare"
        )
        assert preparation["attributes"]["chat_session_id"] == session_id
        assert preparation["attributes"]["audit_schema_version"] == 1
        assert preparation["end_time"] > preparation["start_time"]
        agent_spans = [
            span
            for span in spans
            if span["attributes"].get("gen_ai.operation.name") == "invoke_agent"
        ]
        assert len(agent_spans) == 2
        stages = {
            span["context"]["span_id"]: span
            for span in spans
            if span["name"]
            in {"chat_session.query_rewrite", "chat_session.question_assessment"}
        }
        for span in agent_spans:
            stage = stages[span["parent"]["span_id"]]
            assert stage["parent"]["span_id"] == preparation["context"]["span_id"]
            assert span["context"]["trace_id"] == preparation["context"]["trace_id"]
            assert span["end_time"] <= preparation["end_time"]
        assert any(event["type"] == "tool-approval-request" for event in prepared)
        text = "".join(
            event["delta"] for event in prepared if event["type"] == "text-delta"
        )
        assert text == (
            "Which organizations supported AB 1?\n\n"
            "Complete lobbying records are unavailable.\n\n"
            "CalMatters has 2 available articles."
        )


def test_audit_text_keeps_secret_scrubbing_even_when_it_mentions_a_session(
    startup_dependencies, chat_capture
):
    secret = "credential-shaped-value"
    with TestClient(create_app(), base_url="http://localhost") as client:
        events(
            client.post(
                "/api/chat",
                json=question_request(
                    f"Who backed AB 1 in this session? api_key={secret}"
                ),
            )
        )
    logfire.info(
        "audit redaction probe",
        rendered_text=f"During this session, api_key={secret}",
        selected_sources=[{"passages": [{"text": f"session password={secret}"}]}],
        correction=f"session_token={secret}",
    )
    spans = chat_capture.exported_spans_as_dict(parse_json_attributes=True)
    start = next(span for span in spans if span["name"] == "chat_session.started")
    probe = next(span for span in spans if span["name"] == "audit redaction probe")
    assert UUID(start["attributes"]["chat_session_id"]).version == 4
    assert secret not in json.dumps(start["attributes"])
    for field in ("rendered_text", "selected_sources", "correction"):
        assert secret not in json.dumps(probe["attributes"][field])


def test_legislative_session_id_remains_in_the_recorded_question(
    startup_dependencies, chat_capture
):
    question = "Which bill has legislative session ID 2025-2026?"
    with TestClient(create_app(), base_url="http://localhost") as client:
        events(client.post("/api/chat", json=question_request(question)))

    start = next(
        span
        for span in chat_capture.exported_spans_as_dict(parse_json_attributes=True)
        if span["name"] == "chat_session.started"
    )
    assert start["attributes"]["original_question"] == question


def test_start_records_resolved_settings_and_already_measured_coverage(
    startup_dependencies, chat_capture, monkeypatch
):
    _, driver, _, _, requests, _, _, _ = startup_dependencies
    monkeypatch.setenv("EMBEDDING_MODEL", "embedding-test")

    def git_result(args, **kwargs):
        output = (
            "a" * 40 if "rev-parse" in args else " M src/knowledge_map/core/chat.py"
        )
        return subprocess.CompletedProcess(args, 0, stdout=output, stderr="")

    monkeypatch.setattr(subprocess, "run", git_result)
    before_startup = datetime.now(UTC)
    with TestClient(create_app(), base_url="http://localhost") as client:
        before_question = datetime.now(UTC)
        monkeypatch.setenv("QUERY_REWRITER_MODEL", "changed-after-startup")
        monkeypatch.setenv("EMBEDDING_MODEL", "changed-after-startup")
        events(client.post("/api/chat", json=question_request("Who backed AB 1?")))
    after_question = datetime.now(UTC)

    spans = chat_capture.exported_spans_as_dict(parse_json_attributes=True)
    start = next(
        span["attributes"] for span in spans if span["name"] == "chat_session.started"
    )
    assert start["code_revision"] == "a" * 40
    assert start["worktree_dirty"] is True
    assert (
        before_question
        <= datetime.fromisoformat(start["observed_at"])
        <= after_question
    )
    assert (
        before_startup
        <= datetime.fromisoformat(start["coverage_observed_at"])
        <= before_question
    )
    deployments = start["model_deployments"]
    assert set(deployments) == {
        "query_rewriter",
        "chat_agent",
        "structural_ontology_filter",
        "structural_selector",
        "structural_wiring",
        "structural_binder",
    }
    assert deployments["query_rewriter"]["model"] == "rewriter-test"
    assert deployments["query_rewriter"]["endpoint"] == "http://rewriter.test:8080/v1/"
    assert deployments["chat_agent"]["model"] == "chat-test"
    assert deployments["chat_agent"]["endpoint"] == "http://chat.test:8080/v1/"
    assert deployments["chat_agent"]["request_settings"]["temperature"] == 0
    for role in (
        "structural_ontology_filter",
        "structural_selector",
        "structural_wiring",
        "structural_binder",
    ):
        assert deployments[role] == deployments["chat_agent"]
    assert start["embedding_settings"] == {
        "model": "embedding-test",
        "endpoint": "http://unavailable-embedding.test/v1/",
    }
    assert start["fusion_settings"] == {
        "full_text_weight": 1.0,
        "dense_weight": 1.0,
        "structural_weight": 2.0,
        "rank_constant": 60.0,
        "full_text_candidate_limit": 50,
        "dense_candidate_limit": 50,
        "structural_candidate_limit": 50,
        "fused_candidate_limit": 100,
    }
    assert start["evidence_limits"] == {"character_limit": 24000, "max_passages": 12}
    assert set(start["prompt_hashes"]) == set(deployments) | {"question_policy"}
    for host, role in (
        ("rewriter.test", "query_rewriter"),
        ("chat.test", "chat_agent"),
    ):
        request = next(
            request
            for request in requests
            if request.method == "POST" and request.url.host == host
        )
        prompt = json.loads(request.content)["messages"][0]["content"]
        assert (
            start["prompt_hashes"][role]
            == "sha256:" + hashlib.sha256(prompt.encode()).hexdigest()
        )
    assessment_request = next(
        request
        for request in requests
        if request.method == "POST" and request.url.host == "chat.test"
    )
    assessment = json.loads(
        json.loads(assessment_request.content)["messages"][-1]["content"]
    )
    assert start["coverage"] == assessment["coverage"]
    assert start["coverage"]["entries"][0]["availability"]["available_count"] == 2
    assert (
        start["prompt_hashes"]["question_policy"]
        == "sha256:"
        + hashlib.sha256(assessment["question_policy"].encode()).hexdigest()
    )
    driver.session.return_value.__aenter__.return_value.run.assert_awaited_once()
    assert len([request for request in requests if request.method == "GET"]) == 2
    assert len([request for request in requests if request.method == "POST"]) == 2


def test_invalid_submissions_create_no_trail_and_each_accepted_question_has_its_own_id(
    startup_dependencies, chat_capture
):
    with TestClient(create_app(), base_url="http://localhost") as client:
        assert client.post("/api/chat", json={}).status_code == 422
        assert client.post("/api/chat", json=question_request("  ")).status_code == 422
        assert (
            client.post(
                "/api/chat",
                json={**question_request("Who backed AB 1?"), "model": "other"},
            ).status_code
            == 400
        )
        assert not any(
            span.name.startswith("chat_session.")
            for span in chat_capture.exported_spans
        )
        for conversation_id in ("conversation-1", "conversation-2"):
            request = question_request("Who backed AB 1?", conversation_id)
            events(client.post("/api/chat", json=request))
            assert client.post("/api/chat", json=request).status_code == 409
    spans = chat_capture.exported_spans_as_dict(parse_json_attributes=True)
    starts = [span for span in spans if span["name"] == "chat_session.started"]
    assert len(starts) == 2
    ids = {start["attributes"]["chat_session_id"] for start in starts}
    assert len(ids) == 2
    assert ids.isdisjoint({"conversation-1", "conversation-2"})


def test_openrouter_settings_retain_provider_policy_without_credentials(
    startup_dependencies, chat_capture, monkeypatch
):
    monkeypatch.setenv("CHAT_DEPLOYMENT", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "private-provider-key")
    monkeypatch.setenv("OPENROUTER_MODEL", "openai/chat-test")
    monkeypatch.setenv("OPENROUTER_PROVIDERS", "provider-one,provider-two")
    monkeypatch.setenv("LLM_TEMPERATURE", "0.25")

    def assess(messages, info):
        return ModelResponse(
            parts=[ToolCallPart(info.output_tools[0].name, {"status": "allowed"})]
        )

    @asynccontextmanager
    async def startup():
        async with chat_dependencies() as dependencies:
            with dependencies.chat_agent.override(model=FunctionModel(assess)):
                yield dependencies

    with TestClient(create_app(startup=startup), base_url="http://localhost") as client:
        prepared = events(
            client.post("/api/chat", json=question_request("Who backed AB 1?"))
        )
    assert any(event["type"] == "tool-approval-request" for event in prepared)
    spans = chat_capture.exported_spans_as_dict(parse_json_attributes=True)
    start = next(
        span["attributes"] for span in spans if span["name"] == "chat_session.started"
    )
    deployment = start["model_deployments"]["chat_agent"]
    assert deployment["kind"] == "openrouter"
    assert deployment["model"] == "openai/chat-test"
    assert deployment["endpoint"] == "https://openrouter.ai/api/v1/"
    assert deployment["request_settings"]["temperature"] == 0.25
    assert deployment["provider_policy"] == {
        "providers": ["provider-one", "provider-two"],
        "allow_fallback": True,
        "require_parameters": True,
        "exclusive": True,
    }
    assert "private-provider-key" not in json.dumps(start)
    assert "test-password" not in json.dumps(start)


def test_unavailable_code_metadata_does_not_prevent_preparation(
    startup_dependencies, chat_capture, monkeypatch
):
    def missing_git(*args, **kwargs):
        raise FileNotFoundError("git")

    monkeypatch.setattr(subprocess, "run", missing_git)
    with TestClient(create_app(), base_url="http://localhost") as client:
        prepared = events(
            client.post("/api/chat", json=question_request("Who backed AB 1?"))
        )
    assert any(event["type"] == "tool-approval-request" for event in prepared)
    spans = chat_capture.exported_spans_as_dict(parse_json_attributes=True)
    start = next(
        span["attributes"] for span in spans if span["name"] == "chat_session.started"
    )
    assert json.loads(start["code_revision"]) is None
    assert json.loads(start["worktree_dirty"]) is None


def test_export_failure_after_startup_does_not_change_preparation(
    startup_dependencies, chat_capture, monkeypatch
):
    def export_failure(spans):
        raise OSError("export unavailable")

    with TestClient(create_app(), base_url="http://localhost") as client:
        monkeypatch.setattr(chat_capture, "export", export_failure)
        prepared = events(
            client.post("/api/chat", json=question_request("Who backed AB 1?"))
        )
    assert any(event["type"] == "tool-approval-request" for event in prepared)
    assert "Which organizations supported AB 1?" in json.dumps(prepared)
