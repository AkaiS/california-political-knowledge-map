import pytest
from schemas import SourceArticle, ArticleChunk, ExtractionResult, PipelineResult, Node
from pipeline import (
    StoryPipeline,
    DatabaseAdapter,
    EmbeddingAdapter,
    CoreferenceAdapter,
    EntityExtractionAdapter,
)
from embedding import PydanticAIEmbeddingAdapter
from coreference import PydanticAICoreferenceAdapter, get_annotator_agent, get_critic_agent
from extraction import PydanticAIEntityExtractionAdapter, get_extraction_agent
from unittest.mock import MagicMock, patch
from graph_db import Neo4jAdapter
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
        extraction: ExtractionResult
    ) -> None:
        self.extractions.append((chunk_id, extraction))

class MockEmbeddingAdapter:
    def process_chunks(self, chunks: list[ArticleChunk]) -> list[list[float]]:
        return [[0.1, 0.2, 0.3]] * len(chunks)

class MockCoreferenceAdapter:
    def resolve(self, content: str) -> str:
        return content

class MockEntityExtractionAdapter:
    def extract(self, chunk_text: str) -> ExtractionResult:
        return ExtractionResult(
            nodes=[Node(name="Test Actor", label="PoliticalActor")],
            relationships=[]
        )

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
    chunk_id, stored_extraction = db.extractions[0]
    assert chunk_id == "http://test.com/persist#chunk_0"
    assert stored_extraction.nodes[0].name == "Test Actor"

def test_pipeline_logging(caplog):
    import logging
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
    )

    article = SourceArticle(
        url="http://test.com/error",
        title="Error Title",
        content="Error testing."
    )

    with pytest.raises(ValueError, match="Embedding calculation failed"):
        pipeline.run(article)


def test_pipeline_with_concrete_adapters():
    # 1. Mock embedder
    mock_embedder = MagicMock()
    async def fake_embed(documents):
        return [[0.1] * 768] * len(documents)
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
                        {"name": "Gavin Newsom", "label": "PoliticalActor"}
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
    )
    
    article = SourceArticle(
        url="http://example.com/integration",
        title="Integration Title",
        content="This is integration test content."
    )
    
    with patch("graph_db.Neo4jAdapter._ensure_vector_index"):
        result = pipeline.run(article, dry_run=False)
    
    assert isinstance(result, PipelineResult)
    assert mock_tx.run.call_count >= 2
    queries = [call[0][0] for call in mock_tx.run.call_args_list]
    assert any("MERGE (a:Article {url: $url})" in q for q in queries)
    assert any("MERGE (c:Chunk {id: $chunk_id})" in q for q in queries)



