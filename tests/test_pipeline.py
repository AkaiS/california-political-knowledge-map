import pytest
import logging
from knowledge_map.schemas import SourceArticle, ArticleChunk, ExtractionResult, PipelineResult, Node, StoryLink
from knowledge_map.adapters.extraction import ExtractionError
from knowledge_map.core.pipeline import (
    StoryPipeline,
    DatabaseAdapter,
    EmbeddingAdapter,
    CoreferenceAdapter,
    EntityExtractionAdapter,
)
from knowledge_map.adapters.embedding import PydanticAIEmbeddingAdapter
from knowledge_map.adapters.coreference import PydanticAICoreferenceAdapter, get_annotator_agent, get_critic_agent
from knowledge_map.adapters.extraction import PydanticAIEntityExtractionAdapter, get_extraction_agent
from unittest.mock import MagicMock, patch
from knowledge_map.adapters.neo4j_db import Neo4jAdapter
from pydantic_ai import ModelResponse, ToolCallPart, TextPart
from pydantic_ai.models.function import FunctionModel


class MockDatabaseAdapter:
    def __init__(self):
        self.articles = []
        self.chunks = []
        self.extractions = []

    def ingest_article(self, article: SourceArticle) -> None:
        self.articles.append(article)

    def ingest_chunk(
        self,
        article: SourceArticle,
        chunk: ArticleChunk,
        embedding: list[float]
    ) -> None:
        self.chunks.append((article, chunk, embedding))

    def ingest_chunk_extraction(
        self,
        chunk_id: str,
        extraction: ExtractionResult,
        bill_sessions: dict[str, dict[str, object]] | None = None,
    ) -> None:
        self.extractions.append((chunk_id, extraction, bill_sessions))

class MockEmbeddingAdapter:
    def process_chunks(self, chunks: list[ArticleChunk]) -> list[list[float]]:
        return [[0.1, 0.2, 0.3]] * len(chunks)

class MockCoreferenceAdapter:
    def resolve(self, content: str) -> str:
        return content

EMPTY_ADHERENCE_REPORT = {
    "rejected_labels": {},
    "rejected_relationship_types": {},
    "rejected_property_names": {},
    "rejected_relationship_property_names": {},
}


class MockEntityExtractionAdapter:
    def __init__(self):
        self.reset_calls = 0

    def extract(self, chunk_text: str) -> ExtractionResult:
        return ExtractionResult(
            nodes=[Node(name="Test Actor", label="Politician")],
            relationships=[]
        )

    @property
    def adherence_report(self) -> dict:
        return dict(EMPTY_ADHERENCE_REPORT)

    def reset_adherence_report(self) -> None:
        self.reset_calls += 1

class MockStatusTracker:
    def __init__(self):
        self.updates = []

    def update_status(self, url: str, status: str) -> None:
        self.updates.append((url, status))

def test_pipeline_dry_run():
    db = MockDatabaseAdapter()
    embedding = MockEmbeddingAdapter()
    coref = MockCoreferenceAdapter()
    extraction = MockEntityExtractionAdapter()

    pipeline = StoryPipeline(
        db_adapter=db,
        embedding_adapter=embedding,
        coreference_adapter=coref,
        extraction_adapter=extraction,
        status_tracker=MockStatusTracker(),
    )

    article = SourceArticle(
        url="http://test.com",
        title="Test Title",
        content="Test content for the political story."
    )

    result = pipeline.run(article, dry_run=True)

    assert isinstance(result, PipelineResult)
    assert result.resolved_text == "Test content for the political story."
    assert len(result.chunks) == 1
    assert result.chunks[0].text == "Test content for the political story."
    assert result.embeddings == [[0.1, 0.2, 0.3]]
    assert len(result.extractions) == 1
    assert result.extractions[0].nodes[0].name == "Test Actor"

    # In dry run, DB persistence should be skipped
    assert len(db.articles) == 0
    assert len(db.chunks) == 0
    assert len(db.extractions) == 0

def test_pipeline_persistence():
    db = MockDatabaseAdapter()
    embedding = MockEmbeddingAdapter()
    coref = MockCoreferenceAdapter()
    extraction = MockEntityExtractionAdapter()

    pipeline = StoryPipeline(
        db_adapter=db,
        embedding_adapter=embedding,
        coreference_adapter=coref,
        extraction_adapter=extraction,
        status_tracker=MockStatusTracker(),
    )

    article = SourceArticle(
        url="http://test.com/persist",
        title="Persist Title",
        content="This content should be saved."
    )

    result = pipeline.run(article, dry_run=False)

    assert isinstance(result, PipelineResult)
    assert result.resolved_text == "This content should be saved."
    assert len(result.chunks) == 1
    assert result.chunks[0].text == "This content should be saved."
    assert result.embeddings == [[0.1, 0.2, 0.3]]
    assert len(result.extractions) == 1
    assert result.extractions[0].nodes[0].name == "Test Actor"

    # In persistence run, DB persistence should be invoked
    assert len(db.articles) == 1
    assert db.articles[0].url == "http://test.com/persist"
    
    assert len(db.chunks) == 1
    stored_art, stored_chunk, stored_emb = db.chunks[0]
    assert stored_art.url == "http://test.com/persist"
    assert stored_chunk.text == "This content should be saved."
    assert stored_emb == [0.1, 0.2, 0.3]

    assert len(db.extractions) == 1
    chunk_id, stored_extraction, _bill_sessions = db.extractions[0]
    assert chunk_id == "http://test.com/persist#chunk_0"
    assert stored_extraction.nodes[0].name == "Test Actor"


def test_pipeline_resolves_bill_sessions_once_per_article():
    db = MockDatabaseAdapter()
    extraction = MockEntityExtractionAdapter()
    extraction.extract = lambda _text: ExtractionResult(nodes=[
        Node(name="AB 218", label="Bill", properties={"number": "AB 218"}),
        Node(name="SB 54", label="Bill", properties={"number": "SB 54"}),
        Node(name="AB 99", label="Bill", properties={"number": "AB 99"}),
        Node(name="AB 1", label="Bill", properties={"number": "AB 1"}),
    ])
    pipeline = StoryPipeline(
        db_adapter=db,
        embedding_adapter=MockEmbeddingAdapter(),
        coreference_adapter=MockCoreferenceAdapter(),
        extraction_adapter=extraction,
        status_tracker=MockStatusTracker(),
    )
    article = SourceArticle(
        url="https://example.com/story",
        title="Bills",
        published_date="2026-04-10T12:00:00Z",
        content="first chunk second chunk",
        links=[
            StoryLink(text="June budget", url="https://leginfo.legislature.ca.gov/faces/billTextClient.xhtml?bill_id=201920200AB218"),
            StoryLink(text="sanctuary law", url="https://digitaldemocracy.calmatters.org/bills/ca_201720180sb54"),
            StoryLink(text="with a bill", url="https://example.test/bills/ca_202320240ab1"),
            StoryLink(text="AB 1", url="https://example.test/bills/ca_202520260ab1"),
        ],
    )
    chunks = [
        ArticleChunk(text="first", start_index=0, end_index=5, index=0),
        ArticleChunk(text="second", start_index=6, end_index=12, index=1),
    ]

    with patch("knowledge_map.core.pipeline.chunk_article", return_value=chunks), \
         patch("knowledge_map.core.bill_sessions.parse_bill_url", wraps=__import__(
             "knowledge_map.core.bill_sessions", fromlist=["parse_bill_url"]
         ).parse_bill_url) as parser:
        pipeline.run(article)

    assert parser.call_count == len(article.links)
    first_map = db.extractions[0][2]
    assert db.extractions[1][2] is first_map
    assert first_map == {
        "AB 218": {"session": "2019-2020", "session_verified": True, "session_inferred": False, "needs_review": False},
        "SB 54": {"session": "2017-2018", "session_verified": True, "session_inferred": False, "needs_review": False},
        "AB 99": {"session": "2025-2026", "session_verified": False, "session_inferred": True, "needs_review": False},
        "AB 1": {"session": None, "session_verified": False, "session_inferred": False, "needs_review": True},
    }

def test_pipeline_logging(caplog):
    caplog.set_level(logging.INFO)

    db = MockDatabaseAdapter()
    embedding = MockEmbeddingAdapter()
    coref = MockCoreferenceAdapter()
    extraction = MockEntityExtractionAdapter()

    pipeline = StoryPipeline(
        db_adapter=db,
        embedding_adapter=embedding,
        coreference_adapter=coref,
        extraction_adapter=extraction,
        status_tracker=MockStatusTracker(),
    )

    article = SourceArticle(
        url="http://test.com/log",
        title="Log Title",
        content="Log testing."
    )

    pipeline.run(article, dry_run=False)

    # Verify that key phases are logged
    assert "Starting pipeline run for article" in caplog.text
    assert "Resolving coreferences" in caplog.text
    assert "Chunking text" in caplog.text
    assert "Generating embeddings" in caplog.text
    assert "Extracting entities" in caplog.text
    assert "Ingesting article and chunks into DB" in caplog.text

def test_pipeline_error_handling():
    db = MockDatabaseAdapter()
    embedding = MockEmbeddingAdapter()
    coref = MockCoreferenceAdapter()
    extraction = MockEntityExtractionAdapter()

    # Make embedding adapter raise an error
    def raise_error(chunks):
        raise ValueError("Embedding calculation failed")
    embedding.process_chunks = raise_error

    pipeline = StoryPipeline(
        db_adapter=db,
        embedding_adapter=embedding,
        coreference_adapter=coref,
        extraction_adapter=extraction,
        status_tracker=MockStatusTracker(),
    )

    article = SourceArticle(
        url="http://test.com/error",
        title="Error Title",
        content="Error testing."
    )

    with pytest.raises(ValueError, match="Embedding calculation failed"):
        pipeline.run(article)


def test_pipeline_with_concrete_adapters():
    class MockResult:
        def __init__(self, embeddings):
            self.embeddings = embeddings

    # 1. Mock embedder
    mock_embedder = MagicMock()
    async def fake_embed(documents):
        return MockResult([[0.1] * 768] * len(documents))
    mock_embedder.embed_documents.side_effect = fake_embed
    embedding_adapter = PydanticAIEmbeddingAdapter(embedder=mock_embedder)

    # 2. Mock coreference agents
    annotator_agent = get_annotator_agent(defer_check=True)
    critic_agent = get_critic_agent(defer_check=True)
    
    def mock_annotator(messages, info):
        return ModelResponse(parts=[TextPart(content="Gavin Newsom signed a bill. <ref entity=\"Gavin Newsom\">He</ref> was happy.")])
        
    def mock_critic(messages, info):
        tool_name = info.output_tools[0].name
        return ModelResponse(parts=[
            ToolCallPart(
                tool_name=tool_name,
                args={
                    "is_valid": True,
                    "issues": []
                },
                tool_call_id="call_1"
            )
        ])
    
    coreference_adapter = PydanticAICoreferenceAdapter(
        annotator_agent=annotator_agent,
        critic_agent=critic_agent
    )

    # 3. Mock extraction agent
    extraction_agent = get_extraction_agent(defer_check=True)
    
    def mock_extraction(messages, info):
        tool_name = info.output_tools[0].name
        return ModelResponse(parts=[
            ToolCallPart(
                tool_name=tool_name,
                args={
                    "nodes": [
                        {"name": "Gavin Newsom", "label": "Politician"}
                    ],
                    "relationships": []
                },
                tool_call_id="call_2"
            )
        ])
    
    extraction_adapter = PydanticAIEntityExtractionAdapter(agent=extraction_agent)

    # 4. Instantiate pipeline
    db = MockDatabaseAdapter()
    pipeline = StoryPipeline(
        db_adapter=db,
        embedding_adapter=embedding_adapter,
        coreference_adapter=coreference_adapter,
        extraction_adapter=extraction_adapter,
        status_tracker=MockStatusTracker(),
    )

    article = SourceArticle(
        url="http://test.com/concrete",
        title="Concrete Title",
        content="Gavin Newsom signed a bill. He was happy."
    )

    with annotator_agent.override(model=FunctionModel(mock_annotator)), \
         critic_agent.override(model=FunctionModel(mock_critic)), \
         extraction_agent.override(model=FunctionModel(mock_extraction)):
         
        result = pipeline.run(article, dry_run=False)

    # Assertions
    assert isinstance(result, PipelineResult)
    # The resolved text should be fully resolved (with replaced tags)
    assert result.resolved_text == "Gavin Newsom signed a bill. Gavin Newsom was happy."
    
    # Verify chunks are created
    assert len(result.chunks) > 0
    # Verify embeddings are present
    assert len(result.embeddings) == len(result.chunks)
    assert result.embeddings[0] == [0.1] * 768
    
    # Verify extractions
    assert len(result.extractions) == len(result.chunks)
    assert result.extractions[0].nodes[0].name == "Gavin Newsom"

    # Verify database calls
    assert len(db.articles) == 1
    assert db.articles[0].url == "http://test.com/concrete"
    assert len(db.chunks) == len(result.chunks)
    assert len(db.extractions) == len(result.chunks)


def test_pipeline_with_neo4j_adapter():
    mock_driver = MagicMock()
    mock_session = MagicMock()
    mock_tx = MagicMock()
    
    mock_driver.session.return_value.__enter__.return_value = mock_session
    mock_session.execute_write.side_effect = lambda func, *args, **kwargs: func(mock_tx, *args, **kwargs)
    
    db_adapter = Neo4jAdapter(
        uri="bolt://localhost:7687",
        username="neo4j",
        password="password",
        driver=mock_driver
    )
    
    embedding = MockEmbeddingAdapter()
    coref = MockCoreferenceAdapter()
    extraction = MockEntityExtractionAdapter()
    
    pipeline = StoryPipeline(
        db_adapter=db_adapter,
        embedding_adapter=embedding,
        coreference_adapter=coref,
        extraction_adapter=extraction,
        status_tracker=MockStatusTracker(),
    )
    
    article = SourceArticle(
        url="http://example.com/integration",
        title="Integration Title",
        content="This is integration test content."
    )
    
    with patch("knowledge_map.adapters.neo4j_db.Neo4jAdapter._ensure_vector_index"):
        result = pipeline.run(article, dry_run=False)
    
    assert isinstance(result, PipelineResult)
    assert mock_tx.run.call_count >= 2
    queries = [call[0][0] for call in mock_tx.run.call_args_list]
    assert any("MERGE (a:NewsArticle {id: $url})" in q for q in queries)
    assert any("MERGE (c:Chunk {id: $chunk_id})" in q for q in queries)


from knowledge_map.adapters.coreference import CoreferenceResolutionError

class MockDeadLetterQueueAdapter:
    def __init__(self):
        self.failures = []

    def log_failure(
        self,
        url: str,
        title: str,
        original_text: str,
        annotated_text: str,
        validation_issues: list[str],
        failure_type: str,
        retry_count: int,
        metadata: dict,
        error_category: str = "coreference"
    ) -> None:
        self.failures.append({
            "url": url,
            "title": title,
            "original_text": original_text,
            "annotated_text": annotated_text,
            "validation_issues": validation_issues,
            "failure_type": failure_type,
            "retry_count": retry_count,
            "metadata": metadata,
            "error_category": error_category
        })

def test_pipeline_coreference_failure_logs_to_dlq():
    db = MockDatabaseAdapter()
    embedding = MockEmbeddingAdapter()
    coref = MockCoreferenceAdapter()
    extraction = MockEntityExtractionAdapter()
    dlq = MockDeadLetterQueueAdapter()

    # Stub the resolve method to raise CoreferenceResolutionError
    def raise_coref_error(content):
        raise CoreferenceResolutionError(
            original_text=content,
            annotated_text="mismatched text",
            validation_issues=["Test structural issue"],
            failure_type="structural_mismatch",
            retry_count=3,
            metadata={"model": "gemma"}
        )
    coref.resolve = raise_coref_error

    pipeline = StoryPipeline(
        db_adapter=db,
        embedding_adapter=embedding,
        coreference_adapter=coref,
        extraction_adapter=extraction,
        status_tracker=MockStatusTracker(),
        dlq_adapter=dlq
    )

    article = SourceArticle(
        url="http://test.com/failure-dlq",
        title="Failed Article",
        content="Gavin Newsom went home."
    )

    # Asserts that pipeline propagates the CoreferenceResolutionError
    with pytest.raises(CoreferenceResolutionError):
        pipeline.run(article)

    # Asserts that the DLQ logged the failure correctly
    assert len(dlq.failures) == 1
    failure = dlq.failures[0]
    assert failure["url"] == "http://test.com/failure-dlq"
    assert failure["title"] == "Failed Article"
    assert failure["original_text"] == "Gavin Newsom went home."
    assert failure["annotated_text"] == "mismatched text"
    assert failure["validation_issues"] == ["Test structural issue"]
    assert failure["failure_type"] == "structural_mismatch"
    assert failure["retry_count"] == 3
    assert failure["metadata"] == {"model": "gemma"}
    assert failure["error_category"] == "coreference"


def test_pipeline_extraction_failure_logs_to_dlq():
    db = MockDatabaseAdapter()
    embedding = MockEmbeddingAdapter()
    coref = MockCoreferenceAdapter()
    extraction = MockEntityExtractionAdapter()
    dlq = MockDeadLetterQueueAdapter()

    # Stub the extract method to raise ExtractionError
    def raise_extract_error(chunk_text):
        raise ExtractionError(
            original_text=chunk_text,
            validation_issues=["Test extraction schema issue"],
            failure_type="extraction_validation_failure",
            retry_count=3,
            metadata={"model": "gemma"}
        )
    extraction.extract = raise_extract_error

    pipeline = StoryPipeline(
        db_adapter=db,
        embedding_adapter=embedding,
        coreference_adapter=coref,
        extraction_adapter=extraction,
        status_tracker=MockStatusTracker(),
        dlq_adapter=dlq
    )

    article = SourceArticle(
        url="http://test.com/failure-dlq-extract",
        title="Failed Article Extract",
        content="Gavin Newsom went home."
    )

    # Asserts that pipeline propagates the ExtractionError
    with pytest.raises(ExtractionError):
        pipeline.run(article)

    # Asserts that the DLQ logged the failure correctly
    assert len(dlq.failures) == 1
    failure = dlq.failures[0]
    assert failure["url"] == "http://test.com/failure-dlq-extract"
    assert failure["title"] == "Failed Article Extract"
    assert failure["original_text"] == "Gavin Newsom went home."
    assert failure["annotated_text"] == ""
    assert failure["validation_issues"] == ["Test extraction schema issue"]
    assert failure["failure_type"] == "extraction_validation_failure"
    assert failure["retry_count"] == 3
    assert failure["metadata"] == {"model": "gemma"}
    assert failure["error_category"] == "extraction"


def test_pipeline_status_extraction_failure():
    db = MockDatabaseAdapter()
    embedding = MockEmbeddingAdapter()
    coref = MockCoreferenceAdapter()
    extraction = MockEntityExtractionAdapter()
    status_tracker = MockStatusTracker()

    def raise_extract_error(chunk_text):
        raise ExtractionError(
            original_text=chunk_text,
            validation_issues=["Test extraction schema issue"],
            failure_type="extraction_validation_failure",
            retry_count=3,
            metadata={"model": "gemma"}
        )
    extraction.extract = raise_extract_error

    pipeline = StoryPipeline(
        db_adapter=db,
        embedding_adapter=embedding,
        coreference_adapter=coref,
        extraction_adapter=extraction,
        status_tracker=status_tracker,
    )

    article = SourceArticle(
        url="http://test.com/extract-fail",
        title="Extract Fail Title",
        content="Extract fail content."
    )

    with pytest.raises(ExtractionError):
        pipeline.run(article, dry_run=False)

    assert status_tracker.updates == [
        ("http://test.com/extract-fail", "PROCESSING"),
        ("http://test.com/extract-fail", "FAILED_DLQ")
    ]


def test_pipeline_status_success():
    db = MockDatabaseAdapter()
    embedding = MockEmbeddingAdapter()
    coref = MockCoreferenceAdapter()
    extraction = MockEntityExtractionAdapter()
    status_tracker = MockStatusTracker()

    pipeline = StoryPipeline(
        db_adapter=db,
        embedding_adapter=embedding,
        coreference_adapter=coref,
        extraction_adapter=extraction,
        status_tracker=status_tracker,
    )

    article = SourceArticle(
        url="http://test.com/success",
        title="Success Title",
        content="Success content."
    )

    result = pipeline.run(article, dry_run=False)
    assert status_tracker.updates == [
        ("http://test.com/success", "PROCESSING"),
        ("http://test.com/success", "COMPLETED")
    ]


def test_pipeline_status_coref_failure():
    db = MockDatabaseAdapter()
    embedding = MockEmbeddingAdapter()
    coref = MockCoreferenceAdapter()
    extraction = MockEntityExtractionAdapter()
    status_tracker = MockStatusTracker()

    def raise_coref_error(content):
        raise CoreferenceResolutionError(
            original_text=content,
            annotated_text="mismatched text",
            validation_issues=["Test structural issue"],
            failure_type="structural_mismatch",
            retry_count=3,
            metadata={"model": "gemma"}
        )
    coref.resolve = raise_coref_error

    pipeline = StoryPipeline(
        db_adapter=db,
        embedding_adapter=embedding,
        coreference_adapter=coref,
        extraction_adapter=extraction,
        status_tracker=status_tracker,
    )

    article = SourceArticle(
        url="http://test.com/coref-fail",
        title="Coref Fail Title",
        content="Coref fail content."
    )

    with pytest.raises(CoreferenceResolutionError):
        pipeline.run(article, dry_run=False)

    assert status_tracker.updates == [
        ("http://test.com/coref-fail", "PROCESSING"),
        ("http://test.com/coref-fail", "FAILED_DLQ")
    ]


def test_pipeline_status_unexpected_error():
    db = MockDatabaseAdapter()
    embedding = MockEmbeddingAdapter()
    coref = MockCoreferenceAdapter()
    extraction = MockEntityExtractionAdapter()
    status_tracker = MockStatusTracker()

    def raise_value_error(chunks):
        raise ValueError("Embedding failure")
    embedding.process_chunks = raise_value_error

    pipeline = StoryPipeline(
        db_adapter=db,
        embedding_adapter=embedding,
        coreference_adapter=coref,
        extraction_adapter=extraction,
        status_tracker=status_tracker,
    )

    article = SourceArticle(
        url="http://test.com/unexpected-fail",
        title="Unexpected Fail Title",
        content="Unexpected fail content."
    )

    with pytest.raises(ValueError, match="Embedding failure"):
        pipeline.run(article, dry_run=False)

    assert status_tracker.updates == [
        ("http://test.com/unexpected-fail", "PROCESSING"),
        ("http://test.com/unexpected-fail", "SYSTEM_ERROR")
    ]


def test_pipeline_status_dlq_failure():
    db = MockDatabaseAdapter()
    embedding = MockEmbeddingAdapter()
    coref = MockCoreferenceAdapter()
    extraction = MockEntityExtractionAdapter()
    status_tracker = MockStatusTracker()

    # Stub the resolve method to raise CoreferenceResolutionError
    def raise_coref_error(content):
        raise CoreferenceResolutionError(
            original_text=content,
            annotated_text="mismatched text",
            validation_issues=["Test structural issue"],
            failure_type="structural_mismatch",
            retry_count=3,
            metadata={"model": "gemma"}
        )
    coref.resolve = raise_coref_error

    # Mock DLQ adapter to raise OSError on write failure
    dlq = MockDeadLetterQueueAdapter()
    def raise_os_error(*args, **kwargs):
        raise OSError("Disk full")
    dlq.log_failure = raise_os_error

    pipeline = StoryPipeline(
        db_adapter=db,
        embedding_adapter=embedding,
        coreference_adapter=coref,
        extraction_adapter=extraction,
        status_tracker=status_tracker,
        dlq_adapter=dlq
    )

    article = SourceArticle(
        url="http://test.com/dlq-fail",
        title="DLQ Fail Title",
        content="DLQ fail content."
    )

    with pytest.raises(OSError, match="Disk full"):
        pipeline.run(article, dry_run=False)

    assert status_tracker.updates == [
        ("http://test.com/dlq-fail", "PROCESSING"),
        ("http://test.com/dlq-fail", "SYSTEM_ERROR")
    ]


def test_pipeline_status_dry_run():
    db = MockDatabaseAdapter()
    embedding = MockEmbeddingAdapter()
    coref = MockCoreferenceAdapter()
    extraction = MockEntityExtractionAdapter()
    status_tracker = MockStatusTracker()

    pipeline = StoryPipeline(
        db_adapter=db,
        embedding_adapter=embedding,
        coreference_adapter=coref,
        extraction_adapter=extraction,
        status_tracker=status_tracker,
    )

    article = SourceArticle(
        url="http://test.com/dry-run",
        title="Dry Run Title",
        content="Dry run content."
    )

    pipeline.run(article, dry_run=True)
    assert status_tracker.updates == []
