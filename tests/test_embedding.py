import asyncio
import pytest
import os
import httpx
from unittest.mock import patch, MagicMock
from knowledge_map.adapters.embedding import cosine_similarity, get_embedding_embedder, PydanticAIEmbeddingAdapter
from knowledge_map.config import TransportSettings
from knowledge_map.core.exceptions import (
    PipelineConnectivityError,
    transport_failures_as_pipeline_errors,
)
from knowledge_map.schemas import ArticleChunk
from knowledge_map.utils.event_loop import thread_event_loop


@pytest.fixture
def recorded_embedding_waits(monkeypatch):
    """Record every retry wait and take none of them."""

    waits: list[float] = []
    real_sleep = asyncio.sleep

    async def recording_sleep(delay, *args, **kwargs):
        waits.append(delay)
        return await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", recording_sleep)
    return waits

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
        "LLAMA_CPP_EMBEDDING_BASE_URL": "http://localhost:8081",
        "EMBEDDING_MODEL": "embeddinggemma"
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
        ArticleChunk(
            text="Chunk 2 text",
            start_index=13,
            end_index=25,
            index=1,
            context="Overlap text ",
        )
    ]
    
    result = adapter.process_chunks(chunks)
    assert len(result) == 2
    assert result[0] == [0.1] * 768
    assert result[1] == [0.1] * 768
    mock_embedder.embed_documents.assert_called_once_with(
        ["Chunk 1 text", "Overlap text Chunk 2 text"]
    )

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



class TestTheEmbeddingStageRetriesItsOwnRequests:
    """The embedding stage is not an LLM call and does not pass through the
    model factory, so it does not inherit that factory's retrying client.  It
    builds its own, and these assertions run a real embedding call against an
    ``httpx.MockTransport`` standing in for the local llama.cpp embedding host.
    """

    @staticmethod
    def embedding_response(dimension: int = 768) -> dict:
        """A minimal OpenAI-compatible embeddings body."""

        return {
            "object": "list",
            "model": "embeddinggemma",
            "data": [
                {"object": "embedding", "index": 0, "embedding": [0.1] * dimension}
            ],
            "usage": {"prompt_tokens": 1, "total_tokens": 1},
        }

    @staticmethod
    def adapter_for(transport, **kwargs) -> PydanticAIEmbeddingAdapter:
        return PydanticAIEmbeddingAdapter(
            embedder=get_embedding_embedder(transport=transport, **kwargs)
        )

    def test_a_rate_limited_request_is_retried_after_the_header_delay(
        self, recorded_embedding_waits
    ):
        requests = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if len(requests) == 1:
                return httpx.Response(
                    429,
                    headers={"Retry-After": "7"},
                    json={"error": {"message": "rate limited"}},
                )
            return httpx.Response(200, json=self.embedding_response())

        adapter = self.adapter_for(httpx.MockTransport(handler))

        assert adapter.embed_text("The Governor signed the bill.") == [0.1] * 768
        assert len(requests) == 2
        assert 7.0 in recorded_embedding_waits

    def test_transport_errors_are_retried_until_the_attempt_count_is_exhausted(
        self, recorded_embedding_waits
    ):
        attempts = []

        def handler(request: httpx.Request) -> httpx.Response:
            attempts.append(request)
            raise httpx.ConnectError("connection reset by peer")

        transport_settings = TransportSettings(max_attempts=2)
        adapter = self.adapter_for(
            httpx.MockTransport(handler), transport_settings=transport_settings
        )

        with pytest.raises(Exception):
            adapter.embed_text("The Governor signed the bill.")

        assert len(attempts) == transport_settings.max_attempts

    def test_an_exhausted_retry_reaches_the_pipeline_as_a_connectivity_error(
        self, recorded_embedding_waits
    ):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection reset by peer")

        adapter = self.adapter_for(
            httpx.MockTransport(handler),
            transport_settings=TransportSettings(max_attempts=2),
        )

        with pytest.raises(PipelineConnectivityError) as exc_info:
            with transport_failures_as_pipeline_errors("embedding"):
                adapter.embed_text("The Governor signed the bill.")

        assert exc_info.value.component == "embedding"


def test_embedding_leaves_the_thread_loop_installed_for_the_next_caller():
    """Model clients outlive one call, so they need the loop to outlive it too.

    A loop that is closed and uninstalled after each embed leaves the next
    blocking model call to build a fresh one, and the connection pools bound
    to the old loop then refuse the request as a bare connection error.
    """

    mock_embedder = MagicMock()

    async def fake_embed(documents):
        return MockResult([[0.1] * 768] * len(documents))

    mock_embedder.embed_documents.side_effect = fake_embed

    loop_before = thread_event_loop()
    PydanticAIEmbeddingAdapter(embedder=mock_embedder).embed_text("Chunk text")

    assert asyncio.get_event_loop() is loop_before
    assert not loop_before.is_closed()
