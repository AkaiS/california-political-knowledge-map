"""Independent deployment failure and persistence checks using disposable data."""

import json
import sqlite3
from pathlib import Path

import httpx
import pytest
from neo4j import GraphDatabase
from neo4j.exceptions import AuthError

from knowledge_map import cloud_runtime as runtime
from knowledge_map.adapters.sqlite_db import init_db


def corpus(path: Path) -> None:
    init_db(str(path))
    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO stories(title, url, content) VALUES (?, ?, ?)",
            ("Public article", "https://example.org/article", "Public content"),
        )
        connection.execute(
            "INSERT INTO publications(id, name, base_url) VALUES (?, ?, ?)",
            ("example", "Example", "https://example.org"),
        )


def installed(root: Path, monkeypatch) -> Path:
    (root / "recovery").mkdir()
    (root / "neo4j/databases/neo4j").mkdir(parents=True)
    (root / "sqlite").mkdir()
    (root / "models").mkdir()
    db = root / "sqlite/document_store.db"
    corpus(db)
    model = root / "models" / runtime.ARTIFACTS[2]
    model.write_bytes(b"immutable model fixture")
    monkeypatch.setattr(runtime, "EMBEDDING_SHA256", runtime.sha256(model))
    monkeypatch.setenv("NEO4J_VERSION", "2026.07.1")
    (root / "recovery/installed-release.json").write_text(
        json.dumps({"neo4j_version": "2026.07.1", "corpus_id": "review"})
    )
    return db


def test_restart_retains_visitor_and_admission_state(tmp_path, monkeypatch):
    from knowledge_map.adapters.source_guides import SQLiteGuideStore

    db = installed(tmp_path, monkeypatch)
    store = SQLiteGuideStore(db)
    guide = store.create("Visitor question", owner_id="visitor-one")
    assert store.admit_public_question(20)
    before = db.read_bytes()

    def refuse_restore(*args, **kwargs):
        pytest.fail("A restart must not run a database restore")

    monkeypatch.setattr(runtime.subprocess, "run", refuse_restore)
    runtime.prepare_data(tmp_path)
    runtime.prepare_data(tmp_path)
    assert db.read_bytes() == before
    with sqlite3.connect(db) as connection:
        assert connection.execute(
            "SELECT owner_id FROM source_guides WHERE guide_id = ?", (guide.guide_id,)
        ).fetchone() == ("visitor-one",)
        assert connection.execute(
            "SELECT sum(submissions) FROM public_daily_admissions"
        ).fetchone() == (1,)


def test_installed_model_corruption_stops_restart(tmp_path, monkeypatch):
    db = installed(tmp_path, monkeypatch)
    before = db.read_bytes()
    (tmp_path / "models" / runtime.ARTIFACTS[2]).write_bytes(b"corrupt")
    with pytest.raises(runtime.CloudConfigurationError, match="checksum"):
        runtime.prepare_data(tmp_path)
    assert db.read_bytes() == before


def test_readiness_rejects_bad_graph_auth_without_inference(monkeypatch):
    calls = []

    class Client:
        def __init__(self, **kwargs):
            assert kwargs["trust_env"] is False

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get(self, url):
            calls.append(url)
            return httpx.Response(200)

    class Driver:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def verify_connectivity(self):
            raise AuthError("incorrect credentials")

    def driver(uri, **kwargs):
        assert uri == "bolt://127.0.0.1:7687"
        assert kwargs["auth"] == ("neo4j", "fresh-review-password")
        return Driver()

    monkeypatch.setenv("NEO4J_URI", "bolt://127.0.0.1:7687")
    monkeypatch.setenv("NEO4J_PASSWORD", "fresh-review-password")
    monkeypatch.setattr(runtime.httpx, "Client", Client)
    monkeypatch.setattr(GraphDatabase, "driver", driver)
    assert runtime.dependencies_ready() is False
    assert calls == ["http://127.0.0.1:8081/health"]


def test_denied_secrets_never_expose_response_body(monkeypatch):
    monkeypatch.setenv("CLOUD_SECRET_SOURCE", "bottle")
    monkeypatch.setenv("BOTTLE_ROUTER_URL", "https://bottle.example")
    monkeypatch.setenv("BOTTLE_APP_TOKEN", "review-app-token")
    with (
        httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(403, json={"secret": "private-response"})
            )
        ) as client,
        pytest.raises(runtime.CloudConfigurationError) as error,
    ):
        runtime.load_secrets(client=client)
    assert "private-response" not in str(error.value)
    assert "review-app-token" not in str(error.value)


def test_same_name_incompatible_corpus_schema_is_rejected(tmp_path):
    path = tmp_path / "invalid.db"
    with sqlite3.connect(path) as connection:
        connection.executescript(
            "CREATE TABLE stories(id); INSERT INTO stories VALUES(1);"
            "CREATE TABLE publications(id); INSERT INTO publications VALUES(1);"
        )
    with pytest.raises(runtime.CloudConfigurationError):
        runtime.validate_sqlite(path, sanitized=True)


@pytest.mark.parametrize(
    "schema",
    [
        "CREATE TABLE source_guides(question)",
        "CREATE TABLE source_guide_attempts(outcome_json)",
        "CREATE TABLE public_daily_admissions(day)",
    ],
)
def test_empty_incompatible_private_tables_are_rejected(tmp_path, schema):
    path = tmp_path / "invalid-private-schema.db"
    corpus(path)
    with sqlite3.connect(path) as connection:
        connection.execute(schema)
    with pytest.raises(runtime.CloudConfigurationError):
        runtime.validate_sqlite(path, sanitized=True)
