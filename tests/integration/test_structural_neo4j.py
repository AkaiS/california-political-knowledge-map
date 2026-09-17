import asyncio
import logging

import pytest
from neo4j import AsyncGraphDatabase
from structural_support import (
    approved_request,
    entity_outputs,
    relationship_outputs,
    scripted_agents,
)

from knowledge_map.adapters.structural import Neo4jStructuralRetriever
from knowledge_map.schemas.retrieval import FailedBranch, SuccessfulBranch


def test_entity_lookup_hydrates_grounding_and_source_article(disposable_neo4j_uri):
    async def run():
        async with AsyncGraphDatabase.driver(disposable_neo4j_uri) as driver:
            await driver.execute_query("""
                CREATE (a:NewsArticle {id: 'structural-source', title: 'Housing debate',
                    url: 'https://example.org/housing', published_date: '2026-07-01'})
                CREATE (c:Chunk {id: 'structural-chunk', index: 0, text: 'Ada Vale discussed housing.'})
                CREATE (a)-[:HAS_CHUNK]->(c)
                CREATE (:Politician {id: 'Politician:ada-vale', name: 'Ada Vale'})-[:MENTIONED_IN]->(c)
            """)
            outcome = await Neo4jStructuralRetriever(
                driver, agents=scripted_agents()
            ).retrieve(
                approved_request(), deadline=asyncio.get_running_loop().time() + 15
            )
            assert isinstance(outcome, SuccessfulBranch)
            (candidate,) = outcome.candidates
            assert (
                candidate.chunk_id,
                candidate.source_article_id,
                candidate.ranking.rank,
            ) == ("structural-chunk", "structural-source", 1)
            assert candidate.ranking.branch == "structural"
            assert candidate.grounding is not None
            assert candidate.grounding.text == "Ada Vale discussed housing."
            assert candidate.grounding.citation.title == "Housing debate"
            assert (
                str(candidate.grounding.citation.url) == "https://example.org/housing"
            )
            assert candidate.grounding.citation.published_date == "2026-07-01"
            assert candidate.routes[0].entry_node.id == "Politician:ada-vale"
            assert candidate.routes[0].entry_node.element_id
            assert candidate.routes[0].graph_claims == ()

    asyncio.run(run())


@pytest.mark.parametrize(
    "property,value", [("name", "Senate Bill 00947"), ("id", "Bill:2025-2026:sb-947")]
)
def test_bill_lookup_preserves_duplicate_internal_identities(
    disposable_neo4j_uri, property, value
):
    async def run():
        async with AsyncGraphDatabase.driver(disposable_neo4j_uri) as driver:
            # Use the production Source Article identity, its URL, with no separate url property.
            await driver.execute_query("""
                MERGE (a:NewsArticle {id: 'https://example.org/duplicate-bills'})
                SET a.title = 'Bill identities'
                MERGE (c:Chunk {id: 'duplicate-bill-chunk', text: 'The bill is Senate Bill 947.'})
                MERGE (a)-[:HAS_CHUNK]->(c)
                WITH c
                UNWIND [1, 2] AS occurrence
                MERGE (b:Bill {id: 'Bill:2025-2026:sb-947', name: 'SB 947', occurrence: occurrence})
                MERGE (b)-[:MENTIONED_IN]->(c)
            """)
            outcome = await Neo4jStructuralRetriever(
                driver, agents=scripted_agents(entity_outputs("Bill", value, property))
            ).retrieve(
                approved_request(f"Find {value}"),
                deadline=asyncio.get_running_loop().time() + 15,
            )
            assert isinstance(outcome, SuccessfulBranch)
            assert len(outcome.candidates) == 2
            entries = [c.routes[0].entry_node for c in outcome.candidates]
            assert {e.id for e in entries} == {"Bill:2025-2026:sb-947"}
            assert len({e.element_id for e in entries}) == 2
            assert [c.ranking.rank for c in outcome.candidates] == [1, 2]
            assert all(
                c.grounding is not None
                and str(c.grounding.citation.url)
                == "https://example.org/duplicate-bills"
                for c in outcome.candidates
            )

    asyncio.run(run())


def test_relationship_retains_claim_key_and_only_asserting_chunk_evidence(
    disposable_neo4j_uri,
):
    async def run():
        async with AsyncGraphDatabase.driver(disposable_neo4j_uri) as driver:
            await driver.execute_query("""
                CREATE (a:NewsArticle {id: 'stance-source', title: 'Union position', url: 'https://example.org/stance'})
                CREATE (c:Chunk {id: 'stance-chunk', text: 'The union supports SB 623.'})
                CREATE (unrelated:Chunk {id: 'mention-only', text: 'SB 623 also mentions the union.'})
                CREATE (a)-[:HAS_CHUNK]->(c) CREATE (a)-[:HAS_CHUNK]->(unrelated)
                CREATE (o:Organization:LaborUnion {id: 'union', name: 'Workers United'})
                CREATE (b:Bill {id: 'Bill:2025-2026:sb-623', name: 'SB 623', session: '2025-2026'})
                CREATE (o)-[:DECLARED_STANCE {alignment: 'POSITIVE', chunks: ['stance-chunk'], needs_review: false}]->(b)
                CREATE (o)-[:MENTIONED_IN]->(c) CREATE (b)-[:MENTIONED_IN]->(c)
                CREATE (o)-[:MENTIONED_IN]->(unrelated) CREATE (b)-[:MENTIONED_IN]->(unrelated)
            """)
            outcome = await Neo4jStructuralRetriever(
                driver,
                agents=scripted_agents(
                    relationship_outputs("LaborUnion", "DECLARED_STANCE", "Bill")
                ),
            ).retrieve(
                approved_request("Which unions supported SB 623?"),
                deadline=asyncio.get_running_loop().time() + 15,
            )
            assert isinstance(outcome, SuccessfulBranch)
            (candidate,) = outcome.candidates
            assert candidate.chunk_id == "stance-chunk"
            (claim,) = candidate.routes[0].graph_claims
            assert (claim.source.id, claim.target.id, claim.relationship_type) == (
                "union",
                "Bill:2025-2026:sb-623",
                "DECLARED_STANCE",
            )
            assert claim.claim_key == {"alignment": "POSITIVE"}
            assert claim.chunk_ids == ("stance-chunk",)
            assert claim.source_article_ids == ()
            assert claim.needs_review is False
            assert candidate.grounding is not None
            assert candidate.grounding.text == "The union supports SB 623."

    asyncio.run(run())


@pytest.mark.parametrize(
    "route", ["ABOUT_TOPIC", "DISCUSSES_TOPIC", "PolicyArea", "NewsArticle"]
)
def test_article_level_topic_grounding_follows_source_articles(
    disposable_neo4j_uri, route
):
    async def run():
        async with AsyncGraphDatabase.driver(disposable_neo4j_uri) as driver:
            await driver.execute_query("""
                MERGE (a:NewsArticle {id: 'https://example.org/structural-topic', title: 'Topic report'})
                MERGE (c:Chunk {id: 'structural-topic-chunk', text: 'Coverage of housing policy.'})
                MERGE (a)-[:HAS_CHUNK]->(c)
                MERGE (b:Bill {id: 'topic-bill', name: 'AB 42'})
                MERGE (p:PolicyArea {id: 'topic-area', name: 'Housing'})
                MERGE (a)-[:DISCUSSES_TOPIC {articles: ['https://example.org/structural-topic']}]->(p)
                MERGE (b)-[:ABOUT_TOPIC {articles: ['https://example.org/structural-topic']}]->(p)
            """)
            if route == "PolicyArea":
                outputs = entity_outputs("PolicyArea", "Housing")
            elif route == "NewsArticle":
                outputs = entity_outputs("NewsArticle", "Topic report", "title")
            else:
                outputs = relationship_outputs(
                    "Bill" if route == "ABOUT_TOPIC" else "NewsArticle",
                    route,
                    "PolicyArea",
                    "Housing",
                )
            outcome = await Neo4jStructuralRetriever(
                driver, agents=scripted_agents(outputs)
            ).retrieve(
                approved_request("Which stored sources discuss housing?"),
                deadline=asyncio.get_running_loop().time() + 15,
            )
            assert isinstance(outcome, SuccessfulBranch)
            (candidate,) = outcome.candidates
            assert candidate.grounding is not None
            assert (candidate.chunk_id, candidate.grounding.citation.title) == (
                "structural-topic-chunk",
                "Topic report",
            )
            claims = candidate.routes[0].graph_claims
            if route in {"ABOUT_TOPIC", "DISCUSSES_TOPIC"}:
                (claim,) = claims
                assert claim.relationship_type == route
                assert claim.chunk_ids == ()
                assert claim.source_article_ids == (
                    "https://example.org/structural-topic",
                )
            else:
                assert claims == ()

    asyncio.run(run())


def test_source_publication_dates_use_calendar_bounds(disposable_neo4j_uri):
    async def run():
        async with AsyncGraphDatabase.driver(disposable_neo4j_uri) as driver:
            await driver.execute_query("""
                UNWIND ['2026-06-30T22:00:00', '2026-07-01T09:00:00', '2026-08-01T00:00:00'] AS published
                CREATE (a:NewsArticle {id: 'https://example.org/calendar/' + published,
                    title: 'Calendar report', published_date: published})
                CREATE (a)-[:HAS_CHUNK]->(:Chunk {id: 'calendar-' + published, text: published})
            """)
            outputs = [
                {
                    "labels": ["NewsArticle"],
                    "relationships": [],
                    "filter_properties": {"NewsArticle": ["title", "published_date"]},
                },
                {
                    "role_ids": ["ROLE__NEWSARTICLE"],
                    "relationship_ids": [],
                    "filter_ids": [
                        "FILTER__NEWSARTICLE__TITLE__EQ",
                        "FILTER__NEWSARTICLE__PUBLISHED_DATE__DATE_GTE",
                        "FILTER__NEWSARTICLE__PUBLISHED_DATE__DATE_LT",
                    ],
                },
                {
                    "triples": [],
                    "filters": [{"filter_index": i, "role_index": 0} for i in range(3)],
                },
                {"values": ["Calendar report", "2026-07-01", "2026-08-01"]},
            ]
            outcome = await Neo4jStructuralRetriever(
                driver, agents=scripted_agents(outputs)
            ).retrieve(
                approved_request(
                    "Which Calendar report articles were published in July 2026?"
                ),
                deadline=asyncio.get_running_loop().time() + 15,
            )
            assert isinstance(outcome, SuccessfulBranch)
            assert [c.chunk_id for c in outcome.candidates] == [
                "calendar-2026-07-01T09:00:00"
            ]

    asyncio.run(run())


@pytest.mark.parametrize(
    "missing", ["chunk", "source", "endpoint_mention", "provenance"]
)
def test_matched_claim_with_broken_grounding_is_hydration_failure(
    disposable_neo4j_uri, missing, caplog
):
    async def run():
        async with AsyncGraphDatabase.driver(disposable_neo4j_uri) as driver:
            await driver.execute_query(
                """
                CREATE (o:Organization {id: 'broken-' + $missing})
                CREATE (b:Bill {id: 'broken-bill-' + $missing, name: 'AB 901'})
                CREATE (o)-[:LOBBIED_FOR {chunks: $chunks}]->(b)
                WITH o, b
                WHERE $missing <> 'chunk'
                CREATE (c:Chunk {id: 'broken-chunk-' + $missing, text: 'Stored evidence.'})
                CREATE (o)-[:MENTIONED_IN]->(c)
                FOREACH (_ IN CASE WHEN $missing <> 'endpoint_mention' THEN [1] ELSE [] END |
                    CREATE (b)-[:MENTIONED_IN]->(c))
                FOREACH (_ IN CASE WHEN $missing <> 'source' THEN [1] ELSE [] END |
                    CREATE (:NewsArticle {id: 'https://example.org/broken/' + $missing, title: 'Broken'})-[:HAS_CHUNK]->(c))
            """,
                missing=missing,
                chunks=[] if missing == "provenance" else ["broken-chunk-" + missing],
            )
            outputs = relationship_outputs(value="broken-bill-" + missing)
            outputs[0]["filter_properties"] = {"Bill": ["id"]}
            outputs[1]["filter_ids"] = ["FILTER__BILL__ID__EQ"]
            return await Neo4jStructuralRetriever(
                driver, agents=scripted_agents(outputs)
            ).retrieve(
                approved_request(
                    "Which organizations lobbied for bill ID broken-bill-" + missing
                ),
                deadline=asyncio.get_running_loop().time() + 15,
            )

    with caplog.at_level(logging.WARNING):
        outcome = asyncio.run(run())
    assert outcome == FailedBranch(branch="structural")
    (record,) = [
        r
        for r in caplog.records
        if getattr(r, "event", None) == "retrieval_branch_failed"
    ]
    assert (record.stage, record.failure_kind) == ("hydration", "hydration")


def test_completed_unmatched_lookup_and_literal_cypher_value_are_successful_empty(
    disposable_neo4j_uri, caplog
):
    async def run():
        async with AsyncGraphDatabase.driver(disposable_neo4j_uri) as driver:
            for value in ("No entity has this name", "x' MATCH (n) DETACH DELETE n //"):
                outcome = await Neo4jStructuralRetriever(
                    driver, agents=scripted_agents(entity_outputs(value=value))
                ).retrieve(
                    approved_request(f"Find {value}"),
                    deadline=asyncio.get_running_loop().time() + 15,
                )
                assert outcome == SuccessfulBranch(branch="structural", candidates=())

    with caplog.at_level(logging.WARNING):
        asyncio.run(run())
    assert not [
        r
        for r in caplog.records
        if getattr(r, "event", None) == "retrieval_branch_failed"
    ]


@pytest.mark.parametrize("predicate", ["ABOUT_TOPIC", "DISCUSSES_TOPIC"])
def test_topic_claim_without_grounding_is_hydration_failure(
    disposable_neo4j_uri, predicate, caplog
):
    async def run():
        async with AsyncGraphDatabase.driver(disposable_neo4j_uri) as driver:
            await driver.execute_query("""
                CREATE (p:PolicyArea {id: 'broken-topic', name: 'Broken topic'})
                CREATE (:Bill {id: 'topic-orphan', name: 'AB 812'})
                    -[:ABOUT_TOPIC {articles: ['https://example.org/absent']}]->(p)
                CREATE (:NewsArticle {id: 'https://example.org/no-chunks', title: 'No chunks'})
                    -[:DISCUSSES_TOPIC {articles: ['https://example.org/no-chunks']}]->(p)
            """)
            outputs = relationship_outputs(
                "Bill" if predicate == "ABOUT_TOPIC" else "NewsArticle",
                predicate,
                "PolicyArea",
                "Broken topic",
            )
            return await Neo4jStructuralRetriever(
                driver, agents=scripted_agents(outputs)
            ).retrieve(
                approved_request("Which measures or sources discuss Broken topic?"),
                deadline=asyncio.get_running_loop().time() + 15,
            )

    with caplog.at_level(logging.WARNING):
        outcome = asyncio.run(run())
    assert outcome == FailedBranch(branch="structural")
    (record,) = [
        r
        for r in caplog.records
        if getattr(r, "event", None) == "retrieval_branch_failed"
    ]
    assert (record.stage, record.failure_kind) == ("hydration", "hydration")
