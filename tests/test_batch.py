import os
import sys
import json
import sqlite3
import pytest
import httpx
from unittest.mock import patch, MagicMock
from pydantic import ValidationError, BaseModel

from knowledge_map.config import Settings, BatchIngestionSettings
from knowledge_map.adapters.sqlite_db import (
    init_db,
    save_story,
    update_story_status,
    get_unprocessed_stories,
    SQLiteStatusTracker
)
from knowledge_map.adapters.coreference import CoreferenceResolutionError
from knowledge_map.adapters.extraction import ExtractionError
from knowledge_map.schemas import SourceArticle, ArticleChunk, ExtractionResult, Node
from knowledge_map.core.pipeline import StoryPipeline
from knowledge_map.core.ingestion import BatchIngestionService
from knowledge_map.core.exceptions import (
    classify_exception,
    classify_api_error,
    get_retry_after,
    PipelineConnectivityError,
    PipelineRateLimitError,
    PipelineLockError
)
from knowledge_map.cli.main import main
from knowledge_map.schemas.stories import Story
from knowledge_map.schemas import StoryLink
from test_pipeline import (
    EMPTY_ADHERENCE_REPORT,
    MockDatabaseAdapter,
    MockEmbeddingAdapter,
    MockCoreferenceAdapter,
    MockEntityExtractionAdapter,
    MockStatusTracker,
    MockDeadLetterQueueAdapter
)


def make_mock_pipeline() -> MagicMock:
    """A mock pipeline whose extraction adapter honours the adherence-report protocol."""
    pipeline = MagicMock()
    pipeline.extraction_adapter.adherence_report = dict(EMPTY_ADHERENCE_REPORT)
    return pipeline

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
    db_file = tmp_path / "test_unprocessed.db"
    db_path = str(db_file)
    init_db(db_path)

    # 1. Unprocessed story with content (should be returned)
    story1 = Story(
        title="Unprocessed 1",
        url="http://example.com/unproc1",
        content="Valid content 1"
    )
    # 2. Unprocessed story with empty content (should NOT be returned)
    story2 = Story(
        title="Unprocessed Empty",
        url="http://example.com/unproc2",
        content=""
    )
    # 3. Unprocessed story with None content (should NOT be returned)
    story3 = Story(
        title="Unprocessed None",
        url="http://example.com/unproc3",
        content=None
    )
    # 4. Processing story with content (should NOT be returned)
    story4 = Story(
        title="Processing 1",
        url="http://example.com/proc1",
        content="Valid content 4"
    )
    # 5. Completed story with content (should NOT be returned)
    story5 = Story(
        title="Completed 1",
        url="http://example.com/comp1",
        content="Valid content 5"
    )
    # 6. Another unprocessed story with content (should be returned, ordered by ID asc)
    story6 = Story(
        title="Unprocessed 2",
        url="http://example.com/unproc4",
        content="Valid content 6"
    )

    save_story(story1, db_path=db_path)
    save_story(story2, db_path=db_path)
    save_story(story3, db_path=db_path)
    save_story(story4, db_path=db_path)
    save_story(story5, db_path=db_path)
    save_story(story6, db_path=db_path)

    # Update statuses
    update_story_status(story4.url, "PROCESSING", db_path=db_path)
    update_story_status(story5.url, "COMPLETED", db_path=db_path)

    stories = get_unprocessed_stories(db_path=db_path)
    assert len(stories) == 2
    assert stories[0]["url"] == "http://example.com/unproc1"
    assert stories[1]["url"] == "http://example.com/unproc4"


def test_batch_ingestion_service_sequential_run(tmp_path):
    db_file = tmp_path / "test_service.db"
    db_path = str(db_file)
    init_db(db_path)

    # Save two unprocessed stories
    story1 = Story(
        title="Story A",
        url="http://example.com/a",
        content="Content of Story A",
        links=[StoryLink(text="a bill", url="https://example.com/bill")],
    )
    story2 = Story(
        title="Story B",
        url="http://example.com/b",
        content="Content of Story B"
    )
    save_story(story1, db_path=db_path)
    save_story(story2, db_path=db_path)

    # Mock StoryPipeline
    mock_pipeline = make_mock_pipeline()
    
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
    assert called_article_1.links == [StoryLink(text="a bill", url="https://example.com/bill")]

    # Second call
    called_article_2 = calls[1][0][0]
    assert isinstance(called_article_2, SourceArticle)
    assert called_article_2.url == "http://example.com/b"
    assert called_article_2.content == "Content of Story B"


def test_batch_ingestion_writes_and_resets_adherence_report(tmp_path):
    db_path = str(tmp_path / "empty.db")
    init_db(db_path)
    report_path = tmp_path / "reports" / "adherence.json"
    extraction_adapter = MagicMock()
    extraction_adapter.adherence_report = {
        "rejected_labels": {"Unknown": {"count": 1, "example_chunk_id": "sha256:abc"}},
        "rejected_relationship_types": {},
        "rejected_property_names": {},
        "rejected_relationship_property_names": {},
    }
    pipeline = MagicMock()
    pipeline.extraction_adapter = extraction_adapter
    settings = BatchIngestionSettings(db_path=db_path, adherence_report_path=str(report_path))

    BatchIngestionService(pipeline=pipeline, settings=settings).run()

    extraction_adapter.reset_adherence_report.assert_called_once_with()
    assert json.loads(report_path.read_text()) == extraction_adapter.adherence_report


def test_cli_ingest_command():
    
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
    class LocalMockDatabaseAdapter:
        def ingest_article(self, article): pass
        def ingest_chunk(self, article, chunk, embedding): pass
        def ingest_chunk_extraction(self, chunk_id, extraction, bill_sessions=None): pass

    class LocalMockEmbeddingAdapter:
        def process_chunks(self, chunks): return [[0.1] * 768] * len(chunks)

    class LocalMockCoreferenceAdapter:
        def resolve(self, content): return content

    class LocalMockEntityExtractionAdapter:
        def extract(self, chunk_text):
            return ExtractionResult(nodes=[Node(name="Test Actor", label="PoliticalActor")], relationships=[])

        @property
        def adherence_report(self): return dict(EMPTY_ADHERENCE_REPORT)

        def reset_adherence_report(self): pass
    
    db_file = tmp_path / "test_transitions.db"
    db_path = str(db_file)
    init_db(db_path)
    
    # Save a story
    story = Story(
        title="Transition Title",
        url="http://example.com/transition",
        content="Transition content."
    )
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
        cursor.execute("SELECT status FROM stories WHERE url = ?", (story.url,))
        assert cursor.fetchone()[0] == "COMPLETED"
    finally:
        conn.close()


def test_classify_exception():
    # 1. CoreferenceResolutionError should be classified as non-breaking
    coref_err = CoreferenceResolutionError(
        original_text="test",
        annotated_text="test",
        validation_issues=[],
        failure_type="test",
        retry_count=0,
        metadata={}
    )
    assert classify_exception(coref_err) is True
    
    # 2. ExtractionError should be classified as non-breaking
    extract_err = ExtractionError(
        original_text="test",
        validation_issues=[],
        failure_type="test",
        retry_count=0,
        metadata={}
    )
    assert classify_exception(extract_err) is True
    
    # 3. ValidationError should be classified as breaking
    class DummyModel(BaseModel):
        val: int
    with pytest.raises(ValidationError) as exc_info:
        DummyModel(val="not an int")
    assert classify_exception(exc_info.value) is False
    
    # 4. Standard exceptions should be classified as breaking
    assert classify_exception(ValueError("some error")) is False
    assert classify_exception(RuntimeError("system error")) is False


def test_batch_ingestion_resilience_non_breaking(tmp_path):
    db_file = tmp_path / "test_resilience_nb.db"
    db_path = str(db_file)
    init_db(db_path)
    
    story1 = Story(title="Story 1", url="http://example.com/1", content="Content 1")
    story2 = Story(title="Story 2", url="http://example.com/2", content="Content 2")
    save_story(story1, db_path=db_path)
    save_story(story2, db_path=db_path)
    
    mock_pipeline = make_mock_pipeline()
    
    coref_err = CoreferenceResolutionError(
        original_text="Content 1",
        annotated_text="mismatch",
        validation_issues=["mismatch"],
        failure_type="structural_mismatch",
        retry_count=3,
        metadata={}
    )
    
    def pipeline_run(article, *args, **kwargs):
        if article.url == "http://example.com/1":
            raise coref_err
        return MagicMock()
        
    mock_pipeline.run.side_effect = pipeline_run
    
    settings = BatchIngestionSettings(db_path=db_path)
    service = BatchIngestionService(pipeline=mock_pipeline, settings=settings)
    
    service.run()
    
    assert mock_pipeline.run.call_count == 2


def test_batch_ingestion_resilience_extraction_error(tmp_path):
    db_file = tmp_path / "test_resilience_extract.db"
    db_path = str(db_file)
    init_db(db_path)
    
    story1 = Story(title="Story 1", url="http://example.com/1", content="Content 1")
    story2 = Story(title="Story 2", url="http://example.com/2", content="Content 2")
    save_story(story1, db_path=db_path)
    save_story(story2, db_path=db_path)
    
    mock_pipeline = make_mock_pipeline()
    
    extract_err = ExtractionError(
        original_text="Content 1",
        validation_issues=["extraction failure"],
        failure_type="extraction_validation_failure",
        retry_count=3,
        metadata={}
    )
    
    def pipeline_run(article, *args, **kwargs):
        if article.url == "http://example.com/1":
            raise extract_err
        return MagicMock()
        
    mock_pipeline.run.side_effect = pipeline_run
    
    settings = BatchIngestionSettings(db_path=db_path)
    service = BatchIngestionService(pipeline=mock_pipeline, settings=settings)
    
    service.run()
    
    assert mock_pipeline.run.call_count == 2


def test_batch_ingestion_consecutive_system_errors(tmp_path):
    db_file = tmp_path / "test_system_errors.db"
    db_path = str(db_file)
    init_db(db_path)
    
    # 4 stories
    for i in range(1, 5):
        save_story(Story(
            title=f"Story {i}",
            url=f"http://example.com/{i}",
            content=f"Content {i}",
        ), db_path=db_path)
        
    mock_pipeline = make_mock_pipeline()
    mock_status_tracker = MagicMock()
    mock_pipeline.status_tracker = mock_status_tracker
    
    # pipeline.run will raise ValueError (a breaking system error)
    mock_pipeline.run.side_effect = ValueError("System connection failed")
    
    # Set limit to 2
    settings = BatchIngestionSettings(db_path=db_path, consecutive_failures_limit=2)
    service = BatchIngestionService(pipeline=mock_pipeline, settings=settings)
    
    # When we run, it should raise ValueError after processing 2 stories
    with pytest.raises(ValueError, match="System connection failed"):
        service.run()
        
    # The pipeline should have been run exactly 2 times (limit is 2)
    assert mock_pipeline.run.call_count == 2
    
    # Both stories should have had their status updated to SYSTEM_ERROR
    assert mock_status_tracker.update_status.call_count == 2 # 2 for SYSTEM_ERROR
    mock_status_tracker.update_status.assert_any_call("http://example.com/1", "SYSTEM_ERROR")
    mock_status_tracker.update_status.assert_any_call("http://example.com/2", "SYSTEM_ERROR")


def test_batch_ingestion_system_error_reset_on_success(tmp_path):
    db_file = tmp_path / "test_system_error_reset.db"
    db_path = str(db_file)
    init_db(db_path)
    
    # 3 stories
    for i in range(1, 4):
        save_story(Story(
            title=f"Story {i}",
            url=f"http://example.com/{i}",
            content=f"Content {i}",
        ), db_path=db_path)
        
    mock_pipeline = make_mock_pipeline()
    mock_status_tracker = MagicMock()
    mock_pipeline.status_tracker = mock_status_tracker
    
    # Story 1 raises ValueError, Story 2 succeeds, Story 3 raises ValueError
    # Limit is 2. Since 2 succeeds, consecutive_failures resets to 0. So Story 3 fails but doesn't abort.
    def run_side_effect(article):
        if article.url in ("http://example.com/1", "http://example.com/3"):
            raise ValueError("Transient error")
        return MagicMock()
        
    mock_pipeline.run.side_effect = run_side_effect
    
    settings = BatchIngestionSettings(db_path=db_path, consecutive_failures_limit=2)
    service = BatchIngestionService(pipeline=mock_pipeline, settings=settings)
    
    service.run()
    
    # All 3 stories should have been processed
    assert mock_pipeline.run.call_count == 3
    assert service.consecutive_failures == 1 # ended on failure


def test_exception_classification_and_parsing():

    # 1. Test HTTP 429 Status Error -> RATE_LIMIT
    resp_429 = httpx.Response(429, headers={"Retry-After": "45"})
    err_429 = httpx.HTTPStatusError("Rate Limit", request=httpx.Request("GET", "http://test.com"), response=resp_429)
    assert classify_api_error(err_429) == "RATE_LIMIT"
    assert get_retry_after(err_429) == 45

    # 2. Test text/keyword based -> RATE_LIMIT
    err_msg = ValueError("API rate limit exceeded. Too many requests.")
    assert classify_api_error(err_msg) == "RATE_LIMIT"

    # 3. Test HTTP connectivity errors -> CONNECTIVITY
    err_conn = httpx.ConnectError("Connection refused")
    assert classify_api_error(err_conn) == "CONNECTIVITY"

    # 4. Test TimeoutError -> CONNECTIVITY
    err_timeout = TimeoutError("Request timed out")
    assert classify_api_error(err_timeout) == "CONNECTIVITY"

    # 5. Test recursive cause check for rate limit
    wrapped_err = ValueError("Something failed")
    wrapped_err.__cause__ = err_429
    assert classify_api_error(wrapped_err) == "RATE_LIMIT"
    assert get_retry_after(wrapped_err) == 45


def test_connectivity_retries_and_backoff():
    db = MockDatabaseAdapter()
    embedding = MockEmbeddingAdapter()
    coref = MockCoreferenceAdapter()
    extraction = MockEntityExtractionAdapter()
    status_tracker = MockStatusTracker()

    settings = BatchIngestionSettings(max_retries=3, backoff_factor=2.0)

    pipeline = StoryPipeline(
        db_adapter=db,
        embedding_adapter=embedding,
        coreference_adapter=coref,
        extraction_adapter=extraction,
        status_tracker=status_tracker,
        settings=settings,
    )

    call_count = 0
    def resolve_side_effect(content):
        nonlocal call_count
        call_count += 1
        raise httpx.ConnectError("Connection refused")

    coref.resolve = resolve_side_effect

    article = SourceArticle(
        url="http://test.com/conn-retry",
        title="Conn Title",
        content="Some content."
    )

    sleep_delays = []
    with patch("time.sleep", side_effect=sleep_delays.append):
        with pytest.raises(PipelineConnectivityError) as exc_info:
            pipeline.run(article)

    assert call_count == 4
    assert sleep_delays == [2.0, 4.0, 8.0]
    assert exc_info.value.component == "coreference"
    assert isinstance(exc_info.value.original_exception, httpx.ConnectError)


def test_rate_limit_retry_after_under_cap():
    db = MockDatabaseAdapter()
    embedding = MockEmbeddingAdapter()
    coref = MockCoreferenceAdapter()
    extraction = MockEntityExtractionAdapter()
    status_tracker = MockStatusTracker()

    settings = BatchIngestionSettings(rate_limit_wait_cap=120)
    pipeline = StoryPipeline(
        db_adapter=db,
        embedding_adapter=embedding,
        coreference_adapter=coref,
        extraction_adapter=extraction,
        status_tracker=status_tracker,
        settings=settings,
    )

    call_count = 0
    def resolve_side_effect(content):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            resp = httpx.Response(429, headers={"Retry-After": "45"})
            raise httpx.HTTPStatusError("Rate Limit", request=httpx.Request("GET", "http://test.com"), response=resp)
        return "Gavin Newsom went home."

    coref.resolve = resolve_side_effect

    article = SourceArticle(
        url="http://test.com/rate-under-cap",
        title="Rate Title",
        content="Gavin Newsom went home."
    )

    sleep_delays = []
    with patch("time.sleep", side_effect=sleep_delays.append):
        result = pipeline.run(article)

    assert call_count == 2
    assert sleep_delays == [45.0]
    assert result.resolved_text == "Gavin Newsom went home."


def test_rate_limit_retry_after_over_cap():
    db = MockDatabaseAdapter()
    embedding = MockEmbeddingAdapter()
    coref = MockCoreferenceAdapter()
    extraction = MockEntityExtractionAdapter()
    status_tracker = MockStatusTracker()

    settings = BatchIngestionSettings(rate_limit_wait_cap=120)
    pipeline = StoryPipeline(
        db_adapter=db,
        embedding_adapter=embedding,
        coreference_adapter=coref,
        extraction_adapter=extraction,
        status_tracker=status_tracker,
        settings=settings,
    )

    def resolve_side_effect(content):
        resp = httpx.Response(429, headers={"Retry-After": "150"})
        raise httpx.HTTPStatusError("Rate Limit", request=httpx.Request("GET", "http://test.com"), response=resp)

    coref.resolve = resolve_side_effect

    article = SourceArticle(
        url="http://test.com/rate-over-cap",
        title="Rate Title",
        content="Gavin Newsom went home."
    )

    sleep_delays = []
    with patch("time.sleep", side_effect=sleep_delays.append):
        with pytest.raises(PipelineRateLimitError) as exc_info:
            pipeline.run(article)

    assert len(sleep_delays) == 0
    assert exc_info.value.component == "coreference"
    assert "exceeds cap" in str(exc_info.value)


def test_rate_limit_without_retry_after():
    db = MockDatabaseAdapter()
    embedding = MockEmbeddingAdapter()
    coref = MockCoreferenceAdapter()
    extraction = MockEntityExtractionAdapter()
    status_tracker = MockStatusTracker()

    settings = BatchIngestionSettings(max_retries=3, backoff_factor=2.0)
    pipeline = StoryPipeline(
        db_adapter=db,
        embedding_adapter=embedding,
        coreference_adapter=coref,
        extraction_adapter=extraction,
        status_tracker=status_tracker,
        settings=settings,
    )

    call_count = 0
    def resolve_side_effect(content):
        nonlocal call_count
        call_count += 1
        resp = httpx.Response(429)
        raise httpx.HTTPStatusError("Rate Limit", request=httpx.Request("GET", "http://test.com"), response=resp)

    coref.resolve = resolve_side_effect

    article = SourceArticle(
        url="http://test.com/rate-no-header",
        title="Rate Title",
        content="Gavin Newsom went home."
    )

    sleep_delays = []
    with patch("time.sleep", side_effect=sleep_delays.append):
        with pytest.raises(PipelineRateLimitError) as exc_info:
            pipeline.run(article)

    assert call_count == 4
    assert sleep_delays == [15.0, 30.0, 60.0]
    assert exc_info.value.component == "coreference"


def test_batch_ingestion_rate_limit_tracking_and_locking(tmp_path):

    db_file = tmp_path / "test_locking.db"
    db_path = str(db_file)
    init_db(db_path)

    # Save 4 stories
    for i in range(1, 5):
        save_story(Story(
            title=f"Story {i}",
            url=f"http://example.com/{i}",
            content=f"Content {i}",
        ), db_path=db_path)

    mock_pipeline = make_mock_pipeline()
    mock_status_tracker = MagicMock()
    mock_pipeline.status_tracker = mock_status_tracker

    # Pipeline will raise PipelineRateLimitError
    rate_err = PipelineRateLimitError("Rate limit hit", component="embedding", original_exception=ValueError("429 Too Many Requests"))
    mock_pipeline.run.side_effect = rate_err

    lock_file = tmp_path / "pipeline.lock"
    lock_file_path = str(lock_file)

    settings = BatchIngestionSettings(
        db_path=db_path,
        consecutive_failures_limit=3,
        lock_file_path=lock_file_path
    )

    service = BatchIngestionService(pipeline=mock_pipeline, settings=settings)

    # Run the service. We expect it to raise PipelineLockError when consecutive rate limit failures hit 3
    with pytest.raises(PipelineLockError) as exc_info:
        service.run()

    assert "locked" in str(exc_info.value).lower()

    # Pipeline should have been run exactly 3 times
    assert mock_pipeline.run.call_count == 3

    # The lock file should exist
    assert os.path.exists(lock_file_path)

    # Check lock file JSON contents
    with open(lock_file_path, "r") as f:
        data = json.load(f)

    assert "timestamp" in data
    assert data["component"] == "embedding"
    assert data["error_message"] == "Rate limit hit"

    # Now let's test that a successful run resets the consecutive rate limit failures
    os.remove(lock_file_path)

    mock_pipeline.run.side_effect = None
    call_count = 0
    def run_side_effect(article):
        nonlocal call_count
        call_count += 1
        if call_count in (1, 3): # Story 1 and 3 fail, Story 2 succeeds
            raise PipelineRateLimitError("Rate limit hit", component="embedding", original_exception=ValueError("429"))
        return MagicMock()

    mock_pipeline.run.side_effect = run_side_effect
    mock_pipeline.run.reset_mock()

    db_file_reset = tmp_path / "test_locking_reset.db"
    db_path_reset = str(db_file_reset)
    init_db(db_path_reset)
    for i in range(1, 4):
         save_story(Story(
             title=f"Story {i}",
             url=f"http://example.com/{i}",
             content=f"Content {i}",
         ), db_path=db_path_reset)

    settings_reset = BatchIngestionSettings(
        db_path=db_path_reset,
        lock_file_path=lock_file_path
    )
    service_reset = BatchIngestionService(pipeline=mock_pipeline, settings=settings_reset)

    service_reset.run()

    assert mock_pipeline.run.call_count == 3
    assert not os.path.exists(lock_file_path)


def test_batch_ingestion_startup_lock_check(tmp_path):

    mock_pipeline = make_mock_pipeline()
    lock_file = tmp_path / "pipeline.lock"
    lock_file.write_text("locked content")
    lock_file_path = str(lock_file)

    settings = BatchIngestionSettings(
        db_path=str(tmp_path / "dummy.db"),
        lock_file_path=lock_file_path
    )

    service = BatchIngestionService(pipeline=mock_pipeline, settings=settings)

    # Verify it raises PipelineLockError
    with pytest.raises(PipelineLockError) as exc_info:
        service.run()

    assert "locked" in str(exc_info.value).lower()
    # Verify no pipeline execution occurred
    assert mock_pipeline.run.call_count == 0









