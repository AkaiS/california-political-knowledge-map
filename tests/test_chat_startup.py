"""Startup requirements observed through the local chat ASGI application."""

import json
from functools import partial
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from neo4j import AsyncDriver, AsyncGraphDatabase
from neo4j.exceptions import ServiceUnavailable
from starlette.testclient import TestClient
from test_chat_web import events, question_request
from test_model_factory import chat_completion

from knowledge_map.chat_startup import chat_dependencies
from knowledge_map.schemas.query_preparation import AwaitingQueryApproval, QueryApproval
from knowledge_map.utils.reachability import SKIP_MODEL_CHECK_ENV
from knowledge_map.web import create_app


def test_real_chat_session_prepares_the_question_using_startup_coverage(
    startup_dependencies,
):
    _, _, _, _, requests, _, _, _ = startup_dependencies
    with TestClient(create_app(), base_url="http://localhost") as client:
        response = client.post("/api/chat", json=question_request("Who backed AB 1?"))
        chunks = events(response)

    assessment_request = next(
        request
        for request in requests
        if request.method == "POST" and request.url.host == "chat.test"
    )
    messages = json.loads(assessment_request.content)["messages"]
    assessment = json.loads(messages[-1]["content"])
    assert assessment["question"] == "Which organizations supported AB 1?"
    assert [entry["collection_id"] for entry in assessment["coverage"]["entries"]] == [
        "calmatters"
    ]
    assert "monthly_coverage" not in assessment
    assert "CalMatters has 2 available articles." in response.text
    assert "Complete lobbying records are unavailable." in response.text
    assert "relational" not in response.text
    assert any(chunk["type"] == "tool-approval-request" for chunk in chunks)


@pytest.fixture
def startup_dependencies(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv(SKIP_MODEL_CHECK_ENV, raising=False)
    monkeypatch.setenv("QUERY_REWRITER_MODEL", "rewriter-test")
    monkeypatch.setenv("QUERY_REWRITER_DEPLOYMENT", "local")
    monkeypatch.setenv("QUERY_REWRITER_BASE_URL", "http://rewriter.test:8080/v1")
    monkeypatch.setenv("CHAT_DEPLOYMENT", "local")
    monkeypatch.setenv("LLAMA_CPP_MODEL", "chat-test")
    monkeypatch.setenv("LLAMA_CPP_BASE_URL", "http://chat.test:8080/v1")
    monkeypatch.setenv(
        "LLAMA_CPP_EMBEDDING_BASE_URL", "http://unavailable-embedding.test/v1"
    )
    monkeypatch.setenv("NEO4J_URI", "bolt://graph.test:7687")
    monkeypatch.setenv("NEO4J_USERNAME", "neo4j")
    monkeypatch.setenv("NEO4J_PASSWORD", "test-password")
    driver = MagicMock(spec=AsyncDriver)
    result = AsyncMock()
    result.data.return_value = [
        {
            "available_count": 2,
            "publication_dates": ["2025-03-02", "2026-09-01"],
        }
    ]

    async def query(text, parameters):
        # Ingestion stores the Source Article URL as its id, with no url property.
        if "article.url" in str(text):
            raise ValueError("The stored Source Article URL is article.id")
        if "SHOW INDEXES" in str(text):
            raise ServiceUnavailable("Branch indexes are unavailable")
        return result

    driver.session.return_value.__aenter__.return_value.run = AsyncMock(
        side_effect=query
    )
    drivers = []

    def graph(*args, **kwargs):
        drivers.append(driver)
        return driver

    monkeypatch.setattr(AsyncGraphDatabase, "driver", graph)
    clients = []
    requests = []
    failures = set()
    statuses = {}

    def respond(request: httpx.Request):
        requests.append(request)
        if (
            request.url.host in failures
            or request.url.host == "unavailable-embedding.test"
        ):
            raise httpx.ConnectError("private diagnostic", request=request)
        if request.method == "GET":
            return httpx.Response(statuses.get(request.url.host, 200))
        if request.method == "POST":
            if request.url.host == "rewriter.test":
                output = {
                    "question": "Which organizations supported AB 1?",
                    "relational": True,
                }
            else:
                payload = json.loads(request.content)
                assessment = json.loads(payload["messages"][-1]["content"])
                entry = assessment["coverage"]["entries"][0]
                output = {
                    "status": "deferred",
                    "explanation": "Complete lobbying records are unavailable.",
                    "recoverable_portion": f"{entry['name']} has {entry['availability']['available_count']} available articles.",
                }
            return httpx.Response(200, json=chat_completion(json.dumps(output)))
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client_type = httpx.AsyncClient

    class Client(client_type):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(respond)
            super().__init__(*args, **kwargs)
            clients.append(self)

    monkeypatch.setattr(httpx, "AsyncClient", Client)
    return None, driver, drivers, clients, requests, failures, statuses, result


def test_startup_assembles_once_refreshes_calmatters_and_closes_owned_resources(
    startup_dependencies,
):
    _, driver, drivers, clients, requests, _, _, _ = startup_dependencies
    received = []

    def session_factory(question, dependencies):
        received.append(dependencies)

        class Session:
            async def prepare(self):
                entry = dependencies.coverage.entries[0]
                return AwaitingQueryApproval(
                    approval=QueryApproval(
                        question=question,
                        explanation=f"{entry.name}: {entry.availability.available_count} articles, "
                        f"{entry.earliest_date} to {entry.latest_date}.",
                    )
                )

        return Session()

    with TestClient(
        create_app(session_factory=session_factory), base_url="http://localhost"
    ) as client:
        for index in range(2):
            chunks = events(
                client.post(
                    "/api/chat",
                    json=question_request(
                        "Find housing reporting.", f"question-{index}"
                    ),
                )
            )
            assert "CalMatters: 2 articles, 2025-03-02 to 2026-09-01." in json.dumps(
                chunks
            )
        config = client.get("/api/configure").json()
        assert len(config["models"]) == 1
        assert config["models"][0]["id"] == ""
        assert config["models"][0]["builtinTools"] == []
        assert config["builtinTools"] == []

    assert received[0] is received[1]
    assert len(drivers) == 1
    assert received[0].rewriter is not received[0].chat_agent
    assert received[0].coverage.entries[0].limitations
    assert received[0].coverage.entries[0].availability.expected_count is None
    assert {request.url.host for request in requests} == {"chat.test", "rewriter.test"}
    assert clients and all(value.is_closed for value in clients)
    driver.close.assert_awaited_once()


@pytest.mark.parametrize(
    ("stored_dates", "expected_range"),
    [
        (
            [None, "", "not a date", "2025-03-02T12:00:00Z", "2026-09-01"],
            ("2025-03-02", "2026-09-01"),
        ),
        ([None, "", "not a date"], (None, None)),
    ],
)
def test_startup_ignores_unparseable_publication_dates(
    startup_dependencies,
    stored_dates,
    expected_range,
):
    _, _, _, _, _, _, _, result = startup_dependencies
    result.data.return_value = [
        {"available_count": len(stored_dates), "publication_dates": stored_dates}
    ]
    received = []

    def session_factory(question, dependencies):
        received.append(dependencies)

        class Session:
            async def prepare(self):
                return AwaitingQueryApproval(
                    approval=QueryApproval(
                        question=question,
                        explanation="Review this question.",
                    )
                )

        return Session()

    with TestClient(
        create_app(session_factory=session_factory), base_url="http://localhost"
    ) as client:
        response = client.post(
            "/api/chat", json=question_request("Find CalMatters reporting.")
        )

    assert response.status_code == 200
    entry = received[0].coverage.entries[0]
    actual_range = tuple(
        value.isoformat() if value is not None else None
        for value in (entry.earliest_date, entry.latest_date)
    )
    assert actual_range == expected_range


def test_startup_counts_any_local_model_http_response_as_reachable(
    startup_dependencies,
):
    _, _, _, _, requests, _, statuses, _ = startup_dependencies
    statuses.update({"rewriter.test": 401, "chat.test": 503})

    with TestClient(create_app(), base_url="http://localhost") as client:
        assert client.get("/api/configure").status_code == 200

    assert {request.url.host for request in requests} == {
        "chat.test",
        "rewriter.test",
    }


def test_startup_honors_the_shared_model_reachability_override(
    startup_dependencies,
    monkeypatch,
):
    _, _, _, _, requests, failures, _, _ = startup_dependencies
    failures.update({"rewriter.test", "chat.test"})
    monkeypatch.setenv(SKIP_MODEL_CHECK_ENV, "1")

    with TestClient(create_app(), base_url="http://localhost") as client:
        assert client.get("/api/configure").status_code == 200

    assert requests == []


def test_startup_does_not_probe_openrouter_deployments(
    startup_dependencies,
    monkeypatch,
):
    _, _, _, _, requests, _, _, _ = startup_dependencies
    monkeypatch.setenv("QUERY_REWRITER_DEPLOYMENT", "openrouter")
    monkeypatch.setenv("QUERY_REWRITER_MODEL", "openai/rewriter-test")
    monkeypatch.setenv("CHAT_DEPLOYMENT", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("OPENROUTER_MODEL", "openai/test-model")
    monkeypatch.setenv("OPENROUTER_PROVIDERS", "test-provider")

    with TestClient(create_app(), base_url="http://localhost") as client:
        assert client.get("/api/configure").status_code == 200

    assert requests == []


@pytest.mark.parametrize(
    "failure, explanation",
    [
        ("neo4j", "Neo4j"),
        ("rewriter", "Query Rewriter deployment"),
        ("chat", "Chat Agent deployment"),
        ("coverage_file", "CalMatters coverage"),
        ("coverage_refresh", "CalMatters coverage"),
        ("empty_coverage", "CalMatters coverage"),
    ],
)
def test_startup_names_the_unavailable_dependency_and_cleans_up(
    startup_dependencies,
    failure,
    explanation,
    monkeypatch,
    tmp_path,
):
    _, driver, drivers, clients, _, failures, _, result = startup_dependencies
    startup = chat_dependencies
    if failure == "neo4j":
        driver.verify_connectivity.side_effect = ServiceUnavailable("private detail")
    elif failure == "rewriter":
        failures.add("rewriter.test")
    elif failure == "chat":
        failures.add("chat.test")
    elif failure == "coverage_file":
        startup = partial(chat_dependencies, coverage_path=tmp_path / "missing.json")
    elif failure == "coverage_refresh":
        result.data.side_effect = ServiceUnavailable("private detail")
    elif failure == "empty_coverage":
        result.data.return_value = [{"available_count": 0, "publication_dates": []}]

    with (
        pytest.raises(RuntimeError, match=explanation),
        TestClient(create_app(startup=startup), base_url="http://localhost"),
    ):
        pytest.fail(
            "Unavailable dependencies must prevent the application from serving"
        )

    assert all(value.is_closed for value in clients)
    if drivers:
        driver.close.assert_awaited_once()
