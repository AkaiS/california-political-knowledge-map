"""Full-text discovery of Article Chunks from an approved Query Rewrite."""

import asyncio
import logging
import re
from dataclasses import dataclass
from itertools import zip_longest
from typing import Literal, LiteralString

from neo4j import READ_ACCESS, AsyncDriver, Query
from neo4j.exceptions import DriverError, Neo4jError
from pydantic import ValidationError

from knowledge_map.schemas.query_preparation import QueryRewrite
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
    return FailedBranch(branch=RetrievalBranch.FULL_TEXT)


def _query(text: LiteralString, deadline: float) -> Query:
    remaining = deadline - asyncio.get_running_loop().time()
    if remaining <= 0:
        raise TimeoutError
    return Query(text, timeout=remaining)


_STOP_WORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "how",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "s",
        "that",
        "the",
        "their",
        "these",
        "this",
        "to",
        "was",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "with",
    ]
)


def extract_full_text_keywords(rewrite: QueryRewrite) -> tuple[str, ...]:
    """Keep distinct Unicode words and numbers in their first-occurrence order."""
    return tuple(
        dict.fromkeys(
            word
            for word in re.findall(r"[^\W_]+", rewrite.question.casefold())
            if word not in _STOP_WORDS
        )
    )


_ENTITY_LABELS: tuple[LiteralString, ...] = (
    "Bill",
    "Campaign",
    "Committee",
    "LegislativeEvent",
    "Organization",
    "PolicyArea",
    "Politician",
    "Prop",
)
type _MatchedField = Literal["name", "title", "text"]
type _RouteKind = Literal["entity_name", "article_title", "chunk_text"]


@dataclass(frozen=True)
class _FullTextChannel:
    index_name: LiteralString
    labels: tuple[LiteralString, ...]
    matched_field: _MatchedField
    search_path: LiteralString
    route_kind: _RouteKind


_FULL_TEXT_CHANNELS = (
    _FullTextChannel(
        index_name="entity_name_fulltext_index",
        labels=_ENTITY_LABELS,
        matched_field="name",
        search_path="""
        CALL (node) {
            MATCH (node)-[:MENTIONED_IN]->(c:Chunk)<-[:HAS_CHUNK]-(a:NewsArticle)
            RETURN c, a
            UNION
            MATCH (node:PolicyArea)<-[:DISCUSSES_TOPIC]-(a:NewsArticle)-[:HAS_CHUNK]->(c:Chunk)
            RETURN c, a
        }
    """,
        route_kind="entity_name",
    ),
    _FullTextChannel(
        index_name="article_title_fulltext_index",
        labels=("NewsArticle",),
        matched_field="title",
        search_path=(
            "MATCH (node)-[:HAS_CHUNK]->(c:Chunk) WITH node, score, c, node AS a"
        ),
        route_kind="article_title",
    ),
    _FullTextChannel(
        index_name="chunk_text_fulltext_index",
        labels=("Chunk",),
        matched_field="text",
        search_path=(
            "MATCH (node)<-[:HAS_CHUNK]-(a:NewsArticle) WITH node, score, a, node AS c"
        ),
        route_kind="chunk_text",
    ),
)


class Neo4jFullTextRetriever:
    def __init__(self, driver: AsyncDriver, *, database: str = "neo4j") -> None:
        self.driver = driver
        self.database = database

    async def retrieve(
        self,
        request: RetrievalRequest,
        *,
        deadline: float,
        keywords: tuple[str, ...] | None = None,
    ) -> SuccessfulBranch | FailedBranch:
        attempts = 0
        try:
            if deadline <= asyncio.get_running_loop().time():
                raise TimeoutError
            async with asyncio.timeout_at(deadline):
                attempts = 1
                outcome = await self._retrieve(
                    request, deadline=deadline, keywords=keywords
                )
                if deadline <= asyncio.get_running_loop().time():
                    raise TimeoutError
                return outcome
        except TimeoutError:
            return _failed(
                RetrievalFailureLog(
                    branch=RetrievalBranch.FULL_TEXT,
                    stage="deadline",
                    failure_kind="deadline_exhausted",
                    attempts_consumed=attempts,
                    safe_diagnostic="The retrieval deadline expired during full-text search.",
                )
            )
        except ValidationError:
            return _failed(
                RetrievalFailureLog(
                    branch=RetrievalBranch.FULL_TEXT,
                    stage="execution",
                    failure_kind="validation",
                    attempts_consumed=1,
                    safe_diagnostic="Stored full-text matches cannot form valid chunk candidates.",
                )
            )

    async def _retrieve(
        self,
        request: RetrievalRequest,
        *,
        deadline: float,
        keywords: tuple[str, ...] | None,
    ) -> SuccessfulBranch | FailedBranch:
        if keywords is None:
            keywords = extract_full_text_keywords(request.rewrite)
        if not keywords:
            return _failed(
                RetrievalFailureLog(
                    branch=RetrievalBranch.FULL_TEXT,
                    stage="preparation",
                    failure_kind="validation",
                    attempts_consumed=0,
                    safe_diagnostic="The approved question contains no searchable terms.",
                )
            )
        query = " OR ".join(f'"{word}"' for word in keywords)
        matches = []
        stage: Literal["index", "execution"] = "index"
        try:
            async with self.driver.session(
                database=self.database, default_access_mode=READ_ACCESS
            ) as session:
                result = await session.run(
                    _query(
                        "SHOW INDEXES YIELD name, type, state, labelsOrTypes, properties "
                        "WHERE name IN $names RETURN name, type, state, labelsOrTypes, properties",
                        deadline,
                    ),
                    names=[channel.index_name for channel in _FULL_TEXT_CHANNELS],
                )
                indexes = {row["name"]: row for row in await result.data()}
                for channel in _FULL_TEXT_CHANNELS:
                    index = indexes.get(channel.index_name)
                    if (
                        index is None
                        or index["type"] != "FULLTEXT"
                        or index["state"] != "ONLINE"
                        or set(index["labelsOrTypes"]) != set(channel.labels)
                        or index["properties"] != [channel.matched_field]
                    ):
                        return _failed(
                            RetrievalFailureLog(
                                branch=RetrievalBranch.FULL_TEXT,
                                stage="index",
                                failure_kind="index_unavailable",
                                attempts_consumed=1,
                                safe_diagnostic="A required full-text index is missing, offline, or incompatible.",
                            )
                        )
                stage = "execution"
                for channel in _FULL_TEXT_CHANNELS:
                    result = await session.run(
                        _query(
                            "CALL db.index.fulltext.queryNodes($index, $query) YIELD node, score "
                            + channel.search_path
                            + " "
                            "RETURN DISTINCT c.id AS chunk_id, a.id AS source_article_id, "
                            "node.id AS entry_id, labels(node) AS labels, "
                            "elementId(node) AS element_id, score "
                            "ORDER BY score DESC, chunk_id, entry_id, element_id",
                            deadline,
                        ),
                        parameters={"index": channel.index_name, "query": query},
                    )
                    matches.append([(channel, row) for row in await result.data()])
        except (DriverError, Neo4jError) as error:
            if isinstance(error, Neo4jError):
                if ".Transaction.TransactionTimedOut" in error.code:
                    raise TimeoutError from None
                if error.code.endswith((".IndexNotFound", ".IndexNotApplicable")):
                    return _failed(
                        RetrievalFailureLog(
                            branch=RetrievalBranch.FULL_TEXT,
                            stage="index",
                            failure_kind="index_unavailable",
                            attempts_consumed=1,
                            safe_diagnostic="A full-text index became unavailable during search.",
                        )
                    )
            return _failed(
                RetrievalFailureLog(
                    branch=RetrievalBranch.FULL_TEXT,
                    stage=stage,
                    failure_kind="database",
                    attempts_consumed=1,
                    safe_diagnostic="Neo4j could not complete the full-text search.",
                )
            )
        rows = [match for group in zip_longest(*matches) for match in group if match]
        return SuccessfulBranch(
            branch=RetrievalBranch.FULL_TEXT,
            candidates=tuple(
                BranchCandidate(
                    chunk_id=row["chunk_id"],
                    source_article_id=row["source_article_id"],
                    ranking=BranchRanking(
                        branch=RetrievalBranch.FULL_TEXT,
                        rank=rank,
                        score=BranchScore(row["score"]),
                    ),
                    routes=(
                        RetrievalRoute.model_validate(
                            {
                                "kind": channel.route_kind,
                                "matched_field": channel.matched_field,
                                "entry_node": GraphNodeReference(
                                    id=row["entry_id"],
                                    label=next(
                                        label
                                        for label in (
                                            *_ENTITY_LABELS,
                                            "NewsArticle",
                                            "Chunk",
                                        )
                                        if label in row["labels"]
                                    ),
                                    element_id=row["element_id"],
                                ),
                            }
                        ),
                    ),
                )
                for rank, (channel, row) in enumerate(rows, 1)
            ),
        )
