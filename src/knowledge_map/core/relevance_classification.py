"""Shared operations for metadata-based relevance classification."""

import logging
from typing import Any, NamedTuple, Optional

from knowledge_map.adapters.embedding import PydanticAIEmbeddingAdapter
from knowledge_map.adapters.sqlite_db import (
    DEFAULT_DB_PATH,
    ArticleMetadataUpdateResult,
    RelevanceUpdateResult,
    get_articles_for_metadata_backfill,
    get_cached_html,
    update_article_metadata,
    update_relevance_status,
)
from knowledge_map.core.relevance import extract_metadata

logger = logging.getLogger(__name__)


class MetadataBackfillResult(NamedTuple):
    candidates: int
    updated: int


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
        return PydanticAIEmbeddingAdapter().embed_text(text)
    except Exception:
        logger.warning("Failed to generate relevance metadata embedding", exc_info=True)
        return None


def persist_relevance_label(
    url: str,
    relevance_status: str,
    label_source: str,
    db_path: str = DEFAULT_DB_PATH,
) -> RelevanceUpdateResult:
    """Persist only the relevance decision owned by the classification stage."""
    return update_relevance_status(
        url,
        relevance_status,
        label_source,
        db_path=db_path,
    )


def _find_metadata_value(data: Any, *keys: str) -> Optional[str]:
    if isinstance(data, dict):
        for key in keys:
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        for value in data.values():
            result = _find_metadata_value(value, *keys)
            if result:
                return result
    elif isinstance(data, list):
        for value in data:
            result = _find_metadata_value(value, *keys)
            if result:
                return result
    return None


def populate_article_metadata(
    url: str,
    db_path: str = DEFAULT_DB_PATH,
) -> ArticleMetadataUpdateResult:
    """Populate missing metadata from cached HTML or stored discovery metadata."""
    cached = get_cached_html(url, db_path=db_path)
    if cached is None:
        raise ValueError(f"Cached article not found: {url}")

    raw_html = cached.get("raw_html")
    html_metadata = extract_metadata(raw_html) if raw_html else {}
    stored_metadata = cached.get("raw_metadata_json") or {}

    headline = (
        cached.get("headline")
        or _find_metadata_value(stored_metadata, "headline", "title")
        or html_metadata.get("headline")
    )
    description = (
        cached.get("description")
        or _find_metadata_value(stored_metadata, "description", "summary")
        or html_metadata.get("description")
    )
    embedding = get_metadata_embedding(
        headline,
        description,
        cached.get("embedding"),
    )

    return update_article_metadata(
        url,
        headline,
        description,
        embedding,
        db_path=db_path,
    )


def backfill_relevance_training_data(
    db_path: str = DEFAULT_DB_PATH,
) -> MetadataBackfillResult:
    """Populate cached metadata and embeddings without fetching article URLs."""
    urls = get_articles_for_metadata_backfill(db_path=db_path)
    updated = 0
    for url in urls:
        result = populate_article_metadata(url, db_path=db_path)
        updated += int(result.applied)
    return MetadataBackfillResult(candidates=len(urls), updated=updated)
