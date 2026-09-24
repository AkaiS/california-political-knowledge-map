"""Maintainers locate and export saved observations through the CLI dispatcher."""

import json
import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

from knowledge_map.adapters.audit import SQLiteAuditStore
from knowledge_map.cli.main import main
from knowledge_map.schemas.audit import AuditStageRecord


@pytest.fixture
def audit_database(tmp_path: Path) -> Path:
    path = tmp_path / "audit.sqlite"
    store = SQLiteAuditStore(path)
    store.initialize()
    for session_id, time in (
        ("later-session", "2026-09-24T12:00:00Z"),
        ("earlier-session", "2026-09-23T12:00:00Z"),
    ):
        store.insert(
            AuditStageRecord(
                stage_id=f"{session_id}-start",
                session_id=session_id,
                name="session_start",
                started_at=datetime.fromisoformat(time),
                ended_at=datetime.fromisoformat(time),
                status="succeeded",
                metadata={
                    "original_question": "Who supported AB 1?",
                    "code": {
                        "commit": "abc123"
                        if session_id == "earlier-session"
                        else "def456",
                        "dirty": False,
                    },
                    "deployments": {
                        "query_rewriter": {
                            "kind": "local"
                            if session_id == "earlier-session"
                            else "openrouter",
                            "model": "shared-model",
                        },
                        "chat_agent": {
                            "kind": "local",
                            "model": "chat-a"
                            if session_id == "earlier-session"
                            else "chat-b",
                        },
                    },
                },
            )
        )
    return path


def test_list_locates_saved_sessions_by_their_first_observation(
    audit_database: Path, capsys: pytest.CaptureFixture[str]
):
    main(["audit", "list", "--db", str(audit_database)])

    assert json.loads(capsys.readouterr().out) == {
        "sessions": [
            {
                "session_id": "earlier-session",
                "observed_at": "2026-09-23T12:00:00Z",
                "has_retrieval_answer": False,
            },
            {
                "session_id": "later-session",
                "observed_at": "2026-09-24T12:00:00Z",
                "has_retrieval_answer": False,
            },
        ]
    }


@pytest.mark.parametrize(
    ("filters", "expected"),
    [
        (
            ["--since", "2026-09-23T05:00:00-07:00"],
            ["earlier-session", "later-session"],
        ),
        (["--since", "2026-09-23T12:00:00.000001Z"], ["later-session"]),
        (["--until", "2026-09-23T05:00:00-07:00"], ["earlier-session"]),
        (["--until", "2026-09-23T11:59:59Z"], []),
        (
            ["--since", "2026-09-24T12:00:00Z", "--until", "2026-09-24T12:00:00Z"],
            ["later-session"],
        ),
    ],
)
def test_time_filters_compare_first_observations_with_inclusive_aware_bounds(
    audit_database: Path, capsys: pytest.CaptureFixture[str], filters, expected
):
    main(["audit", "list", "--db", str(audit_database), *filters])

    assert [
        session["session_id"]
        for session in json.loads(capsys.readouterr().out)["sessions"]
    ] == expected


@pytest.mark.parametrize(
    ("presence", "expected"), [("yes", ["later-session"]), ("no", ["earlier-session"])]
)
def test_answer_presence_is_a_saved_record_even_with_zero_passages(
    audit_database: Path, capsys: pytest.CaptureFixture[str], presence, expected
):
    SQLiteAuditStore(audit_database).insert(
        AuditStageRecord(
            session_id="later-session",
            name="retrieval_answer",
            started_at=datetime.fromisoformat("2026-09-24T12:01:00Z"),
            ended_at=datetime.fromisoformat("2026-09-24T12:01:00Z"),
            status="succeeded",
            metadata={
                "rendered_text": "No matching passages were found.",
                "sources": [],
            },
        )
    )

    main(["audit", "list", "--db", str(audit_database), "--has-answer", presence])

    sessions = json.loads(capsys.readouterr().out)["sessions"]
    assert [session["session_id"] for session in sessions] == expected
    assert all(
        session["has_retrieval_answer"] == (presence == "yes") for session in sessions
    )


@pytest.mark.parametrize(
    ("revision", "expected"),
    [
        ("abc123", ["earlier-session"]),
        ("def456", ["later-session"]),
        ("abc", []),
        ("missing", []),
    ],
)
def test_code_revision_filter_matches_the_saved_commit_exactly(
    audit_database: Path, capsys: pytest.CaptureFixture[str], revision, expected
):
    main(["audit", "list", "--db", str(audit_database), "--code-revision", revision])

    assert [
        session["session_id"]
        for session in json.loads(capsys.readouterr().out)["sessions"]
    ] == expected


@pytest.mark.parametrize(
    ("deployment", "expected"),
    [
        ("local:shared-model", ["earlier-session"]),
        ("openrouter:shared-model", ["later-session"]),
        ("local:chat-a", ["earlier-session"]),
        ("local:chat-b", ["later-session"]),
        ("local:shared", []),
        ("openrouter:chat-b", []),
    ],
)
def test_model_deployment_filter_matches_kind_and_model_in_any_saved_role(
    audit_database: Path, capsys: pytest.CaptureFixture[str], deployment, expected
):
    main(
        ["audit", "list", "--db", str(audit_database), "--model-deployment", deployment]
    )

    assert [
        session["session_id"]
        for session in json.loads(capsys.readouterr().out)["sessions"]
    ] == expected


def test_model_deployment_json_filter_distinguishes_saved_routes_and_settings(
    audit_database: Path, capsys: pytest.CaptureFixture[str]
):
    deployments = {
        "local-a": {
            "kind": "local",
            "model": "shared-model",
            "endpoint": "http://localhost:8080/v1",
            "request_settings": {"temperature": 0.0},
        },
        "local-b": {
            "kind": "local",
            "model": "shared-model",
            "endpoint": "http://localhost:8081/v1",
            "request_settings": {"temperature": 0.0},
        },
        "local-settings": {
            "kind": "local",
            "model": "shared-model",
            "endpoint": "http://localhost:8080/v1",
            "request_settings": {"temperature": 0.3},
        },
        "openrouter-a": {
            "kind": "openrouter",
            "model": "shared-model",
            "provider_policy": {"providers": ["provider-a"]},
        },
        "openrouter-b": {
            "kind": "openrouter",
            "model": "shared-model",
            "provider_policy": {"providers": ["provider-b"]},
        },
    }
    store = SQLiteAuditStore(audit_database)
    for session_id, deployment in deployments.items():
        store.insert(
            AuditStageRecord(
                stage_id=f"{session_id}-start",
                session_id=session_id,
                name="session_start",
                started_at=datetime.fromisoformat("2026-09-25T12:00:00Z"),
                ended_at=datetime.fromisoformat("2026-09-25T12:00:00Z"),
                status="succeeded",
                metadata={"deployments": {"chat_agent": deployment}},
            )
        )

    for session_id, deployment in deployments.items():
        main(
            [
                "audit",
                "list",
                "--db",
                str(audit_database),
                "--model-deployment",
                json.dumps(deployment),
            ]
        )
        assert [
            session["session_id"]
            for session in json.loads(capsys.readouterr().out)["sessions"]
        ] == [session_id]

    main(
        [
            "audit",
            "list",
            "--db",
            str(audit_database),
            "--model-deployment",
            "openrouter:shared-model",
        ]
    )
    assert [
        session["session_id"]
        for session in json.loads(capsys.readouterr().out)["sessions"]
    ] == ["later-session", "openrouter-a", "openrouter-b"]


@pytest.mark.parametrize(
    ("filters", "expected"),
    [
        (["--failed-stage", "dense_search"], ["later-session"]),
        (["--failed-stage", "session_start"], []),
        (["--failed-stage", "dense"], []),
        (
            [
                "--failed-stage",
                "dense_search",
                "--has-answer",
                "no",
                "--code-revision",
                "def456",
                "--model-deployment",
                "local:chat-b",
                "--since",
                "2026-09-24T12:00:00Z",
                "--until",
                "2026-09-24T12:00:00Z",
            ],
            ["later-session"],
        ),
        (["--failed-stage", "dense_search", "--code-revision", "abc123"], []),
    ],
)
def test_failed_stage_filter_requires_a_saved_failure_and_combines_with_other_filters(
    audit_database: Path, capsys: pytest.CaptureFixture[str], filters, expected
):
    for session_id, status in (
        ("earlier-session", "skipped"),
        ("later-session", "failed"),
    ):
        SQLiteAuditStore(audit_database).insert(
            AuditStageRecord(
                session_id=session_id,
                name="dense_search",
                started_at=datetime.fromisoformat("2026-09-24T12:00:01Z"),
                ended_at=datetime.fromisoformat("2026-09-24T12:00:02Z"),
                status=status,
                metadata={"failure_kind": "embedding_unavailable"},
            )
        )

    main(["audit", "list", "--db", str(audit_database), *filters])

    assert [
        session["session_id"]
        for session in json.loads(capsys.readouterr().out)["sessions"]
    ] == expected


@pytest.mark.parametrize("action", ["show", "export"])
@pytest.mark.parametrize("has_answer", [False, True])
def test_show_and_export_preserve_saved_stages_and_any_answer_without_a_session_outcome(
    audit_database: Path, capsys: pytest.CaptureFixture[str], action, has_answer
):
    store = SQLiteAuditStore(audit_database)
    (start,) = store.read_trail("earlier-session")
    fulltext = AuditStageRecord(
        stage_id="fulltext-stage",
        session_id="earlier-session",
        name="full_text_search",
        started_at=datetime.fromisoformat("2026-09-23T12:00:01Z"),
        ended_at=datetime.fromisoformat("2026-09-23T12:00:04Z"),
        status="succeeded",
        metadata={"terms": ["AB 1"], "candidate_count": 2},
    )
    dense = AuditStageRecord(
        stage_id="dense-stage",
        session_id="earlier-session",
        name="dense_search",
        started_at=datetime.fromisoformat("2026-09-23T05:00:02-07:00"),
        ended_at=datetime.fromisoformat("2026-09-23T05:00:03-07:00"),
        status="failed",
        metadata={"failure_kind": "embedding_unavailable", "candidate_count": 0},
    )
    answer = AuditStageRecord(
        stage_id="answer-stage",
        session_id="earlier-session",
        name="retrieval_answer",
        started_at=datetime.fromisoformat("2026-09-23T12:00:05Z"),
        ended_at=datetime.fromisoformat("2026-09-23T12:00:05Z"),
        status="succeeded",
        metadata={
            "rendered_text": "Read the reporting.\n\nStored Article Chunk:\n\nCalifornians’ support.",
            "sources": [
                {
                    "citation": {
                        "source_article_id": "article-1",
                        "title": "AB 1 support",
                        "url": "https://example.com/ab-1",
                        "published_date": None,
                    },
                    "passages": [
                        {
                            "chunk_id": "chunk-1",
                            "source_article_id": "article-1",
                            "text": "Californians’ support.",
                            "provenance": "stored_chunk",
                        }
                    ],
                }
            ],
        },
    )
    for record in (dense, fulltext, *((answer,) if has_answer else ())):
        store.insert(record)

    main(["audit", action, "earlier-session", "--db", str(audit_database)])

    expected = [start, fulltext, dense, *((answer,) if has_answer else ())]
    assert json.loads(capsys.readouterr().out) == {
        "session_id": "earlier-session",
        "stages": [record.model_dump(mode="json") for record in expected],
    }


def test_a_trail_missing_session_start_remains_findable_without_inventing_settings(
    audit_database: Path, capsys: pytest.CaptureFixture[str]
):
    SQLiteAuditStore(audit_database).insert(
        AuditStageRecord(
            session_id="partial-session",
            name="query_rewrite_proposal",
            started_at=datetime.fromisoformat("2026-09-22T23:30:00-07:00"),
            ended_at=datetime.fromisoformat("2026-09-22T23:30:02-07:00"),
            status="succeeded",
            metadata={"attempt": 1, "proposed_question": "Who supported AB 1?"},
        )
    )
    main(["audit", "list", "--db", str(audit_database)])
    sessions = json.loads(capsys.readouterr().out)["sessions"]
    assert sessions[0] == {
        "session_id": "partial-session",
        "observed_at": None,
        "has_retrieval_answer": False,
    }
    main(
        [
            "audit",
            "list",
            "--db",
            str(audit_database),
            "--until",
            "2026-09-23T07:00:00Z",
        ]
    )
    assert json.loads(capsys.readouterr().out) == {"sessions": []}
    for filters in (
        ["--code-revision", "abc123"],
        ["--model-deployment", "local:shared-model"],
    ):
        main(["audit", "list", "--db", str(audit_database), *filters])
        assert [
            session["session_id"]
            for session in json.loads(capsys.readouterr().out)["sessions"]
        ] == ["earlier-session"]


@pytest.mark.parametrize(
    "command", [["list"], ["show", "earlier-session"], ["export", "earlier-session"]]
)
def test_read_commands_use_the_configured_database_without_runtime_startup_or_file_changes(
    audit_database: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    command,
):
    def forbidden(*args, **kwargs):
        pytest.fail("Audit inspection must not start runtime dependencies")

    for target in (
        "logfire.configure",
        "httpx.Client",
        "httpx.AsyncClient",
        "neo4j.GraphDatabase.driver",
        "neo4j.AsyncGraphDatabase.driver",
        "uvicorn.run",
        "socket.create_connection",
    ):
        monkeypatch.setattr(target, forbidden)
    monkeypatch.setenv("CHAT_AUDIT_DB_PATH", str(audit_database))
    before = audit_database.read_bytes(), audit_database.stat().st_mtime_ns
    files_before = set(audit_database.parent.iterdir())
    audit_database.chmod(0o444)
    try:
        main(["audit", *command])
        assert json.loads(capsys.readouterr().out)
        assert (
            audit_database.read_bytes(),
            audit_database.stat().st_mtime_ns,
        ) == before
        assert set(audit_database.parent.iterdir()) == files_before
    finally:
        audit_database.chmod(0o600)


@pytest.mark.parametrize(
    "command", [["list"], ["show", "session-1"], ["export", "session-1"]]
)
@pytest.mark.parametrize(
    "database_kind", ["absent", "corrupt", "no_schema", "unreadable"]
)
def test_absent_or_unreadable_storage_has_a_clear_error_and_remains_unchanged(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    command,
    database_kind,
):
    path = tmp_path / "audit.sqlite"
    if database_kind == "corrupt":
        path.write_bytes(b"not a SQLite database")
    elif database_kind == "no_schema":
        sqlite3.connect(path).close()
    elif database_kind == "unreadable":
        SQLiteAuditStore(path).initialize()
    before = (path.read_bytes(), path.stat().st_mtime_ns) if path.exists() else None
    files_before = set(tmp_path.iterdir())
    if database_kind == "unreadable":
        path.chmod(0)
    try:
        with pytest.raises(SystemExit) as error:
            main(["audit", *command, "--db", str(path)])
        assert error.value.code == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == "The audit database could not be read.\n"
    finally:
        if database_kind == "unreadable":
            path.chmod(0o600)
    assert (
        (path.read_bytes(), path.stat().st_mtime_ns) if path.exists() else None
    ) == before
    assert set(tmp_path.iterdir()) == files_before


@pytest.mark.parametrize("action", ["show", "export"])
def test_unknown_session_does_not_export_an_invented_trail(
    audit_database: Path,
    capsys: pytest.CaptureFixture[str],
    action,
):
    with pytest.raises(SystemExit) as error:
        main(["audit", action, "unknown-session", "--db", str(audit_database)])

    assert error.value.code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "No saved stages for this audit ID.\n"


@pytest.mark.parametrize(
    ("filters", "diagnostic"),
    [
        (["--since", "yesterday"], "ISO 8601 timestamp with a timezone"),
        (["--until", "2026-09-23T12:00:00"], "ISO 8601 timestamp with a timezone"),
        (["--model-deployment", "local"], "local:MODEL or openrouter:MODEL"),
        (["--model-deployment", "local:"], "local:MODEL or openrouter:MODEL"),
        (["--model-deployment", "unknown:model"], "local:MODEL or openrouter:MODEL"),
        (["--model-deployment", "{"], "saved Model Deployment JSON object"),
        (
            ["--model-deployment", '{"kind": ["local"], "model": "a"}'],
            "saved Model Deployment JSON object",
        ),
    ],
)
def test_invalid_filter_values_have_clear_usage_errors(
    audit_database: Path,
    capsys: pytest.CaptureFixture[str],
    filters,
    diagnostic,
):
    with pytest.raises(SystemExit) as error:
        main(["audit", "list", "--db", str(audit_database), *filters])
    assert error.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert diagnostic in captured.err
