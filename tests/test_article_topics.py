"""The article-level topic write path.

Drives the Graph Database Adapter's article-level topic method and reads the
Cypher it issued, as the chunk extraction tests beside it do.  Nothing here
asserts how a Policy Area was arrived at — only what reached the graph.
"""

from unittest.mock import MagicMock, patch

import pytest

from knowledge_map.adapters.neo4j_db import Neo4jAdapter
from knowledge_map.core.pipeline import DatabaseAdapter, StoryPipeline
from knowledge_map.ontology.keys import bill_key, derived_key
from knowledge_map.schemas import (
    BillSessionResolution,
    BillSessionResolutions,
    SourceArticle,
    TopicAssignment,
)

ARTICLE = SourceArticle(
    url="http://example.com/1",
    title="Two bills, two subjects",
    content="Assembly Bill 218 and Proposition 33.",
)


@pytest.fixture(autouse=True)
def mock_ensure_vector_index():
    with patch(
        "knowledge_map.adapters.neo4j_db.Neo4jAdapter._ensure_vector_index", create=True
    ):
        yield


@pytest.fixture
def transaction():
    """A Neo4j adapter and the transaction its writes land on."""

    driver = MagicMock()
    session = MagicMock()
    tx = MagicMock()
    driver.session.return_value.__enter__.return_value = session
    session.execute_write.side_effect = lambda func, *a, **kw: func(tx, *a, **kw)
    adapter = Neo4jAdapter("bolt://localhost:7687", "neo4j", "password", driver=driver)
    return adapter, tx


def _queries(tx) -> list[str]:
    return [call[0][0] for call in tx.run.call_args_list]


def _call_for(tx, fragment: str):
    return next(call for call in tx.run.call_args_list if fragment in call[0][0])


def test_policy_areas_merge_a_node_and_an_article_topic_edge(transaction):
    adapter, tx = transaction

    adapter.ingest_article_topics(
        ARTICLE, ["Education (K–12)", "Housing & Community Development"]
    )

    queries = _queries(tx)
    assert sum("MERGE (n:PolicyArea {id: $node_id})" in q for q in queries) == 2
    assert sum("[r:DISCUSSES_TOPIC]" in q for q in queries) == 2

    node_call = _call_for(tx, "MERGE (n:PolicyArea {id: $node_id})")
    assert node_call[1]["node_id"] == derived_key("PolicyArea", "Education (K–12)")
    assert node_call[1]["properties"]["name"] == "Education (K–12)"

    edge_call = _call_for(tx, "[r:DISCUSSES_TOPIC]")
    assert "(src:NewsArticle {id: $src_id})" in edge_call[0][0]
    assert "(tgt:PolicyArea {id: $tgt_id})" in edge_call[0][0]
    assert edge_call[1]["src_id"] == ARTICLE.url
    assert edge_call[1]["tgt_id"] == derived_key("PolicyArea", "Education (K–12)")


def test_assignment_merges_about_topic_from_the_named_measure(transaction):
    adapter, tx = transaction

    adapter.ingest_article_topics(
        ARTICLE,
        ["Education (K–12)"],
        [
            TopicAssignment(
                measure_name="Proposition 33",
                measure_label="Prop",
                policy_area="Education (K–12)",
            )
        ],
    )

    call = _call_for(tx, "[r:ABOUT_TOPIC]")
    assert "(src:Prop {id: $src_id})" in call[0][0]
    assert "(tgt:PolicyArea {id: $tgt_id})" in call[0][0]
    assert call[1]["src_id"] == derived_key("Prop", "Proposition 33")
    assert call[1]["tgt_id"] == derived_key("PolicyArea", "Education (K–12)")


def test_assignment_keys_a_bill_by_its_session_resolution(transaction):
    adapter, tx = transaction
    resolutions = BillSessionResolutions(
        by_name={
            "Assembly Bill 218": BillSessionResolution(
                name="AB 218", session="2023-2024", session_verified=True
            )
        }
    )

    adapter.ingest_article_topics(
        ARTICLE,
        ["Judiciary"],
        [
            TopicAssignment(
                measure_name="Assembly Bill 218",
                measure_label="Bill",
                policy_area="Judiciary",
            )
        ],
        bill_sessions=resolutions,
    )

    call = _call_for(tx, "[r:ABOUT_TOPIC]")
    assert call[1]["src_id"] == bill_key("2023-2024", "AB 218", "Assembly Bill 218")


def test_areas_without_assignments_write_the_article_edges_and_nothing_else(
    transaction,
):
    """The pipeline's own state between classification and assignment."""

    adapter, tx = transaction

    adapter.ingest_article_topics(ARTICLE, ["Health"])

    queries = _queries(tx)
    assert len(queries) == 2
    assert not any("ABOUT_TOPIC" in q for q in queries)


def test_neither_areas_nor_assignments_writes_nothing(transaction):
    adapter, tx = transaction

    adapter.ingest_article_topics(ARTICLE, [])

    tx.run.assert_not_called()


def test_the_pipeline_does_not_yet_write_article_topics():
    """A caller arrives with areas in 02 and with assignments in 04, not here."""

    from test_pipeline import (
        MockCoreferenceAdapter,
        MockDatabaseAdapter,
        MockEmbeddingAdapter,
        MockEntityExtractionAdapter,
        MockStatusTracker,
    )

    class RecordingDatabase(MockDatabaseAdapter):
        def __init__(self):
            super().__init__()
            self.topics = []

        def ingest_article_topics(self, article, policy_areas, assignments=None, bill_sessions=None):
            self.topics.append((article, policy_areas, assignments))

    db = RecordingDatabase()
    StoryPipeline(
        db_adapter=db,
        embedding_adapter=MockEmbeddingAdapter(),
        coreference_adapter=MockCoreferenceAdapter(),
        extraction_adapter=MockEntityExtractionAdapter(),
        status_tracker=MockStatusTracker(),
    ).run(ARTICLE)

    assert db.articles == [ARTICLE]
    assert db.topics == []


def test_the_database_adapter_protocol_declares_the_article_level_write():
    """One seam, extended — not a second seam beside it."""

    assert "ingest_article_topics" in DatabaseAdapter.__protocol_attrs__


def test_every_database_adapter_satisfies_the_protocol():
    adapter = Neo4jAdapter("bolt://localhost:7687", "neo4j", "password", driver=MagicMock())

    assert isinstance(adapter, DatabaseAdapter)


def test_writing_the_same_topics_twice_is_idempotent(transaction):
    adapter, tx = transaction
    assignments = [
        TopicAssignment(
            measure_name="Proposition 33",
            measure_label="Prop",
            policy_area="Health",
        )
    ]

    adapter.ingest_article_topics(ARTICLE, ["Health"], assignments)
    first = list(tx.run.call_args_list)
    tx.run.reset_mock()
    adapter.ingest_article_topics(ARTICLE, ["Health"], assignments)
    second = list(tx.run.call_args_list)

    # One node per area and one edge per pair survives a second write because
    # every write is a MERGE on the same key, not a CREATE.
    assert first == second
    assert all("MERGE" in query for query in _queries(tx))
    assert not any("CREATE" in query for query in _queries(tx))
