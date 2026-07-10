import pytest
import os
from unittest.mock import patch, MagicMock
from knowledge_map.adapters.embedding import cosine_similarity, get_embedding_embedder, PydanticAIEmbeddingAdapter
from knowledge_map.schemas import ArticleChunk

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

def test_get_embedding_embedder():
    with patch.dict(os.environ, {
        "OLLAMA_BASE_URL": "http://localhost:11434",
        "OLLAMA_EMBEDDING_MODEL": "embeddinggemma"
    }):
        embedder = get_embedding_embedder()
        assert embedder is not None
        assert embedder.model.model_name == "embeddinggemma"



class MockResult:
    def __init__(self, embeddings):
        self.embeddings = embeddings

def test_pydantic_ai_embedding_adapter_success():
    mock_embedder = MagicMock()
    async def fake_embed(documents):
        return MockResult([[0.1] * 768] * len(documents))
    mock_embedder.embed_documents.side_effect = fake_embed

    adapter = PydanticAIEmbeddingAdapter(embedder=mock_embedder)
    chunks = [
        ArticleChunk(text="Chunk 1 text", start_index=0, end_index=12, index=0),
        ArticleChunk(text="Chunk 2 text", start_index=13, end_index=25, index=1)
    ]
    
    result = adapter.process_chunks(chunks)
    assert len(result) == 2
    assert result[0] == [0.1] * 768
    assert result[1] == [0.1] * 768
    mock_embedder.embed_documents.assert_called_once_with(["Chunk 1 text", "Chunk 2 text"])

def test_pydantic_ai_embedding_adapter_embed_text_success():
    mock_embedder = MagicMock()
    async def fake_embed(documents):
        return MockResult([[0.1] * 768] * len(documents))
    mock_embedder.embed_documents.side_effect = fake_embed

    adapter = PydanticAIEmbeddingAdapter(embedder=mock_embedder)

    result = adapter.embed_text("Metadata text")

    assert result == [0.1] * 768
    mock_embedder.embed_documents.assert_called_once_with(["Metadata text"])

def test_pydantic_ai_embedding_adapter_embed_text_empty():
    mock_embedder = MagicMock()
    adapter = PydanticAIEmbeddingAdapter(embedder=mock_embedder)

    with pytest.raises(ValueError, match="Text must not be empty"):
        adapter.embed_text("")

    mock_embedder.embed_documents.assert_not_called()

def test_pydantic_ai_embedding_adapter_embed_text_dimension_mismatch():
    mock_embedder = MagicMock()
    async def fake_embed(documents):
        return MockResult([[0.1] * 128])
    mock_embedder.embed_documents.side_effect = fake_embed

    adapter = PydanticAIEmbeddingAdapter(embedder=mock_embedder)

    with pytest.raises(ValueError, match="Embedding dimension mismatch"):
        adapter.embed_text("Metadata text")

def test_pydantic_ai_embedding_adapter_empty():
    mock_embedder = MagicMock()
    adapter = PydanticAIEmbeddingAdapter(embedder=mock_embedder)
    result = adapter.process_chunks([])
    assert result == []
    mock_embedder.embed_documents.assert_not_called()

def test_pydantic_ai_embedding_adapter_dimension_mismatch():
    mock_embedder = MagicMock()
    async def fake_embed(documents):
        return MockResult([[0.1] * 128] * len(documents))  # default config is 768
    mock_embedder.embed_documents.side_effect = fake_embed

    adapter = PydanticAIEmbeddingAdapter(embedder=mock_embedder)
    chunks = [ArticleChunk(text="Some text", start_index=0, end_index=9, index=0)]
    
    with pytest.raises(ValueError, match="Embedding dimension mismatch"):
        adapter.process_chunks(chunks)

def test_pydantic_ai_embedding_adapter_health_check_success():
    mock_embedder = MagicMock()
    async def fake_embed(documents):
        return MockResult([[0.1] * 768])
    mock_embedder.embed_documents.side_effect = fake_embed

    adapter = PydanticAIEmbeddingAdapter(embedder=mock_embedder)
    assert adapter.health_check() is True
    mock_embedder.embed_documents.assert_called_once_with(["health_check"])

def test_pydantic_ai_embedding_adapter_health_check_failure():
    mock_embedder = MagicMock()
    async def fake_embed(documents):
        raise RuntimeError("API Connection failed")
    mock_embedder.embed_documents.side_effect = fake_embed

    adapter = PydanticAIEmbeddingAdapter(embedder=mock_embedder)
    assert adapter.health_check() is False
    mock_embedder.embed_documents.assert_called_once_with(["health_check"])


