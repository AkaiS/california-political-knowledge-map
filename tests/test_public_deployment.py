"""Visitor isolation and bounded execution through the deployed HTTP boundary."""

import asyncio
import sqlite3
from contextlib import asynccontextmanager, closing
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from time import monotonic

import httpx
import pytest
from starlette.testclient import TestClient

from knowledge_map.adapters.source_guides import SQLiteGuideStore
from knowledge_map.public_access import COOKIE_NAME, PublicSettings
from knowledge_map.schemas.query_preparation import QuestionAssessment
from knowledge_map.schemas.source_guides import SourceGuide
from knowledge_map.web import create_app

ORIGIN = "https://guides.example.com"
PUBLIC = PublicSettings(enabled=True, public_origin=ORIGIN)


@asynccontextmanager
async def no_dependencies():
    yield None


class DeclinedSession:
    chat_session_id = "controlled"
    assessment = None
    stage = "assessment"

    async def run(self):
        return QuestionAssessment(
            status="declined", explanation="Test question declined."
        )


def application(path, *, settings=PUBLIC, session_factory=None, readiness=None):
    return create_app(
        startup=no_dependencies,
        session_factory=session_factory or (lambda *_: DeclinedSession()),
        guide_db_path=path,
        public_settings=settings,
        readiness=readiness,
    )


def wait_for_terminal(client, response):
    assert response.status_code == 202
    deadline = monotonic() + 3
    while response.json()["latest_attempt"]["status"] == "running":
        assert monotonic() < deadline
        response = client.get(
            response.headers["Location"]
            if "Location" in response.headers
            else f"/api/guides/{response.json()['guide_id']}"
        )
    return response


def cancel_path(guide):
    return f"/api/guides/{guide['guide_id']}/attempts/{guide['latest_attempt']['attempt_id']}/cancel"


def test_public_mode_is_explicit_and_environment_limits_are_validated(monkeypatch):
    monkeypatch.delenv("CLOUD_PUBLIC_MODE", raising=False)
    assert not PublicSettings.from_environment().enabled
    monkeypatch.setenv("CLOUD_PUBLIC_MODE", "1")
    monkeypatch.delenv("CLOUD_PUBLIC_ORIGIN", raising=False)
    with pytest.raises(ValueError, match="required"):
        PublicSettings.from_environment()
    monkeypatch.setenv("CLOUD_PUBLIC_ORIGIN", ORIGIN)
    monkeypatch.setenv("CLOUD_QUEUED_QUESTIONS", "0")
    monkeypatch.setenv("CLOUD_TRUSTED_PROXIES", "127.0.0.1/32, ::1/128")
    result = PublicSettings.from_environment()
    assert result.enabled and result.queued_questions == 0
    assert result.trusted_proxies == ("127.0.0.1/32", "::1/128")
    with pytest.raises(ValueError):
        replace(result, public_origin="https://guides.example.com/path")
    with pytest.raises(ValueError):
        replace(result, deadline_seconds=0)


def test_two_visitors_cannot_list_read_update_cancel_or_adopt_private_guides(tmp_path):
    path = tmp_path / "guides.db"
    private = SQLiteGuideStore(path).create("Private legacy question")
    app = application(path)
    with TestClient(app, base_url=ORIGIN, headers={"Origin": ORIGIN}) as client:
        response = client.post(
            "/api/questions", json={"question": "Visitor A question"}
        )
        cookie = response.headers["set-cookie"]
        for attribute in ("HttpOnly", "Secure", "SameSite=Lax", "Max-Age="):
            assert attribute in cookie
        visitor_a = client.cookies.get(COOKIE_NAME)
        saved = wait_for_terminal(client, response).json()
        before = SQLiteGuideStore(path).get(saved["guide_id"])
        assert [
            row["guide_id"] for row in client.get("/api/guides").json()["guides"]
        ] == [saved["guide_id"]]
        assert client.get(f"/api/guides/{private.guide_id}").status_code == 404
        assert SQLiteGuideStore(path).get(private.guide_id) == private
        client.cookies.clear()
        assert client.get("/api/guides").json() == {"guides": []}
        visitor_b = client.cookies.get(COOKIE_NAME)
        assert visitor_a != visitor_b
        for guide in (
            saved,
            {
                "guide_id": private.guide_id,
                "latest_attempt": {"attempt_id": private.latest_attempt.attempt_id},
            },
        ):
            assert client.get(f"/api/guides/{guide['guide_id']}").status_code == 404
            assert (
                client.post(
                    f"/api/guides/{guide['guide_id']}/update", json={}
                ).status_code
                == 404
            )
            assert client.post(cancel_path(guide), json={}).status_code == 404
        assert SQLiteGuideStore(path).get(saved["guide_id"]) == before
        client.cookies.clear()
        client.cookies.set(COOKIE_NAME, visitor_a)
        assert client.get(f"/api/guides/{saved['guide_id']}").json() == saved
        with closing(sqlite3.connect(path)) as connection:
            assert connection.execute(
                "SELECT submissions FROM public_daily_admissions"
            ).fetchone() == (1,)
    with TestClient(
        application(path), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as restarted:
        restarted.cookies.set(COOKIE_NAME, visitor_a)
        assert restarted.get(f"/api/guides/{saved['guide_id']}").json() == saved
        assert (
            restarted.post(
                f"/api/guides/{saved['guide_id']}/update", json={}
            ).status_code
            == 202
        )


@pytest.mark.parametrize("origin", [None, "https://other.example.com", "null"])
def test_modifying_requests_require_same_origin_before_work(tmp_path, origin):
    path = tmp_path / "guides.db"
    with TestClient(application(path), base_url=ORIGIN) as client:
        response = client.post(
            "/api/questions",
            json={"question": "Question"},
            headers={"Origin": origin} if origin else {},
        )
        assert response.status_code == 403
        assert SQLiteGuideStore(path).list() == []
        assert "Access-Control-Allow-Origin" not in response.headers


def test_request_and_question_bounds_do_not_create_guides(tmp_path):
    path = tmp_path / "guides.db"
    with TestClient(
        application(path), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as client:
        assert (
            client.post("/api/questions", json={"question": "a" * 4001}).status_code
            == 422
        )
        assert (
            client.post(
                "/api/questions",
                content=b" " * (PUBLIC.max_body_bytes + 1),
                headers={"Content-Type": "application/json"},
            ).status_code
            == 413
        )

        def chunks():
            yield b" " * PUBLIC.max_body_bytes
            yield b"x"

        assert (
            client.post(
                "/api/questions",
                content=chunks(),
                headers={"Content-Type": "application/json"},
            ).status_code
            == 413
        )
        assert client.post("/api/questions", json={"question": ""}).status_code == 422
        assert client.post("/api/questions", content=b"malformed").status_code == 415
        assert SQLiteGuideStore(path).list() == []
        assert (
            client.post("/api/questions", json={"question": "a" * 4000}).status_code
            == 202
        )


def test_daily_quota_survives_restart_and_updates_consume_the_same_quota(tmp_path):
    path = tmp_path / "guides.db"
    settings = replace(PUBLIC, daily_submissions=2)
    with TestClient(
        application(path, settings=settings),
        base_url=ORIGIN,
        headers={"Origin": ORIGIN},
    ) as client:
        saved = wait_for_terminal(
            client, client.post("/api/questions", json={"question": "Question"})
        ).json()
        token = client.cookies.get(COOKIE_NAME)
        wait_for_terminal(
            client, client.post(f"/api/guides/{saved['guide_id']}/update", json={})
        )
    with TestClient(
        application(path, settings=settings),
        base_url=ORIGIN,
        headers={"Origin": ORIGIN},
    ) as client:
        client.cookies.set(COOKIE_NAME, token)
        for url, body in (
            ("/api/questions", {"question": "Another question"}),
            (f"/api/guides/{saved['guide_id']}/update", {}),
        ):
            response = client.post(url, json=body)
            assert response.status_code == 429
            assert "tomorrow" in response.json()["error"]
        with closing(sqlite3.connect(path)) as connection:
            assert connection.execute(
                "SELECT count(*) FROM source_guide_attempts"
            ).fetchone() == (2,)
            assert connection.execute(
                "SELECT submissions FROM public_daily_admissions"
            ).fetchone() == (2,)


def test_hourly_visitor_and_untrusted_ip_cannot_bypass_limits_with_cookies_or_headers(
    tmp_path,
):
    async def exercise():
        path = tmp_path / "guides.db"
        app = application(path, settings=replace(PUBLIC, hourly_submissions=1))
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app, client=("192.0.2.1", 12)),
                base_url=ORIGIN,
                headers={"Origin": ORIGIN},
            ) as client:
                assert (
                    await client.post("/api/questions", json={"question": "One"})
                ).status_code == 202
                token = client.cookies.get(COOKIE_NAME)
                await asyncio.sleep(0)
                client.cookies.clear()
                assert (
                    await client.post(
                        "/api/questions",
                        json={"question": "Two"},
                        headers={"X-Forwarded-For": "192.0.2.2"},
                    )
                ).status_code == 429
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app, client=("192.0.2.3", 12)),
                base_url=ORIGIN,
                headers={"Origin": ORIGIN},
            ) as client:
                client.cookies.set(COOKIE_NAME, token)
                assert (
                    await client.post("/api/questions", json={"question": "Three"})
                ).status_code == 429

    asyncio.run(exercise())


def test_proxy_ip_trust_uses_nearest_untrusted_peer_and_external_origin(tmp_path):
    async def exercise():
        app = application(
            tmp_path / "guides.db",
            settings=replace(
                PUBLIC,
                hourly_submissions=1,
                trusted_proxies=("127.0.0.1/32", "10.0.0.0/8"),
            ),
        )
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 12)),
                base_url="http://127.0.0.1:3000",
                headers={"Origin": ORIGIN},
            ) as client,
        ):
            # Cookies are secure, so this internal transport also acts as a fresh visitor each time.
            assert (
                await client.post(
                    "/api/questions",
                    json={"question": "One"},
                    headers={"X-Forwarded-For": "192.0.2.10, 10.0.0.2"},
                )
            ).status_code == 202
            await asyncio.sleep(0)
            assert (
                await client.post(
                    "/api/questions",
                    json={"question": "Two"},
                    headers={"X-Forwarded-For": "192.0.2.20, 10.0.0.2"},
                )
            ).status_code == 202
            await asyncio.sleep(0)
            assert (
                await client.post(
                    "/api/questions",
                    json={"question": "Three"},
                    headers={"X-Forwarded-For": "spoofed, 192.0.2.20, 10.0.0.2"},
                )
            ).status_code == 429

    asyncio.run(exercise())


def test_queue_cancellation_releases_capacity_and_cannot_cancel_other_visitors(
    tmp_path,
):
    async def exercise():
        entered, stopped = [], []
        releases = {}

        class BlockedSession(DeclinedSession):
            def __init__(self, question):
                self.question = question

            async def run(self):
                entered.append(self.question)
                try:
                    await releases.setdefault(self.question, asyncio.Event()).wait()
                    return await super().run()
                finally:
                    stopped.append(self.question)

        path = tmp_path / "guides.db"
        app = application(
            path,
            settings=replace(PUBLIC, hourly_submissions=20),
            session_factory=lambda question, _: BlockedSession(question),
        )
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url=ORIGIN,
                headers={"Origin": ORIGIN},
            ) as client,
        ):
            submitted = [
                (await client.post("/api/questions", json={"question": name})).json()
                for name in ("Active", "Queued one", "Queued two")
            ]
            await asyncio.sleep(0)
            assert entered == ["Active"]
            assert (
                await client.post("/api/questions", json={"question": "Excess"})
            ).status_code == 429
            visitor_a = client.cookies.get(COOKIE_NAME)
            client.cookies.clear()
            assert (
                await client.post(cancel_path(submitted[0]), json={})
            ).status_code == 404
            assert stopped == []
            client.cookies.clear()
            client.cookies.set(COOKIE_NAME, visitor_a)
            cancelled = await client.post(cancel_path(submitted[1]), json={})
            assert cancelled.json()["latest_attempt"]["status"] == "cancelled"
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            replacement = await client.post(
                "/api/questions", json={"question": "Replacement"}
            )
            assert replacement.status_code == 202
            # A guessed attempt belonging to another owned guide cannot cancel the active guide.
            wrong = cancel_path(submitted[2]).replace(
                submitted[2]["guide_id"], submitted[0]["guide_id"]
            )
            assert (await client.post(wrong, json={})).json()["latest_attempt"][
                "status"
            ] == "running"
            assert stopped == []
            await client.post(cancel_path(submitted[0]), json={})
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            assert entered == ["Active", "Queued two"]
            assert "Queued one" not in entered
            releases["Queued two"].set()
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            assert entered == ["Active", "Queued two", "Replacement"]
            with closing(sqlite3.connect(path)) as connection:
                assert connection.execute(
                    "SELECT submissions FROM public_daily_admissions"
                ).fetchone() == (4,)
        assert set(stopped) == {"Active", "Queued two", "Replacement"}
        assert all(
            guide.latest_attempt.status != "running"
            for guide in SQLiteGuideStore(path).list()
        )

    asyncio.run(exercise())


def test_overall_deadline_covers_queue_and_active_work_and_releases_slots(tmp_path):
    async def exercise():
        entered, stopped = [], []

        class BlockedSession(DeclinedSession):
            def __init__(self, question):
                self.question = question

            async def run(self):
                entered.append(self.question)
                try:
                    await asyncio.Event().wait()
                finally:
                    stopped.append(self.question)

        path = tmp_path / "guides.db"
        app = application(
            path,
            settings=replace(PUBLIC, deadline_seconds=0.05, hourly_submissions=20),
            session_factory=lambda question, _: BlockedSession(question),
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
                await client.post("/api/questions", json={"question": name})
                for name in ("Active", "Queued one", "Queued two")
            ]
            await asyncio.sleep(0.1)
            for response in guides:
                result = (await client.get(response.headers["Location"])).json()
                assert result["latest_attempt"]["status"] == "interrupted"
                assert "time limit" in result["latest_attempt"]["message"]
            assert entered == stopped
            assert (
                await client.post("/api/questions", json={"question": "Replacement"})
            ).status_code == 202

    asyncio.run(exercise())


def test_health_has_no_model_calls_and_required_process_failure_stops_admission(
    tmp_path,
):
    calls = []
    healthy = [True]

    def session_factory(*args):
        calls.append(args)
        raise RuntimeError("Must not be called")

    app = application(
        tmp_path / "guides.db",
        readiness=lambda: healthy[0],
        session_factory=session_factory,
    )
    with TestClient(app, base_url=ORIGIN, headers={"Origin": ORIGIN}) as client:
        assert client.get("/health/live").status_code == 200
        assert client.get("/health/ready").status_code == 200
        healthy[0] = False
        assert client.get("/health/live").status_code == 200
        assert client.get("/health/ready").status_code == 503
        assert (
            client.post("/api/questions", json={"question": "Question"}).status_code
            == 503
        )
        assert calls == []
    with TestClient(app, base_url=ORIGIN) as client:
        assert client.get("/health/ready").status_code == 503


def test_public_error_does_not_expose_provider_exception(tmp_path):
    def broken(*args):
        raise RuntimeError("PRIVATE_KEY_PROVIDER_SENTINEL")

    with TestClient(
        application(tmp_path / "guides.db", session_factory=broken),
        base_url=ORIGIN,
        headers={"Origin": ORIGIN},
    ) as client:
        result = wait_for_terminal(
            client, client.post("/api/questions", json={"question": "Question"})
        )
        assert result.json()["latest_attempt"]["status"] == "failed"
        assert "PRIVATE_KEY" not in result.text
        assert "Retry" in result.json()["message"]


def test_retention_deletes_expired_owned_guides_and_attempts_preserving_local_guides(
    tmp_path,
):
    path = tmp_path / "guides.db"
    store = SQLiteGuideStore(path)
    private = store.create("Private")
    expired = store.create("Expired", owner_id="visitor")
    store.finish(
        expired.guide_id,
        expired.latest_attempt.attempt_id,
        SourceGuide(question="Expired", status="declined", message="Declined"),
    )
    recent = store.create("Recent", owner_id="visitor")
    past = (datetime.now(UTC) - timedelta(days=31)).isoformat()
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute(
            "UPDATE source_guide_attempts SET started_at = ? WHERE guide_id IN (?, ?)",
            (past, private.guide_id, expired.guide_id),
        )
    store.prune_public_guides(30)
    assert {guide.guide_id for guide in store.list()} == {
        private.guide_id,
        recent.guide_id,
    }
    with closing(sqlite3.connect(path)) as connection:
        assert connection.execute(
            "SELECT count(*) FROM source_guide_attempts WHERE guide_id = ?",
            (expired.guide_id,),
        ).fetchone() == (0,)


def test_ownership_migration_leaves_legacy_guides_unowned(tmp_path):
    path = tmp_path / "guides.db"
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute(
            "CREATE TABLE source_guides (guide_id TEXT PRIMARY KEY, question TEXT NOT NULL, "
            "created_at TEXT NOT NULL, latest_attempt_id TEXT NOT NULL, content_json TEXT, retrieved_at TEXT)"
        )
    store = SQLiteGuideStore(path)
    private = store.create("Local question")
    with closing(sqlite3.connect(path)) as connection:
        assert connection.execute(
            "SELECT owner_id FROM source_guides WHERE guide_id = ?", (private.guide_id,)
        ).fetchone() == (None,)
    assert store.list(owner_id="visitor") == []
    with pytest.raises(KeyError):
        store.start_update(private.guide_id, owner_id="visitor")


def test_concurrent_submissions_cannot_exceed_active_and_queue_capacity(tmp_path):
    async def exercise():
        entered = []

        class BlockedSession(DeclinedSession):
            def __init__(self, question):
                self.question = question

            async def run(self):
                entered.append(self.question)
                await asyncio.Event().wait()

        path = tmp_path / "guides.db"
        app = application(
            path,
            settings=replace(PUBLIC, hourly_submissions=20),
            session_factory=lambda question, _: BlockedSession(question),
        )
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url=ORIGIN,
                headers={"Origin": ORIGIN},
            ) as client,
        ):
            await client.get("/api/guides")
            results = await asyncio.gather(
                *(
                    client.post(
                        "/api/questions", json={"question": f"Question {number}"}
                    )
                    for number in range(10)
                )
            )
            await asyncio.sleep(0)
            assert (
                sorted(response.status_code for response in results)
                == [202] * 3 + [429] * 7
            )
            assert len(entered) == 1
            assert len(SQLiteGuideStore(path).list()) == 3
            with closing(sqlite3.connect(path)) as connection:
                assert connection.execute(
                    "SELECT submissions FROM public_daily_admissions"
                ).fetchone() == (3,)
        assert all(
            guide.latest_attempt.status == "interrupted"
            for guide in SQLiteGuideStore(path).list()
        )

    asyncio.run(exercise())


def test_body_limit_stops_stream_consumption_before_parsing_or_admission(tmp_path):
    async def exercise():
        consumed = []

        async def streamed_body():
            for number, chunk in enumerate(
                (b" " * PUBLIC.max_body_bytes, b"x", b"unused")
            ):
                consumed.append(number)
                yield chunk

        path = tmp_path / "guides.db"
        app = application(path)
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url=ORIGIN,
                headers={"Origin": ORIGIN},
            ) as client,
        ):
            response = await client.post(
                "/api/questions",
                content=streamed_body(),
                headers={"Content-Type": "application/json"},
            )
            assert response.status_code == 413
            assert consumed == [0, 1]
            assert SQLiteGuideStore(path).list() == []

    asyncio.run(exercise())


def test_public_environment_does_not_change_the_default_local_app(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("CLOUD_PUBLIC_MODE", "1")
    path = tmp_path / "guides.db"
    private = SQLiteGuideStore(path).create("Private local question")
    app = create_app(
        startup=no_dependencies,
        guide_db_path=path,
        session_factory=lambda *_: DeclinedSession(),
    )
    with TestClient(app, base_url="http://localhost") as client:
        assert client.get(f"/api/guides/{private.guide_id}").status_code == 200
        assert "set-cookie" not in client.get("/api/guides").headers
        for number in range(4):
            response = client.post(
                "/api/questions", json={"question": f"{number}" + "a" * 4001}
            )
            assert wait_for_terminal(client, response).status_code == 200


def test_required_process_failure_does_not_prevent_owner_cancellation(tmp_path):
    async def exercise():
        healthy = [True]
        stopped = asyncio.Event()

        class BlockedSession(DeclinedSession):
            async def run(self):
                try:
                    await asyncio.Event().wait()
                finally:
                    stopped.set()

        app = application(
            tmp_path / "guides.db",
            session_factory=lambda *_: BlockedSession(),
            readiness=lambda: healthy[0],
        )
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url=ORIGIN,
                headers={"Origin": ORIGIN},
            ) as client,
        ):
            response = await client.post(
                "/api/questions", json={"question": "Question"}
            )
            await asyncio.sleep(0)
            healthy[0] = False
            assert (await client.get("/health/ready")).status_code == 503
            cancelled = await client.post(cancel_path(response.json()), json={})
            assert cancelled.status_code == 200
            assert cancelled.json()["latest_attempt"]["status"] == "cancelled"
            await asyncio.wait_for(stopped.wait(), 1)

    asyncio.run(exercise())
