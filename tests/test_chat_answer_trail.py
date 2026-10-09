"""Prepared Retrieval Answer observations through the chat ASGI interface."""

import json

import httpx
import pytest
from opentelemetry.exporter.otlp.proto.common.trace_encoder import encode_spans
from pydantic_ai.exceptions import ModelHTTPError, UnexpectedModelBehavior
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel
from starlette.testclient import TestClient
from test_chat_evidence_trail import application_attributes, complete_chat
from test_chat_preparation_trail import scripted_model
from test_chat_retrieval_trail import chat_app
from test_chat_session_trail import chat_capture as chat_capture  # noqa: PLC0414
from test_chat_web import events, no_dependencies, question_request, submit_guide
from test_query_preparation import rewriter_agent
from test_retrieval import COVERAGE, Branch, candidate, coordinator

from knowledge_map.core.chat import ChatSession, get_chat_agent
from knowledge_map.core.evidence import EvidenceHydrationError
from knowledge_map.schemas.retrieval import (
    GroundingEvidence,
    RetrievalBranch,
    SourceArticleCitation,
)
from knowledge_map.web import create_app


def answer_chat(guidance, **retrieval_options):
    calls = 0

    def respond(messages, info):
        nonlocal calls
        calls += 1
        if calls == 1:
            output = {"status": "allowed"}
        elif isinstance(guidance, Exception):
            raise guidance
        else:
            output = guidance
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, output)])

    agent = get_chat_agent()
    agent.model = FunctionModel(respond)
    rewriter = rewriter_agent()
    rewriter.model = scripted_model(
        [{"question": "Which articles discuss AB 1?", "relational": False}]
    )

    def session_factory(question, dependencies):
        return ChatSession(
            question,
            chat_agent=agent,
            rewriter=rewriter,
            retrieval=coordinator(**retrieval_options),
            coverage=COVERAGE,
            relevant_collection_ids=("reporting",),
        )

    return create_app(startup=no_dependencies, session_factory=session_factory)


def test_guidance_span_contains_the_chat_agent_run_after_evidence_assembly(
    chat_capture,
):
    completed = complete_chat(chat_app(None, relational=False))
    assert completed["status"] == "empty"
    spans = chat_capture.exported_spans_as_dict(parse_json_attributes=True)
    guidance = next(s for s in spans if s["name"] == "chat_session.guidance")
    approval = next(s for s in spans if s["name"] == "chat_session.submit")
    assembly = next(s for s in spans if s["name"] == "chat_session.evidence_assembly")
    assert guidance["attributes"]["status"] == "succeeded"
    assert guidance["attributes"]["audit_schema_version"] == 1
    assert (
        guidance["attributes"]["chat_session_id"]
        == approval["attributes"]["chat_session_id"]
    )
    assert guidance["parent"]["span_id"] == approval["context"]["span_id"]
    assert guidance["context"]["trace_id"] == approval["context"]["trace_id"]
    assert guidance["start_time"] >= assembly["end_time"]
    agent = next(
        s
        for s in spans
        if s["attributes"].get("gen_ai.operation.name") == "invoke_agent"
        and s["parent"]["span_id"] == guidance["context"]["span_id"]
    )
    assert agent["context"]["trace_id"] == guidance["context"]["trace_id"]
    assert agent["end_time"] <= guidance["end_time"]
    assert not {"messages", "input_tokens", "output_tokens", "failure_kind"} & (
        guidance["attributes"].keys()
    )


@pytest.mark.parametrize(
    "output,kind",
    [
        (httpx.ConnectError("private provider address"), "transport"),
        (ModelHTTPError(503, "private model", "private body"), "provider"),
        (UnexpectedModelBehavior("private model output"), "model_output"),
        (RuntimeError("private unexpected problem"), "unexpected"),
        (
            {
                "source_notes": [
                    {
                        "source_article_id": "private missing source",
                        "note": "Read this.",
                    }
                ]
            },
            "validation",
        ),
    ],
)
def test_guidance_failure_records_a_safe_kind_without_preparing_an_answer(
    chat_capture, output, kind
):
    completed = complete_chat(answer_chat(output))
    spans = chat_capture.exported_spans_as_dict(parse_json_attributes=True)
    guidance = next(s for s in spans if s["name"] == "chat_session.guidance")
    attributes = application_attributes(guidance)
    assert attributes["status"] == "failed"
    assert attributes["failure_kind"] == kind
    assert (
        attributes["diagnostic"]
        == "The Chat Agent could not prepare retrieval guidance."
    )
    assert "private" not in json.dumps(attributes)
    assert completed["status"] == "guidance_failed"
    assert not any(s["name"] == "chat_session.answer_prepared" for s in spans)


@pytest.mark.parametrize("assembly_fails", [False, True])
def test_only_a_completed_retrieval_answer_has_an_answer_observation(
    chat_capture, assembly_fails
):
    async def unavailable_store(fused):
        raise EvidenceHydrationError("private database location")

    branches = {
        branch: Branch(branch, None if assembly_fails else ())
        for branch in RetrievalBranch
    }
    completed = complete_chat(
        answer_chat(
            {"introduction": "Consult the reporting."},
            branches=branches,
            load_grounding=unavailable_store,
        )
    )
    rendered = completed.get("message", "")
    spans = chat_capture.exported_spans_as_dict(parse_json_attributes=True)
    answers = [s for s in spans if s["name"] == "chat_session.answer_prepared"]
    if assembly_fails:
        assert completed["status"] == "assembly_failed"
        assert (
            rendered
            == "Retrieved material could not be prepared for relevance review. Choose Retry to search again."
        )
        assert answers == []
        assert not any(s["name"] == "chat_session.guidance" for s in spans)
    else:
        assert completed["status"] == "empty"
        assert "No articles were available to assess" in rendered
        assert len(answers) == 1
        assert rendered in answers[0]["attributes"]["rendered_text"]
        assert answers[0]["attributes"]["selected_sources"] == []


def test_export_failure_after_startup_preserves_prepared_answer_and_search_details(
    chat_capture, monkeypatch
):
    expected = complete_chat(answer_chat({"introduction": "Consult the reporting."}))
    exported_before_failure = len(chat_capture.exported_spans)
    export_attempts = []

    def unavailable_export(spans):
        export_attempts.extend(span.name for span in spans)
        raise OSError("private export address")

    with TestClient(
        answer_chat({"introduction": "Consult the reporting."}),
        base_url="http://localhost",
    ) as client:
        monkeypatch.setattr(chat_capture, "export", unavailable_export)
        payload = question_request("Who backed AB 1?")
        completed = events(submit_guide(client, json=payload))
        for field in (
            "question",
            "status",
            "assessment",
            "message",
            "articles",
            "partial",
        ):
            assert completed.get(field) == expected.get(field)
        assert completed["guide_id"] != expected["guide_id"]
        assert completed["last_retrieved_at"]
        assert client.get(f"/api/guides/{completed['guide_id']}").json() == completed
    assert len(chat_capture.exported_spans) == exported_before_failure
    assert "chat_session.answer_prepared" in export_attempts


def test_large_prepared_answer_keeps_readable_exact_attributes_within_ingest_limits(
    chat_capture, record_property
):
    stored = {}

    async def store(fused):
        text = f"{fused.chunk_id}: " + "Hearing *AB 1* café & housing.\n" * 32
        stored[fused.chunk_id] = text
        return GroundingEvidence(
            chunk_id=fused.chunk_id,
            text=text,
            citation=SourceArticleCitation(
                source_article_id=fused.source_article_id,
                title="Hearing reporting on AB 1",
                url=fused.source_article_id,
                published_date="2026-09-01",
            ),
        )

    branches = {branch: Branch(branch, ()) for branch in RetrievalBranch}
    branches[RetrievalBranch.FULL_TEXT] = Branch(
        RetrievalBranch.FULL_TEXT,
        tuple(
            candidate(RetrievalBranch.FULL_TEXT, f"hearing-{i:02}", i)
            for i in range(1, 13)
        ),
    )
    completed = complete_chat(
        answer_chat(
            {"introduction": "Read all twelve selected sources."},
            branches=branches,
            load_grounding=store,
        )
    )
    spans = chat_capture.exported_spans_as_dict(parse_json_attributes=True)
    attrs = next(
        s["attributes"] for s in spans if s["name"] == "chat_session.answer_prepared"
    )
    rendered = completed.get("message", "")
    assert rendered in attrs["rendered_text"]
    assert len(attrs["selected_sources"]) == 12
    passages = [p for source in attrs["selected_sources"] for p in source["passages"]]
    assert {p["chunk_id"]: p["text"] for p in passages} == stored
    assert all(p["provenance"] == "stored_chunk" for p in passages)
    assembly = next(
        s["attributes"] for s in spans if s["name"] == "chat_session.evidence_assembly"
    )
    assert 20_000 <= assembly["context"]["used"] <= 24_000
    assert all(text not in json.dumps(completed) for text in stored.values())
    raw = next(
        s
        for s in chat_capture.exported_spans
        if s.name == "chat_session.answer_prepared"
    )
    assert raw.attributes is not None
    schema = json.loads(raw.attributes["logfire.json_schema"])
    assert schema["properties"]["selected_sources"]["type"] == "array"
    # https://pydantic.dev/docs/logfire/reference/limits/ (2026-09-24):
    # a record must fit 10 MB; the displayed log message has a separate 512-byte cap.
    otlp_bytes = encode_spans([raw]).ByteSize()
    attribute_bytes = len(json.dumps(dict(raw.attributes)).encode())
    assert otlp_bytes < 10_000_000
    assert attribute_bytes < 10_000_000
    assert len(raw.name.encode()) <= 512
    assert len(str(raw.attributes["logfire.msg"]).encode()) <= 512
    assert "logfire.truncated" not in attrs
    record_property("context_characters", assembly["context"]["used"])
    record_property("rendered_utf8_bytes", len(rendered.encode()))
    record_property("answer_record_otlp_bytes", otlp_bytes)
    record_property("answer_attributes_json_bytes", attribute_bytes)


def test_answer_observation_retains_grounding_but_reader_receives_only_directions(
    chat_capture,
):
    from test_chat_web import guide_client, stored_article

    with guide_client(
        guidance={
            "source_notes": [
                {
                    "source_article_id": "https://example.com/dense",
                    "note": "Read the section on housing provisions.",
                }
            ]
        },
        load_grounding=stored_article,
    ) as (client, _, _):
        response = submit_guide(
            client, json={"question": "What should I read about AB 1?"}
        )
    spans = chat_capture.exported_spans_as_dict(parse_json_attributes=True)
    answer = next(s for s in spans if s["name"] == "chat_session.answer_prepared")
    attrs = answer["attributes"]
    assert attrs["audit_schema_version"] == 2
    assert "PRIVATE_CHUNK_SENTINEL" in json.dumps(attrs["selected_sources"])
    assert "PRIVATE_CHUNK_SENTINEL" not in response.text
    assert "PRIVATE_CHUNK_SENTINEL" not in attrs["rendered_text"]
    assert response.json()["articles"][0]["reading_direction"] in attrs["rendered_text"]
