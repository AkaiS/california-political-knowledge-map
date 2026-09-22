import asyncio
import logging

import pytest
from neo4j import AsyncGraphDatabase

from knowledge_map.adapters.full_text import Neo4jFullTextRetriever
from knowledge_map.schemas.query_preparation import QueryRewrite, QuestionAssessment
from knowledge_map.schemas.retrieval import (
    FailedBranch,
    RetrievalRequest,
    SuccessfulBranch,
)


def test_missing_index_is_failure_even_when_question_would_match_nothing(
    neo4j_schema_uri, caplog
):
    async def run():
        async with AsyncGraphDatabase.driver(neo4j_schema_uri) as driver:
            retriever = Neo4jFullTextRetriever(driver)
            await driver.execute_query("DROP INDEX article_title_fulltext_index")
            return await retriever.retrieve(
                RetrievalRequest(
                    rewrite=QueryRewrite(
                        question="Unmatchedquestion",
                        relational=False,
                        assessment=QuestionAssessment(status="allowed"),
                    )
                ),
                deadline=asyncio.get_running_loop().time() + 15,
            )

    with caplog.at_level(logging.WARNING):
        outcome = asyncio.run(run())
    assert outcome == FailedBranch(branch="full_text")
    (record,) = [
        record
        for record in caplog.records
        if getattr(record, "event", None) == "retrieval_branch_failed"
    ]
    assert (record.branch, record.stage, record.failure_kind) == (
        "full_text",
        "index",
        "index_unavailable",
    )


def test_schema_installs_accepted_indexes_without_uniqueness_or_removing_defaults(
    neo4j_schema_uri,
):
    async def run():
        async with AsyncGraphDatabase.driver(neo4j_schema_uri) as driver:
            records, _, _ = await driver.execute_query("SHOW INDEXES")
            full_text = {
                row["name"]: (set(row["labelsOrTypes"]), row["properties"])
                for row in records
                if row["type"] == "FULLTEXT"
            }
            assert full_text == {
                "entity_name_fulltext_index": (
                    {
                        "Bill",
                        "Campaign",
                        "Committee",
                        "LegislativeEvent",
                        "Organization",
                        "PolicyArea",
                        "Politician",
                        "Prop",
                    },
                    ["name"],
                ),
                "article_title_fulltext_index": ({"NewsArticle"}, ["title"]),
                "chunk_text_fulltext_index": ({"Chunk"}, ["text"]),
            }
            ranges = [row for row in records if row["type"] == "RANGE"]
            assert {tuple(row["labelsOrTypes"]) for row in ranges} == {
                (label,)
                for label in (
                    "Bill",
                    "Campaign",
                    "Committee",
                    "LegislativeEvent",
                    "Organization",
                    "PolicyArea",
                    "Politician",
                    "Prop",
                    "NewsArticle",
                    "Chunk",
                )
            }
            assert all(
                row["properties"] == ["id"]
                and row["owningConstraint"] is None
                and row["state"] == "ONLINE"
                for row in ranges
            )
            (vector,) = [row for row in records if row["type"] == "VECTOR"]
            assert (
                vector["name"],
                vector["labelsOrTypes"],
                vector["properties"],
                vector["state"],
            ) == (
                "chunk_vector_index",
                ["Chunk"],
                ["embedding"],
                "ONLINE",
            )
            assert len([row for row in records if row["type"] == "LOOKUP"]) == 2

    asyncio.run(run())


def test_retains_every_route_and_ambiguous_entity_identity_with_local_scores(
    neo4j_schema_uri,
):
    async def run():
        async with AsyncGraphDatabase.driver(neo4j_schema_uri) as driver:
            retriever = Neo4jFullTextRetriever(driver)
            await driver.execute_query("""
                CREATE (a:NewsArticle {id: 'source-shared', title: 'Eldervoss'})
                CREATE (c:Chunk {id: 'chunk-shared', text: 'Eldervoss'})
                CREATE (a)-[:HAS_CHUNK]->(c)
                CREATE (e1:Bill {id: 'bill', name: 'Eldervoss'})-[:MENTIONED_IN]->(c)
                CREATE (e2:Campaign {id: 'campaign', name: 'Eldervoss'})-[:MENTIONED_IN]->(c)
                CREATE (e3:Committee {id: 'committee', name: 'Eldervoss'})-[:MENTIONED_IN]->(c)
                CREATE (e4:LegislativeEvent {id: 'event', name: 'Eldervoss'})-[:MENTIONED_IN]->(c)
                CREATE (e5:Organization {id: 'duplicate', name: 'Eldervoss'})-[:MENTIONED_IN]->(c)
                CREATE (e6:Organization {id: 'duplicate', name: 'Eldervoss'})-[:MENTIONED_IN]->(c)
                CREATE (e7:Politician {id: 'politician', name: 'Eldervoss'})-[:MENTIONED_IN]->(c)
                CREATE (e8:Prop {id: 'prop', name: 'Eldervoss'})-[:MENTIONED_IN]->(c)
                CREATE (a)-[:DISCUSSES_TOPIC]->(:PolicyArea {id: 'area', name: 'Eldervoss'})
            """)
            request = RetrievalRequest(
                rewrite=QueryRewrite(
                    question='Eldervoss: " OR *',
                    relational=False,
                    assessment=QuestionAssessment(status="allowed"),
                )
            )
            outcome = await retriever.retrieve(
                request, deadline=asyncio.get_running_loop().time() + 15
            )
            assert isinstance(outcome, SuccessfulBranch)
            assert len(outcome.candidates) == 11
            assert {c.chunk_id for c in outcome.candidates} == {"chunk-shared"}
            assert [c.ranking.rank for c in outcome.candidates] == list(range(1, 12))
            assert {c.routes[0].entry_node.label for c in outcome.candidates} == {
                "Bill",
                "Campaign",
                "Committee",
                "LegislativeEvent",
                "Organization",
                "PolicyArea",
                "Politician",
                "Prop",
                "NewsArticle",
                "Chunk",
            }
            organizations = [
                c.routes[0].entry_node
                for c in outcome.candidates
                if c.routes[0].entry_node.label == "Organization"
            ]
            assert {node.id for node in organizations} == {"duplicate"}
            assert len({node.element_id for node in organizations}) == 2
            for kind in ("entity_name", "article_title", "chunk_text"):
                scores = [
                    c.ranking.score.root
                    for c in outcome.candidates
                    if c.routes[0].kind == kind and c.ranking.score is not None
                ]
                assert scores and all(score > 0 for score in scores)
                assert scores == sorted(scores, reverse=True)
            assert all(not r.graph_claims for c in outcome.candidates for r in c.routes)

    asyncio.run(run())


def test_completed_search_without_grounded_matches_is_successful_empty(
    neo4j_schema_uri,
):
    async def run():
        async with AsyncGraphDatabase.driver(neo4j_schema_uri) as driver:
            retriever = Neo4jFullTextRetriever(driver)
            await driver.execute_query("""
                CREATE (:Politician {id: 'orphan', name: 'Orphanessa'})
                CREATE (:NewsArticle {id: 'orphan-source', title: 'Orphanessa'})
            """)
            for question in ("Noresultalium", "Orphanessa"):
                outcome = await retriever.retrieve(
                    RetrievalRequest(
                        rewrite=QueryRewrite(
                            question=question,
                            relational=False,
                            assessment=QuestionAssessment(status="allowed"),
                        )
                    ),
                    deadline=asyncio.get_running_loop().time() + 15,
                )
                assert outcome == SuccessfulBranch(branch="full_text", candidates=())

    asyncio.run(run())


def test_policy_area_name_reaches_article_level_grounding_without_a_graph_claim(
    neo4j_schema_uri,
):
    async def run():
        async with AsyncGraphDatabase.driver(neo4j_schema_uri) as driver:
            retriever = Neo4jFullTextRetriever(driver)
            await driver.execute_query("""
                CREATE (a:NewsArticle {id: 'source-topic', title: 'Policy report'})
                CREATE (c:Chunk {id: 'chunk-topic', text: 'An article passage'})
                CREATE (p:PolicyArea {id: 'policy', name: 'Neltraven'})
                CREATE (a)-[:HAS_CHUNK]->(c)
                CREATE (a)-[:DISCUSSES_TOPIC {articles: ['source-topic']}]->(p)
            """)
            outcome = await retriever.retrieve(
                RetrievalRequest(
                    rewrite=QueryRewrite(
                        question="Neltraven",
                        relational=False,
                        assessment=QuestionAssessment(status="allowed"),
                    )
                ),
                deadline=asyncio.get_running_loop().time() + 15,
            )
            assert isinstance(outcome, SuccessfulBranch)
            (candidate,) = outcome.candidates
            assert (candidate.chunk_id, candidate.source_article_id) == (
                "chunk-topic",
                "source-topic",
            )
            (route,) = candidate.routes
            assert route.entry_node.label == "PolicyArea"
            assert route.graph_claims == ()

    asyncio.run(run())


@pytest.mark.parametrize(
    "field,word,kind,label",
    [
        ("title", "Vantrellis", "article_title", "NewsArticle"),
        ("text", "Lorvendel", "chunk_text", "Chunk"),
    ],
)
def test_article_title_and_chunk_text_matches_reach_source_chunks(
    neo4j_schema_uri,
    field,
    word,
    kind,
    label,
):
    async def run():
        async with AsyncGraphDatabase.driver(neo4j_schema_uri) as driver:
            retriever = Neo4jFullTextRetriever(driver)
            await driver.execute_query(
                """
                CREATE (a:NewsArticle {id: $article, title: $title})
                CREATE (c:Chunk {id: $chunk, text: $text})
                CREATE (a)-[:HAS_CHUNK]->(c)
            """,
                article=f"source-{field}",
                chunk=f"chunk-{field}",
                title=word if field == "title" else "A source",
                text=word if field == "text" else "An unrelated passage",
            )
            request = RetrievalRequest(
                rewrite=QueryRewrite(
                    question=word,
                    relational=False,
                    assessment=QuestionAssessment(status="allowed"),
                )
            )
            outcome = await retriever.retrieve(
                request, deadline=asyncio.get_running_loop().time() + 15
            )
            assert isinstance(outcome, SuccessfulBranch)
            (candidate,) = outcome.candidates
            assert (candidate.chunk_id, candidate.source_article_id) == (
                f"chunk-{field}",
                f"source-{field}",
            )
            assert candidate.ranking.score is not None
            assert candidate.ranking.score.root > 0
            (route,) = candidate.routes
            assert (route.kind, route.matched_field, route.entry_node.label) == (
                kind,
                field,
                label,
            )
            assert route.graph_claims == ()

    asyncio.run(run())


def test_entity_name_match_reaches_grounding_evidence_without_claiming_support(
    neo4j_schema_uri,
):
    async def run():
        async with AsyncGraphDatabase.driver(neo4j_schema_uri) as driver:
            retriever = Neo4jFullTextRetriever(driver)
            await driver.execute_query("""
                CREATE (a:NewsArticle {id: 'source-name', title: 'A biography'})
                CREATE (c:Chunk {id: 'chunk-name', text: 'A committee biography.'})
                CREATE (e:Politician {id: 'actor', name: 'Zantrivelle'})
                CREATE (a)-[:HAS_CHUNK]->(c)
                CREATE (e)-[:MENTIONED_IN]->(c)
            """)
            request = RetrievalRequest(
                rewrite=QueryRewrite(
                    question="Find Zantrivelle",
                    relational=False,
                    assessment=QuestionAssessment(status="allowed"),
                )
            )
            outcome = await retriever.retrieve(
                request, deadline=asyncio.get_running_loop().time() + 15
            )
            assert isinstance(outcome, SuccessfulBranch)
            assert len(outcome.candidates) == 1
            candidate = outcome.candidates[0]
            assert (candidate.chunk_id, candidate.source_article_id) == (
                "chunk-name",
                "source-name",
            )
            assert candidate.ranking.branch == "full_text"
            assert candidate.ranking.rank == 1
            assert candidate.ranking.score is not None
            assert candidate.ranking.score.root > 0
            (route,) = candidate.routes
            assert (route.kind, route.matched_field) == ("entity_name", "name")
            assert (route.entry_node.id, route.entry_node.label) == (
                "actor",
                "Politician",
            )
            assert route.entry_node.element_id
            assert route.graph_claims == ()

    asyncio.run(run())
