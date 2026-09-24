"""Guidance and rendered Retrieval Answers inspected through chat and the CLI."""

import gc
import json
import sqlite3
import weakref
from contextlib import asynccontextmanager, redirect_stdout
from io import StringIO
from threading import Event
from types import SimpleNamespace

import httpx
import pytest
from pydantic_ai.exceptions import UnexpectedModelBehavior
from starlette.testclient import TestClient
from test_chat_audit_preparation import audit_chat, scripted_model
from test_chat_audit_retrieval import answer_question, retrieval_chat
from test_chat_web import events, question_request
from test_chat_web_answers import approval_request
from test_query_preparation import rewriter_agent
from test_retrieval import COVERAGE, Branch, candidate, coordinator

from knowledge_map.adapters.audit import SQLiteAuditStore
from knowledge_map.cli.main import main
from knowledge_map.core.audit import AuditWriter
from knowledge_map.core.chat import ChatSession, get_chat_agent
from knowledge_map.schemas.retrieval import (
    GroundingEvidence,
    RetrievalBranch,
    SourceArticleCitation,
)
from knowledge_map.web import create_app


def saved_trail(path, session_id):
    output = StringIO()
    with redirect_stdout(output):
        main(["audit", "show", session_id, "--db", str(path)])
    trail = json.loads(output.getvalue())
    assert set(trail) == {"session_id", "stages"}
    return trail


def test_snapshot_failure_does_not_interrupt_answer_delivery(caplog):
    class UnserializableCitation:
        def model_dump(self, **kwargs):
            raise ValueError("snapshot unavailable")

    session = object.__new__(ChatSession)
    session.audit_session_id = "session-1"
    session._audit = object()
    answer = SimpleNamespace(
        evidence=SimpleNamespace(
            sources=(SimpleNamespace(citation=UnserializableCitation()),)
        )
    )

    session.record_retrieval_answer(answer, "Rendered answer")

    assert any(
        record.message == "chat_audit_dispatch_failed"
        and record.chat_audit_id == "session-1"
        and record.audit_stage_name == "retrieval_answer"
        for record in caplog.records
    )


def test_guidance_retains_its_result_timing_and_own_model_usage(tmp_path):
    branches = {branch: Branch(branch) for branch in RetrievalBranch}
    with retrieval_chat(tmp_path, branches) as (client, read_trail, _):
        response = answer_question(client)
        records = read_trail()

    (assembly,) = (record for record in records if record.name == "evidence_assembly")
    (guidance,) = (record for record in records if record.name == "chat_agent_guidance")
    assert "Consult the reporting." in response.text
    assert assembly.ended_at <= guidance.started_at < guidance.ended_at
    assert guidance.status == "succeeded"
    assert guidance.metadata == {
        "guidance": {
            "introduction": "Consult the reporting.",
            "source_notes": [],
            "disagreements": [],
        },
        "usage": {"requests": 1, "input_tokens": 17, "output_tokens": 5},
    }


def test_retrieval_answer_saves_exact_browser_text_and_selected_stored_passages(
    tmp_path,
):
    citation = SourceArticleCitation(
        source_article_id="https://example.com/article",
        title="Union [position]",
        url="https://example.com/article",
        published_date="2026-09-01",
    )
    chunks = [
        candidate(RetrievalBranch.FULL_TEXT, f"chunk-{number}", rank=number).model_copy(
            update={
                "source_article_id": citation.source_article_id,
                "grounding": GroundingEvidence(
                    chunk_id=f"chunk-{number}",
                    citation=citation,
                    text="UNVERIFIED_CANDIDATE_WORDING",
                ),
            }
        )
        for number in (1, 2)
    ]
    branches = {
        branch: Branch(
            branch, tuple(chunks) if branch == RetrievalBranch.FULL_TEXT else ()
        )
        for branch in RetrievalBranch
    }

    async def load_grounding(fused):
        return GroundingEvidence(
            chunk_id=fused.chunk_id,
            citation=citation,
            text={
                "chunk-1": "The union supported [AB 1].\n\nIts stated reason was <cost>.",
                "chunk-2": "  The position continued.  ",
            }[fused.chunk_id],
        )

    with retrieval_chat(
        tmp_path, branches, relational=False, load_grounding=load_grounding
    ) as (client, read_trail, _):
        response = answer_question(client)
        records = read_trail()

    (answer,) = (record for record in records if record.name == "retrieval_answer")
    browser_text = "".join(
        event["delta"] for event in events(response) if event["type"] == "text-delta"
    )
    assert browser_text == (
        "Consult the reporting.\n\n"
        "1. [Union \\[position\\]](<https://example.com/article>)\n\n"
        "Stored Article Chunk:\n\n"
        "The union supported \\[AB 1\\].\n\nIts stated reason was &lt;cost&gt;.\n\n"
        "Stored Article Chunk:\n\n  The position continued.  "
    )
    assert answer.status == "succeeded"
    assert answer.metadata == {
        "rendered_text": browser_text,
        "sources": [
            {
                "citation": {
                    "source_article_id": "https://example.com/article",
                    "title": "Union [position]",
                    "url": "https://example.com/article",
                    "published_date": "2026-09-01",
                },
                "passages": [
                    {
                        "chunk_id": "chunk-1",
                        "source_article_id": "https://example.com/article",
                        "text": "The union supported [AB 1].\n\nIts stated reason was <cost>.",
                        "provenance": "stored_chunk",
                    },
                    {
                        "chunk_id": "chunk-2",
                        "source_article_id": "https://example.com/article",
                        "text": "  The position continued.  ",
                        "provenance": "stored_chunk",
                    },
                ],
            }
        ],
    }
    assert len({record.stage_id for record in records}) == len(records)
    assert len({record.session_id for record in records}) == 1


@pytest.mark.parametrize(
    "output, failure_kind, input_tokens, output_tokens",
    [
        (UnexpectedModelBehavior("PRIVATE_MODEL_OUTPUT"), "model_response", 0, 0),
        (httpx.ConnectError("PRIVATE_PROVIDER_BODY"), "transport", 0, 0),
        (RuntimeError("PRIVATE_UNEXPECTED_FAILURE"), "unexpected", 0, 0),
        (
            {
                "source_notes": [
                    {
                        "source_article_id": "PRIVATE_UNSELECTED_SOURCE",
                        "note": "This source was not selected.",
                    }
                ]
            },
            "validation",
            37,
            11,
        ),
    ],
)
def test_guidance_failure_saves_safe_diagnostic_without_a_retrieval_answer(
    tmp_path, output, failure_kind, input_tokens, output_tokens
):
    with audit_chat(
        tmp_path,
        [{"question": "Who supported AB 1?", "relational": False}],
        [{"status": "allowed"}, output],
    ) as (client, read_trail, _):
        response = answer_question(client)
        records = read_trail()

    assert "This question could not be completed." in response.text
    assert not any(record.name == "retrieval_answer" for record in records)
    (guidance,) = (record for record in records if record.name == "chat_agent_guidance")
    assert guidance.status == "failed"
    assert guidance.started_at < guidance.ended_at
    assert guidance.metadata["failure_kind"] == failure_kind
    assert (
        guidance.metadata["diagnostic"] == "The Chat Agent guidance did not complete."
    )
    assert guidance.metadata["usage"]["input_tokens"] == input_tokens
    assert guidance.metadata["usage"]["output_tokens"] == output_tokens
    assert "guidance" not in guidance.metadata
    assert "PRIVATE_" not in response.text + "".join(
        record.model_dump_json() for record in records
    )


def test_zero_selected_passages_still_produce_one_retrieval_answer(tmp_path):
    branches = {branch: Branch(branch, ()) for branch in RetrievalBranch}
    with retrieval_chat(tmp_path, branches, relational=False) as (
        client,
        read_trail,
        _,
    ):
        response = answer_question(client)
        records = read_trail()

    (answer,) = (record for record in records if record.name == "retrieval_answer")
    assert answer.metadata == {
        "rendered_text": "Consult the reporting.\n\nNo passages were selected.",
        "sources": [],
    }
    assert answer.metadata["rendered_text"] == "".join(
        event["delta"] for event in events(response) if event["type"] == "text-delta"
    )


def test_evidence_assembly_failure_has_no_guidance_or_retrieval_answer(tmp_path):
    async def unavailable_grounding(candidate):
        raise OSError("PRIVATE_STORAGE_FAILURE")

    branches = {branch: Branch(branch) for branch in RetrievalBranch}
    with retrieval_chat(tmp_path, branches, load_grounding=unavailable_grounding) as (
        client,
        read_trail,
        _,
    ):
        response = answer_question(client)
        records = read_trail()

    assert "Grounding Evidence could not be assembled." in response.text
    assert records[-1].name == "evidence_assembly"
    assert records[-1].status == "failed"
    assert not {"chat_agent_guidance", "retrieval_answer"} & {
        record.name for record in records
    }


@pytest.mark.parametrize(
    "ending", ["declined", "unavailable_rewrite", "abandoned_approval"]
)
def test_sessions_without_retrieval_only_show_their_saved_preparation_stages(
    tmp_path, ending
):
    proposals = [{"question": "Who supported AB 1?", "relational": False}]
    assessments = [{"status": "allowed"}]
    expected = ["session_start", "query_rewrite", "question_assessment"]
    if ending == "declined":
        assessments = [
            {"status": "declined", "explanation": "Outside question policy."}
        ]
    elif ending == "unavailable_rewrite":
        proposals = [httpx.ConnectError("PRIVATE_PROVIDER_FAILURE")]
        expected = ["session_start", "query_rewrite"]

    with audit_chat(tmp_path, proposals, assessments) as (client, read_trail, _):
        response = client.post("/api/chat", json=question_request("Who backed AB 1?"))
        if ending == "abandoned_approval":
            assert any(
                event["type"] == "tool-approval-request" for event in events(response)
            )
        records = read_trail()

    assert [record.name for record in records] == expected
    trail = saved_trail(tmp_path / "audit.sqlite", records[0].session_id)
    assert [stage["name"] for stage in trail["stages"]] == expected


@pytest.mark.parametrize(
    "storage_outcome", ["delayed", "insert_failure", "dispatch_failure"]
)
def test_final_insert_dispatch_precedes_text_without_gating_delivery_or_cleanup(
    tmp_path, storage_outcome, caplog
):
    baseline_path = tmp_path / "baseline"
    baseline_path.mkdir()
    branches = {branch: Branch(branch) for branch in RetrievalBranch}
    with retrieval_chat(baseline_path, branches, relational=False) as (
        client,
        read_trail,
        _,
    ):
        baseline = events(answer_question(client))
        read_trail()

    def visible_answer(completed):
        return (
            [event["delta"] for event in completed if event["type"] == "text-delta"],
            next(
                event["output"]
                for event in completed
                if event["type"] == "tool-output-available"
                and event["output"].get("outcome") == "retrieval_answer"
            ),
            completed[-1],
        )

    started, release, finished = Event(), Event(), Event()
    observations, created, audit_ids, audit_logs = [], [], [], []
    approving = False

    class ControlledStore(SQLiteAuditStore):
        def insert(self, record):
            if record.name != "retrieval_answer":
                return super().insert(record)
            started.set()
            try:
                assert release.wait(timeout=10), "Test must release the final insert"
                if storage_outcome == "insert_failure":
                    raise sqlite3.OperationalError("PRIVATE_STORAGE_FAILURE")
                super().insert(record)
            finally:
                finished.set()

    class ObservedWriter(AuditWriter):
        def dispatch(self, record):
            if record.name == "retrieval_answer":
                observations.append(("dispatch", record.metadata["rendered_text"]))
                if storage_outcome == "dispatch_failure":
                    raise RuntimeError("PRIVATE_DISPATCH_FAILURE")
            super().dispatch(record)

    path = tmp_path / "audit.sqlite"
    writer = ObservedWriter(ControlledStore(path))
    agent, rewriter = get_chat_agent(), rewriter_agent()

    @asynccontextmanager
    async def startup():
        await writer.initialize()
        yield None

    def session_factory(question, dependencies):
        session = ChatSession(
            question,
            chat_agent=agent,
            rewriter=rewriter,
            retrieval=coordinator(),
            coverage=COVERAGE,
            relevant_collection_ids=("reporting",),
            audit=writer,
            audit_settings={},
        )
        created.append(weakref.ref(session))
        audit_ids.append(session.audit_session_id)
        return session

    app = create_app(startup=startup, session_factory=session_factory)

    async def observed_app(scope, receive, send):
        async def forward(message):
            if approving and message["type"] == "http.response.body":
                for line in message.get("body", b"").decode().splitlines():
                    if line.startswith("data: ") and line != "data: [DONE]":
                        event = json.loads(line[6:])
                        if event["type"] == "text-delta":
                            observations.append(("emission", event["delta"]))
            await send(message)

        await app(scope, receive, forward)

    with (
        agent.override(
            model=scripted_model(
                [{"status": "allowed"}, {"introduction": "Consult the reporting."}],
                input_tokens=17,
                output_tokens=5,
            )
        ),
        rewriter.override(
            model=scripted_model(
                [
                    {
                        "question": "Which organizations supported AB 1?",
                        "relational": False,
                    }
                ],
                input_tokens=11,
                output_tokens=3,
            )
        ),
        TestClient(observed_app, base_url="http://localhost") as client,
    ):
        try:
            prepared = events(
                client.post("/api/chat", json=question_request("Who backed AB 1?"))
            )
            approving = True
            response = client.post("/api/chat", json=approval_request(prepared))
            completed = events(response)
            assert visible_answer(completed) == visible_answer(baseline)
            assert [observation[0] for observation in observations] == [
                "dispatch",
                "emission",
            ]
            assert observations[0][1] == observations[1][1]
            assert "PRIVATE_" not in response.text
            if storage_outcome != "dispatch_failure":
                assert started.wait(timeout=10)
                assert not finished.is_set()
            audit_logs.extend(
                (record.message, record.audit_stage_name, record.chat_audit_id)
                for record in caplog.records
                if record.message == "chat_audit_dispatch_failed"
            )
            # Captured exception tracebacks retain the session independently of ASGI.
            for record in caplog.records:
                record.exc_info = None
            gc.collect()
            assert created[0]() is None
            assert (
                client.post("/api/chat", json=approval_request(prepared)).status_code
                == 409
            )
            assert (
                client.post(
                    "/api/chat", json=question_request("Who backed AB 2?")
                ).status_code
                == 409
            )
            assert len(observations) == 2
        finally:
            release.set()
            assert client.portal is not None
            client.portal.call(writer.wait_for_writes)

    trail = saved_trail(path, audit_ids[0])
    answers = [
        stage for stage in trail["stages"] if stage["name"] == "retrieval_answer"
    ]
    if storage_outcome == "delayed":
        assert len(answers) == 1
        assert answers[0]["metadata"]["rendered_text"] == observations[1][1]
    else:
        assert answers == []
        expected_log = (
            "chat_audit_insert_failed"
            if storage_outcome == "insert_failure"
            else "chat_audit_dispatch_failed"
        )
        audit_logs.extend(
            (record.message, record.audit_stage_name, record.chat_audit_id)
            for record in caplog.records
            if record.message == expected_log
        )
        assert (expected_log, "retrieval_answer", audit_ids[0]) in audit_logs
