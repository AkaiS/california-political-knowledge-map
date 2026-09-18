"""Concrete retrieval hydration reads the original document store."""

import asyncio
import sqlite3
from unittest.mock import AsyncMock, MagicMock

import pytest
from neo4j import AsyncDriver
from neo4j.exceptions import ServiceUnavailable
from test_retrieval import candidate, rewrite

from knowledge_map.adapters.evidence import EvidenceStore
from knowledge_map.adapters.sqlite_db import init_db, save_story
from knowledge_map.core.evidence import EvidenceHydrationError
from knowledge_map.core.fusion import fuse_candidates
from knowledge_map.schemas.retrieval import (
    RetrievalBranch,
    RetrievalExecutionResult,
    RetrievalRequest,
    SkippedBranch,
    SuccessfulBranch,
)
from knowledge_map.schemas.stories import Story


def fused_candidate():
    return fuse_candidates(
        RetrievalExecutionResult(
            request=RetrievalRequest(rewrite=rewrite()),
            outcomes=(
                SuccessfulBranch(
                    branch="full_text",
                    candidates=(candidate(RetrievalBranch.FULL_TEXT),),
                ),
                SuccessfulBranch(branch="dense", candidates=()),
                SkippedBranch(),
            ),
        )
    )[0]


def graph_driver(rows):
    driver = MagicMock(spec=AsyncDriver)
    result = AsyncMock()
    result.data.return_value = rows
    driver.session.return_value.__aenter__.return_value.run = AsyncMock(
        return_value=result
    )
    return driver


def test_selected_grounding_loads_its_citation_and_the_original_story(tmp_path):
    path = str(tmp_path / "stories.db")
    init_db(path)
    story = Story(
        url="https://example.com/full_text",
        title="Union position",
        content="The union supports AB 1.",
    )
    save_story(story, path)
    store = EvidenceStore(
        graph_driver(
            [
                {
                    "chunk_id": "full_text",
                    "source_article_id": story.url,
                    "text": "The union supports AB 1.",
                    "title": story.title,
                    "url": story.url,
                    "published_date": None,
                }
            ]
        ),
        story_db_path=path,
    )

    async def exercise():
        grounding = await store.load_grounding(fused_candidate())
        original = await store.load_story(grounding.citation)
        assert grounding.chunk_id == "full_text"
        assert grounding.citation.source_article_id == story.url
        assert original == story

    asyncio.run(exercise())


@pytest.mark.parametrize("storage", ["graph", "stories"])
def test_database_failures_use_the_assembly_hydration_error_contract(storage, tmp_path):
    driver = graph_driver([])
    driver.session.return_value.__aenter__.return_value.run.side_effect = (
        ServiceUnavailable("private server detail")
    )
    store = EvidenceStore(driver, story_db_path=str(tmp_path / "missing.db"))

    async def exercise():
        with pytest.raises(EvidenceHydrationError) as caught:
            if storage == "graph":
                await store.load_grounding(fused_candidate())
            else:
                from knowledge_map.schemas.retrieval import SourceArticleCitation

                await store.load_story(
                    SourceArticleCitation(
                        source_article_id="article",
                        title="Story",
                        url="https://example.com/story",
                    )
                )
        assert "private server detail" not in str(caught.value)
        assert not (tmp_path / "missing.db").exists()

    asyncio.run(exercise())


def test_source_article_url_primary_key_hydrates_without_a_duplicate_url_property(
    tmp_path,
):
    store = EvidenceStore(
        graph_driver(
            [
                {
                    "chunk_id": "full_text",
                    "source_article_id": "https://example.com/full_text",
                    "text": "The union supports AB 1.",
                    "title": "Union position",
                    "url": None,
                    "published_date": None,
                }
            ]
        ),
        story_db_path=str(tmp_path / "unused.db"),
    )
    grounding = asyncio.run(store.load_grounding(fused_candidate()))
    assert str(grounding.citation.url) == "https://example.com/full_text"


def test_story_lookup_uses_the_unnormalized_source_article_primary_key(tmp_path):
    from knowledge_map.schemas.retrieval import SourceArticleCitation

    path = str(tmp_path / "stories.db")
    init_db(path)
    story = Story(
        url="https://example.com",
        title="Root URL",
        content="The stored URL has no trailing slash.",
    )
    save_story(story, path)
    store = EvidenceStore(graph_driver([]), story_db_path=path)
    citation = SourceArticleCitation(
        source_article_id=story.url,
        title=story.title,
        url=story.url,
    )

    assert str(citation.url) == "https://example.com/"
    assert asyncio.run(store.load_story(citation)) == story


def test_a_locked_document_store_does_not_leave_a_worker_waiting_past_the_deadline(
    tmp_path,
):
    from knowledge_map.schemas.retrieval import SourceArticleCitation

    path = str(tmp_path / "stories.db")
    init_db(path)
    store = EvidenceStore(graph_driver([]), story_db_path=path)
    connection = sqlite3.connect(path)
    connection.execute("BEGIN EXCLUSIVE")

    async def exercise():
        with pytest.raises(EvidenceHydrationError):
            await asyncio.wait_for(
                store.load_story(
                    SourceArticleCitation(
                        source_article_id="article",
                        title="Story",
                        url="https://example.com/story",
                    )
                ),
                timeout=0.2,
            )

    try:
        asyncio.run(exercise())
    finally:
        connection.rollback()
        connection.close()
