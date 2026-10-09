"""Submission owns one question until the synchronous response finishes."""

import asyncio
from contextlib import asynccontextmanager

import httpx
from starlette.testclient import TestClient
from test_chat_web import no_dependencies

from knowledge_map.schemas.query_preparation import QuestionAssessment
from knowledge_map.web import create_app


def test_application_opens_and_closes_dependencies_once_for_several_questions():
    lifecycle = []

    @asynccontextmanager
    async def startup():
        lifecycle.append("started")
        yield None
        lifecycle.append("closed")

    class Session:
        chat_session_id = "test-session"

        async def run(self):
            return QuestionAssessment(status="needs_edit", explanation="Name the bill.")

    with TestClient(
        create_app(startup=startup, session_factory=lambda *_: Session()),
        base_url="http://localhost",
    ) as client:
        for _ in range(2):
            assert (
                client.post(
                    "/api/questions", json={"question": "Who backed that bill?"}
                ).json()["status"]
                == "needs_edit"
            )
        assert lifecycle == ["started"]
    assert lifecycle == ["started", "closed"]


def test_submission_is_saved_before_execution_and_interruption_retains_the_question(
    tmp_path,
):
    async def exercise():
        entered = asyncio.Event()
        released = asyncio.Event()
        calls = []

        class Session:
            chat_session_id = "test-session"

            async def run(self):
                calls.append("run")
                if len(calls) == 1:
                    try:
                        entered.set()
                        await asyncio.Event().wait()
                    finally:
                        released.set()
                return QuestionAssessment(
                    status="needs_edit", explanation="Name the bill."
                )

        app = create_app(
            startup=no_dependencies,
            session_factory=lambda *_: Session(),
            guide_db_path=tmp_path / "guides.db",
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://localhost"
        ) as client:
            task = asyncio.create_task(
                client.post(
                    "/api/questions", json={"question": "Who backed that bill?"}
                )
            )
            await asyncio.wait_for(entered.wait(), 2)
            saved = (await client.get("/api/guides")).json()["guides"]
            assert len(saved) == 1
            first = (await client.get(f"/api/guides/{saved[0]['guide_id']}")).json()
            assert first["question"] == "Who backed that bill?"
            assert first["status"] == "running"
            assert first["latest_attempt"]["status"] == "running"
            assert "last_retrieved_at" not in first
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            await asyncio.wait_for(released.wait(), 2)
            interrupted = (await client.get(f"/api/guides/{first['guide_id']}")).json()
            assert interrupted["latest_attempt"]["status"] == "interrupted"
            assert interrupted["latest_attempt"]["finished_at"]
            assert interrupted["question"] == first["question"]
            assert (
                interrupted["latest_attempt"]["attempt_id"]
                == first["latest_attempt"]["attempt_id"]
            )
            response = await client.post(
                "/api/questions", json={"question": "Who backed another bill?"}
            )
        assert response.json()["question"] == "Who backed another bill?"
        assert response.json()["status"] == "needs_edit"
        assert response.json()["guide_id"] != first["guide_id"]
        return interrupted

    interrupted = asyncio.run(exercise())
    with TestClient(
        create_app(startup=no_dependencies, guide_db_path=tmp_path / "guides.db"),
        base_url="http://localhost",
    ) as client:
        assert (
            client.get(f"/api/guides/{interrupted['guide_id']}").json() == interrupted
        )
