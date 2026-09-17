"""Article Chunk vector retrieval from an approved Query Rewrite."""

import asyncio
import logging
import math
from collections.abc import Sequence
from typing import Literal, LiteralString

from neo4j import READ_ACCESS, AsyncDriver, Query
from neo4j.exceptions import DriverError, Neo4jError
from pydantic_ai import Embedder
from pydantic_ai.exceptions import ModelAPIError

from knowledge_map.adapters.embedding import get_embedding_embedder
from knowledge_map.config import settings
from knowledge_map.schemas.retrieval import (
    BranchCandidate,
    BranchRanking,
    BranchScore,
    FailedBranch,
    GraphNodeReference,
    RetrievalBranch,
    RetrievalFailureLog,
    RetrievalRequest,
    RetrievalRoute,
    SuccessfulBranch,
)

logger = logging.getLogger(__name__)


def _failed(diagnostic: RetrievalFailureLog) -> FailedBranch:
    logger.warning(
        "retrieval_branch_failed",
        extra={
            "event": "retrieval_branch_failed",
            **diagnostic.model_dump(),
            "deadline_exhausted": diagnostic.deadline_exhausted,
        },
    )
    return FailedBranch(branch=RetrievalBranch.DENSE)


def _query(text: LiteralString, deadline: float) -> Query:
    remaining = deadline - asyncio.get_running_loop().time()
    if remaining <= 0:
        raise TimeoutError
    return Query(text, timeout=remaining)


class Neo4jDenseRetriever:
    def __init__(
        self,
        driver: AsyncDriver,
        embedder: Embedder | None = None,
        *,
        candidate_limit: int,
        database: str = "neo4j",
    ) -> None:
        if type(candidate_limit) is not int or candidate_limit <= 0:
            raise ValueError("candidate_limit must be a positive integer")
        self.driver = driver
        self.embedder = embedder or get_embedding_embedder()
        self.candidate_limit = candidate_limit
        self.database = database

    async def retrieve(
        self, request: RetrievalRequest, *, deadline: float
    ) -> SuccessfulBranch | FailedBranch:
        attempts = 0
        stage: Literal["preparation", "execution"] = "preparation"
        try:
            if deadline <= asyncio.get_running_loop().time():
                raise TimeoutError
            async with asyncio.timeout_at(deadline):
                attempts = 1
                embedding = await self.embedder.embed_query(request.rewrite.question)
                if len(embedding.embeddings) != 1:
                    raise ValueError("Expected one query embedding")
                vector = embedding.embeddings[0]
                if (
                    len(vector) != settings.embedding.dimension
                    or not all(math.isfinite(value) for value in vector)
                    or not any(vector)
                ):
                    raise ValueError(
                        "Query embedding is incompatible with the chunk index"
                    )
                stage = "execution"
                outcome = await self._search(vector, deadline=deadline)
                if deadline <= asyncio.get_running_loop().time():
                    raise TimeoutError
                return outcome
        except TimeoutError:
            return _failed(
                RetrievalFailureLog(
                    branch=RetrievalBranch.DENSE,
                    stage="deadline",
                    failure_kind="deadline_exhausted",
                    attempts_consumed=attempts,
                    safe_diagnostic="The retrieval deadline expired during dense search.",
                )
            )
        except ModelAPIError:
            return _failed(
                RetrievalFailureLog(
                    branch=RetrievalBranch.DENSE,
                    stage="preparation",
                    failure_kind="transport",
                    attempts_consumed=1,
                    safe_diagnostic="The embedding provider could not embed the approved question.",
                )
            )
        except (TypeError, ValueError):
            return _failed(
                RetrievalFailureLog(
                    branch=RetrievalBranch.DENSE,
                    stage=stage,
                    failure_kind="validation",
                    attempts_consumed=1,
                    safe_diagnostic=(
                        "The embedding provider returned an invalid query embedding."
                        if stage == "preparation"
                        else "Stored dense matches cannot form valid chunk candidates."
                    ),
                )
            )

    async def _search(
        self, embedding: Sequence[float], *, deadline: float
    ) -> SuccessfulBranch | FailedBranch:
        stage: Literal["index", "execution"] = "index"
        try:
            async with self.driver.session(
                database=self.database, default_access_mode=READ_ACCESS
            ) as session:
                result = await session.run(
                    _query(
                        "SHOW INDEXES YIELD name, type, state, labelsOrTypes, properties, options "
                        "WHERE name = $name "
                        "RETURN name, type, state, labelsOrTypes, properties, options",
                        deadline,
                    ),
                    name="chunk_vector_index",
                )
                indexes = await result.data()
                index = indexes[0] if indexes else None
                if (
                    index is None
                    or index["type"] != "VECTOR"
                    or index["state"] != "ONLINE"
                    or index["labelsOrTypes"] != ["Chunk"]
                    or index["properties"] != ["embedding"]
                    or index["options"]["indexConfig"].get("vector.dimensions")
                    != settings.embedding.dimension
                    or index["options"]["indexConfig"]
                    .get("vector.similarity_function", "")
                    .lower()
                    != "cosine"
                ):
                    return _failed(
                        RetrievalFailureLog(
                            branch=RetrievalBranch.DENSE,
                            stage="index",
                            failure_kind="index_unavailable",
                            attempts_consumed=1,
                            safe_diagnostic="The Article Chunk vector index is missing, offline, or incompatible.",
                        )
                    )
                stage = "execution"
                result = await session.run(
                    _query(
                        "CALL db.index.vector.queryNodes($index, $limit, $embedding) "
                        "YIELD node, score "
                        "MATCH (node)<-[:HAS_CHUNK]-(a:NewsArticle) "
                        "RETURN DISTINCT node.id AS chunk_id, a.id AS source_article_id, "
                        "elementId(node) AS element_id, score "
                        "ORDER BY score DESC, chunk_id, source_article_id, element_id "
                        "LIMIT $limit",
                        deadline,
                    ),
                    parameters={
                        "index": "chunk_vector_index",
                        "limit": self.candidate_limit,
                        "embedding": list(embedding),
                    },
                )
                rows = await result.data()
        except (DriverError, Neo4jError) as error:
            if isinstance(error, Neo4jError):
                if ".Transaction.TransactionTimedOut" in error.code:
                    raise TimeoutError from None
                if error.code.endswith((".IndexNotFound", ".IndexNotApplicable")):
                    return _failed(
                        RetrievalFailureLog(
                            branch=RetrievalBranch.DENSE,
                            stage="index",
                            failure_kind="index_unavailable",
                            attempts_consumed=1,
                            safe_diagnostic="The Article Chunk vector index became unavailable during search.",
                        )
                    )
            return _failed(
                RetrievalFailureLog(
                    branch=RetrievalBranch.DENSE,
                    stage=stage,
                    failure_kind="database",
                    attempts_consumed=1,
                    safe_diagnostic="Neo4j could not complete the dense search.",
                )
            )

        return SuccessfulBranch(
            branch=RetrievalBranch.DENSE,
            candidates=tuple(
                BranchCandidate(
                    chunk_id=row["chunk_id"],
                    source_article_id=row["source_article_id"],
                    ranking=BranchRanking(
                        branch=RetrievalBranch.DENSE,
                        rank=rank,
                        score=BranchScore(row["score"]),
                    ),
                    routes=(
                        RetrievalRoute(
                            kind="chunk_embedding",
                            matched_field="embedding",
                            entry_node=GraphNodeReference(
                                id=row["chunk_id"],
                                label="Chunk",
                                element_id=row["element_id"],
                            ),
                        ),
                    ),
                )
                for rank, row in enumerate(rows, 1)
            ),
        )
