import pytest
from unittest.mock import MagicMock, patch
from knowledge_map.adapters.neo4j_db import Neo4jAdapter, Neo4jConfigError, Neo4jConnectionError, ingest_extraction_result
from knowledge_map.schemas import ExtractionResult, Node, Relationship, SourceArticle, ArticleChunk

@pytest.fixture(autouse=True)
def mock_ensure_vector_index(request):
    if "no_mock_ensure_index" in request.keywords:
        yield
    else:
        with patch("knowledge_map.adapters.neo4j_db.Neo4jAdapter._ensure_vector_index", create=True) as m:
            yield m

def test_missing_uri_raises_error():
    with pytest.raises(Neo4jConfigError) as exc_info:
        Neo4jAdapter(uri="", username="neo4j", password="password")
    assert "NEO4J_URI environment variable is missing or empty" in str(exc_info.value)

def test_missing_username_raises_error():
    with pytest.raises(Neo4jConfigError) as exc_info:
        Neo4jAdapter(uri="bolt://localhost:7687", username="", password="password")
    assert "NEO4J_USERNAME environment variable is missing or empty" in str(exc_info.value)

def test_missing_password_raises_error():
    with pytest.raises(Neo4jConfigError) as exc_info:
        Neo4jAdapter(uri="bolt://localhost:7687", username="neo4j", password="")
    assert "NEO4J_PASSWORD environment variable is missing or empty" in str(exc_info.value)

def test_clear_database_executes_correct_query():
    mock_driver = MagicMock()
    mock_session = MagicMock()
    mock_tx = MagicMock()
    
    mock_driver.session.return_value.__enter__.return_value = mock_session
    
    def fake_execute_write(func, *args, **kwargs):
        return func(mock_tx, *args, **kwargs)
    mock_session.execute_write.side_effect = fake_execute_write
    
    manager = Neo4jAdapter(
        uri="bolt://localhost:7687",
        username="neo4j",
        password="password",
        driver=mock_driver
    )
    
    manager.clear_database()
    
    mock_driver.session.assert_called_once()
    mock_session.execute_write.assert_called_once()
    mock_tx.run.assert_called_once_with("MATCH (n) DETACH DELETE n")

def test_driver_connection_error_raises_custom_exception():
    mock_driver = MagicMock()
    mock_driver.verify_connectivity.side_effect = Exception("Failed to connect to Neo4j")
    
    manager = Neo4jAdapter(
        uri="bolt://localhost:7687",
        username="neo4j",
        password="password",
        driver=mock_driver
    )
    
    with pytest.raises(Neo4jConnectionError) as exc_info:
        manager.connect()
    assert "Could not connect to Neo4j database" in str(exc_info.value)

def test_query_execution_error_raises_custom_exception():
    mock_driver = MagicMock()
    mock_session = MagicMock()
    mock_driver.session.return_value.__enter__.return_value = mock_session
    mock_session.execute_write.side_effect = Exception("Cypher execution failed")
    
    manager = Neo4jAdapter(
        uri="bolt://localhost:7687",
        username="neo4j",
        password="password",
        driver=mock_driver
    )
    
    with pytest.raises(Neo4jConnectionError) as exc_info:
        manager.clear_database()
    assert "Failed to clear Neo4j database" in str(exc_info.value)

def test_ingest_extraction_result_nodes():
    mock_tx = MagicMock()
    extraction = ExtractionResult(
        nodes=[
            Node(name="Gavin Newsom", label="Politician", properties={"current_party": "Democratic"}),
            Node(name="California Teachers Association", label="Organization", sub_labels=["LaborUnion"])
        ],
        relationships=[]
    )
    
    ingest_extraction_result(mock_tx, extraction, source_url="http://example.com/story")
    
    assert mock_tx.run.call_count == 2
    
    # Check first call (Gavin Newsom)
    first_call_args = mock_tx.run.call_args_list[0]
    first_query = first_call_args[0][0]
    first_kwargs = first_call_args[1]
    
    assert "MERGE (n:Politician {id: $node_id})" in first_query
    assert "n.source_url = $source_url" in first_query
    assert "n += $properties" in first_query
    assert first_kwargs["node_id"] == "Politician:gavin-newsom"
    assert first_kwargs["name"] == "Gavin Newsom"
    assert first_kwargs["source_url"] == "http://example.com/story"
    assert first_kwargs["properties"] == {"current_party": "Democratic"}
    assert first_kwargs["provenance"] == "news-derived"
    
    # Check second call (Democratic Party)
    second_call_args = mock_tx.run.call_args_list[1]
    second_query = second_call_args[0][0]
    second_kwargs = second_call_args[1]
    
    assert "MERGE (n:Organization:LaborUnion {id: $node_id})" in second_query
    assert second_kwargs["node_id"] == "Organization:california-teachers-association"
    assert second_kwargs["name"] == "California Teachers Association"
    assert second_kwargs["source_url"] == "http://example.com/story"
    assert second_kwargs["properties"] == {}

def test_ingest_extraction_result_relationships():
    mock_tx = MagicMock()
    extraction = ExtractionResult(
        nodes=[
            Node(name="Gavin Newsom", label="Politician"),
            Node(name="Education Committee", label="Committee")
        ],
        relationships=[
            Relationship(
                source="Gavin Newsom",
                target="Education Committee",
                relationship_type="SERVES_ON",
                properties={"status": "Active"}
            )
        ]
    )
    
    ingest_extraction_result(mock_tx, extraction, source_url="http://example.com/story")
    
    # Expected call count: 2 (nodes) + 1 (relationship) = 3
    assert mock_tx.run.call_count == 3
    
    # Third call is the relationship insertion
    rel_call_args = mock_tx.run.call_args_list[2]
    rel_query = rel_call_args[0][0]
    rel_kwargs = rel_call_args[1]
    
    assert "MATCH (src:Politician {id: $src_id}), (tgt:Committee {id: $tgt_id})" in rel_query
    assert "MERGE (src)-[r:SERVES_ON]->(tgt)" in rel_query
    assert "SET r += $properties" in rel_query
    
    assert rel_kwargs["src_id"] == "Politician:gavin-newsom"
    assert rel_kwargs["tgt_id"] == "Committee:education-committee"
    assert rel_kwargs["properties"] == {
        "status": "Active", "provenance": "news-derived", "skips": "LegislativeTenure"
    }

def test_ingest_extraction_result_invalid_identifiers():
    from pydantic import ValidationError

    # 1. Invalid node label raises ValidationError
    with pytest.raises(ValidationError) as exc_info:
        Node(name="Gavin Newsom", label="Political`Actor")
    assert "Invalid character in node label" in str(exc_info.value)
    
    # 2. Invalid relationship type raises ValidationError
    with pytest.raises(ValidationError) as exc_info:
        Relationship(
            source="Gavin Newsom",
            target="Democratic Party",
            relationship_type="MEMBER`OF"
        )
    assert "Invalid character in relationship type" in str(exc_info.value)

def test_get_distinct_labels_success():
    mock_driver = MagicMock()
    mock_session = MagicMock()
    mock_tx = MagicMock()
    
    mock_driver.session.return_value.__enter__.return_value = mock_session
    
    def fake_execute_read(func, *args, **kwargs):
        return func(mock_tx, *args, **kwargs)
    mock_session.execute_read.side_effect = fake_execute_read
    
    mock_record1 = {"label": "PoliticalActor"}
    mock_record2 = {"label": "Organization"}
    mock_tx.run.return_value = [mock_record1, mock_record2]
    
    manager = Neo4jAdapter(
        uri="bolt://localhost:7687",
        username="neo4j",
        password="password",
        driver=mock_driver
    )
    
    labels = manager.get_distinct_labels()
    
    assert labels == ["Organization", "PoliticalActor"]
    mock_driver.session.assert_called_once()
    mock_session.execute_read.assert_called_once()
    mock_tx.run.assert_called_once_with("CALL db.labels() YIELD label RETURN label")

def test_get_distinct_labels_empty():
    mock_driver = MagicMock()
    mock_session = MagicMock()
    mock_tx = MagicMock()
    
    mock_driver.session.return_value.__enter__.return_value = mock_session
    
    def fake_execute_read(func, *args, **kwargs):
        return func(mock_tx, *args, **kwargs)
    mock_session.execute_read.side_effect = fake_execute_read
    
    mock_tx.run.return_value = []
    
    manager = Neo4jAdapter(
        uri="bolt://localhost:7687",
        username="neo4j",
        password="password",
        driver=mock_driver
    )
    
    labels = manager.get_distinct_labels()
    assert labels == []
    mock_tx.run.assert_called_once_with("CALL db.labels() YIELD label RETURN label")

def test_get_distinct_labels_failure():
    mock_driver = MagicMock()
    mock_session = MagicMock()
    
    mock_driver.session.return_value.__enter__.return_value = mock_session
    mock_session.execute_read.side_effect = Exception("Query timed out")
    
    manager = Neo4jAdapter(
        uri="bolt://localhost:7687",
        username="neo4j",
        password="password",
        driver=mock_driver
    )
    
    with pytest.raises(Neo4jConnectionError) as exc_info:
        manager.get_distinct_labels()
    assert "Failed to retrieve node labels from Neo4j" in str(exc_info.value)

def test_get_nodes_by_label_success():
    mock_driver = MagicMock()
    mock_session = MagicMock()
    mock_tx = MagicMock()
    
    mock_driver.session.return_value.__enter__.return_value = mock_session
    
    def fake_execute_read(func, *args, **kwargs):
        return func(mock_tx, *args, **kwargs)
    mock_session.execute_read.side_effect = fake_execute_read
    
    mock_tx.run.return_value = [{"name": "Gavin Newsom"}, {"name": "Jerry Brown"}]
    
    manager = Neo4jAdapter(
        uri="bolt://localhost:7687",
        username="neo4j",
        password="password",
        driver=mock_driver
    )
    
    nodes = manager.get_nodes_by_label("PoliticalActor")
    
    assert nodes == ["Gavin Newsom", "Jerry Brown"]
    mock_driver.session.assert_called_once()
    mock_session.execute_read.assert_called_once()
    mock_tx.run.assert_called_once_with("MATCH (n:PoliticalActor) RETURN n.name as name")

def test_get_nodes_by_label_invalid_identifier():
    mock_driver = MagicMock()
    manager = Neo4jAdapter(
        uri="bolt://localhost:7687",
        username="neo4j",
        password="password",
        driver=mock_driver
    )
    with pytest.raises(ValueError) as exc_info:
        manager.get_nodes_by_label("Political;Actor")
    assert "Invalid character in node label" in str(exc_info.value)

def test_get_nodes_by_label_failure():
    mock_driver = MagicMock()
    mock_session = MagicMock()
    mock_driver.session.return_value.__enter__.return_value = mock_session
    mock_session.execute_read.side_effect = Exception("Neo4j database query failed")
    
    manager = Neo4jAdapter(
        uri="bolt://localhost:7687",
        username="neo4j",
        password="password",
        driver=mock_driver
    )
    with pytest.raises(Neo4jConnectionError) as exc_info:
        manager.get_nodes_by_label("PoliticalActor")
    assert "Failed to retrieve nodes for label" in str(exc_info.value)

@pytest.mark.no_mock_ensure_index
def test_connect_creates_and_verifies_vector_index():
    mock_driver = MagicMock()
    mock_session = MagicMock()
    
    mock_driver.session.return_value.__enter__.return_value = mock_session
    
    # Mock return value for SHOW INDEXES query
    mock_result = MagicMock()
    mock_result.peek.return_value = {"name": "chunk_vector_index"}
    mock_session.run.return_value = mock_result
    
    manager = Neo4jAdapter(
        uri="bolt://localhost:7687",
        username="neo4j",
        password="password",
        driver=mock_driver
    )
    
    manager.connect()
    
    assert mock_session.run.call_count == 2
    
    # 1. Check create index Cypher
    create_query = mock_session.run.call_args_list[0][0][0]
    assert "CREATE VECTOR INDEX chunk_vector_index" in create_query
    assert "FOR (c:Chunk)" in create_query
    assert "ON (c.embedding)" in create_query
    assert "768" in create_query
    
    # 2. Check verify index Cypher
    verify_query = mock_session.run.call_args_list[1][0][0]
    assert "SHOW INDEXES" in verify_query
    assert "chunk_vector_index" in verify_query

def test_ingest_article():
    mock_driver = MagicMock()
    mock_session = MagicMock()
    mock_tx = MagicMock()
    
    mock_driver.session.return_value.__enter__.return_value = mock_session
    mock_session.execute_write.side_effect = lambda func, *args, **kwargs: func(mock_tx, *args, **kwargs)
    
    manager = Neo4jAdapter(
        uri="bolt://localhost:7687",
        username="neo4j",
        password="password",
        driver=mock_driver
    )
    
    article = SourceArticle(
        url="http://example.com/1",
        title="Breaking News",
        author="John Doe",
        published_date="2026-06-27",
        content="Article content"
    )
    manager.ingest_article(article)
    
    mock_tx.run.assert_called_once()
    query = mock_tx.run.call_args[0][0]
    kwargs = mock_tx.run.call_args[1]
    
    assert "MERGE (a:NewsArticle {url: $url})" in query
    assert "SET a.title = $title" in query
    assert "a.author = $author" in query
    assert "a.published_date = $published_date" in query
    assert kwargs["url"] == "http://example.com/1"
    assert kwargs["title"] == "Breaking News"
    assert kwargs["author"] == "John Doe"
    assert kwargs["published_date"] == "2026-06-27"

def test_ingest_chunk():
    mock_driver = MagicMock()
    mock_session = MagicMock()
    mock_tx = MagicMock()
    
    mock_driver.session.return_value.__enter__.return_value = mock_session
    mock_session.execute_write.side_effect = lambda func, *args, **kwargs: func(mock_tx, *args, **kwargs)
    
    manager = Neo4jAdapter(
        uri="bolt://localhost:7687",
        username="neo4j",
        password="password",
        driver=mock_driver
    )
    
    article = SourceArticle(
        url="http://example.com/1",
        title="Breaking News",
        content="Article content"
    )
    
    chunk = ArticleChunk(
        text="Gavin Newsom did something.",
        start_index=0,
        end_index=27,
        index=0
    )
    
    manager.ingest_chunk(
        article=article,
        chunk=chunk,
        embedding=[0.1, 0.2, 0.3]
    )
    
    mock_tx.run.assert_called_once()
    query = mock_tx.run.call_args[0][0]
    kwargs = mock_tx.run.call_args[1]
    
    assert "MERGE (c:Chunk {id: $chunk_id})" in query
    assert "SET c.text = $text" in query
    assert "c.chunk_index = $chunk_index" in query
    assert "c.embedding = $embedding" in query
    assert "MATCH (a:NewsArticle {url: $url})" in query
    assert "MERGE (a)-[:HAS_CHUNK]->(c)" in query
    assert kwargs["url"] == "http://example.com/1"
    assert kwargs["chunk_id"] == "http://example.com/1#chunk_0"
    assert kwargs["text"] == "Gavin Newsom did something."
    assert kwargs["chunk_index"] == 0
    assert kwargs["embedding"] == [0.1, 0.2, 0.3]

def test_ingest_chunk_extraction():
    mock_driver = MagicMock()
    mock_session = MagicMock()
    mock_tx = MagicMock()
    
    mock_driver.session.return_value.__enter__.return_value = mock_session
    mock_session.execute_write.side_effect = lambda func, *args, **kwargs: func(mock_tx, *args, **kwargs)
    
    manager = Neo4jAdapter(
        uri="bolt://localhost:7687",
        username="neo4j",
        password="password",
        driver=mock_driver
    )
    
    extraction = ExtractionResult(
        nodes=[
            Node(name="California Teachers Association", label="Organization", sub_labels=["LaborUnion"]),
            Node(name="Yes on Schools", label="Campaign", sub_labels=["BallotMeasureCampaign"]),
            Node(name="Education (K–12)", label="PolicyArea")
        ],
        relationships=[
            Relationship(
                source="California Teachers Association",
                target="Yes on Schools",
                relationship_type="FUNDED",
                properties={"status": "active"}
            )
        ]
    )
    
    manager.ingest_chunk_extraction(
        chunk_id="http://example.com/1#chunk_0",
        extraction=extraction
    )
    
    # Three node merges and mentions, one topic edge, and one extracted relationship.
    assert mock_tx.run.call_count == 8
    
    # Inspect calls
    calls = [call[0][0] for call in mock_tx.run.call_args_list]
    assert any("MERGE (n:Organization:LaborUnion {id: $node_id})" in q for q in calls)
    assert any("MERGE (n:Campaign:BallotMeasureCampaign {id: $node_id})" in q for q in calls)
    assert any("[:MENTIONED_IN]" in q for q in calls)
    assert any("MERGE (c)-[:DISCUSSES_TOPIC]->(n)" in q for q in calls)
    assert not any("NewsArticle" in q and "DISCUSSES_TOPIC" in q for q in calls)
    assert any("MERGE (src)-[r:FUNDED]->(tgt)" in q for q in calls)

    node_calls = [call for call in mock_tx.run.call_args_list if "MERGE (n:" in call[0][0]]
    assert {call[1]["provenance"] for call in node_calls} == {"news-derived"}
    rel_call = next(call for call in mock_tx.run.call_args_list if "[r:FUNDED]" in call[0][0])
    assert rel_call[1]["properties"] == {"status": "active", "provenance": "news-derived"}


def test_ingest_chunk_extraction_rejects_unvalidated_sub_label():
    mock_driver = MagicMock()
    mock_session = MagicMock()
    mock_tx = MagicMock()
    mock_driver.session.return_value.__enter__.return_value = mock_session
    mock_session.execute_write.side_effect = lambda func: func(mock_tx)
    manager = Neo4jAdapter("bolt://localhost:7687", "neo4j", "password", driver=mock_driver)

    extraction = ExtractionResult(nodes=[
        Node(name="Some Club", label="Organization", sub_labels=["Club"]),
    ])

    with pytest.raises(Neo4jConnectionError, match="Invalid sub-label for Organization: Club"):
        manager.ingest_chunk_extraction("article#chunk_0", extraction)
    mock_tx.run.assert_not_called()


def test_bill_session_participates_in_node_primary_key():
    mock_driver = MagicMock()
    mock_session = MagicMock()
    mock_tx = MagicMock()
    mock_driver.session.return_value.__enter__.return_value = mock_session
    mock_session.execute_write.side_effect = lambda func: func(mock_tx)
    manager = Neo4jAdapter("bolt://localhost:7687", "neo4j", "password", driver=mock_driver)
    extraction = ExtractionResult(nodes=[
        Node(name="Assembly Bill 218", label="Bill", properties={"number": "AB 218"}),
    ])

    manager.ingest_chunk_extraction(
        "article#chunk_0",
        extraction,
        {"AB 218": {"session": "2019-2020", "session_verified": True,
                    "session_inferred": False, "needs_review": False}},
    )
    manager.ingest_chunk_extraction(
        "article#chunk_1",
        extraction,
        {"AB 218": {"session": "2025-2026", "session_verified": True,
                    "session_inferred": False, "needs_review": False}},
    )

    node_calls = [call for call in mock_tx.run.call_args_list if "MERGE (n:Bill" in call[0][0]]
    assert [call[1]["node_id"] for call in node_calls] == [
        "Bill:2019-2020:ab-218",
        "Bill:2025-2026:ab-218",
    ]
    assert node_calls[0][1]["properties"]["session_verified"] is True

def test_context_manager_lifecycle():
    mock_driver = MagicMock()
    mock_driver.verify_connectivity.return_value = None
    
    manager = Neo4jAdapter(
        uri="bolt://localhost:7687",
        username="neo4j",
        password="password",
        driver=mock_driver
    )
    
    with manager as m:
        assert m is manager
        mock_driver.verify_connectivity.assert_called_once()
        
    mock_driver.close.assert_called_once()

def test_context_manager_failure_closes_driver():
    mock_driver = MagicMock()
    mock_driver.verify_connectivity.side_effect = Exception("Connectivity failed")
    
    manager = Neo4jAdapter(
        uri="bolt://localhost:7687",
        username="neo4j",
        password="password",
        driver=mock_driver
    )
    
    with pytest.raises(Neo4jConnectionError):
        with manager:
            pass
            
    mock_driver.close.assert_called_once()

def test_neo4j_adapter_health_check_success():
    mock_driver = MagicMock()
    mock_session = MagicMock()
    mock_result = MagicMock()
    
    mock_driver.session.return_value.__enter__.return_value = mock_session
    mock_session.run.return_value = mock_result
    mock_result.single.return_value = [1]
    
    manager = Neo4jAdapter(
        uri="bolt://localhost:7687",
        username="neo4j",
        password="password",
        driver=mock_driver
    )
    assert manager.health_check() is True
    mock_session.run.assert_called_once_with("RETURN 1")

def test_neo4j_adapter_health_check_failure():
    mock_driver = MagicMock()
    mock_session = MagicMock()
    
    mock_driver.session.return_value.__enter__.return_value = mock_session
    mock_session.run.side_effect = Exception("Cypher query failed")
    
    manager = Neo4jAdapter(
        uri="bolt://localhost:7687",
        username="neo4j",
        password="password",
        driver=mock_driver
    )
    assert manager.health_check() is False
