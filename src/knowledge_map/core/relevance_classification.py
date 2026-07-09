"""Shared operations for metadata-based relevance classification."""

import logging
from typing import Optional

from knowledge_map.adapters.embedding import PydanticAIEmbeddingAdapter
from knowledge_map.adapters.sqlite_db import DEFAULT_DB_PATH, update_relevance_status
from knowledge_map.schemas import ArticleChunk

logger = logging.getLogger(__name__)


def get_metadata_embedding(
    headline: Optional[str],
    description: Optional[str],
    existing_embedding: Optional[list[float]] = None,
) -> Optional[list[float]]:
    """Return an existing or newly generated embedding for article metadata."""
    if existing_embedding:
        return existing_embedding

    text = f"{headline or ''} {description or ''}".strip()
    if not text:
        return None

    try:
        chunk = ArticleChunk(text=text, start_index=0, end_index=len(text), index=0)
        embeddings = PydanticAIEmbeddingAdapter().process_chunks([chunk])
        return embeddings[0] if embeddings else None
    except Exception:
        logger.warning("Failed to generate relevance metadata embedding", exc_info=True)
        return None


def persist_relevance_label(
    url: str,
    relevance_status: str,
    validation: Optional[str],
    label_source: str,
    headline: Optional[str],
    description: Optional[str],
    embedding: Optional[list[float]],
    db_path: str = DEFAULT_DB_PATH,
) -> None:
    """Persist a relevance decision with its reusable metadata representation."""
    update_relevance_status(
        url,
        relevance_status,
        validation,
        relevance_label_source=label_source,
        headline=headline,
        description=description,
        embedding=embedding,
        db_path=db_path,
    )
