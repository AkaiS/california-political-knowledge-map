"""Run the documented SQL over observations captured at the chat ASGI seam."""

import json
import re
import sqlite3
import subprocess
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

import httpx
from starlette.testclient import TestClient
from structural_support import relationship_outputs
from test_chat_answer_trail import answer_chat
from test_chat_evidence_trail import complete_chat
from test_chat_preparation_trail import scripted_model
from test_chat_retrieval_trail import chat_app
from test_chat_session_trail import chat_capture as chat_capture  # noqa: PLC0414
from test_chat_startup import (
    startup_dependencies as startup_dependencies,  # noqa: PLC0414
)
from test_chat_structural_trail import structural_chat
from test_chat_web import events, question_request
from test_structural_retrieval import driver_for

from knowledge_map.chat_startup import chat_dependencies
from knowledge_map.web import create_app

GUIDE = Path(__file__).resolve().parents[1] / "docs/chat-session-trails.md"


def documented_query(name, **replacements):
    match = re.search(rf"```sql\n-- {name}\n(.*?)```", GUIDE.read_text(), re.DOTALL)
    assert match is not None, f"Missing documented query: {name}"
    query = match.group(1)
    for key, value in replacements.items():
        query = query.replace(f"<{key}>", value)
    return query


def captured_records(capture):
    # SQLite checks the portable SQL/JSON subset against actual emitted values.
    # This test-only, in-memory projection does not emulate Logfire ingestion.
    database = sqlite3.connect(":memory:")
    database.row_factory = sqlite3.Row
    database.execute(
        "CREATE TABLE records (start_timestamp TEXT, end_timestamp TEXT, "
        "span_name TEXT, trace_id TEXT, span_id TEXT, parent_span_id TEXT, "
        "attributes TEXT)"
    )
    for span in capture.exported_spans_as_dict(parse_json_attributes=True):
        if span["attributes"].get("logfire.span_type") == "pending_span":
            continue
        parent = span["parent"]
        database.execute(
            "INSERT INTO records VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                datetime.fromtimestamp(span["start_time"] / 1e9, UTC).isoformat(),
                datetime.fromtimestamp(span["end_time"] / 1e9, UTC).isoformat(),
                span["name"],
                f"{span['context']['trace_id']:032x}",
                f"{span['context']['span_id']:016x}",
                f"{parent['span_id']:016x}" if parent else None,
                json.dumps(span["attributes"]),
            ),
        )
    return database


def test_documented_session_search_joins_requests_and_keeps_stage_outcomes(
    chat_capture,
):
    complete_chat(chat_app(None, relational=False))
    session_id = next(
        span.attributes["chat_session_id"]
        for span in chat_capture.exported_spans
        if span.name == "chat_session.started"
    )
    with TestClient(chat_app(None), base_url="http://localhost") as client:
        events(client.post("/api/questions", json=question_request("Another question")))

    with captured_records(chat_capture) as records:
        rows = records.execute(
            documented_query("single-session", **{"chat-session-id": session_id})
        ).fetchall()

    assert {row["chat_session_id"] for row in rows} == {session_id}
    by_name = {row["span_name"]: row for row in rows}
    approval = by_name["chat_session.submit"]
    assert by_name["chat_session.assessment"]["status"] == "allowed"
    assert "chat_session.query_rewrite" not in by_name
    assert by_name["chat_session.guidance"]["status"] == "succeeded"
    assert by_name["chat_session.answer_prepared"]["status"] is None
    branches = [
        row for row in rows if row["span_name"] == "chat_session.retrieval_branch"
    ]
    assert {row["branch"]: row["status"] for row in branches} == {
        "full_text": "succeeded",
        "dense": "succeeded",
        "structural": "succeeded",
    }
    assert {row["parent_span_id"] for row in branches} == {approval["span_id"]}
    assert {row["trace_id"] for row in branches} == {approval["trace_id"]}
    for row in rows:
        assert len(row["trace_id"]) == 32
        assert len(row["span_id"]) == 16
        assert row["start_timestamp"] <= row["end_timestamp"]


def test_documented_cohort_search_compares_settings_and_observed_answer_presence(
    startup_dependencies, chat_capture, monkeypatch
):
    revision = "a" * 40

    def git_result(args, **kwargs):
        output = revision if "rev-parse" in args else ""
        return subprocess.CompletedProcess(args, 0, stdout=output, stderr="")

    monkeypatch.setattr(subprocess, "run", git_result)

    @asynccontextmanager
    async def startup():
        async with chat_dependencies() as dependencies:
            dependencies.chat_agent.model = scripted_model(
                [{"status": "declined", "explanation": "Outside the question policy."}]
                if revision == "b" * 40
                else [{"status": "allowed"}, {"introduction": "Read the reporting."}]
            )
            yield dependencies

    window_start = datetime.now(UTC).isoformat()
    with TestClient(create_app(startup=startup), base_url="http://localhost") as client:
        payload = question_request("First question")
        before_approval = datetime.now(UTC).isoformat()
        events(client.post("/api/questions", json=payload))
    revision = "b" * 40
    monkeypatch.setenv("LLAMA_CPP_MODEL", "changed-chat")
    with TestClient(create_app(startup=startup), base_url="http://localhost") as client:
        events(
            client.post("/api/questions", json=question_request("Declined question"))
        )
    window_end = datetime.now(UTC).isoformat()

    with captured_records(chat_capture) as records:
        query = documented_query(
            "session-cohort", **{"window-start": window_start, "window-end": window_end}
        )
        rows = records.execute(query).fetchall()
        by_question = {row["original_question"]: row for row in rows}
        assert set(by_question) == {"First question", "Declined question"}
        answered = by_question["First question"]
        pending = by_question["Declined question"]
        assert answered["chat_session_id"] != pending["chat_session_id"]
        assert answered["code_revision"] == "a" * 40
        assert pending["code_revision"] == "b" * 40
        assert answered["chat_model"] == "chat-test"
        assert pending["chat_model"] == "changed-chat"
        assert answered["answer_observed_in_window"] == 1
        assert pending["answer_observed_in_window"] == 0
        assert answered["answer_records"] == 1
        assert pending["answer_records"] == 0
        assert before_approval <= answered["first_answer_observed_at"] < window_end
        assert pending["first_answer_observed_at"] is None
        for row in rows:
            assert window_start <= row["observed_at"] < window_end
            assert row["chat_deployment_kind"] == "local"
            assert row["chat_endpoint"] == "http://chat.test:8080/v1/"
            assert row["worktree_dirty"] == 0
            assert "query_rewriter" not in json.loads(row["model_deployments"])

        earlier = records.execute(
            documented_query(
                "session-cohort",
                **{"window-start": window_start, "window-end": before_approval},
            )
        ).fetchall()
        assert earlier == []


def test_documented_failure_search_includes_returned_and_raised_stage_failures(
    startup_dependencies, chat_capture
):
    window_start = datetime.now(UTC).isoformat()
    outputs = relationship_outputs()
    outputs[0] = httpx.ConnectError("private provider detail")
    complete_chat(structural_chat(driver_for(), outputs))
    complete_chat(answer_chat(httpx.ConnectError("private guidance detail")))
    with TestClient(create_app(), base_url="http://localhost") as client:
        startup_dependencies[5].add("chat.test")
        events(
            client.post(
                "/api/questions", json=question_request("Unavailable assessment")
            )
        )
    window_end = datetime.now(UTC).isoformat()

    with captured_records(chat_capture) as records:
        rows = records.execute(
            documented_query(
                "failed-stages",
                **{"window-start": window_start, "window-end": window_end},
            )
        ).fetchall()

    assert len(rows) == 4
    by_name = {row["span_name"]: row for row in rows}
    assert set(by_name) == {
        "chat_session.structural_stage",
        "chat_session.retrieval_branch",
        "chat_session.guidance",
        "chat_session.assessment",
    }
    structural = by_name["chat_session.structural_stage"]
    branch = by_name["chat_session.retrieval_branch"]
    assert structural["structural_stage"] == "schema_filtering"
    assert structural["failure_stage"] == branch["failure_stage"] == "schema_filtering"
    assert structural["chat_session_id"] == branch["chat_session_id"]
    assert structural["trace_id"] == branch["trace_id"]
    assert structural["parent_span_id"] == branch["span_id"]
    assert branch["branch"] == "structural"
    assert by_name["chat_session.assessment"]["status"] == "failed"
    assert by_name["chat_session.guidance"]["failure_stage"] is None
    for row in rows:
        assert row["failure_kind"] == (
            "provider" if row["span_name"] == "chat_session.assessment" else "transport"
        )
        assert window_start <= row["start_timestamp"] < window_end
        assert row["diagnostic"]
        assert "private" not in row["diagnostic"]
    assert len({row["chat_session_id"] for row in rows}) == 3
