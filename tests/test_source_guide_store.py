"""Configured storage and saved-guide summaries through the application API."""

import json
import sqlite3
from contextlib import asynccontextmanager, closing

import pytest
from starlette.testclient import TestClient
from test_chat_web import guide_client, no_dependencies, stored_article, submit_guide

from knowledge_map.adapters.source_guides import SQLiteGuideStore
from knowledge_map.adapters.sqlite_db import (
    cache_scraped_html,
    init_db,
    register_publication,
    save_story,
)
from knowledge_map.schemas.source_guides import SourceGuide
from knowledge_map.schemas.stories import Story
from knowledge_map.web import create_app


@pytest.mark.parametrize("explicit", [False, True])
def test_configured_store_saves_guides_with_its_publication_and_original_highlights(
    tmp_path, monkeypatch, explicit
):
    configured = tmp_path / "configured.db"
    override = tmp_path / "override.db"
    monkeypatch.setenv("SQLITE_DB_PATH", str(configured))
    url = "https://example.com/dense"
    selected = "The committee heard testimony about housing eligibility."
    for path, name in (
        (configured, "Configured publication"),
        (override, "Override publication"),
    ):
        init_db(str(path))
        register_publication(
            "reporting", name, "https://example.com", db_path=str(path)
        )
        cache_scraped_html(url, "reporting", "<p>Stored story</p>", db_path=str(path))
        save_story(Story(url=url, title="Hearing", content=selected), str(path))

    async def grounding(candidate):
        return (await stored_article(candidate)).model_copy(update={"text": selected})

    selected_path = override if explicit else configured
    with guide_client(
        db_path=override if explicit else None,
        guidance={
            "source_notes": [{"source_article_id": url, "note": "Read the hearing."}]
        },
        load_grounding=grounding,
    ) as (client, _, _):
        saved = submit_guide(
            client, json={"question": "Where should I read about housing?"}
        ).json()
        assert saved["status"] == "completed"
        article = saved["articles"][0]
        assert article["publication"] == (
            "Override publication" if explicit else "Configured publication"
        )
        assert article["section_links"] == [
            "https://example.com/dense#:~:text=The%20committee%20heard%20testimony%20about%20housing%20eligibility."
        ]

    with guide_client(
        db_path=selected_path, assessment=RuntimeError("No model after restart")
    ) as (client, prompts, _):
        assert client.get(f"/api/guides/{saved['guide_id']}").json() == saved
        assert (
            client.get("/api/guides").json()["guides"][0]["question"]
            == saved["question"]
        )
        assert prompts == []


def test_default_store_is_resolved_after_application_startup_loads_configuration(
    tmp_path, monkeypatch
):
    configured = tmp_path / "startup-configured.db"

    @asynccontextmanager
    async def startup():
        monkeypatch.setenv("SQLITE_DB_PATH", str(configured))
        yield None

    def unavailable(question, dependencies):
        raise RuntimeError("Model unavailable")

    app = create_app(startup=startup, session_factory=unavailable)
    with TestClient(app, base_url="http://localhost") as client:
        saved = submit_guide(
            client, json={"question": "Where should I read about housing?"}
        ).json()
    with guide_client(db_path=configured) as (client, prompts, _):
        assert client.get(f"/api/guides/{saved['guide_id']}").json() == saved
        assert prompts == []


@pytest.mark.parametrize("malformed_articles", [False, True])
def test_saved_list_reads_only_summaries_in_one_connection(
    tmp_path, monkeypatch, malformed_articles
):
    path = tmp_path / "guides.db"
    store = SQLiteGuideStore(path)
    saved = []
    for number in range(12):
        guide = store.create(f"Where should I read about housing proposal {number}?")
        saved.append(
            store.finish(
                guide.guide_id,
                guide.latest_attempt.attempt_id,
                SourceGuide(question=guide.question, status="completed"),
            )
        )
    updating = store.start_update(saved[0].guide_id)
    store.finish(
        updating.guide_id,
        updating.latest_attempt.attempt_id,
        SourceGuide(
            question=updating.question,
            status="guidance_failed",
            message="Guidance failed.",
        ),
    )

    with TestClient(
        create_app(startup=no_dependencies, guide_db_path=path),
        base_url="http://localhost",
    ) as client:
        articles = [
            {"malformed": "Not a GuideArticle"}
            if malformed_articles
            else {
                "citation": {
                    "source_article_id": "https://example.com/report",
                    "url": "https://example.com/report",
                    "title": "Housing",
                },
                "reading_direction": "PRIVATE_LARGE_CONTENT " * 10000,
            }
        ]
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.executemany(
                "UPDATE source_guides SET content_json = ? WHERE guide_id = ?",
                [
                    (
                        json.dumps(
                            {
                                "question": guide.question,
                                "status": "completed",
                                "articles": articles,
                            }
                        ),
                        guide.guide_id,
                    )
                    for guide in saved
                ],
            )

        connect = sqlite3.connect
        opened = []

        def counted_connection(*args, **kwargs):
            opened.append(args[0])
            return connect(*args, **kwargs)

        with monkeypatch.context() as patch:
            patch.setattr(sqlite3, "connect", counted_connection)
            response = client.get("/api/guides")
        assert response.status_code == 200
        rows = response.json()["guides"]
        assert [row["guide_id"] for row in rows] == [
            guide.guide_id for guide in reversed(saved)
        ]
        assert all(row["status"] == "completed" for row in rows)
        assert rows[-1]["latest_attempt"]["status"] == "failed"
        assert rows[-1]["latest_attempt"]["outcome"] == "guidance_failed"
        assert len(opened) == 1
        assert len(response.content) < 15000
        assert "articles" not in response.text
        assert "PRIVATE_LARGE_CONTENT" not in response.text
