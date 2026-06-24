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

