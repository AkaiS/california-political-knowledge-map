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

def test_console_notifier_warning_banner(caplog):
    with caplog.at_level(logging.CRITICAL):
        ConsoleNotifier.print_warning_banner("Test Title", "Test Message", {"key1": "val1"})
        assert any("TEST TITLE" in rec.message for rec in caplog.records)
        assert any("Test Message" in rec.message for rec in caplog.records)
        assert any("key1" in rec.message for rec in caplog.records)
        assert any("val1" in rec.message for rec in caplog.records)

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
    has_logfire = any(type(h).__name__ == "LogfireLoggingHandler" for h in root_logger.handlers)
    assert len(root_logger.handlers) == (2 if has_logfire else 1)
    
    handler_types = [type(h).__name__ for h in root_logger.handlers]
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


def test_cli_validate_articles_success(tmp_path, monkeypatch):
    from unittest.mock import MagicMock, patch
    from knowledge_map.adapters.sqlite_db import init_db
    from knowledge_map.cli.main import main
    
    db_file = tmp_path / "test_cli_validate.db"
    db_path = str(db_file)
    init_db(db_path)
    
    monkeypatch.setenv("SQLITE_DB_PATH", db_path)
    
    from unittest.mock import AsyncMock
    with patch("knowledge_map.core.validation.ArticleValidatorService") as MockServiceClass:
        mock_service_instance = MagicMock()
        mock_service_instance.validate_pending_articles = AsyncMock(return_value=[
            {"status": "VALIDATED", "url": "https://test.com/1"},
            {"status": "VALIDATION_FAILED", "url": "https://test.com/2"}
        ])
        MockServiceClass.return_value = mock_service_instance
        
        try:
            main(["validate-articles"])
        except SystemExit as e:
            assert e.code == 0
            
        mock_service_instance.validate_pending_articles.assert_called_once()


def test_cli_classifier_train_success(tmp_path, monkeypatch):
    from unittest.mock import patch
    from knowledge_map.adapters.sqlite_db import init_db, cache_scraped_html
    from knowledge_map.cli.main import main
    
    db_file = tmp_path / "test_cli_classifier_train.db"
    db_path = str(db_file)
    init_db(db_path)
    
    # Insert 3 HUMAN relevant, 3 LLM irrelevant
    for i in range(3):
        cache_scraped_html(
            f"https://example.com/human-rel/{i}", "pub1", None,
            validation="PENDING", headline="R", description="D",
            embedding=[1.0, 1.0, 0.0], relevance_status="RELEVANT",
            relevance_label_source="HUMAN", db_path=db_path
        )
        cache_scraped_html(
            f"https://example.com/llm-irrel/{i}", "pub1", None,
            validation=None, headline="I", description="D",
            embedding=[-1.0, -1.0, 0.0], relevance_status="IRRELEVANT",
            relevance_label_source="LLM", db_path=db_path
        )
        
    monkeypatch.setenv("SQLITE_DB_PATH", db_path)
    
    weights_test_path = str(tmp_path / "classifier_weights_test.json")
    with patch("classifier.trainer.WEIGHTS_PATH", weights_test_path):
        try:
            main(["classifier", "train"])
        except SystemExit as e:
            assert e.code == 0
        assert os.path.exists(weights_test_path)
        with open(weights_test_path, "r") as f:
            weights = json.load(f)
        assert weights["n_samples"] == 6


def test_cli_update_sources_runs_validation(tmp_path, monkeypatch):
    from unittest.mock import MagicMock, patch, AsyncMock
    from knowledge_map.adapters.sqlite_db import init_db
    from knowledge_map.cli.main import main
    
    db_file = tmp_path / "test_cli_update_sources.db"
    db_path = str(db_file)
    init_db(db_path)
    
    monkeypatch.setenv("SQLITE_DB_PATH", db_path)
    
    with patch("knowledge_map.cli.main.ListingPageDiscoveryService") as MockDiscoveryClass, \
         patch("knowledge_map.core.validation.ArticleValidatorService") as MockValidatorClass:
         
        mock_discovery = MagicMock()
        mock_discovery.discover_and_scrape_all = AsyncMock(return_value={})
        MockDiscoveryClass.return_value = mock_discovery
        
        mock_validator = MagicMock()
        mock_validator.validate_pending_articles = AsyncMock(return_value=[])
        MockValidatorClass.return_value = mock_validator
        
        try:
            main(["update-sources"])
        except SystemExit as e:
            assert e.code == 0
            
        mock_discovery.discover_and_scrape_all.assert_called_once()
        mock_validator.validate_pending_articles.assert_called_once()


def test_cli_scrape_archive_runs_validation(tmp_path, monkeypatch):
    from unittest.mock import MagicMock, patch, AsyncMock
    from knowledge_map.adapters.sqlite_db import init_db
    from knowledge_map.cli.main import main
    
    db_file = tmp_path / "test_cli_scrape_archive.db"
    db_path = str(db_file)
    init_db(db_path)
    
    monkeypatch.setenv("SQLITE_DB_PATH", db_path)
    
    with patch("knowledge_map.adapters.sqlite_db.get_publication") as mock_get_pub, \
         patch("knowledge_map.cli.main.ArchiveDiscoveryService") as MockDiscoveryClass, \
         patch("knowledge_map.core.validation.ArticleValidatorService") as MockValidatorClass:
         
        mock_get_pub.return_value = {"id": "test_pub", "name": "Test Pub"}
        
        mock_discovery = MagicMock()
        mock_discovery.run_archive_crawl = AsyncMock(return_value=[])
        MockDiscoveryClass.return_value = mock_discovery
        
        mock_validator = MagicMock()
        mock_validator.validate_pending_articles = AsyncMock(return_value=[])
        MockValidatorClass.return_value = mock_validator
        
        try:
            main(["scrape-archive", "--publication-id", "test_pub"])
        except SystemExit as e:
            assert e.code == 0
            
        mock_get_pub.assert_called_once_with("test_pub", db_path=db_path)
        mock_discovery.run_archive_crawl.assert_called_once()
        mock_validator.validate_pending_articles.assert_called_once()


def test_cli_classifier_label_default(tmp_path, monkeypatch):
    import sqlite3
    from unittest.mock import patch
    from knowledge_map.adapters.sqlite_db import init_db, cache_scraped_html
    from knowledge_map.cli.main import main
    
    db_file = tmp_path / "test_cli_label_default.db"
    db_path = str(db_file)
    init_db(db_path)
    
    # 1. Insert an article with validation = 'PENDING_RELEVANCE'
    cache_scraped_html(
        "https://example.com/pending-rel", "pub1", "<html></html>",
        validation="PENDING_RELEVANCE", headline="California Budget Proposal",
        description="Gavin Newsom proposes a new budget.", db_path=db_path
    )
    
    # 2. Insert another article with validation = None and relevance_label_source = 'LLM' (should NOT be reviewed by default)
    cache_scraped_html(
        "https://example.com/llm-labeled", "pub1", "<html></html>",
        validation=None, headline="Other news",
        description="Not for daily label", db_path=db_path
    )
    
    monkeypatch.setenv("SQLITE_DB_PATH", db_path)
    
    # We simulate user choosing 'y' (relevant) for the first one, then quitting
    with patch("builtins.input", side_effect=["y"]):
        try:
            main(["classifier", "label"])
        except SystemExit as e:
            assert e.code == 0
            
    # Verify database updates
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT relevance_status, validation, relevance_label_source FROM scraped_html_cache WHERE url = ?", ("https://example.com/pending-rel",))
        row = cursor.fetchone()
        assert row["relevance_status"] == "RELEVANT"
        assert row["validation"] == "PENDING"
        assert row["relevance_label_source"] == "HUMAN"
        
        # Verify the second was not labeled/changed
        cursor.execute("SELECT relevance_status, relevance_label_source FROM scraped_html_cache WHERE url = ?", ("https://example.com/llm-labeled",))
        row = cursor.fetchone()
        assert row["relevance_status"] == "RELEVANT" # default from cache_scraped_html
        assert row["relevance_label_source"] == "KEYWORD"
    finally:
        conn.close()


def test_cli_classifier_label_review_all(tmp_path, monkeypatch):
    import sqlite3
    from unittest.mock import patch
    from knowledge_map.adapters.sqlite_db import init_db, cache_scraped_html
    from knowledge_map.cli.main import main
    
    db_file = tmp_path / "test_cli_label_review_all.db"
    db_path = str(db_file)
    init_db(db_path)
    
    # 1. Insert an article with relevance_label_source = 'LLM'
    cache_scraped_html(
        "https://example.com/llm-labeled", "pub1", "<html></html>",
        validation=None, headline="LLM Labeled Article",
        description="This was classified by LLM.", relevance_label_source="LLM", db_path=db_path
    )
    
    # 2. Insert another article with relevance_label_source = 'HUMAN' (should NOT be reviewed)
    cache_scraped_html(
        "https://example.com/human-labeled", "pub1", "<html></html>",
        validation=None, headline="Human Labeled Article",
        description="This was classified by Human.", relevance_label_source="HUMAN", db_path=db_path
    )
    
    monkeypatch.setenv("SQLITE_DB_PATH", db_path)
    
    # We simulate user choosing 'n' (irrelevant) for the first one
    with patch("builtins.input", side_effect=["n"]):
        try:
            main(["classifier", "label", "--review-all"])
        except SystemExit as e:
            assert e.code == 0
            
    # Verify database updates
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        
        # Verify the first was updated
        cursor.execute("SELECT relevance_status, validation, relevance_label_source FROM scraped_html_cache WHERE url = ?", ("https://example.com/llm-labeled",))
        row = cursor.fetchone()
        assert row["relevance_status"] == "IRRELEVANT"
        assert row["validation"] is None
        assert row["relevance_label_source"] == "HUMAN"
        
        # Verify the second was not changed
        cursor.execute("SELECT relevance_status, relevance_label_source FROM scraped_html_cache WHERE url = ?", ("https://example.com/human-labeled",))
        row = cursor.fetchone()
        assert row["relevance_status"] == "RELEVANT"
        assert row["relevance_label_source"] == "HUMAN"
    finally:
        conn.close()


