"""HTTP regressions for dependency stalls and retained visitor ownership."""

import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from http.cookies import SimpleCookie
from threading import Event
from typing import Literal

import httpx
import pytest

from knowledge_map.public_access import COOKIE_NAME, PublicSettings
from knowledge_map.schemas.query_preparation import QuestionAssessment
from knowledge_map.web import create_app

ORIGIN = "https://guides.example.com"
PUBLIC = PublicSettings(enabled=True, public_origin=ORIGIN)


@asynccontextmanager
async def no_dependencies():
    yield None


class DeclinedSession:
    chat_session_id = "controlled"
    assessment: QuestionAssessment | None = None
    stage: Literal["assessment", "retrieval", "guidance"] = "assessment"

    async def run(self):
        return QuestionAssessment(status="declined", explanation="Fixture response.")


@pytest.mark.parametrize("request_kind", ["readiness", "submission", "update"])
def test_dependency_stall_keeps_polling_cancellation_liveness_and_deadlines_running(
    tmp_path,
    request_kind,
):
    async def exercise():
        loop = asyncio.get_running_loop()
        dependency_entered = asyncio.Event()
        release_dependency = Event()
        stall = False

        def readiness():
            if stall:
                loop.call_soon_threadsafe(dependency_entered.set)
                if not release_dependency.wait(5):
                    return False
            return True

        class BlockedSession(DeclinedSession):
            async def run(self):
                await asyncio.Event().wait()

        app = create_app(
            startup=no_dependencies,
            session_factory=lambda *_: BlockedSession(),
            guide_db_path=tmp_path / "guides.db",
            public_settings=replace(
                PUBLIC,
                active_questions=2,
                hourly_submissions=20,
                deadline_seconds=1,
            ),
            readiness=readiness,
        )
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url=ORIGIN,
                headers={"Origin": ORIGIN},
            ) as client,
        ):
            guides = [
                (
                    await client.post("/api/questions", json={"question": question})
                ).json()
                for question in ("Cancel this search", "Deadline search")
            ]
            stall = True
            if request_kind == "readiness":
                request = client.get("/health/ready")
            elif request_kind == "submission":
                request = client.post("/api/questions", json={"question": "Waiting"})
            else:
                request = client.post(
                    f"/api/guides/{guides[0]['guide_id']}/update", json={}
                )
            stalled_request = asyncio.create_task(request)
            try:
                await asyncio.wait_for(dependency_entered.wait(), 6)
                assert not stalled_request.done(), (
                    "Dependency check blocked the event loop"
                )
                assert (await client.get("/health/live")).status_code == 200
                assert (
                    await client.get(f"/api/guides/{guides[0]['guide_id']}")
                ).json()["latest_attempt"]["status"] == "running"
                cancelled = await client.post(
                    f"/api/guides/{guides[0]['guide_id']}/attempts/"
                    f"{guides[0]['latest_attempt']['attempt_id']}/cancel",
                    json={},
                )
                assert cancelled.json()["latest_attempt"]["status"] == "cancelled"

                async def deadline_result():
                    while True:
                        response = await client.get(
                            f"/api/guides/{guides[1]['guide_id']}"
                        )
                        if response.json()["latest_attempt"]["status"] != "running":
                            return response.json()
                        await asyncio.sleep(0.01)

                expired = await asyncio.wait_for(deadline_result(), 2)
                assert expired["latest_attempt"]["status"] == "interrupted"
                assert "time limit" in expired["latest_attempt"]["message"]
                assert not stalled_request.done()
            finally:
                release_dependency.set()
                await stalled_request

    asyncio.run(exercise())


def test_near_expiry_submission_renews_same_visitor_and_keeps_recent_guide_private(
    tmp_path,
    monkeypatch,
):
    now = [datetime(2026, 1, 1, tzinfo=UTC)]

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now[0].astimezone(tz)

    monkeypatch.setattr("http.cookiejar.time.time", lambda: now[0].timestamp())
    monkeypatch.setattr("knowledge_map.adapters.source_guides.datetime", Clock)

    async def exercise():
        app = create_app(
            startup=no_dependencies,
            session_factory=lambda *_: DeclinedSession(),
            guide_db_path=tmp_path / "guides.db",
            public_settings=PUBLIC,
        )
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url=ORIGIN,
                headers={"Origin": ORIGIN},
            ) as client,
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url=ORIGIN,
                headers={"Origin": ORIGIN},
            ) as stranger,
        ):
            await client.get("/api/guides")
            original_token = client.cookies.get(COOKIE_NAME)
            now[0] += timedelta(days=29)
            submitted = await client.post(
                "/api/questions", json={"question": "Recent question"}
            )
            assert submitted.status_code == 202
            guide = submitted.json()
            assert client.cookies.get(COOKIE_NAME) == original_token
            now[0] += timedelta(days=2)
            read = await client.get(f"/api/guides/{guide['guide_id']}")
            assert read.status_code == 200
            assert read.json()["question"] == "Recent question"
            assert client.cookies.get(COOKIE_NAME) == original_token
            assert [
                row["guide_id"]
                for row in (await client.get("/api/guides")).json()["guides"]
            ] == [guide["guide_id"]]
            for response in (submitted, read):
                cookie = SimpleCookie()
                cookie.load(response.headers["set-cookie"])
                renewed = cookie[COOKIE_NAME]
                assert renewed.value == original_token
                assert renewed["max-age"] == "2592000"
                assert renewed["secure"] and renewed["httponly"]
                assert renewed["samesite"] == "Lax" and renewed["path"] == "/"
                assert response.headers["cache-control"] == "no-store"
            assert (await stranger.get("/api/guides")).json() == {"guides": []}
            assert (
                await stranger.get(f"/api/guides/{guide['guide_id']}")
            ).status_code == 404
            assert (
                await stranger.post(f"/api/guides/{guide['guide_id']}/update", json={})
            ).status_code == 404
            assert (
                await stranger.post(
                    f"/api/guides/{guide['guide_id']}/attempts/"
                    f"{guide['latest_attempt']['attempt_id']}/cancel",
                    json={},
                )
            ).status_code == 404

    asyncio.run(exercise())
