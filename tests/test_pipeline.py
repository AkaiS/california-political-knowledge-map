import pytest
import logging
from knowledge_map.schemas import (
    AdherenceReport,
    ArticleChunk,
    CoreferenceResolutionRun,
    BillSessionResolution,
    BillSessionResolutions,
    ExtractionResult,
    LegislativeEventDates,
    Node,
    PipelineResult,
    SourceArticle,
    StoryLink,
)
from pydantic_ai.exceptions import ModelHTTPError

from knowledge_map.adapters.extraction import ExtractionError
from knowledge_map.adapters.policy_areas import PolicyAreaClassificationError
from knowledge_map.core.exceptions import (
    PipelineConnectivityError,
    PipelineRateLimitError,
    classify_exception,
)
from knowledge_map.core.pipeline import (
    StoryPipeline,
    DatabaseAdapter,
    EmbeddingAdapter,
    CoreferenceAdapter,
    EntityExtractionAdapter,
    PolicyAreaAdapter,
)
from knowledge_map.core.bill_sessions import parse_bill_designation, resolve_bill_sessions
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
        bill_sessions: BillSessionResolutions | None = None,
        event_dates: LegislativeEventDates | None = None,
    ) -> None:
        self.extractions.append((chunk_id, extraction, bill_sessions, event_dates))


@pytest.mark.parametrize(
    ("name", "designation"),
    [
        ("SB 623", "SB 623"),
        ("sb623", "SB 623"),
        ("Senate Bill 623", "SB 623"),
        ("senate bill 623", "SB 623"),
        ("AB-1751", "AB 1751"),
        ("Assembly Bill 1751", "AB 1751"),
        ("assembly bill1751", "AB 1751"),
    ],
)
def test_bill_designation_parser_accepts_the_four_supported_forms(name, designation):
    assert parse_bill_designation(name) == designation


@pytest.mark.parametrize("name", ["ll 623", "to 5", "the bill"])
def test_bill_designation_parser_rejects_non_designations(name):
    assert parse_bill_designation(name) is None


class MockEmbeddingAdapter:
    def process_chunks(self, chunks: list[ArticleChunk]) -> list[list[float]]:
        return [[0.1, 0.2, 0.3]] * len(chunks)

class MockCoreferenceAdapter:
    def resolve(self, content: str) -> CoreferenceResolutionRun:
        return CoreferenceResolutionRun(
            resolved_text=content,
            discarded_proportion=0.0,
        )

EMPTY_ADHERENCE_REPORT = AdherenceReport()


class MockEntityExtractionAdapter:
    def __init__(self):
        self.reset_calls = 0
        self.calls = []

    def extract(self, chunk_text: str) -> ExtractionResult:
        self.calls.append(chunk_text)
        return ExtractionResult(
            nodes=[Node(name="Test Actor", label="Politician")],
            relationships=[]
        )

    @property
    def adherence_report(self) -> AdherenceReport:
        return EMPTY_ADHERENCE_REPORT.model_copy(deep=True)

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
    chunk_id, stored_extraction, _bill_sessions, _event_dates = db.extractions[0]
    assert chunk_id == "http://test.com/persist#chunk_0"
    assert stored_extraction.nodes[0].name == "Test Actor"


def test_pipeline_extracts_owned_chunk_text_without_context():
    db = MockDatabaseAdapter()
    extraction = MockEntityExtractionAdapter()
    chunks = [
        ArticleChunk(
            text="owned chunk text",
            start_index=10,
            end_index=26,
            index=0,
            context="overlap context ",
        )
    ]
    pipeline = StoryPipeline(
        db_adapter=db,
        embedding_adapter=MockEmbeddingAdapter(),
        coreference_adapter=MockCoreferenceAdapter(),
        extraction_adapter=extraction,
        status_tracker=MockStatusTracker(),
    )
    article = SourceArticle(
        url="http://test.com/extraction-text",
        title="Extraction Text",
        content="article content",
    )

    with patch("knowledge_map.core.pipeline.chunk_article", return_value=chunks):
        pipeline.run(article, dry_run=True)

    assert extraction.calls == ["owned chunk text"]


def test_pipeline_resolves_bill_sessions_once_per_article():
    db = MockDatabaseAdapter()
    extraction = MockEntityExtractionAdapter()
    extraction.extract = lambda _text: ExtractionResult(nodes=[
        Node(name="Senate Bill 623", label="Bill"),
        Node(name="ll 623", label="Bill"),
        Node(name="sb623", label="Bill"),
        Node(name="sb54", label="Bill"),
        Node(name="AB 99", label="Bill"),
        Node(name="Senate Bill 1", label="Bill"),
        Node(name="AB 1", label="Bill"),
        Node(name="the bill", label="Bill"),
        Node(name="Richardson's legislation", label="Bill"),
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
            StoryLink(text="June budget", url="https://leginfo.legislature.ca.gov/faces/billTextClient.xhtml?bill_id=201920200SB623"),
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
    assert isinstance(first_map, BillSessionResolutions)
    assert first_map == BillSessionResolutions(by_name={
        "Senate Bill 623": BillSessionResolution(
            name="SB 623", session="2019-2020", session_verified=True
        ),
        "ll 623": BillSessionResolution(
            name="SB 623", session="2019-2020", session_verified=True
        ),
        "sb623": BillSessionResolution(
            name="SB 623", session="2019-2020", session_verified=True
        ),
        "sb54": BillSessionResolution(
            name="SB 54", session="2017-2018", session_verified=True
        ),
        "AB 99": BillSessionResolution(
            name="AB 99", session="2025-2026", session_inferred=True
        ),
        "Senate Bill 1": BillSessionResolution(
            name="SB 1", session="2025-2026", session_inferred=True
        ),
        "AB 1": BillSessionResolution(name="AB 1", needs_review=True),
        "the bill": BillSessionResolution(needs_review=True),
        "Richardson's legislation": BillSessionResolution(needs_review=True),
    })


def test_pipeline_marks_ambiguous_bill_designation_recovery_for_review():
    db = MockDatabaseAdapter()
    extraction = MockEntityExtractionAdapter()
    extraction.extract = lambda _text: ExtractionResult(nodes=[
        Node(name="SB 623", label="Bill"),
        Node(name="AB 623", label="Bill"),
        Node(name="ll 623", label="Bill"),
    ])
    pipeline = StoryPipeline(
        db_adapter=db,
        embedding_adapter=MockEmbeddingAdapter(),
        coreference_adapter=MockCoreferenceAdapter(),
        extraction_adapter=extraction,
        status_tracker=MockStatusTracker(),
    )
    article = SourceArticle(
        url="https://example.com/ambiguous-bills",
        title="Ambiguous Bills",
        published_date="2026-04-10T12:00:00Z",
        content="one chunk",
    )

    pipeline.run(article)

    assert db.extractions[0][2] == BillSessionResolutions(by_name={
        "AB 623": BillSessionResolution(
            name="AB 623", session="2025-2026", session_inferred=True
        ),
        "SB 623": BillSessionResolution(
            name="SB 623", session="2025-2026", session_inferred=True
        ),
        "ll 623": BillSessionResolution(needs_review=True),
    })


def test_bill_designation_recovery_is_independent_of_extraction_order():
    article = SourceArticle(
        url="https://example.com/order-independent",
        title="Order Independent",
        published_date="2026-04-10T12:00:00Z",
        content="article content",
    )
    extractions = [
        ExtractionResult(nodes=[Node(name="ll 623", label="Bill")]),
        ExtractionResult(nodes=[Node(name="Senate Bill 623", label="Bill")]),
    ]

    forward = resolve_bill_sessions(article, extractions)
    reverse = resolve_bill_sessions(article, list(reversed(extractions)))

    assert forward == reverse == BillSessionResolutions(by_name={
        "Senate Bill 623": BillSessionResolution(
            name="SB 623", session="2025-2026", session_inferred=True
        ),
        "ll 623": BillSessionResolution(
            name="SB 623", session="2025-2026", session_inferred=True
        ),
    })


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
        tool_name = info.output_tools[0].name
        return ModelResponse(parts=[
            ToolCallPart(
                tool_name=tool_name,
                args={
                    "response": [
                        {
                            "sentence_label": "2",
                            "mention_text": "He",
                            "canonical_entity_name": "Gavin Newsom",
                        }
                    ]
                },
                tool_call_id="call_1",
            )
        ])
        
    def mock_critic(messages, info):
        tool_name = info.output_tools[0].name
        return ModelResponse(parts=[
            ToolCallPart(
                tool_name=tool_name,
                args={
                    "response": [
                        {
                            "sentence_label": "2",
                            "mention_text": "He",
                            "accepted": True,
                        }
                    ]
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
    # The resolved text should contain canonical entity names.
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
            validation_issues=["Test coreference issue"],
            failure_type="all_mentions_rejected",
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
    assert "annotated_text" not in failure
    assert failure["validation_issues"] == ["Test coreference issue"]
    assert failure["failure_type"] == "all_mentions_rejected"
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
    assert "annotated_text" not in failure
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
            validation_issues=["Test coreference issue"],
            failure_type="all_mentions_rejected",
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
            validation_issues=["Test coreference issue"],
            failure_type="all_mentions_rejected",
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


class MockPolicyAreaAdapter:
    """A fake classification stage that returns the areas it was given."""

    def __init__(self, policy_areas=None, call_log=None):
        self.policy_areas = list(policy_areas or [])
        self.classified = []
        self.call_log = call_log if call_log is not None else []

    def classify(self, resolved_text: str) -> list[str]:
        self.classified.append(resolved_text)
        self.call_log.append("classify")
        return list(self.policy_areas)

    def health_check(self) -> bool:
        return True


class TopicRecordingDatabase(MockDatabaseAdapter):
    """A database that remembers the article-level topic writes it received."""

    def __init__(self, call_log=None):
        super().__init__()
        self.topics = []
        self.call_log = call_log if call_log is not None else []

    def ingest_article_topics(
        self, article, policy_areas, assignments=None, bill_sessions=None
    ):
        self.topics.append((article, policy_areas, assignments))


class ResolvingCoreferenceAdapter:
    """A coreference stage whose resolved text differs from the article."""

    def __init__(self, resolved_text: str, call_log=None):
        self.resolved_text = resolved_text
        self.call_log = call_log if call_log is not None else []

    def resolve(self, content: str) -> CoreferenceResolutionRun:
        self.call_log.append("resolve")
        return CoreferenceResolutionRun(
            resolved_text=self.resolved_text, discarded_proportion=0.0
        )


class OrderRecordingEmbeddingAdapter(MockEmbeddingAdapter):
    def __init__(self, call_log):
        self.call_log = call_log

    def process_chunks(self, chunks):
        self.call_log.append("embed")
        return super().process_chunks(chunks)


POLICY_AREA_ARTICLE = SourceArticle(
    url="http://test.com/policy-areas",
    title="Rent and clinics",
    content="She signed it.",
)


def test_classified_areas_reach_the_database_as_article_level_topics():
    db = TopicRecordingDatabase()
    classifier = MockPolicyAreaAdapter(["Housing & Community Development", "Health"])

    pipeline = StoryPipeline(
        db_adapter=db,
        embedding_adapter=MockEmbeddingAdapter(),
        coreference_adapter=MockCoreferenceAdapter(),
        extraction_adapter=MockEntityExtractionAdapter(),
        status_tracker=MockStatusTracker(),
        policy_area_adapter=classifier,
    )

    pipeline.run(POLICY_AREA_ARTICLE)

    assert db.topics == [
        (
            POLICY_AREA_ARTICLE,
            ["Housing & Community Development", "Health"],
            None,
        )
    ]


def test_classification_reads_the_resolved_text_before_chunking():
    call_log: list[str] = []
    coref = ResolvingCoreferenceAdapter("Kamala Harris signed it.", call_log)
    classifier = MockPolicyAreaAdapter(["Health"], call_log)

    pipeline = StoryPipeline(
        db_adapter=TopicRecordingDatabase(),
        embedding_adapter=OrderRecordingEmbeddingAdapter(call_log),
        coreference_adapter=coref,
        extraction_adapter=MockEntityExtractionAdapter(),
        status_tracker=MockStatusTracker(),
        policy_area_adapter=classifier,
    )

    pipeline.run(POLICY_AREA_ARTICLE)

    assert classifier.classified == ["Kamala Harris signed it."]
    assert call_log == ["resolve", "classify", "embed"]


def test_the_pipeline_result_carries_the_classified_areas():
    pipeline = StoryPipeline(
        db_adapter=TopicRecordingDatabase(),
        embedding_adapter=MockEmbeddingAdapter(),
        coreference_adapter=MockCoreferenceAdapter(),
        extraction_adapter=MockEntityExtractionAdapter(),
        status_tracker=MockStatusTracker(),
        policy_area_adapter=MockPolicyAreaAdapter(["Water"]),
    )

    result = pipeline.run(POLICY_AREA_ARTICLE, dry_run=True)

    assert result.policy_areas == ["Water"]


def test_an_article_with_no_policy_areas_completes_and_is_persisted():
    db = TopicRecordingDatabase()
    status_tracker = MockStatusTracker()

    pipeline = StoryPipeline(
        db_adapter=db,
        embedding_adapter=MockEmbeddingAdapter(),
        coreference_adapter=MockCoreferenceAdapter(),
        extraction_adapter=MockEntityExtractionAdapter(),
        status_tracker=status_tracker,
        policy_area_adapter=MockPolicyAreaAdapter([]),
    )

    pipeline.run(POLICY_AREA_ARTICLE)

    assert db.articles == [POLICY_AREA_ARTICLE]
    assert len(db.chunks) == 1
    assert db.topics == [(POLICY_AREA_ARTICLE, [], None)]
    assert status_tracker.updates[-1] == (POLICY_AREA_ARTICLE.url, "COMPLETED")


def test_a_dry_run_classifies_without_writing_article_topics():
    db = TopicRecordingDatabase()

    pipeline = StoryPipeline(
        db_adapter=db,
        embedding_adapter=MockEmbeddingAdapter(),
        coreference_adapter=MockCoreferenceAdapter(),
        extraction_adapter=MockEntityExtractionAdapter(),
        status_tracker=MockStatusTracker(),
        policy_area_adapter=MockPolicyAreaAdapter(["Health"]),
    )

    result = pipeline.run(POLICY_AREA_ARTICLE, dry_run=True)

    assert result.policy_areas == ["Health"]
    assert db.topics == []


class FailingPolicyAreaAdapter:
    def __init__(self, error):
        self.error = error

    def classify(self, resolved_text: str) -> list[str]:
        raise self.error

    def health_check(self) -> bool:
        return True


def test_a_classification_failure_logs_to_the_dlq_and_fails_the_article():
    dlq = MockDeadLetterQueueAdapter()
    status_tracker = MockStatusTracker()
    db = TopicRecordingDatabase()

    pipeline = StoryPipeline(
        db_adapter=db,
        embedding_adapter=MockEmbeddingAdapter(),
        coreference_adapter=MockCoreferenceAdapter(),
        extraction_adapter=MockEntityExtractionAdapter(),
        status_tracker=status_tracker,
        dlq_adapter=dlq,
        policy_area_adapter=FailingPolicyAreaAdapter(
            PolicyAreaClassificationError(
                original_text="She signed it.",
                validation_issues=["Interstellar Affairs is not a Policy Area"],
                retry_count=3,
                metadata={"model": "gemma"},
            )
        ),
    )

    with pytest.raises(PolicyAreaClassificationError):
        pipeline.run(POLICY_AREA_ARTICLE)

    assert len(dlq.failures) == 1
    failure = dlq.failures[0]
    assert failure["url"] == POLICY_AREA_ARTICLE.url
    assert failure["original_text"] == "She signed it."
    assert failure["validation_issues"] == [
        "Interstellar Affairs is not a Policy Area"
    ]
    assert failure["failure_type"] == "policy_area_classification_failure"
    assert failure["retry_count"] == 3
    assert failure["metadata"] == {"model": "gemma"}
    assert failure["error_category"] == "policy_area_classification"
    assert status_tracker.updates[-1] == (POLICY_AREA_ARTICLE.url, "FAILED_DLQ")
    assert db.articles == []


@pytest.mark.parametrize(
    ("status_code", "expected_error", "expected_status"),
    [
        (429, PipelineRateLimitError, "UNPROCESSED"),
        (503, PipelineConnectivityError, "UNPROCESSED"),
        (401, PipelineConnectivityError, "SYSTEM_ERROR"),
    ],
)
def test_a_transport_failure_in_classification_is_classified_like_every_stage(
    status_code, expected_error, expected_status
):
    status_tracker = MockStatusTracker()

    pipeline = StoryPipeline(
        db_adapter=TopicRecordingDatabase(),
        embedding_adapter=MockEmbeddingAdapter(),
        coreference_adapter=MockCoreferenceAdapter(),
        extraction_adapter=MockEntityExtractionAdapter(),
        status_tracker=status_tracker,
        policy_area_adapter=FailingPolicyAreaAdapter(
            ModelHTTPError(
                status_code=status_code, model_name="remote-model", body=None
            )
        ),
    )

    with pytest.raises(expected_error) as failure:
        pipeline.run(POLICY_AREA_ARTICLE)

    assert failure.value.component == "policy_area_classification"
    assert status_tracker.updates[-1] == (POLICY_AREA_ARTICLE.url, expected_status)


def test_a_classification_failure_is_routed_to_the_dlq_by_batch_ingestion():
    """The batch loop treats it as a Story-level failure, not a batch abort."""

    assert classify_exception(
        PolicyAreaClassificationError(original_text="She signed it.")
    )
