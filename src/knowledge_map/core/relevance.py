import json
import os
import re
from typing import Dict, Any, Optional, Tuple
from bs4 import BeautifulSoup

def _find_key_recursive(data: Any, key: str) -> Optional[Any]:
    """
    Recursively search for a key in a JSON-like dictionary or list structure.
    Returns the first matching value, or None if not found.
    """
    if isinstance(data, dict):
        if key in data:
            return data[key]
        for v in data.values():
            result = _find_key_recursive(v, key)
            if result is not None:
                return result
    elif isinstance(data, list):
        for item in data:
            result = _find_key_recursive(item, key)
            if result is not None:
                return result
    return None

def extract_metadata(html: str) -> Dict[str, Optional[str]]:
    """
    Extracts the headline and description from the raw HTML page.
    Attempts to parse JSON-LD scripts first, and falls back to HTML meta/title tags.
    """
    soup = BeautifulSoup(html, "html.parser")
    headline = None
    description = None

    # 1. Parse JSON-LD blocks
    json_ld_scripts = soup.find_all("script", type="application/ld+json")
    for script in json_ld_scripts:
        if not script.string:
            continue
        try:
            data = json.loads(script.string.strip())
            # Recursively look for headline and description
            if headline is None:
                headline = _find_key_recursive(data, "headline")
            if description is None:
                description = _find_key_recursive(data, "description")
        except Exception:
            # Skip invalid json blocks
            continue

    # 2. Fallback to HTML meta tags / title tags
    # Headline fallbacks:
    if not headline:
        og_title = soup.find("meta", attrs={"property": "og:title"})
        if og_title and og_title.get("content"):
            headline = og_title.get("content").strip()
            
    if not headline:
        twitter_title = soup.find("meta", attrs={"name": "twitter:title"})
        if twitter_title and twitter_title.get("content"):
            headline = twitter_title.get("content").strip()
            
    if not headline:
        title_tag = soup.find("title")
        if title_tag:
            headline = title_tag.get_text().strip()

    # Description fallbacks:
    if not description:
        meta_desc = soup.find("meta", attrs={"name": "description"})
        if meta_desc and meta_desc.get("content"):
            description = meta_desc.get("content").strip()
            
    if not description:
        og_desc = soup.find("meta", attrs={"property": "og:description"})
        if og_desc and og_desc.get("content"):
            description = og_desc.get("content").strip()
            
    if not description:
        twitter_desc = soup.find("meta", attrs={"name": "twitter:description"})
        if twitter_desc and twitter_desc.get("content"):
            description = twitter_desc.get("content").strip()

    return {
        "headline": headline,
        "description": description
    }


def has_word(text: str, keyword: str) -> bool:
    """
    Checks if a keyword exists in the text using word boundaries.
    """
    pattern = r'\b' + re.escape(keyword.lower()) + r'\b'
    return bool(re.search(pattern, text))


WEIGHTS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
    "src",
    "knowledge_map",
    "resources",
    "classifier_weights.json"
)

_cached_weights = None

def load_classifier_weights() -> Optional[Dict[str, Any]]:
    global _cached_weights
    if _cached_weights is not None:
        return _cached_weights
    if os.path.exists(WEIGHTS_PATH):
        try:
            with open(WEIGHTS_PATH, "r") as f:
                _cached_weights = json.load(f)
            return _cached_weights
        except Exception:
            pass
    return None


def classify_inconclusive_embeddings(headline: str, description: str) -> str:
    """
    Hook for future Logistic Regression embeddings-based classifier.
    This will take the headline and description, compute metadata embeddings,
    and predict if the article is RELEVANT or IRRELEVANT.
    Currently returns 'INCONCLUSIVE'.
    """
    return "INCONCLUSIVE"


def classify_article(
    headline: Optional[str],
    description: Optional[str],
    embedding: Optional[list[float]] = None
) -> str:
    """
    Classifies an article into RELEVANT, IRRELEVANT, or INCONCLUSIVE based on
    its metadata matching configured keyword lists or Logistic Regression model.
    """
    import math
    weights = load_classifier_weights()
    if weights and embedding:
        coef = weights.get("coefficients")
        intercept = weights.get("intercept")
        if isinstance(intercept, list):
            intercept = intercept[0] if intercept else 0.0
        elif intercept is None:
            intercept = 0.0

        if coef and len(embedding) == len(coef):
            z = sum(w * x for w, x in zip(coef, embedding)) + intercept
            try:
                prob = 1.0 / (1.0 + math.exp(-z))
            except OverflowError:
                prob = 0.0 if z < 0 else 1.0

            if prob >= 0.7:
                return "RELEVANT"
            elif prob < 0.3:
                return "IRRELEVANT"
            else:
                return "INCONCLUSIVE"

    from knowledge_map.config import (
        POLITICAL_RELEVANCE_KEYWORDS,
        NEGATIVE_RELEVANCE_KEYWORDS,
        SECONDARY_RELEVANCE_KEYWORDS
    )
    
    text = f"{headline or ''} {description or ''}".lower()

    # 1. Negative keywords match -> IRRELEVANT
    if any(has_word(text, kw) for kw in NEGATIVE_RELEVANCE_KEYWORDS):
        return "IRRELEVANT"

    # 2. High-confidence political keywords -> RELEVANT
    if any(has_word(text, kw) for kw in POLITICAL_RELEVANCE_KEYWORDS):
        return "RELEVANT"

    # 3. Secondary local/state keywords -> INCONCLUSIVE
    if any(has_word(text, kw) for kw in SECONDARY_RELEVANCE_KEYWORDS):
        return classify_inconclusive_embeddings(headline or "", description or "")

    # 4. Zero keyword matches -> IRRELEVANT
    return "IRRELEVANT"


def check_relevance(html: str, embedding: Optional[list[float]] = None) -> Tuple[str, Dict[str, Optional[str]], Optional[list[float]]]:
    """
    Extracts metadata, optionally computes embedding, and classifies the article relevance.
    Returns a 3-tuple of (relevance_status, metadata_dict, embedding).
    """
    meta = extract_metadata(html)
    headline = meta.get("headline")
    description = meta.get("description")
    
    if embedding is None:
        text_to_embed = f"{headline or ''} {description or ''}".strip()
        if text_to_embed:
            try:
                from knowledge_map.adapters.embedding import PydanticAIEmbeddingAdapter
                from knowledge_map.schemas import ArticleChunk
                adapter = PydanticAIEmbeddingAdapter()
                chunk = ArticleChunk(text=text_to_embed, start_index=0, end_index=len(text_to_embed), index=0)
                embeddings = adapter.process_chunks([chunk])
                if embeddings:
                    embedding = embeddings[0]
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(f"Failed to generate embedding for relevance check: {e}")
                
    status = classify_article(headline, description, embedding)
    return status, meta, embedding


def serialize_embedding(embedding: Optional[list[float]]) -> Optional[bytes]:
    """
    Serializes a list of floats to a binary BLOB (bytes) of float32 values.
    """
    if embedding is None:
        return None
    import struct
    return struct.pack(f"{len(embedding)}f", *embedding)


def deserialize_embedding(blob: Optional[bytes]) -> Optional[list[float]]:
    """
    Deserializes a binary BLOB (bytes) of float32 values back to a list of floats.
    """
    if blob is None:
        return None
    import struct
    n = len(blob) // 4
    if n == 0:
        return []
    return list(struct.unpack(f"{n}f", blob))

