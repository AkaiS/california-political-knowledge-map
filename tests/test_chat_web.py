"""Local chat behavior observed through its ASGI application."""

import json
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import httpx2
import pytest
from starlette.testclient import TestClient

from knowledge_map.schemas.query_preparation import (
    AwaitingQueryApproval,
    DeclinedQuestion,
    QueryApproval,
    RewriteRejection,
    RewriteUnavailable,
)
from knowledge_map.web import create_app


@asynccontextmanager
async def no_dependencies():
    yield None


@pytest.mark.parametrize(
    "option",
    [
        {"model": "openai:another-model"},
        {"builtinTools": ["web_search"]},
    ],
)
def test_chat_rejects_runtime_model_and_tool_selection(option):
    def unexpected_session(*_):
        raise AssertionError(
            "Runtime selection must be rejected before preparing a question"
        )

    with TestClient(
        create_app(startup=no_dependencies, session_factory=unexpected_session),
        base_url="http://localhost",
    ) as client:
        response = client.post(
            "/api/chat", json={**question_request("Who supported AB 1?"), **option}
        )
    assert response.status_code == 400


def question_request(question: str, conversation_id: str = "conversation-1") -> dict:
    return {
        "id": conversation_id,
        "messages": [
            {
                "id": "question-1",
                "role": "user",
                "parts": [{"type": "text", "text": question}],
            }
        ],
    }


def events(response: httpx.Response | httpx2.Response) -> list[dict]:
    assert response.status_code == 200
    assert response.headers["x-vercel-ai-ui-message-stream"] == "v1"
    return [
        json.loads(line[6:])
        for line in response.text.splitlines()
        if line.startswith("data: ") and line != "data: [DONE]"
    ]


@pytest.mark.parametrize("use_frontend_options", [False, True])
def test_first_question_prepares_one_session_and_exposes_only_public_approval(
    use_frontend_options,
):
    questions = []

    class Session:
        async def prepare(self):
            return AwaitingQueryApproval(
                approval=QueryApproval(question="Which organizations supported AB 1?")
            )

        async def approve(self):
            pytest.fail("Preparation must never enter retrieval")

        def reject(self, correction=None) -> RewriteRejection:
            pytest.fail("Preparation must never reject a proposal")

    def session_factory(question, dependencies):
        questions.append(question)
        return Session()

    with TestClient(
        create_app(startup=no_dependencies, session_factory=session_factory),
        base_url="http://127.0.0.1:7932",
    ) as client:
        payload = question_request("Who backed AB 1?")
        if use_frontend_options:
            config = client.get("/api/configure").json()
            # The stock UI selects models[0].id on mount and sends it on every turn.
            payload.update(
                model=config["models"][0]["id"], builtinTools=[], effort="medium"
            )
        response = client.post("/api/chat", json=payload)
        chunks = events(response)
        repeated = client.post("/api/chat", json=payload)

    assert questions == ["Who backed AB 1?"]
    assert [chunk["type"] for chunk in chunks] == [
        "start",
        "text-start",
        "text-delta",
        "text-end",
        "tool-input-available",
        "tool-approval-request",
        "finish",
    ]
    approval = next(
        chunk for chunk in chunks if chunk["type"] == "tool-input-available"
    )
    assert approval["toolName"] == "Query approval"
    assert approval["input"] == {"question": "Which organizations supported AB 1?"}
    assert "relational" not in response.text
    assert repeated.status_code == 409


def test_deferred_proposal_shows_the_coverage_limit_and_recoverable_portion():
    class Session:
        async def prepare(self):
            return AwaitingQueryApproval(
                approval=QueryApproval(
                    question="How did legislators vote on AB 1?",
                    explanation="Complete roll calls are not available.",
                    recoverable_portion="CalMatters reporting can identify some votes.",
                )
            )

        async def approve(self):
            pytest.fail("Preparation must never enter retrieval")

        def reject(self, correction=None) -> RewriteRejection:
            pytest.fail("Preparation must never reject a proposal")

    with TestClient(
        create_app(startup=no_dependencies, session_factory=lambda *_: Session()),
        base_url="http://127.0.0.1:7932",
    ) as client:
        chunks = events(
            client.post("/api/chat", json=question_request("Who voted yes?"))
        )

    text = "".join(chunk["delta"] for chunk in chunks if chunk["type"] == "text-delta")
    assert "Complete roll calls are not available." in text
    assert "CalMatters reporting can identify some votes." in text
    assert any(chunk["type"] == "tool-approval-request" for chunk in chunks)


@pytest.mark.parametrize(
    "outcome",
    [
        DeclinedQuestion(
            message="Predictions are outside this collection's question policy."
        ),
        RewriteUnavailable(
            message="The question cannot be rewritten right now. Try again later."
        ),
    ],
)
def test_terminal_preparation_outcomes_offer_neither_approval_nor_retrieval(outcome):
    class Session:
        async def prepare(self):
            return outcome

        async def approve(self):
            pytest.fail("Preparation must never enter retrieval")

        def reject(self, correction=None) -> RewriteRejection:
            pytest.fail("Preparation must never reject a proposal")

    with TestClient(
        create_app(startup=no_dependencies, session_factory=lambda *_: Session()),
        base_url="http://127.0.0.1:7932",
    ) as client:
        chunks = events(
            client.post("/api/chat", json=question_request("Who will win?"))
        )

    assert [chunk["type"] for chunk in chunks] == [
        "start",
        "text-start",
        "text-delta",
        "text-end",
        "finish",
    ]
    assert (
        next(chunk["delta"] for chunk in chunks if chunk["type"] == "text-delta")
        == outcome.message
    )


@pytest.mark.parametrize(
    "path", ["/", "/api/configure", "/api/chat", "/docs", "/redoc", "/openapi.json"]
)
def test_chat_rejects_a_nonlocal_host(path: str):
    with TestClient(
        create_app(startup=no_dependencies), base_url="http://attacker.example"
    ) as client:
        response = client.request("POST" if path == "/api/chat" else "GET", path)

    assert response.status_code == 421


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "[::1]"])
def test_chat_accepts_local_hosts(host: str):
    with TestClient(
        create_app(startup=no_dependencies), base_url="http://127.0.0.1:7932"
    ) as client:
        response = client.get("/api/configure", headers={"Host": f"{host}:7932"})

    assert response.status_code == 200
    assert response.json() == {
        "models": [
            {
                "id": "",
                "name": "Local retrieval",
                "builtinTools": [],
            }
        ],
        "builtinTools": [],
    }


def test_root_serves_the_default_cdn_frontend_and_reuses_the_local_cache(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    downloads: list[httpx.URL] = []
    frontend = b"<!doctype html><title>CDN response fixture</title>"

    def cdn(request: httpx.Request) -> httpx.Response:
        downloads.append(request.url)
        return httpx.Response(200, content=frontend)

    http_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda: http_client(transport=httpx.MockTransport(cdn))
    )
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    # A fresh application must reuse the filesystem cache, without a second download.
    for _ in range(2):
        with TestClient(
            create_app(startup=no_dependencies), base_url="http://127.0.0.1:7932"
        ) as client:
            response = client.get("/")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")
        assert response.content == frontend

    assert len(downloads) == 1
    assert downloads[0].scheme == "https"
    assert downloads[0].host == "cdn.jsdelivr.net"
    assert downloads[0].path.startswith("/npm/@pydantic/ai-chat-ui@")
    assert downloads[0].path.endswith("/dist/index.html")
