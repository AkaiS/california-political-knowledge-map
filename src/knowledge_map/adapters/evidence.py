"""Hydrate selected Article Chunks and original Stories for Evidence Assembly."""

import asyncio
import sqlite3
from contextlib import closing
from pathlib import Path

from neo4j import READ_ACCESS, AsyncDriver
from neo4j.exceptions import DriverError, Neo4jError

from knowledge_map.core.evidence import EvidenceHydrationError
from knowledge_map.schemas.retrieval import (
    FusedCandidate,
    GroundingEvidence,
    SourceArticleCitation,
)
from knowledge_map.schemas.stories import Story


class EvidenceStore:
    def __init__(
        self,
        driver: AsyncDriver,
        *,
        story_db_path: str,
        database: str = "neo4j",
    ) -> None:
        self._driver = driver
        self._story_db_path = Path(story_db_path).resolve().as_uri() + "?mode=ro"
        self._database = database

    async def load_grounding(self, candidate: FusedCandidate) -> GroundingEvidence:
        try:
            return await self._read_grounding(candidate)
        except (DriverError, Neo4jError) as error:
            raise EvidenceHydrationError(
                "Grounding Evidence could not be loaded"
            ) from error

    async def _read_grounding(self, candidate: FusedCandidate) -> GroundingEvidence:
        async with self._driver.session(
            database=self._database, default_access_mode=READ_ACCESS
        ) as session:
            result = await session.run(
                "MATCH (article:NewsArticle)-[:HAS_CHUNK]->(chunk:Chunk) "
                "WHERE chunk.id = $chunk_id AND article.id = $source_article_id "
                "RETURN DISTINCT chunk.id AS chunk_id, chunk.text AS text, "
                "article.id AS source_article_id, article.title AS title, "
                "article.url AS url, article.published_date AS published_date LIMIT 2",
                parameters={
                    "chunk_id": candidate.chunk_id,
                    "source_article_id": candidate.source_article_id,
                },
            )
            rows = await result.data()
        if len(rows) != 1:
            raise LookupError("Selected Grounding Evidence is absent or ambiguous")
        row = rows[0]
        return GroundingEvidence(
            chunk_id=row["chunk_id"],
            text=row["text"],
            citation=SourceArticleCitation(
                source_article_id=row["source_article_id"],
                title=row["title"],
                url=row["url"] or row["source_article_id"],
                published_date=row["published_date"],
            ),
        )

    async def load_story(self, citation: SourceArticleCitation) -> Story:
        try:
            return await asyncio.to_thread(self._read_story, citation.source_article_id)
        except sqlite3.Error as error:
            raise EvidenceHydrationError(
                "The original Story could not be loaded"
            ) from error

    def _read_story(self, url: str) -> Story:
        # A cancelled coroutine cannot stop SQLite's worker from waiting on a lock.
        with closing(
            sqlite3.connect(self._story_db_path, uri=True, timeout=0)
        ) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                "SELECT id, title, url, category, author, published_date, summary, "
                "content, status FROM stories WHERE url = ?",
                (url,),
            ).fetchone()
            if row is None:
                raise LookupError("The original Story is absent")
            values = dict(row)
            story_id = values.pop("id")
            links = connection.execute(
                "SELECT text, url FROM story_links WHERE story_id = ? ORDER BY id",
                (story_id,),
            ).fetchall()
            return Story.model_validate(
                {**values, "links": [dict(link) for link in links]}
            )
