import os
import pytest
from unittest.mock import patch
from knowledge_map.config import Settings, BatchIngestionSettings

def test_batch_ingestion_settings_defaults():
    # Verify default values
    settings = Settings()
    # Check that settings has batch_ingestion
    assert hasattr(settings, "batch_ingestion")
    
    batch_cfg = settings.batch_ingestion
    assert batch_cfg.max_retries == 3
    assert batch_cfg.backoff_factor == 2.0
    assert batch_cfg.rate_limit_wait_cap == 120
    assert batch_cfg.consecutive_failures_limit == 3
    assert batch_cfg.lock_file_path == ".scratch/pipeline.lock"
    assert batch_cfg.db_path == "document_store.db"

def test_batch_ingestion_settings_env_override():
    # Verify environment overrides work
    env_vars = {
        "BATCH_MAX_RETRIES": "5",
        "BATCH_BACKOFF_FACTOR": "3.5",
        "BATCH_RATE_LIMIT_WAIT_CAP": "60",
        "BATCH_CONSECUTIVE_FAILURES_LIMIT": "4",
        "BATCH_LOCK_FILE_PATH": "test.lock",
        "SQLITE_DB_PATH": "test_db.db"
    }
    with patch.dict(os.environ, env_vars):
        # We instantiate a new BatchIngestionSettings to see if it loads from env
        batch_cfg = BatchIngestionSettings()
        assert batch_cfg.max_retries == 5
        assert batch_cfg.backoff_factor == 3.5
        assert batch_cfg.rate_limit_wait_cap == 60
        assert batch_cfg.consecutive_failures_limit == 4
        assert batch_cfg.lock_file_path == "test.lock"
        assert batch_cfg.db_path == "test_db.db"

def test_get_unprocessed_stories(tmp_path):
    from knowledge_map.adapters.sqlite_db import (
        init_db,
        save_story,
        update_story_status,
        get_unprocessed_stories,
    )
    db_file = tmp_path / "test_unprocessed.db"
    db_path = str(db_file)
    init_db(db_path)

    # 1. Unprocessed story with content (should be returned)
    story1 = {
        "title": "Unprocessed 1",
        "url": "http://example.com/unproc1",
        "content": "Valid content 1"
    }
    # 2. Unprocessed story with empty content (should NOT be returned)
    story2 = {
        "title": "Unprocessed Empty",
        "url": "http://example.com/unproc2",
        "content": ""
    }
    # 3. Unprocessed story with None content (should NOT be returned)
    story3 = {
        "title": "Unprocessed None",
        "url": "http://example.com/unproc3",
        "content": None
    }
    # 4. Processing story with content (should NOT be returned)
    story4 = {
        "title": "Processing 1",
        "url": "http://example.com/proc1",
        "content": "Valid content 4"
    }
    # 5. Completed story with content (should NOT be returned)
    story5 = {
        "title": "Completed 1",
        "url": "http://example.com/comp1",
        "content": "Valid content 5"
    }
    # 6. Another unprocessed story with content (should be returned, ordered by ID asc)
    story6 = {
        "title": "Unprocessed 2",
        "url": "http://example.com/unproc4",
        "content": "Valid content 6"
    }

    save_story(story1, db_path=db_path)
    save_story(story2, db_path=db_path)
    save_story(story3, db_path=db_path)
    save_story(story4, db_path=db_path)
    save_story(story5, db_path=db_path)
    save_story(story6, db_path=db_path)

    # Update statuses
    update_story_status(story4["url"], "PROCESSING", db_path=db_path)
    update_story_status(story5["url"], "COMPLETED", db_path=db_path)

    stories = get_unprocessed_stories(db_path=db_path)
    assert len(stories) == 2
    assert stories[0]["url"] == "http://example.com/unproc1"
    assert stories[1]["url"] == "http://example.com/unproc4"


def test_batch_ingestion_service_sequential_run(tmp_path):
    from knowledge_map.core.ingestion import BatchIngestionService
    from knowledge_map.adapters.sqlite_db import init_db, save_story
    from knowledge_map.schemas import SourceArticle
    from knowledge_map.config import BatchIngestionSettings
    from unittest.mock import MagicMock

    db_file = tmp_path / "test_service.db"
    db_path = str(db_file)
    init_db(db_path)

    # Save two unprocessed stories
    story1 = {
        "title": "Story A",
        "url": "http://example.com/a",
        "content": "Content of Story A"
    }
    story2 = {
        "title": "Story B",
        "url": "http://example.com/b",
        "content": "Content of Story B"
    }
    save_story(story1, db_path=db_path)
    save_story(story2, db_path=db_path)

    # Mock StoryPipeline
    mock_pipeline = MagicMock()
    
    # Instantiate service
    settings = BatchIngestionSettings(db_path=db_path)
    service = BatchIngestionService(pipeline=mock_pipeline, settings=settings)

    service.run()

    # Verify pipeline.run was called twice, once for each article, in order
    assert mock_pipeline.run.call_count == 2
    
    calls = mock_pipeline.run.call_args_list
    # First call
    called_article_1 = calls[0][0][0]
    assert isinstance(called_article_1, SourceArticle)
    assert called_article_1.url == "http://example.com/a"
    assert called_article_1.content == "Content of Story A"

    # Second call
    called_article_2 = calls[1][0][0]
    assert isinstance(called_article_2, SourceArticle)
    assert called_article_2.url == "http://example.com/b"
    assert called_article_2.content == "Content of Story B"


def test_cli_ingest_command():
    from knowledge_map.cli.main import main
    
    with patch("knowledge_map.cli.main.BatchIngestionService") as MockService, \
         patch("knowledge_map.cli.main.Neo4jAdapter") as MockNeo4j, \
         patch("knowledge_map.cli.main.PydanticAIEmbeddingAdapter") as MockEmbedding, \
         patch("knowledge_map.cli.main.PydanticAICoreferenceAdapter") as MockCoref, \
         patch("knowledge_map.cli.main.PydanticAIEntityExtractionAdapter") as MockExtraction, \
         patch("knowledge_map.cli.main.LocalFileDLQAdapter") as MockDLQ, \
         patch("knowledge_map.cli.main.SQLiteStatusTracker") as MockStatusTracker:
         
         # Call main with ingest subcommand
         try:
             main(["ingest"])
         except SystemExit as e:
             assert e.code == 0
             
         # Verify service and runner execution
         MockService.assert_called_once()
         MockService.return_value.run.assert_called_once()
         MockNeo4j.assert_called_once()


def test_cli_clear_command(capsys):
    from knowledge_map.cli.main import main
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


def test_cli_analyze_command(capsys):
    from knowledge_map.cli.main import main
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
        assert "Distinct node labels:" in captured.out


def test_batch_ingestion_service_status_transitions(tmp_path):
    from knowledge_map.core.ingestion import BatchIngestionService
    from knowledge_map.adapters.sqlite_db import init_db, save_story, SQLiteStatusTracker
    from knowledge_map.core.pipeline import StoryPipeline
    from knowledge_map.config import BatchIngestionSettings
    from knowledge_map.schemas import ArticleChunk, ExtractionResult, Node
    
    class LocalMockDatabaseAdapter:
        def ingest_article(self, article): pass
        def ingest_chunk(self, article, chunk, embedding): pass
        def ingest_chunk_extraction(self, chunk_id, extraction): pass
        
    class LocalMockEmbeddingAdapter:
        def process_chunks(self, chunks): return [[0.1] * 768] * len(chunks)
        
    class LocalMockCoreferenceAdapter:
        def resolve(self, content): return content
        
    class LocalMockEntityExtractionAdapter:
        def extract(self, chunk_text):
            return ExtractionResult(nodes=[Node(name="Test Actor", label="PoliticalActor")], relationships=[])
    
    db_file = tmp_path / "test_transitions.db"
    db_path = str(db_file)
    init_db(db_path)
    
    # Save a story
    story = {
        "title": "Transition Title",
        "url": "http://example.com/transition",
        "content": "Transition content."
    }
    save_story(story, db_path=db_path)
    
    # Use real SQLite status tracker
    status_tracker = SQLiteStatusTracker(db_path=db_path)
    
    # Setup StoryPipeline with mock adapters
    pipeline = StoryPipeline(
        db_adapter=LocalMockDatabaseAdapter(),
        embedding_adapter=LocalMockEmbeddingAdapter(),
        coreference_adapter=LocalMockCoreferenceAdapter(),
        extraction_adapter=LocalMockEntityExtractionAdapter(),
        status_tracker=status_tracker
    )
    
    settings = BatchIngestionSettings(db_path=db_path)
    service = BatchIngestionService(pipeline=pipeline, settings=settings)
    
    # Run service
    service.run()
    
    # Verify DB status updated to COMPLETED
    import sqlite3
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT status FROM stories WHERE url = ?", (story["url"],))
        assert cursor.fetchone()[0] == "COMPLETED"
    finally:
        conn.close()





