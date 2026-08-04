import re
import html
import unicodedata
import datetime
import json
import sqlite3
import logging
from typing import List, Optional, Any, Dict, Tuple
from bs4 import BeautifulSoup
from knowledge_map.config import settings
from knowledge_map.adapters.sqlite_db import (
    clear_cached_html,
    replace_story,
    save_story,
    update_cached_html_status,
    DEFAULT_DB_PATH,
    get_publication,
    increment_publication_failure_points,
    reset_publication_failure_points,
    pause_publication_validation,
    unpause_publication_validation,
    update_relevance_status,
    delete_uningested_story,
)
from knowledge_map.core.selectors import (
    get_selector_versions_by_proximity,
    widen_selector_version_window
)
from knowledge_map.core.relevance import load_classifier_weights, classify_article
from knowledge_map.core.relevance_agent import classify_article_with_llm
from knowledge_map.core.relevance_classification import populate_article_metadata

logger = logging.getLogger(__name__)
from knowledge_map.schemas.pipeline import ArticleStatus
from knowledge_map.schemas.relevance import (
    LabelSource,
    RelevanceStatus,
    ValidationStatus,
)
from knowledge_map.schemas.stories import Story, StoryLink
from knowledge_map.utils.console import ConsoleNotifier
from knowledge_map.utils.urls import clean_and_resolve_url

ILLEGITIMATE_ANCESTORS = {"aside", "nav", "footer", "figure"}

TOLERANCE = 0.05

try:
    import logfire
except ImportError:
    logfire = None

def damerau_levenshtein_distance(s1: str, s2: str) -> int:
    """
    Computes the Damerau-Levenshtein distance between two strings s1 and s2.
    Supports insertions, deletions, substitutions, and transpositions.
    """
    d = {}
    lenstr1 = len(s1)
    lenstr2 = len(s2)
    for i in range(-1, lenstr1 + 1):
        d[(i, -1)] = i + 1
    for j in range(-1, lenstr2 + 1):
        d[(-1, j)] = j + 1
    for i in range(lenstr1):
        for j in range(lenstr2):
            if s1[i] == s2[j]:
                cost = 0
            else:
                cost = 1
            d[(i, j)] = min(
                d[(i - 1, j)] + 1,  # deletion
                d[(i, j - 1)] + 1,  # insertion
                d[(i - 1, j - 1)] + cost,  # substitution
            )
            if i and j and s1[i] == s2[j - 1] and s1[i - 1] == s2[j]:
                d[(i, j)] = min(d[(i, j)], d[(i - 2, j - 2)] + cost)  # transposition
    return d[(lenstr1 - 1, lenstr2 - 1)]


def edit_distance_ratio(s1: str, s2: str) -> float:
    """
    Calculates the similarity ratio based on Damerau-Levenshtein distance:
    1.0 - (distance / max(len1, len2))
    """
    if not s1 and not s2:
        return 1.0
    if not s1 or not s2:
        return 0.0
    dist = damerau_levenshtein_distance(s1, s2)
    return 1.0 - (dist / max(len(s1), len(s2)))


def clean_and_normalize_text(text: str) -> str:
    """
    Decodes HTML entities and normalizes Unicode whitespace in a string.
    Collapses multiple whitespace characters into single spaces and strips leading/trailing space.
    """
    if not text:
        return ""
    # Double unescape to handle double-encoded entities safely
    decoded = html.unescape(text)
    decoded = html.unescape(decoded)
    normalized = unicodedata.normalize("NFKC", decoded)
    cleaned = re.sub(r"\s+", " ", normalized)
    return cleaned.strip()


def normalize_author_string(author_str: str) -> List[str]:
    """
    Normalizes an author string:
    - Case-insensitive strip of filler words ('By', 'Staff', 'Special to', 'Reporter', 'Written by').
    - Split on commas and 'and'.
    - Returns a list of lowercase normalized individual author names.
    """
    if not author_str:
        return []

    # HTML decode and unicode normalize/clean the author string
    cleaned = clean_and_normalize_text(author_str)

    # Case-insensitive replacement of known filler patterns/words.
    # We use regex to remove these filler words case-insensitively with word boundaries.
    fillers = [
        r"\bby\b",
        r"\bstaff\b",
        r"\bspecial to\b",
        r"\breporter\b",
        r"\bwritten by\b"
    ]
    for filler in fillers:
        cleaned = re.sub(filler, "", cleaned, flags=re.IGNORECASE)

    parts = []
    # Split on commas
    comma_split = cleaned.split(",")
    for p in comma_split:
        # Split on "and" with word boundaries
        and_split = re.split(r"\band\b", p, flags=re.IGNORECASE)
        for a in and_split:
            final_part = a.strip()
            # Collapse multiple whitespaces
            final_part = re.sub(r"\s+", " ", final_part)
            # Remove any leading/trailing non-alphanumeric chars (like punctuation, dots, etc. at start/end)
            final_part = re.sub(r"^[^a-zA-Z0-9]+|[^a-zA-Z0-9]+$", "", final_part)
            if final_part:
                parts.append(final_part.lower())
    return parts


def parse_date_string(date_str: str) -> Optional[datetime.datetime]:
    """
    Parses a date string in ISO 8601 or other common human-readable formats.
    Resolves timezone offsets and returns a UTC datetime (timezone-aware).
    """
    if not date_str:
        return None

    cleaned = date_str.strip()

    # 1. Try parsing ISO 8601 format
    iso_candidate = cleaned
    if iso_candidate.endswith("Z"):
        iso_candidate = iso_candidate[:-1] + "+00:00"
    try:
        dt = datetime.datetime.fromisoformat(iso_candidate)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt.astimezone(datetime.timezone.utc)
    except ValueError:
        pass

    # 2. Try common human-readable formats
    formats = [
        "%B %d, %Y",       # June 18, 2026
        "%b %d, %Y",       # Jun 18, 2026
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%d %B %Y",        # 18 June 2026
        "%m/%d/%Y",        # 06/18/2026
    ]

    # Pre-clean weekday prefixes
    cleaned_prefix = re.sub(
        r'^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|Mon|Tue|Wed|Thu|Fri|Sat|Sun),\s*',
        '',
        cleaned,
        flags=re.IGNORECASE
    )
    cleaned_prefix = cleaned_prefix.strip()

    for fmt in formats:
        try:
            dt = datetime.datetime.strptime(cleaned_prefix, fmt)
            return dt.replace(tzinfo=datetime.timezone.utc)
        except ValueError:
            continue

    return None


def extract_json_ld_ground_truth(html: str) -> Optional[Dict[str, Any]]:
    """
    Finds and parses all JSON-LD blocks in the HTML, looking for article metadata.
    Prioritizes NewsArticle, BlogPosting, or Article types, then falls back to other types.
    Returns a dictionary with 'headline', 'datePublished', 'authors' (list of names), and 'wordCount'.
    If no valid JSON-LD metadata is found, returns None.
    """
    soup = BeautifulSoup(html, "html.parser")
    json_ld_scripts = soup.find_all("script", type="application/ld+json")
    
    candidates = []
    id_map = {}
    
    def get_node_rank(node: Dict[str, Any]) -> int:
        if not isinstance(node, dict) or not node.get("@id"):
            return 0
        has_name = "name" in node
        node_type = node.get("@type")
        is_person = False
        if isinstance(node_type, str):
            is_person = (node_type == "Person")
        elif isinstance(node_type, list):
            is_person = any(t == "Person" for t in node_type)
        if has_name and is_person:
            return 3
        if has_name:
            return 2
        return 1

    def process_node(node: Any):
        if isinstance(node, dict):
            node_id = node.get("@id")
            if node_id and isinstance(node_id, str):
                new_rank = get_node_rank(node)
                existing = id_map.get(node_id)
                if existing is None:
                    id_map[node_id] = node
                else:
                    existing_rank = get_node_rank(existing)
                    if new_rank > existing_rank:
                        id_map[node_id] = node
                    elif new_rank == existing_rank:
                        if len(node) > len(existing):
                            id_map[node_id] = node
            
            node_type = node.get("@type")
            if isinstance(node_type, str) and node_type in ("NewsArticle", "BlogPosting", "Article", "WebPage"):
                candidates.append(node)
            elif isinstance(node_type, list) and any(t in ("NewsArticle", "BlogPosting", "Article", "WebPage") for t in node_type):
                candidates.append(node)
            
            for v in node.values():
                process_node(v)
        elif isinstance(node, list):
            for item in node:
                process_node(item)
                
    for script in json_ld_scripts:
        if not script.string:
            continue
        try:
            data = json.loads(script.string.strip())
            process_node(data)
        except Exception:
            continue
            
    if not candidates:
        for script in json_ld_scripts:
            if not script.string:
                continue
            try:
                data = json.loads(script.string.strip())
                if isinstance(data, dict):
                    candidates.append(data)
                elif isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict):
                            candidates.append(item)
            except Exception:
                continue

    if not candidates:
        return None
        
    def type_priority(c: Dict[str, Any]) -> int:
        nt = c.get("@type")
        if isinstance(nt, list):
            types = set(nt)
        else:
            types = {nt}
        if "NewsArticle" in types:
            return 0
        if "BlogPosting" in types:
            return 1
        if "Article" in types:
            return 2
        return 3
        
    candidates.sort(key=type_priority)
    
    def resolve_author_names(author_node: Any) -> List[str]:
        if not author_node:
            return []
        if isinstance(author_node, str):
            return [author_node]
        if isinstance(author_node, list):
            names = []
            for item in author_node:
                names.extend(resolve_author_names(item))
            return names
        if isinstance(author_node, dict):
            name = author_node.get("name")
            if name:
                if isinstance(name, list):
                    return [str(n) for n in name if n]
                return [str(name)]
            node_id = author_node.get("@id")
            if node_id and node_id in id_map:
                resolved = id_map[node_id]
                resolved_name = resolved.get("name")
                if resolved_name:
                    if isinstance(resolved_name, list):
                        return [str(n) for n in resolved_name if n]
                    return [str(resolved_name)]
        return []
    
    for c in candidates:
        headline = c.get("headline")
        date_pub = c.get("datePublished")
        author = c.get("author")
        word_count = c.get("wordCount")
        
        if headline or date_pub:
            parsed_authors = []
            if author:
                parsed_authors.extend(resolve_author_names(author))
            
            # Sanitize word count
            parsed_wc = None
            if word_count is not None:
                try:
                    parsed_wc = int(word_count)
                except ValueError:
                    pass
            
            headline = clean_and_normalize_text(headline)

            return {
                "headline": headline,
                "datePublished": date_pub,
                "authors": parsed_authors,
                "wordCount": parsed_wc
            }
            
    return None


ENGLISH_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "of", "with", "by", 
    "is", "was", "were", "are", "it", "this", "that", "they", "he", "she", "you", "i", "we", 
    "as", "be", "have", "has", "had", "do", "does", "did", "from", "at", "by", "not", "but", 
    "who", "which", "what", "their", "his", "her", "my", "your", "our", "me", "them", "him", 
    "us", "so", "up", "out", "if", "about", "who", "whom", "will", "would", "can", "could",
    "should", "than", "then", "their", "theirs", "there", "here", "other", "some", "any",
    "no", "nor", "only", "own", "same", "too", "very", "just", "into", "over", "under",
    "again", "further", "once"
}

def count_words(text: str) -> int:
    """
    Consistently count words in a body of text.
    """
    if not text:
        return 0
    return len(text.split())

def validate_extraction(extracted: Dict[str, Any], ground_truth: Dict[str, Any]) -> Tuple[bool, Dict[str, str], int]:
    """
    Validates CSS-extracted content against JSON-LD ground truth per validation rules.
    Returns a tuple of (is_valid, field_errors, failure_points).
    """
    field_errors = {}
    points = 0
    
    # 1. Title Validation
    gt_headline = ground_truth.get("headline")
    ext_title = extracted.get("title") or ""
    if gt_headline:
        ratio = edit_distance_ratio(
            clean_and_normalize_text(ext_title).lower(),
            clean_and_normalize_text(gt_headline).lower()
        )
        if ratio < 0.90:
            field_errors["title"] = f"Title mismatch: ratio {ratio:.3f} < 0.90 ('{ext_title}' vs '{gt_headline}')"
            points = 3
            
    # 2. Author Validation
    gt_authors = ground_truth.get("authors")
    ext_author_raw = extracted.get("author") or ""
    if gt_authors:
        # Normalize both sides
        normalized_gt = []
        for a in gt_authors:
            normalized_gt.extend(normalize_author_string(a))
            
        normalized_ext = normalize_author_string(ext_author_raw)
        
        # Check if each normalized GT author has a matching normalized ext author
        for gt_a in normalized_gt:
            matched = False
            for ext_a in normalized_ext:
                if edit_distance_ratio(gt_a, ext_a) >= 0.90:
                    matched = True
                    break
            if not matched:
                field_errors["author"] = f"Author mismatch: JSON-LD author '{gt_a}' not matched in CSS extraction '{ext_author_raw}'"
                points = 3
                
    # 3. Date Validation
    gt_date_raw = ground_truth.get("datePublished")
    ext_date_raw = extracted.get("date")
    
    if gt_date_raw:
        gt_dt = parse_date_string(gt_date_raw)
        ext_dt = parse_date_string(ext_date_raw)
        
        if not gt_dt or not ext_dt:
            field_errors["date"] = f"Date parsing failed: JSON-LD date '{gt_date_raw}' parsed as {gt_dt}, Extracted date '{ext_date_raw}' parsed as {ext_dt}"
            points = 3
        else:
            gt_day = gt_dt.astimezone(datetime.timezone.utc).date()
            ext_day = ext_dt.astimezone(datetime.timezone.utc).date()
            if gt_day != ext_day:
                field_errors["date"] = f"Date mismatch: JSON-LD date '{gt_day}' != Extracted date '{ext_day}'"
                points = 3
                
    # 4. Body Validation
    gt_word_count = ground_truth.get("wordCount")
    ext_body = extracted.get("body") or ""
    ext_word_count = count_words(ext_body)
    
    if gt_word_count is not None:
        # JSON-LD wordCount exists
        if gt_word_count > 0:
            ratio = ext_word_count / gt_word_count
            if ratio < 1 - TOLERANCE or ratio > 1 + TOLERANCE:
                field_errors["body"] = f"Body word count ratio {ratio:.3f} outside [{1-TOLERANCE}, {1+TOLERANCE}] ({ext_word_count} vs {gt_word_count})"
                points = 3
        else:
            # If wordCount is 0 or negative in JSON-LD, skip ratio
            pass
    else:
        # Fallback sanity checks on body_elements
        body_elements = extracted.get("body_elements") or []
        if body_elements:
            # Check if there is any word at all across all elements to preserve empty body error behavior
            total_text = "\n\n".join(el.get_text() for el in body_elements)
            total_words = [w.strip(".,!?;:()[]{}'\"").lower() for w in total_text.split()]
            total_words = [w for w in total_words if w]
            
            if not total_words:
                field_errors["body"] = "Fallback stopword ratio failure: No words found in body"
                points = max(points, 1)
            else:
                # Validate each element individually
                for el in body_elements:
                    el_text = el.get_text()
                    cleaned_words = [w.strip(".,!?;:()[]{}'\"").lower() for w in el_text.split()]
                    cleaned_words = [w for w in cleaned_words if w]
                    
                    if not cleaned_words:
                        continue  # Skip elements with no text
                        
                    el_chars = len(el_text)
                    anchor_chars = sum(len(a.get_text()) for a in el.find_all('a'))
                    link_density = anchor_chars / el_chars if el_chars > 0 else 0.0
                    
                    if link_density >= 0.15:
                        field_errors["body"] = f"Fallback link density failure: {link_density:.3f} >= 0.15"
                        points = max(points, 1)
                        break
                        
                    stopword_count = sum(1 for w in cleaned_words if w in ENGLISH_STOPWORDS)
                    stopword_ratio = stopword_count / len(cleaned_words)
                    if stopword_ratio <= 0.25:
                        field_errors["body"] = f"Fallback stopword ratio failure: {stopword_ratio:.3f} <= 0.25"
                        points = max(points, 1)
                        break
        else:
            field_errors["body"] = "No body elements found for fallback checks"
            points = max(points, 1)
            
    is_valid = len(field_errors) == 0
    return is_valid, field_errors, points


class ArticleValidatorService:
    def __init__(self, db_path: str = None):
        self.db_path = db_path or settings.batch_ingestion.db_path

    def validate_article(self, url: str, publication_id: str, raw_html: str, scraped_at: datetime.datetime) -> Dict[str, Any]:
        """
        Validates a single raw HTML content using selector versions.
        Tries versions in proximity order.
        Returns a dict describing the outcome.
        """
        # 1. Extract JSON-LD ground truth
        gt = extract_json_ld_ground_truth(raw_html)
        if not gt:
            return {
                "status": "UNVALIDATABLE",
                "errors": ["No JSON-LD ground truth found"],
                "failure_points": 0
            }

        # 2. Get selector versions by proximity
        versions = get_selector_versions_by_proximity(publication_id, scraped_at, db_path=self.db_path)
        if not versions:
            return {
                "status": "VALIDATION_FAILED",
                "errors": [f"No selector versions found for publication '{publication_id}'"],
                "failure_points": 3
            }

        best_attempt = None
        best_points = 999
        best_errors = []

        for v in versions:
            extracted = extract_fields(raw_html, v.selectors)
            is_valid, field_errors, points = validate_extraction(extracted, gt)
            if is_valid:
                return {
                    "status": "VALIDATED",
                    "errors": [],
                    "failure_points": 0,
                    "selector_version_id": v.id,
                    "extracted": extracted
                }
            else:
                errors = list(field_errors.values())
                if points < best_points:
                    best_points = points
                    best_attempt = v
                    best_errors = errors

        return {
            "status": "VALIDATION_FAILED",
            "errors": best_errors,
            "failure_points": best_points if best_points != 999 else 3,
            "selector_version_id": best_attempt.id if best_attempt else None
        }

    async def validate_pending_articles(self) -> List[Dict[str, Any]]:
        """
        Reads PENDING entries from scraped_html_cache, validates them,
        and saves successfully validated ones to the stories table.
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = []
        try:
            cursor = conn.cursor()
            cursor.execute("""
                WITH latest_selector AS (
                    SELECT publication_id, MAX(created_at) AS max_created_at
                    FROM publication_selectors
                    GROUP BY publication_id
                ),
                candidate AS (
                    SELECT
                        c.url,
                        c.publication_id,
                        c.raw_html,
                        c.scraped_at,
                        c.relevance_status,
                        c.validation,
                        c.validation_date,
                        s.id AS story_id,
                        s.title AS story_title,
                        s.author AS story_author,
                        s.published_date AS story_published_date,
                        s.content AS story_content,
                        ls.max_created_at,
                        COALESCE(ls.max_created_at > c.validation_date, 0)
                            AS selectors_created_after_validation
                    FROM scraped_html_cache c
                    JOIN publications p ON c.publication_id = p.id
                    LEFT JOIN stories s ON s.url = c.url
                    LEFT JOIN latest_selector ls ON ls.publication_id = c.publication_id
                    WHERE p.validation_paused = 0
                )
                SELECT
                    url,
                    publication_id,
                    raw_html,
                    scraped_at,
                    relevance_status,
                    validation_date,
                    story_id,
                    story_title,
                    story_author,
                    story_published_date,
                    story_content,
                    selectors_created_after_validation
                FROM candidate
                WHERE (
                        validation = 'PENDING'
                        OR (
                          validation = 'VALIDATION_FAILED'
                          AND validation_date < COALESCE(max_created_at, '1970-01-01 00:00:00')
                        )
                      )
                  AND (
                        raw_html IS NOT NULL
                        OR (story_id IS NOT NULL AND NOT selectors_created_after_validation)
                      )
                ORDER BY CASE WHEN validation = 'VALIDATION_FAILED' THEN 0 ELSE 1 END ASC, scraped_at ASC
            """)
            rows = cursor.fetchall()
        finally:
            conn.close()

        results = []
        if not rows:
            logger.info("No pending scraped HTML cache rows found to validate.")
            return results

        logger.info(f"Found {len(rows)} pending cache rows to validate.")
        
        for row in rows:
            url = row["url"]
            publication_id = row["publication_id"]
            raw_html = row["raw_html"]
            relevance_status = RelevanceStatus(row["relevance_status"])
            extraction_skipped = bool(
                row["story_id"]
                and not row["selectors_created_after_validation"]
            )
            from knowledge_map.core.selectors import parse_db_datetime
            scraped_at = parse_db_datetime(row["scraped_at"]) if row["scraped_at"] else datetime.datetime.now(datetime.timezone.utc)

            span = logfire.span(f"Validating Article: {url}", url=url, publication_id=publication_id) if logfire else None
            if span:
                span.__enter__()

            circuit_breaker_tripped = False
            try:
                if extraction_skipped:
                    res = {
                        "status": "VALIDATED",
                        "errors": [],
                        "failure_points": 0,
                        "extracted": {
                            "title": row["story_title"],
                            "author": row["story_author"],
                            "date": row["story_published_date"],
                            "body": row["story_content"],
                            "body_elements": [],
                        },
                    }
                else:
                    res = self.validate_article(url, publication_id, raw_html, scraped_at)
                status = ValidationStatus(res["status"])

                if status == ValidationStatus.VALIDATED:
                    extracted = res["extracted"]
                    article_metadata = populate_article_metadata(url, db_path=self.db_path)
                    
                    if not extraction_skipped:
                        version_id = res["selector_version_id"]
                        widen_selector_version_window(version_id, scraped_at, db_path=self.db_path)

                    normalized_authors = normalize_author_string(extracted["author"])
                    author_field = ", ".join(normalized_authors) if normalized_authors else None

                    parsed_dt = parse_date_string(extracted["date"])
                    if parsed_dt:
                        from knowledge_map.core.selectors import format_datetime_utc
                        pub_date_str = format_datetime_utc(parsed_dt)
                    else:
                        pub_date_str = extracted["date"]

                    title = extracted.get("title", "").strip()
                    body = extracted.get("body", "").strip()
                    headline = article_metadata.headline or title
                    description = article_metadata.description or ""
                    embedding = article_metadata.embedding

                    effective_relevance_status = relevance_status
                    if relevance_status == RelevanceStatus.PENDING:
                        weights = load_classifier_weights()
                        effective_relevance_status = RelevanceStatus.INCONCLUSIVE
                        label_source = LabelSource.KEYWORD

                        if weights and embedding:
                            effective_relevance_status = RelevanceStatus(classify_article(
                                headline,
                                description,
                                embedding,
                            ))
                            label_source = LabelSource.MODEL

                        if effective_relevance_status == RelevanceStatus.INCONCLUSIVE or not weights:
                            try:
                                classification_res = await classify_article_with_llm(
                                    title,
                                    body,
                                    db_path=self.db_path,
                                )
                                effective_relevance_status = RelevanceStatus(classification_res.classification)
                                label_source = LabelSource.LLM
                            except Exception as e:
                                logger.error(f"LLM relevance classification failed: {e}", exc_info=True)
                                effective_relevance_status = RelevanceStatus.IRRELEVANT
                                label_source = LabelSource.LLM

                        relevance_update = update_relevance_status(
                            url,
                            effective_relevance_status,
                            label_source,
                            db_path=self.db_path,
                        )
                        effective_relevance_status = relevance_update.status

                    if effective_relevance_status == RelevanceStatus.RELEVANT:
                        if not extraction_skipped:
                            story = Story(
                                title=extracted["title"],
                                url=url,
                                author=author_field,
                                published_date=pub_date_str,
                                content=extracted["body"],
                                status=ArticleStatus.UNPROCESSED,
                                links=extract_links_from_elements(extracted.get("body_elements", []), url),
                            )
                            replace_story(story, db_path=self.db_path)
                        update_cached_html_status(url, ValidationStatus.VALIDATED, db_path=self.db_path)
                        clear_cached_html(url, db_path=self.db_path)
                    else:
                        delete_uningested_story(url, db_path=self.db_path)
                        update_cached_html_status(url, None, db_path=self.db_path)

                    logger.info("Validation content available", extra={
                        "url": url,
                        "publication_id": publication_id,
                        "validation_status": ValidationStatus.VALIDATED.value if effective_relevance_status == RelevanceStatus.RELEVANT else None,
                        "relevance_status": effective_relevance_status.value,
                        "failure_points": 0,
                        "errors": []
                    })
                    
                    if not extraction_skipped:
                        pub = get_publication(publication_id, db_path=self.db_path)
                        if pub and not pub.get("validation_paused"):
                            reset_publication_failure_points(publication_id, db_path=self.db_path)

                elif status == ValidationStatus.VALIDATION_FAILED:
                    update_cached_html_status(url, status, db_path=self.db_path)
                    logger.info("Validation outcome: VALIDATION_FAILED", extra={
                        "url": url,
                        "publication_id": publication_id,
                        "validation_status": "VALIDATION_FAILED",
                        "failure_points": res["failure_points"],
                        "errors": res["errors"]
                    })
                    pub = get_publication(publication_id, db_path=self.db_path)
                    if pub and not pub.get("validation_paused"):
                        new_points = increment_publication_failure_points(
                            publication_id,
                            res["failure_points"],
                            db_path=self.db_path
                        )
                        if new_points >= 10:
                            logger.info("Circuit breaker state changed: ACTIVE -> PAUSED", extra={
                                "publication_id": publication_id,
                                "previous_state": "ACTIVE",
                                "new_state": "PAUSED",
                                "reason": "failure_points_reached",
                                "tripping_url": url,
                                "failure_points": new_points
                            })
                            ConsoleNotifier.notify_circuit_breaker_tripped(publication_id, url, new_points)
                            pause_publication_validation(publication_id, url, db_path=self.db_path)
                            from knowledge_map.core.healing import trigger_selector_healing_stub
                            trigger_selector_healing_stub(publication_id, url, db_path=self.db_path)
                            circuit_breaker_tripped = True

                elif status == ValidationStatus.UNVALIDATABLE:
                    update_cached_html_status(url, status, db_path=self.db_path)
                    logger.info("Validation outcome: UNVALIDATABLE", extra={
                        "url": url,
                        "publication_id": publication_id,
                        "validation_status": "UNVALIDATABLE",
                        "failure_points": 0,
                        "errors": res.get("errors", ["No JSON-LD ground truth found"])
                    })

                res["url"] = url
                res["publication_id"] = publication_id
                results.append(res)

                if span:
                    span.set_attribute("status", status)
                    span.__exit__(None, None, None)
            except Exception as e:
                logger.error(f"Error validating article '{url}': {e}", exc_info=True)
                if span:
                    span.__exit__(type(e), e, e.__traceback__)

            if circuit_breaker_tripped:
                break


        return results


def extract_fields(html: str, selectors) -> Dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    
    # Helper to check if element has an illegitimate ancestor
    def has_illegitimate_ancestor(el) -> bool:
        return any(parent.name in ILLEGITIMATE_ANCESTORS for parent in el.parents)
    
    # Helper to check if element starts with a promotional prefix (e.g., READ NEXT)
    def is_promotional_element(el) -> bool:
        text = el.get_text()
        if not text:
            return False
        cleaned = text.strip().lower()
        # Remove leading non-alphanumeric punctuation
        cleaned = re.sub(r"^[^a-z0-9]+", "", cleaned).strip()
        promotional_prefixes = (
            "read next",
            "more news",
            "more of",
            "learn more",
            "most popular",
            "in summary",
        )
        return any(cleaned.startswith(prefix) for prefix in promotional_prefixes)
    
    title_el = soup.select_one(selectors.title) if selectors.title else None
    if title_el and has_illegitimate_ancestor(title_el):
        title_el = None
    title = title_el.get_text().strip() if title_el else ""
    
    author_els = soup.select(selectors.author) if selectors.author else []
    author_els = [el for el in author_els if not has_illegitimate_ancestor(el)]
    author = ", ".join(el.get_text().strip() for el in author_els) if author_els else ""
    
    date_el = soup.select_one(selectors.date) if selectors.date else None
    if date_el and has_illegitimate_ancestor(date_el):
        date_el = None
    date_val = ""
    if date_el:
        if date_el.name == "time" and date_el.has_attr("datetime"):
            date_val = date_el["datetime"].strip()
        else:
            date_val = date_el.get_text().strip()
            
    body_els = soup.select(selectors.body) if selectors.body else []
    body_els = [
        el for el in body_els 
        if not has_illegitimate_ancestor(el) and not is_promotional_element(el)
    ]
    body_text = "\n\n".join(el.get_text().strip() for el in body_els) if body_els else ""
    
    return {
        "title": title,
        "author": author,
        "date": date_val,
        "body": body_text,
        "body_elements": body_els
    }


def extract_links_from_elements(elements: List[Any], base_url: str) -> List[StoryLink]:
    """
    Extracts, resolves, and deduplicates all hyperlinks from body elements.
    Only keeps links in the body that are not self-links and have valid http/https schemes.
    """
    links = []
    seen = set()
    for el in elements:
        for a in el.find_all("a", href=True):
            href = a["href"]
            resolved = clean_and_resolve_url(base_url, href)
            if resolved and resolved not in seen:
                seen.add(resolved)
                links.append(StoryLink(text=a.get_text().strip(), url=resolved))
    return links


def run_recovery_check(
    publication_id: str,
    trigger_article_url: str,
    db_path: str = DEFAULT_DB_PATH
) -> bool:
    """
    Runs the Recovery Check on the article that triggered selector healing.
    If validation passes, resets publication failure points to 0, sets validation to active,
    updates the article's validation status, and saves the article.
    Returns True if validation succeeded, False otherwise.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT raw_html, scraped_at
            FROM scraped_html_cache
            WHERE url = ?
        """, (trigger_article_url,))
        row = cursor.fetchone()
    finally:
        conn.close()

    if not row or not row["raw_html"]:
        logger.error(f"Recovery article '{trigger_article_url}' not found in raw HTML cache.")
        return False

    raw_html = row["raw_html"]
    scraped_at_str = row["scraped_at"]
    from knowledge_map.core.selectors import parse_db_datetime
    scraped_at = parse_db_datetime(scraped_at_str) if scraped_at_str else datetime.datetime.now(datetime.timezone.utc)

    # Run validation
    validator = ArticleValidatorService(db_path=db_path)
    res = validator.validate_article(trigger_article_url, publication_id, raw_html, scraped_at)
    status = ValidationStatus(res["status"])

    update_cached_html_status(trigger_article_url, status, db_path=db_path)

    if status == ValidationStatus.VALIDATED:
        # Widen selector version window
        version_id = res.get("selector_version_id")
        if version_id:
            widen_selector_version_window(version_id, scraped_at, db_path=db_path)

        # Extract and save story
        extracted = res["extracted"]
        normalized_authors = normalize_author_string(extracted["author"])
        author_field = ", ".join(normalized_authors) if normalized_authors else None

        parsed_dt = parse_date_string(extracted["date"])
        if parsed_dt:
            from knowledge_map.core.selectors import format_datetime_utc
            pub_date_str = format_datetime_utc(parsed_dt)
        else:
            pub_date_str = extracted["date"]

        story = Story(
            title=extracted["title"],
            url=trigger_article_url,
            author=author_field,
            published_date=pub_date_str,
            content=extracted["body"],
            links=extract_links_from_elements(extracted.get("body_elements", []), trigger_article_url),
        )
        save_story(story, db_path=db_path)

        # Reset failure points & unpause validation
        reset_publication_failure_points(publication_id, db_path=db_path)
        unpause_publication_validation(publication_id, db_path=db_path)
        logger.info("Circuit breaker state changed: PAUSED -> ACTIVE", extra={
            "publication_id": publication_id,
            "previous_state": "PAUSED",
            "new_state": "ACTIVE",
            "reason": "recovery_check_passed",
            "tripping_url": None,
            "failure_points": 0
        })
        logger.info(f"Recovery Check passed for '{trigger_article_url}'. Publication validation is now ACTIVE.")
        return True
    else:
        # Failure leaves the publication paused
        logger.warning(f"Recovery Check failed for '{trigger_article_url}'. Errors: {res.get('errors')}. Publication remains PAUSED.")
        return False
