import math
import os
import asyncio
from dotenv import load_dotenv
from pydantic_ai import Embedder
from pydantic_ai.embeddings.openai import OpenAIEmbeddingModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.embeddings import EmbeddingSettings
from knowledge_map.config import settings
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

def get_embedding_embedder() -> Embedder:
    load_dotenv()
    ollama_base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
    ollama_embedding_model = os.environ.get("OLLAMA_EMBEDDING_MODEL", "embeddinggemma")
    
    base_url = ollama_base_url
    if not base_url.endswith("/v1"):
        base_url = f"{base_url}/v1"
        
    provider = OpenAIProvider(
        base_url=base_url,
        api_key="ollama",
    )
    
    model = OpenAIEmbeddingModel(
        ollama_embedding_model,
        provider=provider,
    )
    
    return Embedder(model, settings=EmbeddingSettings(dimension=settings.embedding.dimension))


class PydanticAIEmbeddingAdapter:
    """Concrete adapter for embeddings that conforms to the EmbeddingAdapter protocol."""
    
    def __init__(self, embedder: Embedder | None = None) -> None:
        self.embedder = embedder or get_embedding_embedder()

    def process_chunks(self, chunks: List[ArticleChunk]) -> List[List[float]]:
        if not chunks:
            return []
            
        texts = [chunk.text for chunk in chunks]
        embeddings = asyncio.run(self.embedder.embed_documents(texts))
        
        expected_dim = settings.embedding.dimension
        for i, emb in enumerate(embeddings):
            if len(emb) != expected_dim:
                raise ValueError(
                    f"Embedding dimension mismatch at chunk {i}: "
                    f"expected {expected_dim}, got {len(emb)}"
                )
                
        return embeddings

