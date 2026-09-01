import math
import os
import asyncio
import httpx
from dotenv import load_dotenv
from openai import AsyncOpenAI
from pydantic_ai import Embedder
from pydantic_ai.embeddings.openai import OpenAIEmbeddingModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.embeddings import EmbeddingSettings
from knowledge_map.config import TransportSettings, settings
from knowledge_map.utils.models import build_retrying_client, resolve_embedding_base_url
from typing import List
from knowledge_map.schemas import ArticleChunk

def cosine_similarity(v1: list[float], v2: list[float]) -> float:
    if len(v1) != len(v2):
        raise ValueError("Vectors must be of the same dimension.")
    dot_product = sum(x * y for x, y in zip(v1, v2))
    mag1 = math.sqrt(sum(x * x for x in v1))
    mag2 = math.sqrt(sum(x * x for x in v2))
    if mag1 == 0.0 or mag2 == 0.0:
        return 0.0
    return dot_product / (mag1 * mag2)

def get_embedding_embedder(
    *,
    transport_settings: TransportSettings | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> Embedder:
    """Build the Embedder for the embedding stage, on the retrying HTTP client.

    The embedding stage bypasses the model factory, so it builds its own
    client here.  An exhausted retry budget still reaches the Story Pipeline
    as a transport failure for the embedding component.
    """

    load_dotenv()
    # Keep the legacy embedding variable as a compatibility read for existing
    # local configs.  It only selects the local embedding model; it cannot
    # affect chat deployment selection.
    embedding_model = os.environ.get("EMBEDDING_MODEL") or os.environ.get(
        "OLLAMA_EMBEDDING_MODEL", "embeddinggemma"
    )

    # Retries belong to the transport, so the SDK makes exactly one attempt
    # rather than multiplying the configured count.
    openai_client = AsyncOpenAI(
        base_url=resolve_embedding_base_url(),
        # llama-server does not check it, but the SDK refuses to build without one.
        api_key="llama.cpp",
        http_client=build_retrying_client(transport_settings, transport),
        max_retries=0,
    )
    provider = OpenAIProvider(openai_client=openai_client)

    model = OpenAIEmbeddingModel(
        embedding_model,
        provider=provider,
    )

    return Embedder(model, settings=EmbeddingSettings(dimension=settings.embedding.dimension))


class PydanticAIEmbeddingAdapter:
    """Concrete adapter for embeddings that conforms to the EmbeddingAdapter protocol."""
    
    def __init__(self, embedder: Embedder | None = None) -> None:
        self.embedder = embedder or get_embedding_embedder()

    def _run_async(self, func, *args, **kwargs):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
            
        if loop is not None and loop.is_running():
            import concurrent.futures
            def runner():
                return asyncio.run(func(*args, **kwargs))
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(runner)
                return future.result()
        else:
            return asyncio.run(func(*args, **kwargs))

    def _validate_embedding(self, embedding: list[float], context: str = "") -> list[float]:
        expected_dim = settings.embedding.dimension
        if len(embedding) != expected_dim:
            prefix = f"{context}: " if context else ""
            raise ValueError(
                f"{prefix}Embedding dimension mismatch: "
                f"expected {expected_dim}, got {len(embedding)}"
            )
        return embedding

    def embed_text(self, text: str) -> list[float]:
        """Generate and validate one document embedding for a text value."""
        if not text:
            raise ValueError("Text must not be empty.")

        result = self._run_async(self.embedder.embed_documents, [text])
        if len(result.embeddings) != 1:
            raise ValueError(
                f"Expected one embedding, got {len(result.embeddings)}"
            )

        return self._validate_embedding(result.embeddings[0])

    def process_chunks(self, chunks: List[ArticleChunk]) -> List[List[float]]:
        if not chunks:
            return []
            
        texts = [chunk.embedded_text for chunk in chunks]
        result = self._run_async(self.embedder.embed_documents, texts)
        embeddings = result.embeddings
        
        for i, emb in enumerate(embeddings):
            self._validate_embedding(emb, context=f"At chunk {i}")
                
        return embeddings

    def health_check(self) -> bool:
        try:
            result = self._run_async(self.embedder.embed_documents, ["health_check"])
            return bool(result and result.embeddings)
        except Exception:
            return False
