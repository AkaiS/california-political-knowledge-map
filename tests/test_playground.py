import pytest
from unittest.mock import MagicMock, patch
from playground import Neo4jManager, Neo4jConfigError, Neo4jConnectionError, main, cosine_similarity, get_embedding_embedder

@pytest.fixture(autouse=True)
def mock_ensure_vector_index(request):
    if "no_mock_ensure_index" in request.keywords:
        yield
    else:
        with patch("playground.Neo4jManager._ensure_vector_index", create=True) as m:
            yield m



def test_missing_uri_raises_error():
    with pytest.raises(Neo4jConfigError) as exc_info:
        Neo4jManager(uri="", username="neo4j", password="password")
    assert "NEO4J_URI environment variable is missing or empty" in str(exc_info.value)

def test_missing_username_raises_error():
    with pytest.raises(Neo4jConfigError) as exc_info:
        Neo4jManager(uri="bolt://localhost:7687", username="", password="password")
    assert "NEO4J_USERNAME environment variable is missing or empty" in str(exc_info.value)

def test_missing_password_raises_error():
    with pytest.raises(Neo4jConfigError) as exc_info:
        Neo4jManager(uri="bolt://localhost:7687", username="neo4j", password="")
    assert "NEO4J_PASSWORD environment variable is missing or empty" in str(exc_info.value)

def test_clear_database_executes_correct_query():
    mock_driver = MagicMock()
    mock_session = MagicMock()
    mock_tx = MagicMock()
    
    mock_driver.session.return_value.__enter__.return_value = mock_session
    
    def fake_execute_write(func, *args, **kwargs):
        return func(mock_tx, *args, **kwargs)
    mock_session.execute_write.side_effect = fake_execute_write
    
    manager = Neo4jManager(
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
    
    manager = Neo4jManager(
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
    
    manager = Neo4jManager(
        uri="bolt://localhost:7687",
        username="neo4j",
        password="password",
        driver=mock_driver
    )
    
    with pytest.raises(Neo4jConnectionError) as exc_info:
        manager.clear_database()
    assert "Failed to clear Neo4j database" in str(exc_info.value)

def test_cli_clear_success(capsys):
    with patch("playground.Neo4jManager") as MockManager:
        mock_instance = MockManager.return_value
        
        try:
            main(["clear"])
        except SystemExit as e:
            assert e.code == 0
            
        MockManager.assert_called_once()
        mock_instance.clear_database.assert_called_once()
        mock_instance.close.assert_called_once()
        
        captured = capsys.readouterr()
        assert "Neo4j database cleared successfully" in captured.out

def test_cli_clear_config_error(capsys):
    with patch("playground.Neo4jManager") as MockManager:
        MockManager.side_effect = Neo4jConfigError("NEO4J_URI environment variable is missing or empty.")
        
        with pytest.raises(SystemExit) as exc_info:
            main(["clear"])
        assert exc_info.value.code == 1
        
        captured = capsys.readouterr()
        assert "Configuration Error:" in (captured.err + captured.out)
        assert "NEO4J_URI environment variable is missing" in (captured.err + captured.out)

def test_cli_clear_connection_error(capsys):
    with patch("playground.Neo4jManager") as MockManager:
        mock_instance = MockManager.return_value
        mock_instance.clear_database.side_effect = Neo4jConnectionError("Could not connect to Neo4j database")
        
        with pytest.raises(SystemExit) as exc_info:
            main(["clear"])
        assert exc_info.value.code == 1
        
        captured = capsys.readouterr()
        assert "Connection Error:" in (captured.err + captured.out)
        assert "Could not connect to Neo4j database" in (captured.err + captured.out)

from extraction import ExtractionResult, Node, Relationship
from chunking import ArticleChunk

@pytest.fixture
def mock_pipeline_deps():
    mock_embedder = MagicMock()
    async def fake_embed(texts, settings=None):
        res = MagicMock()
        res.embeddings = [[0.1] * 768] * len(texts)
        return res
    mock_embedder.embed_documents.side_effect = fake_embed

    with patch("playground.resolve_coreferences", side_effect=lambda x: x) as mock_resolve, \
         patch("playground.replace_tags_with_entities", side_effect=lambda x: x) as mock_replace, \
         patch("playground.chunk_article", side_effect=lambda text: [ArticleChunk(text=text, start_index=0, end_index=len(text), index=0)]) as mock_chunk, \
         patch("playground.get_embedding_embedder", return_value=mock_embedder) as mock_get_embedder:
        yield {
            "resolve": mock_resolve,
            "replace": mock_replace,
            "chunk": mock_chunk,
            "get_embedder": mock_get_embedder,
            "embedder": mock_embedder
        }

def test_cli_run_dry_run_with_text(capsys, mock_pipeline_deps):
    mock_result = ExtractionResult(
        nodes=[Node(name="Gavin Newsom", label="PoliticalActor")],
        relationships=[]
    )
    with patch("playground.extract_entities", return_value=mock_result) as mock_extract:
        try:
            main(["run", "--dry-run", "--text", "My custom text"])
        except SystemExit as e:
            assert e.code == 0
            
        mock_extract.assert_called_once_with("My custom text")
        captured = capsys.readouterr()
        assert "Gavin Newsom" in captured.out
        assert "PoliticalActor" in captured.out

def test_cli_run_dry_run_fallback_text(capsys, mock_pipeline_deps):
    mock_result = ExtractionResult(
        nodes=[Node(name="Fallback Actor", label="PoliticalActor")],
        relationships=[]
    )
    with patch("playground.get_last_n_stories", return_value=[]), \
         patch("playground.extract_entities", return_value=mock_result) as mock_extract:
        try:
            main(["run", "--dry-run"])
        except SystemExit as e:
            assert e.code == 0
            
        mock_extract.assert_called_once()
        called_args, _ = mock_extract.call_args
        assert len(called_args[0]) > 0
        
        captured = capsys.readouterr()
        assert "Fallback Actor" in captured.out

def test_cli_run_dry_run_sqlite_text(capsys, mock_pipeline_deps):
    mock_result = ExtractionResult(
        nodes=[Node(name="SQLite Actor", label="PoliticalActor")],
        relationships=[]
    )
    mock_stories = [{"title": "My Title", "content": "Article body about politics"}]
    with patch("playground.get_last_n_stories", return_value=mock_stories), \
         patch("playground.extract_entities", return_value=mock_result) as mock_extract:
        try:
            main(["run", "--dry-run"])
        except SystemExit as e:
            assert e.code == 0
            
        mock_extract.assert_called_once_with("Article body about politics")
        
        captured = capsys.readouterr()
        assert "SQLite Actor" in captured.out

from playground import ingest_extraction_result

def test_ingest_extraction_result_nodes():
    mock_tx = MagicMock()
    extraction = ExtractionResult(
        nodes=[
            Node(name="Gavin Newsom", label="PoliticalActor", properties={"role": "Governor"}),
            Node(name="Democratic Party", label="Organization")
        ],
        relationships=[]
    )
    
    ingest_extraction_result(mock_tx, extraction, source_url="http://example.com/story")
    
    assert mock_tx.run.call_count == 2
    
    # Check first call (Gavin Newsom)
    first_call_args = mock_tx.run.call_args_list[0]
    first_query = first_call_args[0][0]
    first_kwargs = first_call_args[1]
    
    assert "MERGE (n:PoliticalActor {name: $name})" in first_query
    assert "SET n.source_url = $source_url" in first_query
    assert "n += $properties" in first_query
    assert first_kwargs["name"] == "Gavin Newsom"
    assert first_kwargs["source_url"] == "http://example.com/story"
    assert first_kwargs["properties"] == {"role": "Governor"}
    
    # Check second call (Democratic Party)
    second_call_args = mock_tx.run.call_args_list[1]
    second_query = second_call_args[0][0]
    second_kwargs = second_call_args[1]
    
    assert "MERGE (n:Organization {name: $name})" in second_query
    assert second_kwargs["name"] == "Democratic Party"
    assert second_kwargs["source_url"] == "http://example.com/story"
    assert second_kwargs["properties"] == {}

def test_ingest_extraction_result_relationships():
    mock_tx = MagicMock()
    extraction = ExtractionResult(
        nodes=[
            Node(name="Gavin Newsom", label="PoliticalActor"),
            Node(name="Democratic Party", label="Organization")
        ],
        relationships=[
            Relationship(
                source="Gavin Newsom",
                target="Democratic Party",
                relationship_type="MEMBER_OF",
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
    
    assert "MATCH (src:PoliticalActor {name: $src_name})" in rel_query
    assert "MATCH (src:PoliticalActor {name: $src_name}), (tgt:Organization {name: $tgt_name})" in rel_query or "MATCH (src:PoliticalActor {name: $src_name}),(tgt:Organization {name: $tgt_name})" in rel_query
    assert "MERGE (src)-[r:MEMBER_OF]->(tgt)" in rel_query
    assert "SET r += $properties" in rel_query
    
    assert rel_kwargs["src_name"] == "Gavin Newsom"
    assert rel_kwargs["tgt_name"] == "Democratic Party"
    assert rel_kwargs["properties"] == {"status": "Active"}

def test_ingest_extraction_result_invalid_identifiers():
    mock_tx = MagicMock()
    
    # 1. Invalid node label
    extraction_bad_label = ExtractionResult(
        nodes=[Node(name="Gavin Newsom", label="Political`Actor")],
        relationships=[]
    )
    with pytest.raises(ValueError) as exc_info:
        ingest_extraction_result(mock_tx, extraction_bad_label)
    assert "Invalid character in node label" in str(exc_info.value)
    
    # 2. Invalid relationship type
    extraction_bad_rel = ExtractionResult(
        nodes=[
            Node(name="Gavin Newsom", label="PoliticalActor"),
            Node(name="Democratic Party", label="Organization")
        ],
        relationships=[
            Relationship(
                source="Gavin Newsom",
                target="Democratic Party",
                relationship_type="MEMBER`OF"
            )
        ]
    )
    with pytest.raises(ValueError) as exc_info:
        ingest_extraction_result(mock_tx, extraction_bad_rel)
    assert "Invalid character in relationship type" in str(exc_info.value)

def test_cli_run_integration_all_stories(capsys, mock_pipeline_deps):
    mock_stories = [
        {"title": "Story 1", "url": "http://example.com/1", "content": "Content 1"},
        {"title": "Story 2", "url": "http://example.com/2", "content": "Content 2"}
    ]
    
    mock_result1 = ExtractionResult(nodes=[Node(name="Actor 1", label="PoliticalActor")], relationships=[])
    mock_result2 = ExtractionResult(nodes=[Node(name="Actor 2", label="PoliticalActor")], relationships=[])
    
    def side_effect(text, *args, **kwargs):
        if text == "Content 1":
            return mock_result1
        elif text == "Content 2":
            return mock_result2
        raise ValueError(f"Unexpected content: {text}")
        
    with patch("playground.Neo4jManager") as MockManager, \
         patch("playground.get_all_stories", return_value=mock_stories) as mock_get_all, \
         patch("playground.extract_entities", side_effect=side_effect) as mock_extract:
         
        mock_manager_instance = MockManager.return_value
        
        try:
            main(["run"])
        except SystemExit as e:
            assert e.code == 0
            
        MockManager.assert_called_once()
        mock_get_all.assert_called_once()
        
        assert mock_pipeline_deps["resolve"].call_count == 2
        assert mock_pipeline_deps["chunk"].call_count == 2
        
        assert mock_extract.call_count == 2
        mock_extract.assert_any_call("Content 1")
        mock_extract.assert_any_call("Content 2")
        
        assert mock_manager_instance.ingest_article.call_count == 2
        mock_manager_instance.ingest_article.assert_any_call(
            url="http://example.com/1",
            title="Story 1",
            author=None,
            published_date=None
        )
        mock_manager_instance.ingest_article.assert_any_call(
            url="http://example.com/2",
            title="Story 2",
            author=None,
            published_date=None
        )
        
        assert mock_manager_instance.ingest_chunk.call_count == 2
        mock_manager_instance.ingest_chunk.assert_any_call(
            url="http://example.com/1",
            chunk_id="http://example.com/1#chunk_0",
            text="Content 1",
            chunk_index=0,
            embedding=[0.1] * 768
        )
        mock_manager_instance.ingest_chunk.assert_any_call(
            url="http://example.com/2",
            chunk_id="http://example.com/2#chunk_0",
            text="Content 2",
            chunk_index=0,
            embedding=[0.1] * 768
        )
        
        assert mock_manager_instance.ingest_chunk_extraction.call_count == 2
        mock_manager_instance.ingest_chunk_extraction.assert_any_call(
            chunk_id="http://example.com/1#chunk_0",
            extraction=mock_result1
        )
        mock_manager_instance.ingest_chunk_extraction.assert_any_call(
            chunk_id="http://example.com/2#chunk_0",
            extraction=mock_result2
        )
        
        mock_manager_instance.close.assert_called_once()
        
        captured = capsys.readouterr()
        assert "Successfully processed 2 stories" in captured.out

def test_cli_run_pipeline_integration(mock_pipeline_deps):
    mock_story = {
        "id": 1,
        "title": "Pipeline News",
        "url": "http://example.com/pipeline",
        "author": "Alice",
        "published_date": "2026-06-28",
        "content": "Newsom signed AB-5. He was happy."
    }
    
    mock_pipeline_deps["resolve"].side_effect = None
    mock_pipeline_deps["resolve"].return_value = "Gavin Newsom signed AB-5. <ref entity=\"Gavin Newsom\">He</ref> was happy."
    mock_pipeline_deps["replace"].side_effect = None
    mock_pipeline_deps["replace"].return_value = "Gavin Newsom signed AB-5. Gavin Newsom was happy."
    
    mock_chunks = [
        ArticleChunk(text="Gavin Newsom signed AB-5.", start_index=0, end_index=25, index=0),
        ArticleChunk(text="Gavin Newsom was happy.", start_index=26, end_index=49, index=1)
    ]
    mock_pipeline_deps["chunk"].side_effect = None
    mock_pipeline_deps["chunk"].return_value = mock_chunks
    
    mock_extraction_chunk0 = ExtractionResult(
        nodes=[
            Node(name="Gavin Newsom", label="PoliticalActor"),
            Node(name="AB-5", label="PublicPolicy")
        ],
        relationships=[
            Relationship(source="Gavin Newsom", target="AB-5", relationship_type="SIGNED")
        ]
    )
    mock_extraction_chunk1 = ExtractionResult(
        nodes=[Node(name="Gavin Newsom", label="PoliticalActor")],
        relationships=[]
    )
    
    def mock_extract(text, *args, **kwargs):
        if "signed" in text:
            return mock_extraction_chunk0
        elif "happy" in text:
            return mock_extraction_chunk1
        return ExtractionResult(nodes=[], relationships=[])
        
    with patch("playground.Neo4jManager") as MockManager, \
         patch("playground.get_all_stories", return_value=[mock_story]), \
         patch("playground.extract_entities", side_effect=mock_extract) as mock_extract_entities:
         
        mock_manager_instance = MockManager.return_value
        
        main(["run"])
        
        mock_pipeline_deps["resolve"].assert_called_once_with("Newsom signed AB-5. He was happy.")
        mock_pipeline_deps["replace"].assert_called_once_with("Gavin Newsom signed AB-5. <ref entity=\"Gavin Newsom\">He</ref> was happy.")
        mock_pipeline_deps["chunk"].assert_called_once_with("Gavin Newsom signed AB-5. Gavin Newsom was happy.")
        mock_pipeline_deps["get_embedder"].assert_called_once()
        
        mock_manager_instance.ingest_article.assert_called_once_with(
            url="http://example.com/pipeline",
            title="Pipeline News",
            author="Alice",
            published_date="2026-06-28"
        )
        
        assert mock_manager_instance.ingest_chunk.call_count == 2
        mock_manager_instance.ingest_chunk.assert_any_call(
            url="http://example.com/pipeline",
            chunk_id="http://example.com/pipeline#chunk_0",
            text="Gavin Newsom signed AB-5.",
            chunk_index=0,
            embedding=[0.1] * 768
        )
        mock_manager_instance.ingest_chunk.assert_any_call(
            url="http://example.com/pipeline",
            chunk_id="http://example.com/pipeline#chunk_1",
            text="Gavin Newsom was happy.",
            chunk_index=1,
            embedding=[0.1] * 768
        )
        
        assert mock_extract_entities.call_count == 2
        mock_extract_entities.assert_any_call("Gavin Newsom signed AB-5.")
        mock_extract_entities.assert_any_call("Gavin Newsom was happy.")
        
        assert mock_manager_instance.ingest_chunk_extraction.call_count == 2
        mock_manager_instance.ingest_chunk_extraction.assert_any_call(
            chunk_id="http://example.com/pipeline#chunk_0",
            extraction=mock_extraction_chunk0
        )
        mock_manager_instance.ingest_chunk_extraction.assert_any_call(
            chunk_id="http://example.com/pipeline#chunk_1",
            extraction=mock_extraction_chunk1
        )
        
        mock_manager_instance.close.assert_called_once()

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
    
    manager = Neo4jManager(
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
    
    manager = Neo4jManager(
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
    
    manager = Neo4jManager(
        uri="bolt://localhost:7687",
        username="neo4j",
        password="password",
        driver=mock_driver
    )
    
    with pytest.raises(Neo4jConnectionError) as exc_info:
        manager.get_distinct_labels()
    assert "Failed to retrieve node labels from Neo4j" in str(exc_info.value)

def test_cli_analyze_success(capsys):
    with patch("playground.Neo4jManager") as MockManager:
        mock_instance = MockManager.return_value
        mock_instance.get_distinct_labels.return_value = ["Organization", "PoliticalActor"]
        
        try:
            main(["analyze"])
        except SystemExit as e:
            assert e.code == 0
            
        MockManager.assert_called_once()
        mock_instance.get_distinct_labels.assert_called_once()
        mock_instance.close.assert_called_once()
        
        captured = capsys.readouterr()
        assert "Distinct node labels" in captured.out
        assert "- Organization" in captured.out
        assert "- PoliticalActor" in captured.out

def test_cli_analyze_empty(capsys):
    with patch("playground.Neo4jManager") as MockManager:
        mock_instance = MockManager.return_value
        mock_instance.get_distinct_labels.return_value = []
        
        try:
            main(["analyze"])
        except SystemExit as e:
            assert e.code == 0
            
        MockManager.assert_called_once()
        mock_instance.get_distinct_labels.assert_called_once()
        mock_instance.close.assert_called_once()
        
        captured = capsys.readouterr()
        assert "No node labels found in the database." in captured.out

def test_cli_analyze_connection_error(capsys):
    with patch("playground.Neo4jManager") as MockManager:
        mock_instance = MockManager.return_value
        mock_instance.get_distinct_labels.side_effect = Neo4jConnectionError("Could not connect to Neo4j database")
        
        with pytest.raises(SystemExit) as exc_info:
            main(["analyze"])
        assert exc_info.value.code == 1
        
        captured = capsys.readouterr()
        assert "Connection Error:" in (captured.err + captured.out)
        assert "Could not connect to Neo4j database" in (captured.err + captured.out)

def test_cosine_similarity_exact_match():
    v1 = [1.0, 2.0, 3.0]
    v2 = [1.0, 2.0, 3.0]
    assert pytest.approx(cosine_similarity(v1, v2)) == 1.0

def test_cosine_similarity_opposite():
    v1 = [1.0, 0.0]
    v2 = [-1.0, 0.0]
    assert pytest.approx(cosine_similarity(v1, v2)) == -1.0

def test_cosine_similarity_orthogonal():
    v1 = [1.0, 0.0]
    v2 = [0.0, 1.0]
    assert pytest.approx(cosine_similarity(v1, v2)) == 0.0

def test_cosine_similarity_arbitrary():
    v1 = [3.0, 4.0]
    v2 = [4.0, 3.0]
    # Cosine similarity = (3*4 + 4*3) / (sqrt(3^2+4^2) * sqrt(4^2+3^2))
    # = (12+12) / (5 * 5) = 24 / 25 = 0.96
    assert pytest.approx(cosine_similarity(v1, v2)) == 0.96

def test_cosine_similarity_zero_vector():
    assert cosine_similarity([0.0, 0.0], [1.0, 2.0]) == 0.0
    assert cosine_similarity([1.0, 2.0], [0.0, 0.0]) == 0.0
    assert cosine_similarity([0.0, 0.0], [0.0, 0.0]) == 0.0

def test_cosine_similarity_dimension_mismatch():
    with pytest.raises(ValueError) as exc_info:
        cosine_similarity([1.0, 2.0], [1.0, 2.0, 3.0])
    assert "Vectors must be of the same dimension" in str(exc_info.value)

def test_get_nodes_by_label_success():
    mock_driver = MagicMock()
    mock_session = MagicMock()
    mock_tx = MagicMock()
    
    mock_driver.session.return_value.__enter__.return_value = mock_session
    
    def fake_execute_read(func, *args, **kwargs):
        return func(mock_tx, *args, **kwargs)
    mock_session.execute_read.side_effect = fake_execute_read
    
    mock_tx.run.return_value = [{"name": "Gavin Newsom"}, {"name": "Jerry Brown"}]
    
    manager = Neo4jManager(
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
    manager = Neo4jManager(
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
    
    manager = Neo4jManager(
        uri="bolt://localhost:7687",
        username="neo4j",
        password="password",
        driver=mock_driver
    )
    with pytest.raises(Neo4jConnectionError) as exc_info:
        manager.get_nodes_by_label("PoliticalActor")
    assert "Failed to retrieve nodes for label" in str(exc_info.value)

def test_get_embedding_embedder():
    import os
    with patch.dict(os.environ, {
        "OLLAMA_BASE_URL": "http://localhost:11434",
        "OLLAMA_EMBEDDING_MODEL": "embeddinggemma"
    }):
        embedder = get_embedding_embedder()
        assert embedder is not None
        assert embedder.model.model_name == "embeddinggemma"

def test_cli_analyze_duplicates_found(capsys):
    mock_manager = MagicMock()
    mock_manager.get_distinct_labels.return_value = ["PoliticalActor"]
    mock_manager.get_nodes_by_label.return_value = ["Gavin Newsom", "Gavin Newsome", "Jerry Brown"]
    
    mock_embedder = MagicMock()
    mock_embedding_result = MagicMock()
    mock_embedding_result.embeddings = [
        [1.0, 0.0, 0.0],  # Gavin Newsom
        [0.9, 0.1, 0.0],  # Gavin Newsome
        [0.0, 1.0, 0.0]   # Jerry Brown
    ]
    async def fake_embed_documents(inputs, settings=None):
        return mock_embedding_result
    mock_embedder.embed_documents.side_effect = fake_embed_documents

    with patch("playground.Neo4jManager", return_value=mock_manager), \
         patch("playground.get_embedding_embedder", return_value=mock_embedder):
        try:
            main(["analyze"])
        except SystemExit as e:
            assert e.code == 0
            
    captured = capsys.readouterr()
    assert "Distinct node labels:" in captured.out
    assert "- PoliticalActor" in captured.out
    assert "Potential duplicates in label 'PoliticalActor':" in captured.out
    assert "Gavin Newsom" in captured.out
    assert "Gavin Newsome" in captured.out
    assert "Jerry Brown" not in captured.out

def test_cli_analyze_no_duplicates(capsys):
    mock_manager = MagicMock()
    mock_manager.get_distinct_labels.return_value = ["PoliticalActor"]
    mock_manager.get_nodes_by_label.return_value = ["Gavin Newsom", "Jerry Brown"]
    
    mock_embedder = MagicMock()
    mock_embedding_result = MagicMock()
    mock_embedding_result.embeddings = [
        [1.0, 0.0, 0.0],
        [0.0, 1.0, 0.0]
    ]
    async def fake_embed_documents(inputs, settings=None):
        return mock_embedding_result
    mock_embedder.embed_documents.side_effect = fake_embed_documents

    with patch("playground.Neo4jManager", return_value=mock_manager), \
         patch("playground.get_embedding_embedder", return_value=mock_embedder):
        try:
            main(["analyze"])
        except SystemExit as e:
            assert e.code == 0
            
    captured = capsys.readouterr()
    assert "Distinct node labels:" in captured.out
    assert "- PoliticalActor" in captured.out
    assert "Potential duplicates" not in captured.out

def test_cli_analyze_too_few_nodes(capsys):
    mock_manager = MagicMock()
    mock_manager.get_distinct_labels.return_value = ["PoliticalActor"]
    mock_manager.get_nodes_by_label.return_value = ["Gavin Newsom"]
    
    mock_embedder = MagicMock()
    with patch("playground.Neo4jManager", return_value=mock_manager), \
         patch("playground.get_embedding_embedder", return_value=mock_embedder):
        try:
            main(["analyze"])
        except SystemExit as e:
            assert e.code == 0
            
    mock_embedder.embed_documents.assert_not_called()
    captured = capsys.readouterr()
    assert "Distinct node labels:" in captured.out

@pytest.mark.no_mock_ensure_index
def test_connect_creates_and_verifies_vector_index():
    mock_driver = MagicMock()
    mock_session = MagicMock()
    
    mock_driver.session.return_value.__enter__.return_value = mock_session
    
    # Mock return value for SHOW INDEXES query
    mock_result = MagicMock()
    mock_result.peek.return_value = {"name": "chunk_vector_index"}
    mock_session.run.return_value = mock_result
    
    manager = Neo4jManager(
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
    
    manager = Neo4jManager(
        uri="bolt://localhost:7687",
        username="neo4j",
        password="password",
        driver=mock_driver
    )
    
    manager.ingest_article(
        url="http://example.com/1",
        title="Breaking News",
        author="John Doe",
        published_date="2026-06-27"
    )
    
    mock_tx.run.assert_called_once()
    query = mock_tx.run.call_args[0][0]
    kwargs = mock_tx.run.call_args[1]
    
    assert "MERGE (a:Article {url: $url})" in query
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
    
    manager = Neo4jManager(
        uri="bolt://localhost:7687",
        username="neo4j",
        password="password",
        driver=mock_driver
    )
    
    manager.ingest_chunk(
        url="http://example.com/1",
        chunk_id="http://example.com/1#chunk_0",
        text="Gavin Newsom did something.",
        chunk_index=0,
        embedding=[0.1, 0.2, 0.3]
    )
    
    mock_tx.run.assert_called_once()
    query = mock_tx.run.call_args[0][0]
    kwargs = mock_tx.run.call_args[1]
    
    assert "MERGE (c:Chunk {id: $chunk_id})" in query
    assert "SET c.text = $text" in query
    assert "c.chunk_index = $chunk_index" in query
    assert "c.embedding = $embedding" in query
    assert "MERGE (c)-[:BELONGS_TO]->(a)" in query
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
    
    manager = Neo4jManager(
        uri="bolt://localhost:7687",
        username="neo4j",
        password="password",
        driver=mock_driver
    )
    
    extraction = ExtractionResult(
        nodes=[
            Node(name="Gavin Newsom", label="PoliticalActor", properties={"role": "Governor"}),
            Node(name="Democratic Party", label="Organization")
        ],
        relationships=[
            Relationship(
                source="Gavin Newsom",
                target="Democratic Party",
                relationship_type="MEMBER_OF",
                properties={"status": "active"}
            )
        ]
    )
    
    manager.ingest_chunk_extraction(
        chunk_id="http://example.com/1#chunk_0",
        extraction=extraction
    )
    
    # Expected: 2 node merges, 2 mentions, 1 relationship merge = 5 tx runs
    assert mock_tx.run.call_count == 5
    
    # Inspect calls
    calls = [call[0][0] for call in mock_tx.run.call_args_list]
    assert any("MERGE (n:PoliticalActor" in q for q in calls)
    assert any("MERGE (n:Organization" in q for q in calls)
    assert any("[:MENTIONED_IN]" in q for q in calls)
    assert any("MERGE (src)-[r:MEMBER_OF]->(tgt)" in q for q in calls)
    assert any("r.source_chunk_id = $chunk_id" in q for q in calls)
    
    # Check that relationship query actually uses the chunk_id parameter
    found_rel_kwargs = False
    for call in mock_tx.run.call_args_list:
        kwargs = call[1]
        if "chunk_id" in kwargs and kwargs.get("chunk_id") == "http://example.com/1#chunk_0" and "src_name" in kwargs:
            found_rel_kwargs = True
            break
    assert found_rel_kwargs


