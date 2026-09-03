"""The article-level topic write path.

Drives the Graph Database Adapter's article-level topic method and reads the
Cypher it issued, as the chunk extraction tests beside it do.  Nothing here
asserts how a Policy Area was arrived at — only what reached the graph.
"""

import inspect
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
    assert sum("MERGE (src)-[r:DISCUSSES_TOPIC]" in q for q in queries) == 2

    node_call = _call_for(tx, "MERGE (n:PolicyArea {id: $node_id})")
    assert node_call[1]["node_id"] == derived_key("PolicyArea", "Education (K–12)")
    assert node_call[1]["properties"]["name"] == "Education (K–12)"

    edge_call = _call_for(tx, "MERGE (src)-[r:DISCUSSES_TOPIC]")
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

    call = _call_for(tx, "MERGE (src)-[r:ABOUT_TOPIC]")
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

    call = _call_for(tx, "MERGE (src)-[r:ABOUT_TOPIC]")
    assert call[1]["src_id"] == bill_key("2023-2024", "AB 218", "Assembly Bill 218")


def test_areas_without_assignments_write_the_article_edges_and_nothing_else(
    transaction,
):
    """The pipeline's own state between classification and assignment."""

    adapter, tx = transaction

    adapter.ingest_article_topics(ARTICLE, ["Health"])

    written = [q for q in _queries(tx) if "DELETE r" not in q]
    assert len(written) == 2
    assert not any("ABOUT_TOPIC" in q for q in written)


def test_neither_areas_nor_assignments_still_retracts_what_the_article_wrote(
    transaction,
):
    """An article that classifies to nothing is a decision, not a no-op: the
    areas an earlier run recorded are no longer supported by any run."""

    adapter, tx = transaction

    adapter.ingest_article_topics(ARTICLE, [])

    queries = _queries(tx)
    assert all("MERGE" not in query for query in queries)

    discusses = _call_for(tx, "[r:DISCUSSES_TOPIC]")
    assert "DELETE r" in discusses[0][0]
    assert discusses[1]["area_ids"] == []

    about = _call_for(tx, "[r:ABOUT_TOPIC]")
    assert "DELETE r" in about[0][0]
    assert about[1]["pairs"] == []


def test_an_area_the_latest_run_dropped_loses_this_articles_topic_edge(transaction):
    adapter, tx = transaction

    adapter.ingest_article_topics(ARTICLE, ["Health"])

    call = _call_for(tx, "DELETE r")
    query = call[0][0]
    # Scoped to this article's own edges: another article's classification of
    # the same area is a decision this run did not make and cannot retract.
    assert "(:NewsArticle {id: $article_id})-[r:DISCUSSES_TOPIC]->(p:PolicyArea)" in query
    assert "NOT p.id IN $area_ids" in query
    assert call[1]["article_id"] == ARTICLE.url
    assert call[1]["area_ids"] == [derived_key("PolicyArea", "Health")]


def test_an_assignment_the_latest_run_dropped_loses_this_articles_support(transaction):
    adapter, tx = transaction

    adapter.ingest_article_topics(
        ARTICLE,
        ["Health"],
        [
            TopicAssignment(
                measure_name="Proposition 33",
                measure_label="Prop",
                policy_area="Health",
            )
        ],
    )

    call = next(
        c for c in tx.run.call_args_list
        if "DELETE r" in c[0][0] and "ABOUT_TOPIC" in c[0][0]
    )
    query = call[0][0]
    # An ABOUT_TOPIC edge hangs between a measure and an area, so what scopes
    # the retraction is the provenance the edge carries, not an endpoint.
    assert "$article_id IN coalesce(r.articles, [])" in query
    assert "NOT [m.id, p.id] IN $pairs" in query
    # The article stops asserting the claim; the edge survives if another
    # article still does.
    assert "SET r.articles = [url IN r.articles WHERE url <> $article_id]" in query
    assert "size(r.articles) = 0" in query
    assert call[1]["pairs"] == [
        [derived_key("Prop", "Proposition 33"), derived_key("PolicyArea", "Health")]
    ]


def test_an_assignment_edge_records_the_articles_asserting_it(transaction):
    """The article-level counterpart of the chunks a per-chunk edge collects."""

    adapter, tx = transaction

    adapter.ingest_article_topics(
        ARTICLE,
        ["Health"],
        [
            TopicAssignment(
                measure_name="Proposition 33",
                measure_label="Prop",
                policy_area="Health",
            )
        ],
    )

    call = _call_for(tx, "MERGE (src)-[r:ABOUT_TOPIC")
    assert "r.articles" in call[0][0]
    assert call[1]["article_id"] == ARTICLE.url


def test_the_pipeline_cannot_be_assembled_without_the_classification_stage():
    """The write path is driven by Policy Area Classification, so a pipeline
    that could be assembled without that stage would silently write no
    article-level topics.  The stage is a collaborator like Coreference
    Resolution and Entity Extraction, not an optional side channel."""

    from test_pipeline import (
        MockCoreferenceAdapter,
        MockDatabaseAdapter,
        MockEmbeddingAdapter,
        MockEntityExtractionAdapter,
        MockStatusTracker,
    )

    with pytest.raises(TypeError):
        StoryPipeline(
            db_adapter=MockDatabaseAdapter(),
            embedding_adapter=MockEmbeddingAdapter(),
            coreference_adapter=MockCoreferenceAdapter(),
            extraction_adapter=MockEntityExtractionAdapter(),
            status_tracker=MockStatusTracker(),
        )


def _protocol_methods() -> list[str]:
    return [
        name
        for name, _ in inspect.getmembers(DatabaseAdapter, inspect.isfunction)
        if not name.startswith("_")
    ]


def test_the_database_adapter_protocol_declares_the_article_level_write():
    """One seam, extended — not a second seam beside it."""

    assert "ingest_article_topics" in _protocol_methods()


def test_the_neo4j_adapter_implements_the_whole_protocol():
    """The repo's only Database Adapter: ``sqlite_db`` exposes a status
    tracker, not a second implementer of this seam.

    Parameter names are compared, not just method presence, so a write the
    pipeline calls by keyword cannot drift from the Protocol unnoticed.
    """

    for name in _protocol_methods():
        assert callable(getattr(Neo4jAdapter, name, None)), name

    declared = inspect.signature(DatabaseAdapter.ingest_article_topics)
    implemented = inspect.signature(Neo4jAdapter.ingest_article_topics)
    assert list(implemented.parameters) == list(declared.parameters)


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
    written = [query for query in _queries(tx) if "DELETE r" not in query]
    assert all("MERGE" in query for query in written)
    assert not any("CREATE" in query for query in _queries(tx))
