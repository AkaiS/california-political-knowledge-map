"""Independent HTTP regressions for public admission and saved-guide state transitions."""

import asyncio
import sqlite3
from contextlib import asynccontextmanager, closing
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import httpx

from knowledge_map.public_access import PublicSettings
from knowledge_map.schemas.query_preparation import QuestionAssessment
from knowledge_map.web import create_app

ORIGIN = "https://review.example.org"
SETTINGS = PublicSettings(enabled=True, public_origin=ORIGIN)


@asynccontextmanager
async def no_external_dependencies():
    yield None


class DeclinedSession:
    stage = "assessment"
    assessment = None
    chat_session_id = "review"

    async def run(self):
        return QuestionAssessment(status="declined", explanation="Fixture response.")


def make_app(path, *, settings=SETTINGS, session_factory=None):
    return create_app(
        startup=no_external_dependencies,
        session_factory=session_factory or (lambda *_: DeclinedSession()),
        guide_db_path=path,
        public_settings=settings,
    )


async def terminal(client, guide):
    for _ in range(100):
        response = await client.get(f"/api/guides/{guide['guide_id']}")
        if response.json()["latest_attempt"]["status"] != "running":
            return response.json()
        await asyncio.sleep(0)
    raise AssertionError("Fixture execution failed to terminate")


def daily_count(path):
    with closing(sqlite3.connect(path)) as connection:
        return connection.execute(
            "SELECT COALESCE(sum(submissions), 0) FROM public_daily_admissions"
        ).fetchone()[0]


def test_expiring_guide_update_never_rejects_after_consuming_admission(tmp_path):
    async def exercise():
        path = tmp_path / "guides.db"
        app = make_app(path)
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url=ORIGIN,
                headers={"Origin": ORIGIN},
            ) as client,
        ):
            submitted = await client.post("/api/questions", json={"question": "Saved question"})
            guide = await terminal(client, submitted.json())
            old = (datetime.now(UTC) - timedelta(days=31)).isoformat()
            with closing(sqlite3.connect(path)) as connection, connection:
                connection.execute(
                    "UPDATE source_guide_attempts SET started_at=? WHERE guide_id=?",
                    (old, guide["guide_id"]),
                )
            before = daily_count(path)
            response = await client.post(f"/api/guides/{guide['guide_id']}/update", json={})
            assert response.status_code == 202
            assert daily_count(path) == before + 1
            result = await terminal(client, response.json())
            assert result["question"] == guide["question"]
            assert result["latest_attempt"]["attempt_id"] != guide["latest_attempt"]["attempt_id"]

    asyncio.run(exercise())


def test_stale_cancel_never_cancels_a_new_same_visitor_update_or_consumes_quota(tmp_path):
    async def exercise():
        release = asyncio.Event()

        class BlockedSession(DeclinedSession):
            async def run(self):
                await release.wait()
                return await super().run()

        factories = iter((DeclinedSession, BlockedSession))
        path = tmp_path / "guides.db"
        app = make_app(path, session_factory=lambda *_: next(factories)())
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url=ORIGIN,
                headers={"Origin": ORIGIN},
            ) as client,
        ):
            first = await client.post("/api/questions", json={"question": "Original"})
            guide = await terminal(client, first.json())
            updated = await client.post(f"/api/guides/{guide['guide_id']}/update", json={})
            assert updated.status_code == 202
            old_attempt = guide["latest_attempt"]["attempt_id"]
            new_attempt = updated.json()["latest_attempt"]["attempt_id"]
            before = daily_count(path)
            stale = await client.post(
                f"/api/guides/{guide['guide_id']}/attempts/{old_attempt}/cancel", json={},
            )
            assert stale.status_code == 200
            assert stale.json()["latest_attempt"]["attempt_id"] == new_attempt
            assert stale.json()["latest_attempt"]["status"] == "running"
            conflicting = await client.post(f"/api/guides/{guide['guide_id']}/update", json={})
            assert conflicting.status_code == 409
            assert daily_count(path) == before
            release.set()
            finished = await terminal(client, guide)
            assert finished["latest_attempt"]["status"] == "completed"

    asyncio.run(exercise())


def test_fixed_window_rejection_does_not_extend_window_or_bypass_persistent_daily_gate(
    tmp_path, monkeypatch,
):
    clock = [100.0]
    monkeypatch.setattr("limits.storage.memory.time.time", lambda: clock[0])

    async def exercise():
        path = tmp_path / "guides.db"
        app = make_app(path, settings=replace(SETTINGS, hourly_submissions=1, daily_submissions=2))
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app, client=("192.0.2.5", 1)),
                base_url=ORIGIN, headers={"Origin": ORIGIN},
            ) as client,
        ):
            first = await client.post("/api/questions", json={"question": "First"})
            assert first.status_code == 202
            await terminal(client, first.json())
            clock[0] += 3599
            assert (await client.post("/api/questions", json={"question": "Rejected"})).status_code == 429
            assert daily_count(path) == 1
            clock[0] += 1
            second = await client.post("/api/questions", json={"question": "Second"})
            assert second.status_code == 202
            await terminal(client, second.json())
            clock[0] += 3600
            third = await client.post("/api/questions", json={"question": "Daily rejected"})
            assert third.status_code == 429
            assert "tomorrow" in third.json()["error"]
            assert daily_count(path) == 2

    asyncio.run(exercise())


def test_forwarded_origin_and_host_cannot_authorize_work_or_spend_admission(tmp_path):
    async def exercise():
        path = tmp_path / "guides.db"
        app = make_app(path, settings=replace(SETTINGS, trusted_proxies=("127.0.0.1/32",)))
        consumed = []

        async def body():
            consumed.append(True)
            yield b'{"question":"Never admitted"}'

        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 1)),
                base_url=ORIGIN,
            ) as client,
        ):
            response = await client.post(
                "/api/questions", content=body(),
                headers={
                    "Content-Type": "application/json",
                    "Origin": "https://attacker.example.org",
                    "X-Forwarded-Host": "review.example.org",
                    "X-Forwarded-Proto": "https",
                },
            )
            assert response.status_code == 403
            assert consumed == []
            spoofed_host = await client.post(
                "/api/questions", json={"question": "Never admitted"},
                headers={"Origin": ORIGIN, "Host": "attacker.example.org"},
            )
            assert spoofed_host.status_code == 421
            assert daily_count(path) == 0
            with closing(sqlite3.connect(path)) as connection:
                assert connection.execute("SELECT count(*) FROM source_guides").fetchone()[0] == 0

    asyncio.run(exercise())
