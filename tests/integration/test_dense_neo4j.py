import asyncio
import json
import logging

import httpx
import pytest
from neo4j import AsyncGraphDatabase, GraphDatabase
from pydantic_ai import Embedder
from pydantic_ai.embeddings.test import TestEmbeddingModel

from knowledge_map.adapters.dense import Neo4jDenseRetriever
from knowledge_map.adapters.embedding import get_embedding_embedder
from knowledge_map.schemas.query_preparation import QueryRewrite, QuestionAssessment
from knowledge_map.schemas.retrieval import (
    FailedBranch,
    RetrievalRequest,
    SuccessfulBranch,
)


@pytest.fixture
def dense_neo4j_uri(neo4j_schema_uri):
    with GraphDatabase.driver(neo4j_schema_uri) as driver:
        driver.execute_query("MATCH (n) DETACH DELETE n")
    return neo4j_schema_uri


def test_approved_rewrite_finds_ranked_chunks_without_extracted_relationships(
    dense_neo4j_uri,
):
    question = "Which organizations supported SB 623?"

    def embed(request):
        assert json.loads(request.content)["input"] == [question]
        return httpx.Response(
            200,
            json={
                "object": "list",
                "model": "embeddinggemma",
                "data": [
                    {
                        "object": "embedding",
                        "index": 0,
                        "embedding": [1.0] + [0.0] * 767,
                    }
                ],
                "usage": {"prompt_tokens": 8, "total_tokens": 8},
            },
        )

    async def run():
        async with AsyncGraphDatabase.driver(dense_neo4j_uri) as driver:
            await driver.execute_query(
                """
                UNWIND $chunks AS chunk
                CREATE (a:NewsArticle {id: chunk.article})
                CREATE (c:Chunk {id: chunk.id, text: 'Unextracted reporting', embedding: chunk.embedding})
                CREATE (a)-[:HAS_CHUNK]->(c)
                """,
                chunks=[
                    {
                        "id": "orthogonal",
                        "article": "article-other",
                        "embedding": [0.0, 1.0] + [0.0] * 766,
                    },
                    {
                        "id": "near",
                        "article": "article-near",
                        "embedding": [0.6, 0.8] + [0.0] * 766,
                    },
                    {
                        "id": "aligned",
                        "article": "article-aligned",
                        "embedding": [1.0] + [0.0] * 767,
                    },
                ],
            )
            retriever = Neo4jDenseRetriever(
                driver,
                get_embedding_embedder(transport=httpx.MockTransport(embed)),
                candidate_limit=2,
            )
            outcome = await retriever.retrieve(
                RetrievalRequest(
                    rewrite=QueryRewrite(
                        question=question,
                        relational=True,
                        assessment=QuestionAssessment(status="allowed"),
                    )
                ),
                deadline=asyncio.get_running_loop().time() + 15,
            )
            assert isinstance(outcome, SuccessfulBranch)
            assert outcome.branch == "dense"
            assert [
                (
                    candidate.chunk_id,
                    candidate.source_article_id,
                    candidate.ranking.rank,
                )
                for candidate in outcome.candidates
            ] == [("aligned", "article-aligned", 1), ("near", "article-near", 2)]
            assert [
                candidate.ranking.score.root
                for candidate in outcome.candidates
                if candidate.ranking.score is not None
            ] == pytest.approx([1.0, 0.8], abs=0.01)
            for candidate in outcome.candidates:
                assert candidate.ranking.branch == "dense"
                (route,) = candidate.routes
                assert (route.kind, route.matched_field) == (
                    "chunk_embedding",
                    "embedding",
                )
                assert (route.entry_node.id, route.entry_node.label) == (
                    candidate.chunk_id,
                    "Chunk",
                )
                assert route.entry_node.element_id
                assert route.graph_claims == ()

    asyncio.run(run())


def test_empty_vector_search_succeeds_but_missing_index_fails(dense_neo4j_uri, caplog):
    async def run():
        async with AsyncGraphDatabase.driver(dense_neo4j_uri) as driver:
            retriever = Neo4jDenseRetriever(
                driver, Embedder(TestEmbeddingModel(dimensions=768)), candidate_limit=5
            )
            request = RetrievalRequest(
                rewrite=QueryRewrite(
                    question="Find reporting about housing.",
                    relational=False,
                    assessment=QuestionAssessment(status="allowed"),
                )
            )
            outcome = await retriever.retrieve(
                request, deadline=asyncio.get_running_loop().time() + 15
            )
            assert outcome == SuccessfulBranch(branch="dense", candidates=())
            await driver.execute_query("DROP INDEX chunk_vector_index")
            outcome = await retriever.retrieve(
                request, deadline=asyncio.get_running_loop().time() + 15
            )
            assert outcome == FailedBranch(branch="dense")

    with caplog.at_level(logging.WARNING):
        asyncio.run(run())
    (record,) = [
        r
        for r in caplog.records
        if getattr(r, "event", None) == "retrieval_branch_failed"
    ]
    assert (record.branch, record.stage, record.failure_kind) == (
        "dense",
        "index",
        "index_unavailable",
    )
