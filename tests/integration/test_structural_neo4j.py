import asyncio
import json
import logging
from copy import deepcopy

import pytest
from neo4j import AsyncGraphDatabase
from pydantic_ai.messages import RetryPromptPart, UserPromptPart
from structural_support import (
    approved_request,
    entity_outputs,
    influence_outputs,
    multi_bill_outputs,
    relationship_outputs,
    scripted_agents,
)

from knowledge_map.adapters.structural import Neo4jStructuralRetriever
from knowledge_map.schemas.retrieval import FailedBranch, SuccessfulBranch


@pytest.fixture
def three_hop_graph(disposable_neo4j_uri):
    async def seed():
        async with AsyncGraphDatabase.driver(disposable_neo4j_uri) as driver:
            await driver.execute_query("""
                MERGE (o:Organization {id: 'three-funder', name: 'Three hop funder'})
                MERGE (campaign:Campaign {id: 'three-campaign'})
                MERGE (p:Politician {id: 'three-politician'})
                MERGE (b:Bill {id: 'three-bill', name: 'AB 800'})
                MERGE (o)-[:FUNDED {chunks: ['three-funding']}]->(campaign)
                MERGE (campaign)-[:CAMPAIGN_FOR {chunks: ['three-candidate']}]->(p)
                MERGE (p)-[:DECLARED_STANCE {chunks: ['three-stance'], alignment: 'POSITIVE'}]->(b)
                MERGE (funding:Chunk {id: 'three-funding', text: 'The organization funded a campaign.'})
                MERGE (candidate:Chunk {id: 'three-candidate', text: 'The campaign is for this politician.'})
                MERGE (stance:Chunk {id: 'three-stance', text: 'The politician supports AB 800.'})
                MERGE (o)-[:MENTIONED_IN]->(funding) MERGE (campaign)-[:MENTIONED_IN]->(funding)
                MERGE (campaign)-[:MENTIONED_IN]->(candidate) MERGE (p)-[:MENTIONED_IN]->(candidate)
                MERGE (p)-[:MENTIONED_IN]->(stance) MERGE (b)-[:MENTIONED_IN]->(stance)
                MERGE (a:NewsArticle {id: 'https://example.org/three-hops', title: 'Three links'})
                MERGE (a)-[:HAS_CHUNK]->(funding) MERGE (a)-[:HAS_CHUNK]->(candidate)
                MERGE (a)-[:HAS_CHUNK]->(stance)
            """)

    asyncio.run(seed())
    return disposable_neo4j_uri


def test_three_hop_search_hydrates_all_claims_and_can_complete_empty(three_hop_graph):
    async def run():
        async with AsyncGraphDatabase.driver(three_hop_graph) as driver:
            for funder in ("Three hop funder", "Absent three hop funder"):
                outcome = await Neo4jStructuralRetriever(
                    driver, agents=scripted_agents(influence_outputs(3, funder))
                ).retrieve(
                    approved_request(
                        f"Which bills have a position recorded by candidates connected through campaigns funded by {funder}?"
                    ),
                    deadline=asyncio.get_running_loop().time() + 15,
                )
                assert isinstance(outcome, SuccessfulBranch)
                if funder.startswith("Absent"):
                    assert outcome.candidates == ()
                    continue
                assert [c.chunk_id for c in outcome.candidates] == [
                    "three-candidate",
                    "three-funding",
                    "three-stance",
                ]
                assert [c.ranking.rank for c in outcome.candidates] == [1, 2, 3]
                for candidate in outcome.candidates:
                    assert candidate.grounding is not None
                    assert candidate.grounding.citation.title == "Three links"
                    assert [
                        (claim.relationship_type, claim.chunk_ids)
                        for claim in candidate.routes[0].graph_claims
                    ] == [
                        ("FUNDED", ("three-funding",)),
                        ("CAMPAIGN_FOR", ("three-candidate",)),
                        ("DECLARED_STANCE", ("three-stance",)),
                    ]

    asyncio.run(run())


@pytest.mark.parametrize("stage_index", range(4))
@pytest.mark.parametrize("rejections", [1, 2, 3])
def test_each_construction_stage_has_two_specific_corrections(
    three_hop_graph, stage_index, rejections, caplog
):
    outputs = influence_outputs(3, "Three hop funder")
    rejected = deepcopy(outputs[stage_index])
    if stage_index == 0:
        rejected["filter_properties"] = {"Organization": ["session"]}
        expected_feedback = "filter properties must belong to selected labels"
    elif stage_index == 1:
        rejected["role_ids"][0] = "ROLE__POLICYAREA"
        expected_feedback = "select only supplied pieces of the requested kind"
    elif stage_index == 2:
        rejected["triples"][0]["target_role_index"] = 3
        expected_feedback = "relationship endpoints must have their declared labels"
    else:
        rejected["values"] = []
        expected_feedback = "bind one value per wired filter"
    outputs[stage_index] = [rejected] * rejections + [outputs[stage_index]]
    feedback = []

    def inspect(index, messages, info):
        if index == stage_index:
            feedback.append(
                [
                    part.content
                    for message in messages
                    for part in message.parts
                    if isinstance(part, RetryPromptPart)
                ]
            )

    async def run():
        async with AsyncGraphDatabase.driver(three_hop_graph) as driver:
            return await Neo4jStructuralRetriever(
                driver, agents=scripted_agents(outputs, inspect=inspect)
            ).retrieve(
                approved_request(
                    "Which bills are connected through candidates and campaigns to Three hop funder?"
                ),
                deadline=asyncio.get_running_loop().time() + 15,
            )

    with caplog.at_level(logging.INFO):
        outcome = asyncio.run(run())
    assert feedback == [[expected_feedback] * i for i in range(min(rejections + 1, 3))]
    if rejections < 3:
        assert isinstance(outcome, SuccessfulBranch)
        assert [c.chunk_id for c in outcome.candidates] == [
            "three-candidate",
            "three-funding",
            "three-stance",
        ]
        (usage,) = [
            r
            for r in caplog.records
            if getattr(r, "event", None) == "retrieval_model_usage"
        ]
        assert usage.requests == 4 + rejections
    else:
        assert outcome == FailedBranch(branch="structural")
        (failure,) = [
            r
            for r in caplog.records
            if getattr(r, "event", None) == "retrieval_branch_failed"
        ]
        assert (failure.stage, failure.failure_kind, failure.attempts_consumed) == (
            ["schema_filtering", "typed_selection", "wiring", "validation"][
                stage_index
            ],
            "validation",
            3,
        )


def test_controlled_graph_cannot_execute_four_semantic_hops(three_hop_graph, caplog):
    outputs = influence_outputs(3, "Three hop funder")
    outputs[1]["relationship_ids"].append(outputs[1]["relationship_ids"][0])

    async def run():
        async with AsyncGraphDatabase.driver(three_hop_graph) as driver:
            return await Neo4jStructuralRetriever(
                driver, agents=scripted_agents(outputs)
            ).retrieve(
                approved_request(
                    "Follow four semantic relationships from Three hop funder"
                ),
                deadline=asyncio.get_running_loop().time() + 15,
            )

    with caplog.at_level(logging.WARNING):
        assert asyncio.run(run()) == FailedBranch(branch="structural")
    (failure,) = [
        r
        for r in caplog.records
        if getattr(r, "event", None) == "retrieval_branch_failed"
    ]
    assert (failure.stage, failure.failure_kind, failure.attempts_consumed) == (
        "hop_bound",
        "hop_bound_exhausted",
        3,
    )


def test_multiple_bill_names_are_assigned_to_explicit_slots(disposable_neo4j_uri):
    def inspect(index, messages, info):
        if index == 3:
            (prompt,) = [
                part.content
                for message in messages
                for part in message.parts
                if isinstance(part, UserPromptPart)
            ]
            slots = json.loads(prompt)["filters"]
            assert [(slot["slot_index"], slot["role_index"]) for slot in slots] == [
                (0, 0),
                (1, 2),
            ]

    async def run():
        async with AsyncGraphDatabase.driver(disposable_neo4j_uri) as driver:
            await driver.execute_query("""
                CREATE (o:Organization {id: 'two-bills-org'})
                CREATE (left:Bill {id: 'bill-186', name: 'AB 186'})
                CREATE (right:Bill {id: 'bill-1947', name: 'SB 1947'})
                CREATE (o)-[:LOBBIED_FOR {chunks: ['two-bills-chunk']}]->(left)
                CREATE (o)-[:LOBBIED_AGAINST {chunks: ['two-bills-chunk']}]->(right)
                CREATE (c:Chunk {id: 'two-bills-chunk', text: 'The organization lobbied for AB 186 and against SB 1947.'})
                CREATE (o)-[:MENTIONED_IN]->(c) CREATE (left)-[:MENTIONED_IN]->(c)
                CREATE (right)-[:MENTIONED_IN]->(c)
                CREATE (:NewsArticle {id: 'https://example.org/two-bills', title: 'Two bills'})-[:HAS_CHUNK]->(c)
            """)
            outcome = await Neo4jStructuralRetriever(
                driver, agents=scripted_agents(multi_bill_outputs(), inspect=inspect)
            ).retrieve(
                approved_request(
                    "Which organizations lobbied for Assembly Bill 186 and against Senate Bill 1947?"
                ),
                deadline=asyncio.get_running_loop().time() + 15,
            )
            assert isinstance(outcome, SuccessfulBranch)
            (candidate,) = outcome.candidates
            assert candidate.chunk_id == "two-bills-chunk"
            assert [
                (claim.relationship_type, claim.target.id)
                for claim in candidate.routes[0].graph_claims
            ] == [("LOBBIED_FOR", "bill-186"), ("LOBBIED_AGAINST", "bill-1947")]

    asyncio.run(run())


def test_two_hop_influence_chain_hydrates_every_claim(disposable_neo4j_uri):
    async def run():
        async with AsyncGraphDatabase.driver(disposable_neo4j_uri) as driver:
            await driver.execute_query("""
                CREATE (o:Organization {id: 'multi-funder', name: 'California Leads'})
                CREATE (c:Campaign {id: 'multi-campaign', name: 'Ed Musgrove campaign'})
                CREATE (p:Politician {id: 'multi-politician', name: 'Ed Musgrove'})
                CREATE (o)-[:FUNDED {chunks: ['multi-funding'], amount: 6000000}]->(c)
                CREATE (c)-[:CAMPAIGN_FOR {chunks: ['multi-target']}]->(p)
                CREATE (funding:Chunk {id: 'multi-funding', text: 'California Leads funded the campaign.'})
                CREATE (target:Chunk {id: 'multi-target', text: 'The campaign is for Ed Musgrove.'})
                CREATE (o)-[:MENTIONED_IN]->(funding) CREATE (c)-[:MENTIONED_IN]->(funding)
                CREATE (c)-[:MENTIONED_IN]->(target) CREATE (p)-[:MENTIONED_IN]->(target)
                CREATE (:NewsArticle {id: 'https://example.org/multi-funding', title: 'Funding'})-[:HAS_CHUNK]->(funding)
                CREATE (:NewsArticle {id: 'https://example.org/multi-target', title: 'Candidate'})-[:HAS_CHUNK]->(target)
            """)
            outcome = await Neo4jStructuralRetriever(
                driver, agents=scripted_agents(influence_outputs())
            ).retrieve(
                approved_request(
                    "Which candidates are connected to California Leads through campaigns it funds?"
                ),
                deadline=asyncio.get_running_loop().time() + 15,
            )
            assert isinstance(outcome, SuccessfulBranch)
            assert [candidate.chunk_id for candidate in outcome.candidates] == [
                "multi-funding",
                "multi-target",
            ]
            for candidate in outcome.candidates:
                assert candidate.grounding is not None
                assert (
                    str(candidate.grounding.citation.url)
                    == "https://example.org/" + candidate.chunk_id
                )
                assert [
                    (claim.source.id, claim.relationship_type, claim.target.id)
                    for claim in candidate.routes[0].graph_claims
                ] == [
                    ("multi-funder", "FUNDED", "multi-campaign"),
                    ("multi-campaign", "CAMPAIGN_FOR", "multi-politician"),
                ]

    asyncio.run(run())


def test_same_side_intersection_excludes_the_named_organization(disposable_neo4j_uri):
    outputs = [
        {
            "labels": ["Organization", "Bill"],
            "relationships": ["LOBBIED_FOR"],
            "filter_properties": {
                "Organization": ["name"],
                "Bill": ["name", "session"],
            },
        },
        {
            "role_ids": ["ROLE__ORGANIZATION", "ROLE__BILL", "ROLE__ORGANIZATION"],
            "relationship_ids": ["REL__ORGANIZATION__LOBBIED_FOR__BILL"] * 2,
            "filter_ids": [
                "FILTER__ORGANIZATION__NAME__EQ",
                "FILTER__BILL__NAME__EQ",
                "FILTER__BILL__SESSION__EQ",
            ],
        },
        {
            "triples": [
                {
                    "relationship_index": 0,
                    "source_role_index": 0,
                    "target_role_index": 1,
                },
                {
                    "relationship_index": 1,
                    "source_role_index": 2,
                    "target_role_index": 1,
                },
            ],
            "filters": [
                {"filter_index": 0, "role_index": 0},
                {"filter_index": 1, "role_index": 1},
                {"filter_index": 2, "role_index": 1},
            ],
            "distinct_roles": [{"left_role_index": 0, "right_role_index": 2}],
        },
        {"values": ["Walt Disney", "AB 186", "2025-2026"]},
    ]

    async def run():
        async with AsyncGraphDatabase.driver(disposable_neo4j_uri) as driver:
            await driver.execute_query("""
                CREATE (seed:Organization {id: 'same-seed', name: 'Walt Disney'})
                CREATE (peer:Organization {id: 'same-peer', name: 'Creative Artists Agency'})
                CREATE (b:Bill {id: 'same-bill', name: 'AB 186', session: '2025-2026'})
                CREATE (seed)-[:LOBBIED_FOR {chunks: ['same-chunk']}]->(b)
                CREATE (peer)-[:LOBBIED_FOR {chunks: ['same-chunk']}]->(b)
                CREATE (c:Chunk {id: 'same-chunk', text: 'Both organizations lobbied for AB 186.'})
                CREATE (seed)-[:MENTIONED_IN]->(c) CREATE (peer)-[:MENTIONED_IN]->(c)
                CREATE (b)-[:MENTIONED_IN]->(c)
                CREATE (:NewsArticle {id: 'https://example.org/same-side', title: 'Shared support'})-[:HAS_CHUNK]->(c)
            """)
            outcome = await Neo4jStructuralRetriever(
                driver, agents=scripted_agents(outputs)
            ).retrieve(
                approved_request(
                    "Which other organizations lobbied for AB 186 alongside Walt Disney in the 2025-2026 session?"
                ),
                deadline=asyncio.get_running_loop().time() + 15,
            )
            assert isinstance(outcome, SuccessfulBranch)
            (candidate,) = outcome.candidates
            assert [
                (c.source.id, c.target.id) for c in candidate.routes[0].graph_claims
            ] == [("same-seed", "same-bill"), ("same-peer", "same-bill")]

    asyncio.run(run())


def test_three_semantic_hops_include_article_topic_provenance(disposable_neo4j_uri):
    outputs = [
        {
            "labels": ["Organization", "Bill", "PolicyArea", "NewsArticle"],
            "relationships": ["LOBBIED_FOR", "ABOUT_TOPIC", "DISCUSSES_TOPIC"],
            "filter_properties": {"Organization": ["name"]},
        },
        {
            "role_ids": [
                "ROLE__ORGANIZATION",
                "ROLE__BILL",
                "ROLE__POLICYAREA",
                "ROLE__NEWSARTICLE",
            ],
            "relationship_ids": [
                "REL__ORGANIZATION__LOBBIED_FOR__BILL",
                "REL__BILL__ABOUT_TOPIC__POLICYAREA",
                "REL__NEWSARTICLE__DISCUSSES_TOPIC__POLICYAREA",
            ],
            "filter_ids": ["FILTER__ORGANIZATION__NAME__EQ"],
        },
        {
            "triples": [
                {
                    "relationship_index": 2,
                    "source_role_index": 3,
                    "target_role_index": 2,
                },
                {
                    "relationship_index": 0,
                    "source_role_index": 0,
                    "target_role_index": 1,
                },
                {
                    "relationship_index": 1,
                    "source_role_index": 1,
                    "target_role_index": 2,
                },
            ],
            "filters": [{"filter_index": 0, "role_index": 0}],
        },
        {"values": ["Topic chain organization"]},
    ]

    async def run():
        async with AsyncGraphDatabase.driver(disposable_neo4j_uri) as driver:
            await driver.execute_query("""
                CREATE (o:Organization {id: 'topic-chain-org', name: 'Topic chain organization'})
                CREATE (b:Bill {id: 'topic-chain-bill', name: 'AB 1740'})
                CREATE (p:PolicyArea {id: 'topic-chain-area', name: 'Housing & Community Development'})
                CREATE (a:NewsArticle {id: 'https://example.org/topic-chain', title: 'Article-level topic'})
                CREATE (o)-[:LOBBIED_FOR {chunks: ['topic-chain-lobby']}]->(b)
                CREATE (b)-[:ABOUT_TOPIC {articles: ['https://example.org/topic-chain']}]->(p)
                CREATE (a)-[:DISCUSSES_TOPIC {articles: ['https://example.org/topic-chain']}]->(p)
                CREATE (c:Chunk {id: 'topic-chain-lobby', text: 'The organization lobbied for this housing bill.'})
                CREATE (o)-[:MENTIONED_IN]->(c) CREATE (b)-[:MENTIONED_IN]->(c)
                CREATE (a)-[:HAS_CHUNK]->(c)
                CREATE (a)-[:HAS_CHUNK]->(:Chunk {id: 'topic-chain-topic', text: 'Further discussion of housing.'})
            """)
            outcome = await Neo4jStructuralRetriever(
                driver, agents=scripted_agents(outputs)
            ).retrieve(
                approved_request(
                    "Which articles discuss policy areas attached to bills lobbied for by Topic chain organization?"
                ),
                deadline=asyncio.get_running_loop().time() + 15,
            )
            assert isinstance(outcome, SuccessfulBranch)
            assert [c.chunk_id for c in outcome.candidates] == [
                "topic-chain-lobby",
                "topic-chain-topic",
            ]
            for candidate in outcome.candidates:
                claims = candidate.routes[0].graph_claims
                assert [claim.relationship_type for claim in claims] == [
                    "LOBBIED_FOR",
                    "ABOUT_TOPIC",
                    "DISCUSSES_TOPIC",
                ]
                assert claims[0].chunk_ids == ("topic-chain-lobby",)
                assert claims[1].source_article_ids == (
                    "https://example.org/topic-chain",
                )
                assert claims[2].source_article_ids == (
                    "https://example.org/topic-chain",
                )
                assert candidate.grounding is not None
                assert candidate.grounding.citation.title == "Article-level topic"

    asyncio.run(run())


def test_reported_vote_lookup_searches_every_recorded_position(disposable_neo4j_uri):
    outputs = [
        {
            "labels": ["Politician", "LegislativeEvent", "Bill"],
            "relationships": ["VOTED_AYE", "VOTED_NO", "ABSTAINED", "ACTION_ON"],
            "filter_properties": {"Politician": ["name"], "Bill": ["name", "session"]},
        },
        {
            "role_ids": ["ROLE__POLITICIAN", "ROLE__LEGISLATIVEEVENT", "ROLE__BILL"],
            "relationship_ids": [
                "REL__POLITICIAN__RECORDED_VOTE__LEGISLATIVEEVENT",
                "REL__LEGISLATIVEEVENT__ACTION_ON__BILL",
            ],
            "filter_ids": [
                "FILTER__POLITICIAN__NAME__EQ",
                "FILTER__BILL__NAME__EQ",
                "FILTER__BILL__SESSION__EQ",
            ],
        },
        {
            "triples": [
                {
                    "relationship_index": 0,
                    "source_role_index": 0,
                    "target_role_index": 1,
                },
                {
                    "relationship_index": 1,
                    "source_role_index": 1,
                    "target_role_index": 2,
                },
            ],
            "filters": [
                {"filter_index": 0, "role_index": 0},
                {"filter_index": 1, "role_index": 2},
                {"filter_index": 2, "role_index": 2},
            ],
        },
        {"values": ["Catherine Blakespear", "SB 1007", "2025-2026"]},
    ]

    async def run():
        async with AsyncGraphDatabase.driver(disposable_neo4j_uri) as driver:
            await driver.execute_query("""
                CREATE (p:Politician {id: 'reported-voter', name: 'Catherine Blakespear'})
                CREATE (b:Bill {id: 'reported-bill', name: 'SB 1007', session: '2025-2026'})
                CREATE (aye:LegislativeEvent {id: 'reported-aye'})
                CREATE (no:LegislativeEvent {id: 'reported-no'})
                CREATE (abstained:LegislativeEvent {id: 'reported-abstained'})
                CREATE (p)-[:VOTED_AYE {chunks: ['reported-aye-chunk']}]->(aye)
                CREATE (p)-[:VOTED_NO {chunks: ['reported-no-chunk']}]->(no)
                CREATE (p)-[:ABSTAINED {chunks: ['reported-abstained-chunk']}]->(abstained)
                WITH p, b, [aye, no, abstained] AS events
                UNWIND events AS event
                CREATE (event)-[:ACTION_ON {chunks: [event.id + '-chunk']}]->(b)
                CREATE (c:Chunk {id: event.id + '-chunk', text: 'A reported vote.'})
                CREATE (p)-[:MENTIONED_IN]->(c) CREATE (event)-[:MENTIONED_IN]->(c)
                CREATE (b)-[:MENTIONED_IN]->(c)
                CREATE (:NewsArticle {id: 'https://example.org/' + event.id, title: 'Reported vote'})-[:HAS_CHUNK]->(c)
            """)
            outcome = await Neo4jStructuralRetriever(
                driver, agents=scripted_agents(outputs)
            ).retrieve(
                approved_request(
                    "What vote is recorded for Catherine Blakespear on SB 1007 in the 2025-2026 session?"
                ),
                deadline=asyncio.get_running_loop().time() + 15,
            )
            assert isinstance(outcome, SuccessfulBranch)
            assert [
                (
                    c.chunk_id,
                    tuple(
                        claim.relationship_type for claim in c.routes[0].graph_claims
                    ),
                )
                for c in outcome.candidates
            ] == [
                ("reported-abstained-chunk", ("ABSTAINED", "ACTION_ON")),
                ("reported-aye-chunk", ("VOTED_AYE", "ACTION_ON")),
                ("reported-no-chunk", ("VOTED_NO", "ACTION_ON")),
            ]

    asyncio.run(run())


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
