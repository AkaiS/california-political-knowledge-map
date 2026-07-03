import re
import datetime
import json
import sqlite3
import logging
from typing import List, Optional, Any, Dict, Tuple
from bs4 import BeautifulSoup
from knowledge_map.config import settings
from knowledge_map.adapters.sqlite_db import (
    save_story,
    update_cached_html_status,
    DEFAULT_DB_PATH,
    get_publication,
    increment_publication_failure_points,
    reset_publication_failure_points,
    pause_publication_validation,
    unpause_publication_validation
)
from knowledge_map.core.selectors import (
    get_selector_versions_by_proximity,
    widen_selector_version_window
)

logger = logging.getLogger(__name__)

def trigger_selector_healing_stub(publication_id: str, tripping_article_url: str) -> None:
    """
    Seam for invoking the Selector Healing Pipeline when the circuit breaker trips.
    Implementation is deferred to issue 08.
    """
    logger.info(
        f"Circuit Breaker tripped for publication '{publication_id}' "
        f"due to article '{tripping_article_url}'. Triggering Selector Healing Pipeline."
    )

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


def normalize_author_string(author_str: str) -> List[str]:
    """
    Normalizes an author string:
    - Case-insensitive strip of filler words ('By', 'Staff', 'Special to', 'Reporter', 'Written by').
    - Split on commas and 'and'.
    - Returns a list of lowercase normalized individual author names.
    """
    if not author_str:
        return []

    # Strip leading/trailing whitespace
    cleaned = author_str.strip()

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
    
    def process_node(node: Any):
        if isinstance(node, dict):
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
    
    for c in candidates:
        headline = c.get("headline")
        date_pub = c.get("datePublished")
        author = c.get("author")
        word_count = c.get("wordCount")
        
        if headline or date_pub:
            parsed_authors = []
            if author:
                if isinstance(author, str):
                    parsed_authors.append(author)
                elif isinstance(author, dict):
                    name = author.get("name")
                    if name:
                        parsed_authors.append(name)
                elif isinstance(author, list):
                    for a in author:
                        if isinstance(a, str):
                            parsed_authors.append(a)
                        elif isinstance(a, dict):
                            name = a.get("name")
                            if name:
                                parsed_authors.append(name)
            
            # Sanitize word count
            parsed_wc = None
            if word_count is not None:
                try:
                    parsed_wc = int(word_count)
                except ValueError:
                    pass
            
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

def validate_extraction(extracted: Dict[str, Any], ground_truth: Dict[str, Any]) -> Tuple[bool, List[str], int]:
    """
    Validates CSS-extracted content against JSON-LD ground truth per validation rules.
    Returns a tuple of (is_valid, error_messages, failure_points).
    """
    errors = []
    points = 0
    
    # 1. Title Validation
    gt_headline = ground_truth.get("headline")
    ext_title = extracted.get("title") or ""
    if gt_headline:
        ratio = edit_distance_ratio(ext_title.strip().lower(), gt_headline.strip().lower())
        if ratio < 0.90:
            errors.append(f"Title mismatch: ratio {ratio:.3f} < 0.90 ('{ext_title}' vs '{gt_headline}')")
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
                errors.append(f"Author mismatch: JSON-LD author '{gt_a}' not matched in CSS extraction '{ext_author_raw}'")
                points = 3
                
    # 3. Date Validation
    gt_date_raw = ground_truth.get("datePublished")
    ext_date_raw = extracted.get("date")
    
    if gt_date_raw:
        gt_dt = parse_date_string(gt_date_raw)
        ext_dt = parse_date_string(ext_date_raw)
        
        if not gt_dt or not ext_dt:
            errors.append(f"Date parsing failed: JSON-LD date '{gt_date_raw}' parsed as {gt_dt}, Extracted date '{ext_date_raw}' parsed as {ext_dt}")
            points = 3
        else:
            gt_day = gt_dt.astimezone(datetime.timezone.utc).date()
            ext_day = ext_dt.astimezone(datetime.timezone.utc).date()
            if gt_day != ext_day:
                errors.append(f"Date mismatch: JSON-LD date '{gt_day}' != Extracted date '{ext_day}'")
                points = 3
                
    # 4. Body Validation
    gt_word_count = ground_truth.get("wordCount")
    ext_body = extracted.get("body") or ""
    ext_words = ext_body.split()
    ext_word_count = len(ext_words)
    
    if gt_word_count is not None:
        # JSON-LD wordCount exists
        if gt_word_count > 0:
            ratio = ext_word_count / gt_word_count
            if ratio < 0.9 or ratio > 1.1:
                errors.append(f"Body word count ratio {ratio:.3f} outside [0.9, 1.1] ({ext_word_count} vs {gt_word_count})")
                points = 3
        else:
            # If wordCount is 0 or negative in JSON-LD, skip ratio
            pass
    else:
        # Fallback sanity checks on body_element
        body_el = extracted.get("body_element")
        if body_el:
            total_text = body_el.get_text()
            total_chars = len(total_text)
            
            # Link density
            anchor_chars = sum(len(a.get_text()) for a in body_el.find_all('a'))
            link_density = anchor_chars / total_chars if total_chars > 0 else 0.0
            
            if link_density >= 0.15:
                errors.append(f"Fallback link density failure: {link_density:.3f} >= 0.15")
                points = max(points, 1)
                
            # Stopword ratio
            cleaned_words = [w.strip(".,!?;:()[]{}'\"").lower() for w in total_text.split()]
            cleaned_words = [w for w in cleaned_words if w]
            
            if not cleaned_words:
                errors.append("Fallback stopword ratio failure: No words found in body")
                points = max(points, 1)
            else:
                stopword_count = sum(1 for w in cleaned_words if w in ENGLISH_STOPWORDS)
                stopword_ratio = stopword_count / len(cleaned_words)
                if stopword_ratio <= 0.25:
                    errors.append(f"Fallback stopword ratio failure: {stopword_ratio:.3f} <= 0.25")
                    points = max(points, 1)
        else:
            errors.append("No body element found for fallback checks")
            points = max(points, 1)
            
    is_valid = len(errors) == 0
    return is_valid, errors, points


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
            is_valid, errors, points = validate_extraction(extracted, gt)
            if is_valid:
                return {
                    "status": "VALIDATED",
                    "errors": [],
                    "failure_points": 0,
                    "selector_version_id": v.id,
                    "extracted": extracted
                }
            else:
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

    def validate_pending_articles(self) -> List[Dict[str, Any]]:
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
                SELECT c.url, c.publication_id, c.raw_html, c.scraped_at
                FROM scraped_html_cache c
                JOIN publications p ON c.publication_id = p.id
                WHERE c.validation = 'PENDING' AND p.validation_paused = 0
                ORDER BY c.scraped_at ASC
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
            from knowledge_map.core.selectors import parse_db_datetime
            scraped_at = parse_db_datetime(row["scraped_at"]) if row["scraped_at"] else datetime.datetime.now(datetime.timezone.utc)

            span = logfire.span("validate_article", url=url, publication_id=publication_id) if logfire else None
            if span:
                span.__enter__()

            try:
                res = self.validate_article(url, publication_id, raw_html, scraped_at)
                status = res["status"]
                
                update_cached_html_status(url, status, db_path=self.db_path)

                if status == "VALIDATED":
                    extracted = res["extracted"]
                    
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

                    story = {
                        "title": extracted["title"],
                        "url": url,
                        "author": author_field,
                        "published_date": pub_date_str,
                        "content": extracted["body"]
                    }
                    save_story(story, db_path=self.db_path)
                    logger.info(f"Successfully validated and saved story '{url}' to database.")
                    
                    pub = get_publication(publication_id, db_path=self.db_path)
                    if pub and not pub.get("validation_paused"):
                        reset_publication_failure_points(publication_id, db_path=self.db_path)

                elif status == "VALIDATION_FAILED":
                    logger.warning(
                        f"Validation failed for article '{url}' of publication '{publication_id}' "
                        f"with failure weight {res['failure_points']}. Errors: {res['errors']}"
                    )
                    pub = get_publication(publication_id, db_path=self.db_path)
                    if pub and not pub.get("validation_paused"):
                        new_points = increment_publication_failure_points(
                            publication_id,
                            res["failure_points"],
                            db_path=self.db_path
                        )
                        if new_points >= 10:
                            pause_publication_validation(publication_id, url, db_path=self.db_path)
                            trigger_selector_healing_stub(publication_id, url)

                elif status == "UNVALIDATABLE":
                    logger.info(f"Article '{url}' marked UNVALIDATABLE (missing JSON-LD).")

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

        return results


def extract_fields(html: str, selectors) -> Dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    
    title_el = soup.select_one(selectors.title) if selectors.title else None
    title = title_el.get_text().strip() if title_el else ""
    
    author_el = soup.select_one(selectors.author) if selectors.author else None
    author = author_el.get_text().strip() if author_el else ""
    
    date_el = soup.select_one(selectors.date) if selectors.date else None
    date_val = ""
    if date_el:
        if date_el.name == "time" and date_el.has_attr("datetime"):
            date_val = date_el["datetime"].strip()
        else:
            date_val = date_el.get_text().strip()
            
    body_el = soup.select_one(selectors.body) if selectors.body else None
    body_text = body_el.get_text().strip() if body_el else ""
    
    return {
        "title": title,
        "author": author,
        "date": date_val,
        "body": body_text,
        "body_element": body_el
    }
