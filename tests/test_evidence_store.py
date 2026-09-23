"""Concrete retrieval hydration reads stored Article Chunks."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from neo4j import AsyncDriver
from neo4j.exceptions import ServiceUnavailable
from test_retrieval import candidate, rewrite

from knowledge_map.adapters.evidence import EvidenceStore
from knowledge_map.core.evidence import EvidenceHydrationError
from knowledge_map.core.fusion import fuse_candidates
from knowledge_map.schemas.retrieval import (
    RetrievalBranch,
    RetrievalExecutionResult,
    RetrievalRequest,
    SkippedBranch,
    SuccessfulBranch,
)


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


def test_selected_grounding_loads_its_chunk_and_citation():
    store = EvidenceStore(
        graph_driver(
            [
                {
                    "chunk_id": "full_text",
                    "source_article_id": "https://example.com/full_text",
                    "text": "The union supports AB 1.",
                    "title": "Union position",
                    "url": "https://example.com/full_text",
                    "published_date": None,
                }
            ]
        )
    )

    async def exercise():
        grounding = await store.load_grounding(fused_candidate())
        assert grounding.chunk_id == "full_text"
        assert grounding.text == "The union supports AB 1."
        assert grounding.citation.source_article_id == "https://example.com/full_text"

    asyncio.run(exercise())


def test_graph_failures_use_the_assembly_hydration_error_contract():
    driver = graph_driver([])
    driver.session.return_value.__aenter__.return_value.run.side_effect = (
        ServiceUnavailable("private server detail")
    )
    store = EvidenceStore(driver)

    async def exercise():
        with pytest.raises(EvidenceHydrationError) as caught:
            await store.load_grounding(fused_candidate())
        assert "private server detail" not in str(caught.value)

    asyncio.run(exercise())


def test_source_article_url_primary_key_hydrates_without_a_duplicate_url_property():
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
        )
    )
    grounding = asyncio.run(store.load_grounding(fused_candidate()))
    assert str(grounding.citation.url) == "https://example.com/full_text"
