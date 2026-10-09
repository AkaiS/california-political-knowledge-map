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


def test_interrupted_request_releases_work_and_a_new_submission_is_independent():
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

        app = create_app(startup=no_dependencies, session_factory=lambda *_: Session())
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://localhost"
        ) as client:
            task = asyncio.create_task(
                client.post(
                    "/api/questions", json={"question": "Who backed that bill?"}
                )
            )
            await asyncio.wait_for(entered.wait(), 2)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            await asyncio.wait_for(released.wait(), 2)
            response = await client.post(
                "/api/questions", json={"question": "Who backed another bill?"}
            )
        assert response.json()["question"] == "Who backed another bill?"
        assert response.json()["status"] == "needs_edit"

    asyncio.run(exercise())
