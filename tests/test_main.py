import pytest
import sys
import os
import json
import logging
from unittest.mock import patch, MagicMock
from knowledge_map.cli.main import main, setup_logging
from knowledge_map.utils.console import ConsoleNotifier
from knowledge_map.adapters.neo4j_db import Neo4jConfigError, Neo4jConnectionError
from knowledge_map.core.exceptions import PipelineLockError, PipelineRateLimitError
from knowledge_map.core.ingestion import BatchIngestionService
from knowledge_map.adapters.sqlite_db import init_db, save_story
from knowledge_map.config import BatchIngestionSettings

def test_console_notifier_warning_banner(capsys):
    ConsoleNotifier.print_warning_banner("Test Title", "Test Message", {"key1": "val1"})
    captured = capsys.readouterr()
    assert "TEST TITLE" in captured.err
    assert "Test Message" in captured.err
    assert "key1" in captured.err
    assert "val1" in captured.err

def test_batch_ingestion_rate_limit_lock_notifier(tmp_path):
    db_file = tmp_path / "test_locking_alert.db"
    db_path = str(db_file)
    init_db(db_path)
    for i in range(1, 4):
        save_story({
            "title": f"Story {i}",
            "url": f"http://example.com/{i}",
            "content": f"Content {i}"
        }, db_path=db_path)
        
    mock_pipeline = MagicMock()
    mock_status_tracker = MagicMock()
    mock_pipeline.status_tracker = mock_status_tracker
    rate_err = PipelineRateLimitError("Rate limit hit", component="embedding", original_exception=ValueError("429"))
    mock_pipeline.run.side_effect = rate_err
    
    lock_file_path = str(tmp_path / "pipeline.lock")
    settings = BatchIngestionSettings(
        db_path=db_path,
        consecutive_failures_limit=3,
        lock_file_path=lock_file_path
    )
    service = BatchIngestionService(pipeline=mock_pipeline, settings=settings)
    
    with patch("knowledge_map.core.ingestion.ConsoleNotifier") as MockNotifier:
        with pytest.raises(PipelineLockError):
            service.run()
        MockNotifier.notify_lock_triggered.assert_called_once_with(
            component="embedding",
            lock_file_path=lock_file_path,
            error_message="Rate limit hit"
        )

# CLI Main Ingest tests
def test_cli_ingest_success():
    with patch("knowledge_map.cli.main.BatchIngestionService") as MockService, \
         patch("knowledge_map.cli.main.Neo4jAdapter") as MockNeo4j, \
         patch("knowledge_map.cli.main.PydanticAIEmbeddingAdapter"), \
         patch("knowledge_map.cli.main.PydanticAICoreferenceAdapter"), \
         patch("knowledge_map.cli.main.PydanticAIEntityExtractionAdapter"), \
         patch("knowledge_map.cli.main.LocalFileDLQAdapter"), \
         patch("knowledge_map.cli.main.SQLiteStatusTracker"):
         
         try:
             main(["ingest"])
         except SystemExit as e:
             assert e.code == 0
         MockService.return_value.run.assert_called_once()

def test_cli_ingest_lock_detected_at_startup(tmp_path):
    lock_file = tmp_path / "pipeline.lock"
    lock_data = {
        "timestamp": "2026-06-30T12:00:00Z",
        "component": "embedding",
        "error_message": "Rate limit reached"
    }
    with open(lock_file, "w") as f:
        json.dump(lock_data, f)
        
    with patch("knowledge_map.config.settings.batch_ingestion.lock_file_path", str(lock_file)), \
         patch("knowledge_map.cli.main.Neo4jAdapter"), \
         patch("knowledge_map.cli.main.ConsoleNotifier") as MockNotifier:
         
         with pytest.raises(SystemExit) as exc_info:
             main(["ingest"])
             
         assert exc_info.value.code == 1
         MockNotifier.notify_lock_detected.assert_called_once_with(
             component="embedding",
             lock_file_path=str(lock_file),
             timestamp="2026-06-30T12:00:00Z",
             error_message="Rate limit reached"
         )

def test_cli_ingest_neo4j_config_error():
    with patch("knowledge_map.cli.main.Neo4jAdapter", side_effect=Neo4jConfigError("URI missing")), \
         patch("knowledge_map.cli.main.ConsoleNotifier") as MockNotifier:
         
         with pytest.raises(SystemExit) as exc_info:
             main(["ingest"])
         assert exc_info.value.code == 1
         MockNotifier.notify_critical_failure.assert_called_once_with(
             error_title="Configuration Error",
             message="Neo4j Configuration is invalid.",
             details={"Error": "URI missing"}
         )

def test_cli_ingest_neo4j_connection_error():
    with patch("knowledge_map.cli.main.Neo4jAdapter", side_effect=Neo4jConnectionError("Conn failed")), \
         patch("knowledge_map.cli.main.ConsoleNotifier") as MockNotifier:
         
         with pytest.raises(SystemExit) as exc_info:
             main(["ingest"])
         assert exc_info.value.code == 1
         MockNotifier.notify_critical_failure.assert_called_once_with(
             error_title="Connection Error",
             message="Failed to connect to Neo4j database.",
             details={"Error": "Conn failed"}
         )

# CLI Clear tests
def test_cli_clear_success(capsys):
    with patch("knowledge_map.cli.main.Neo4jAdapter") as MockAdapter:
        mock_instance = MockAdapter.return_value
        try:
            main(["clear"])
        except SystemExit as e:
            assert e.code == 0
        MockAdapter.assert_called_once()
        mock_instance.clear_database.assert_called_once()
        mock_instance.close.assert_called_once()
        captured = capsys.readouterr()
        assert "Neo4j database cleared successfully" in captured.out

def test_cli_clear_config_error():
    with patch("knowledge_map.cli.main.Neo4jAdapter", side_effect=Neo4jConfigError("URI missing")), \
         patch("knowledge_map.cli.main.ConsoleNotifier") as MockNotifier:
         
         with pytest.raises(SystemExit) as exc_info:
             main(["clear"])
         assert exc_info.value.code == 1
         MockNotifier.notify_critical_failure.assert_called_once_with(
             error_title="Configuration Error",
             message="Neo4j Configuration is invalid.",
             details={"Error": "URI missing"}
         )

# CLI Analyze tests
def test_cli_analyze_success(capsys):
    with patch("knowledge_map.cli.main.Neo4jAdapter") as MockAdapter:
        mock_instance = MockAdapter.return_value
        mock_instance.get_distinct_labels.return_value = ["PoliticalActor"]
        mock_instance.get_nodes_by_label.return_value = ["Gavin Newsom"]
        try:
            main(["analyze"])
        except SystemExit as e:
            assert e.code == 0
        MockAdapter.assert_called_once()
        mock_instance.get_distinct_labels.assert_called_once()
        mock_instance.close.assert_called_once()
        captured = capsys.readouterr()
        assert "Distinct node labels" in captured.out

def test_cli_analyze_connection_error():
    with patch("knowledge_map.cli.main.Neo4jAdapter") as MockAdapter, \
         patch("knowledge_map.cli.main.ConsoleNotifier") as MockNotifier:
         mock_instance = MockAdapter.return_value
         mock_instance.get_distinct_labels.side_effect = Neo4jConnectionError("Conn failed")
         
         with pytest.raises(SystemExit) as exc_info:
             main(["analyze"])
         assert exc_info.value.code == 1
         MockNotifier.notify_critical_failure.assert_called_once_with(
             error_title="Connection Error",
             message="Failed to connect to Neo4j database.",
             details={"Error": "Conn failed"}
         )

def test_setup_logging(tmp_path):
    log_file = tmp_path / "test_pipeline.log"
    setup_logging(log_file_path=str(log_file), log_level=logging.DEBUG)
    
    root_logger = logging.getLogger()
    assert len(root_logger.handlers) == 2
    
    handler_types = [type(h).__name__ for h in root_logger.handlers]
    assert "StreamHandler" in handler_types
    assert "RotatingFileHandler" in handler_types
    
    test_logger = logging.getLogger("test_setup_logging_logger")
    test_logger.debug("test log message")
    
    for h in root_logger.handlers:
        h.close()
        
    with open(log_file, "r") as f:
        content = f.read()
        assert "test log message" in content
        assert "DEBUG" in content

def test_console_notifier_non_tty(caplog):
    with patch("sys.stderr.isatty", return_value=False):
        with caplog.at_level(logging.CRITICAL):
            ConsoleNotifier.print_warning_banner("Test Title", "Test Message", {"key1": "val1"})
            
        assert len(caplog.records) == 1
        record = caplog.records[0]
        assert record.levelname == "CRITICAL"
        assert "[TEST TITLE] Test Message" in record.message
        assert "key1=val1" in record.message
