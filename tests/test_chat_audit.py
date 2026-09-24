"""Saved Chat Session observations are inspectable independently of chat."""

import json
import sqlite3
from datetime import UTC, datetime

import logfire
import pytest
from logfire.testing import TestExporter as SpanExporter
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from test_chat_startup import (
    startup_dependencies as startup_dependencies,  # noqa: PLC0414
)

from knowledge_map.adapters.audit import SQLiteAuditStore
from knowledge_map.cli.main import main
from knowledge_map.schemas.audit import AuditStageRecord


@pytest.fixture
def audit_spans():
    from knowledge_map.utils.telemetry import setup_telemetry

    setup_telemetry()
    exporter = SpanExporter()
    logfire.configure(
        send_to_logfire=False,
        console=False,
        additional_span_processors=[SimpleSpanProcessor(exporter)],
    )
    yield exporter
    logfire.configure(send_to_logfire=False, console=False)


def test_committed_stage_is_shown_after_reopening_without_changing_the_database(
    tmp_path, capsys, monkeypatch
):
    path = tmp_path / "audit.sqlite"
    store = SQLiteAuditStore(path)
    store.initialize()
    record = AuditStageRecord(
        session_id="session-1",
        name="session_start",
        started_at=datetime(2026, 9, 23, 12, tzinfo=UTC),
        ended_at=datetime(2026, 9, 23, 12, tzinfo=UTC),
        status="succeeded",
        metadata={"original_question": "Who supported AB 1?"},
    )
    store.insert(record)
    before = path.read_bytes(), path.stat().st_mtime_ns

    def forbidden(*args, **kwargs):
        raise AssertionError("Audit inspection must not start runtime dependencies")

    monkeypatch.setattr("knowledge_map.cli.main.setup_telemetry", forbidden)
    monkeypatch.setattr("knowledge_map.cli.main.setup_logging", forbidden)
    monkeypatch.setattr("knowledge_map.cli.main.enforce_model_reachability", forbidden)
    main(["audit", "show", "session-1", "--db", str(path)])

    shown = json.loads(capsys.readouterr().out)
    assert shown["session_id"] == "session-1"
    assert shown["stages"] == [record.model_dump(mode="json")]
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before
    assert SQLiteAuditStore(path).read_trail("session-1") == (record,)


def test_reusing_a_stage_id_cannot_replace_a_committed_observation(tmp_path):
    store = SQLiteAuditStore(tmp_path / "audit.sqlite")
    store.initialize()
    record = AuditStageRecord(
        session_id="session-1",
        name="session_start",
        started_at=datetime(2026, 9, 23, tzinfo=UTC),
        ended_at=datetime(2026, 9, 23, tzinfo=UTC),
        status="succeeded",
        metadata={"original_question": "Who supported AB 1?"},
    )
    store.insert(record)
    with pytest.raises(sqlite3.IntegrityError):
        store.insert(record.model_copy(update={"metadata": {"replaced": True}}))
    assert store.read_trail("session-1") == (record,)


def test_first_question_and_correction_keep_one_audit_id_with_effective_settings(
    startup_dependencies, tmp_path, monkeypatch, capsys, audit_spans
):
    from functools import partial

    from starlette.testclient import TestClient
    from test_chat_web import events, question_request
    from test_chat_web_corrections import correction_request, rejection_request

    from knowledge_map.chat_startup import chat_dependencies, new_chat_session
    from knowledge_map.web import create_app

    path = tmp_path / "audit.sqlite"
    monkeypatch.setenv("CHAT_AUDIT_DB_PATH", str(path))
    monkeypatch.setenv("QUERY_REWRITER_BASE_URL", "http://rewriter.test:8080")
    received = []

    def session_factory(question, dependencies):
        session = new_chat_session(question, dependencies)
        received.append((session, dependencies))
        return session

    startup = partial(chat_dependencies)
    before = datetime.now(UTC)
    with TestClient(
        create_app(startup=startup, session_factory=session_factory),
        base_url="http://localhost",
    ) as client:
        monkeypatch.setenv("QUERY_REWRITER_MODEL", "changed-after-startup")
        assert client.post("/api/chat", json=question_request("  ")).status_code == 422
        prepared = events(
            client.post("/api/chat", json=question_request("Who backed AB 1?"))
        )
        session, dependencies = received[0]
        audit_id = session.audit_session_id
        events(client.post("/api/chat", json=rejection_request(prepared)))
        corrected = events(
            client.post(
                "/api/chat", json=correction_request(prepared, "Focus on unions.")
            )
        )
        assert any(event["type"] == "tool-approval-request" for event in corrected)
        assert session.audit_session_id == audit_id
        assert len(received) == 1
        assert client.portal is not None
        client.portal.call(dependencies.audit.wait_for_writes)

    capsys.readouterr()
    main(["audit", "show", audit_id, "--db", str(path)])
    trail = json.loads(capsys.readouterr().out)
    (record,) = [stage for stage in trail["stages"] if stage["name"] == "session_start"]
    assert record["session_id"] == audit_id
    assert record["stage_id"] != audit_id
    assert audit_id != "conversation-1"
    assert record["name"] == "session_start"
    assert record["status"] == "succeeded"
    assert record["schema_version"] == 1
    assert (
        before
        <= datetime.fromisoformat(record["started_at"])
        <= datetime.fromisoformat(record["ended_at"])
    )
    metadata = record["metadata"]
    assert metadata["original_question"] == "Who backed AB 1?"
    assert datetime.fromisoformat(metadata["observed_at"]) == datetime.fromisoformat(
        record["ended_at"]
    )
    assert len(metadata["code"]["commit"]) == 40
    assert isinstance(metadata["code"]["dirty"], bool)
    assert metadata["deployments"]["query_rewriter"]["model"] == "rewriter-test"
    assert (
        metadata["deployments"]["query_rewriter"]["endpoint"]
        == "http://rewriter.test:8080/v1"
    )
    assert metadata["deployments"]["chat_agent"]["model"] == "chat-test"
    assert metadata["deployments"]["chat_agent"]["request_settings"]["temperature"] == 0
    assert set(metadata["prompt_revisions"]) >= {
        "query_rewriter",
        "chat_agent",
        "question_policy",
        "structural_selector",
    }
    assert all(
        value.startswith("sha256:") for value in metadata["prompt_revisions"].values()
    )
    assert metadata["fusion"]["structural_weight"] == 2
    assert metadata["fusion"]["fused_candidate_limit"] == 100
    assert metadata["context_limits"] == {"character_limit": 24000, "max_passages": 12}
    assert metadata["coverage"]["entries"][0]["availability"]["available_count"] == 2
    assert (
        before
        <= datetime.fromisoformat(metadata["coverage_observed_at"])
        <= datetime.fromisoformat(record["started_at"])
    )
    _, driver, _, _, _, _, _, _ = startup_dependencies
    assert driver.session.return_value.__aenter__.return_value.run.await_count == 1
    correlated = [
        span
        for span in audit_spans.exported_spans
        if span.name in {"chat_prepare", "chat_correct"}
        and span.attributes.get("logfire.span_type") == "span"
    ]
    assert [span.name for span in correlated] == [
        "chat_prepare",
        "chat_correct",
        "chat_prepare",
    ]
    assert {span.attributes["chat_audit_id"] for span in correlated} == {audit_id}
    with TestClient(create_app(), base_url="http://localhost"):
        assert (
            SQLiteAuditStore(path).read_trail(audit_id)[0].model_dump(mode="json")
            == record
        )


@pytest.mark.parametrize("existing_database", [False, True])
def test_show_neither_initializes_missing_storage_nor_invents_a_session_outcome(
    tmp_path, capsys, existing_database
):
    path = tmp_path / "audit.sqlite"
    if existing_database:
        SQLiteAuditStore(path).initialize()
    with pytest.raises(SystemExit) as error:
        main(["audit", "show", "unsaved-session", "--db", str(path)])
    assert error.value.code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert path.exists() == existing_database
    assert captured.err.strip() == (
        "No saved stages for this audit ID."
        if existing_database
        else "The audit database could not be read."
    )


def test_audit_initialization_failure_is_logged_without_stopping_chat(
    startup_dependencies, tmp_path, monkeypatch, caplog
):
    from starlette.testclient import TestClient
    from test_chat_web import events, question_request

    from knowledge_map.web import create_app

    path = tmp_path / "missing-directory" / "audit.sqlite"
    monkeypatch.setenv("CHAT_AUDIT_DB_PATH", str(path))
    with TestClient(create_app(), base_url="http://localhost") as client:
        prepared = events(
            client.post("/api/chat", json=question_request("Who backed AB 1?"))
        )
        assert any(event["type"] == "tool-approval-request" for event in prepared)

    assert not path.exists()
    assert "chat_audit_initialization_failed" in caplog.text


@pytest.mark.parametrize("fail_insert", [False, True])
def test_answer_proceeds_while_audit_insert_is_blocked_and_survives_write_failure(
    tmp_path, fail_insert, caplog
):
    from contextlib import asynccontextmanager
    from threading import Event

    from pydantic_ai.messages import ModelResponse, ToolCallPart
    from pydantic_ai.models.function import FunctionModel
    from starlette.testclient import TestClient
    from test_chat_web import events, question_request
    from test_chat_web_answers import approval_request
    from test_query_preparation import rewrite_response, rewriter_agent
    from test_retrieval import COVERAGE, coordinator, rewrite

    from knowledge_map.core.audit import AuditWriter
    from knowledge_map.core.chat import ChatSession, get_chat_agent
    from knowledge_map.web import create_app

    started, release, finished = Event(), Event(), Event()

    class ControlledStore(SQLiteAuditStore):
        def insert(self, record):
            started.set()
            try:
                assert release.wait(timeout=10), "Test must release the insert"
                if fail_insert:
                    raise sqlite3.OperationalError("PRIVATE_DATABASE_DIAGNOSTIC")
                super().insert(record)
            finally:
                finished.set()

    store = ControlledStore(tmp_path / "audit.sqlite")
    writer = AuditWriter(store)
    sessions = []
    calls = []

    def respond(messages, info):
        calls.append(messages)
        output = (
            {"status": "allowed"}
            if len(calls) == 1
            else {"introduction": "Read the reporting."}
        )
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, output)])

    agent, rewriter = get_chat_agent(), rewriter_agent()

    @asynccontextmanager
    async def startup():
        await writer.initialize()
        yield agent, rewriter

    def session_factory(question, dependencies):
        agent, rewriter = dependencies
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
        sessions.append(session)
        return session

    with (
        agent.override(model=FunctionModel(respond)),
        rewriter.override(model=rewrite_response(rewrite().question, False)),
        TestClient(
            create_app(startup=startup, session_factory=session_factory),
            base_url="http://localhost",
        ) as client,
    ):
        try:
            prepared = events(
                client.post("/api/chat", json=question_request("Who backed AB 1?"))
            )
            assert started.wait(timeout=10)
            answered = client.post("/api/chat", json=approval_request(prepared))
            completed = events(answered)
            assert "Read the reporting." in answered.text
            assert completed[-1] == {"type": "finish", "finishReason": "stop"}
            assert "PRIVATE_DATABASE_DIAGNOSTIC" not in answered.text
            assert not finished.is_set()
        finally:
            release.set()
            assert client.portal is not None
            client.portal.call(writer.wait_for_writes)

    records = store.read_trail(sessions[0].audit_session_id)
    if fail_insert:
        assert records == ()
        failures = [
            record
            for record in caplog.records
            if record.message == "chat_audit_insert_failed"
        ]
        assert failures
        assert all(
            failure.chat_audit_id == sessions[0].audit_session_id
            for failure in failures
        )
    else:
        assert [record.name for record in records[:4]] == [
            "session_start",
            "query_rewrite",
            "question_assessment",
            "query_approval",
        ]
        assert {record.name for record in records[4:]} == {
            "full_text_search",
            "dense_search",
            "structural_search",
            "fusion",
            "evidence_assembly",
        }
