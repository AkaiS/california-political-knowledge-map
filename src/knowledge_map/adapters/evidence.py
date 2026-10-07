"""Hydrate selected Article Chunks for Evidence Assembly."""

from neo4j import READ_ACCESS, AsyncDriver
from neo4j.exceptions import DriverError, Neo4jError

from knowledge_map.core.evidence import EvidenceHydrationError
from knowledge_map.schemas.retrieval import (
    FusedCandidate,
    GroundingEvidence,
    SourceArticleCitation,
)


class EvidenceStore:
    def __init__(
        self,
        driver: AsyncDriver,
        *,
        database: str = "neo4j",
    ) -> None:
        self._driver = driver
        self._database = database

    async def load_grounding(self, candidate: FusedCandidate) -> GroundingEvidence:
        return await self.load_chunk(
            chunk_id=candidate.chunk_id, source_article_id=candidate.source_article_id
        )

    async def load_chunk(
        self, *, chunk_id: str, source_article_id: str
    ) -> GroundingEvidence:
        try:
            return await self._read_grounding(
                chunk_id=chunk_id, source_article_id=source_article_id
            )
        except (DriverError, Neo4jError) as error:
            raise EvidenceHydrationError(
                "Grounding Evidence could not be loaded"
            ) from error

    async def _read_grounding(
        self, *, chunk_id: str, source_article_id: str
    ) -> GroundingEvidence:
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
                    "chunk_id": chunk_id,
                    "source_article_id": source_article_id,
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
