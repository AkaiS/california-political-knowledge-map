import pytest
from unittest.mock import MagicMock, patch
from playground import Neo4jManager, Neo4jConfigError, Neo4jConnectionError, main

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

def test_cli_run_dry_run_with_text(capsys):
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

def test_cli_run_dry_run_fallback_text(capsys):
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

def test_cli_run_dry_run_sqlite_text(capsys):
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
                type="MEMBER_OF",
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
                type="MEMBER`OF"
            )
        ]
    )
    with pytest.raises(ValueError) as exc_info:
        ingest_extraction_result(mock_tx, extraction_bad_rel)
    assert "Invalid character in relationship type" in str(exc_info.value)

def test_cli_run_integration_all_stories(capsys):
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
        
        assert mock_extract.call_count == 2
        mock_extract.assert_any_call("Content 1")
        mock_extract.assert_any_call("Content 2")
        
        assert mock_manager_instance.ingest_extraction.call_count == 2
        mock_manager_instance.ingest_extraction.assert_any_call(mock_result1, source_url="http://example.com/1")
        mock_manager_instance.ingest_extraction.assert_any_call(mock_result2, source_url="http://example.com/2")
        
        mock_manager_instance.close.assert_called_once()
        
        captured = capsys.readouterr()
        assert "Successfully processed 2 stories" in captured.out

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





