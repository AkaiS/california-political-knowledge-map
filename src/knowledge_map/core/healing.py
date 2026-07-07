import os
import json
import logging
import sqlite3
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime, timezone
from bs4 import BeautifulSoup, Tag
from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.models.ollama import OllamaModel
from pydantic_ai.providers.ollama import OllamaProvider
from dotenv import load_dotenv

from knowledge_map.config import settings
from knowledge_map.adapters.sqlite_db import (
    DEFAULT_DB_PATH,
    get_publication,
    insert_selector_proposal,
    has_unresolved_selector_proposal,
    set_publication_healing_in_progress
)
from knowledge_map.core.validation import (
    edit_distance_ratio,
    normalize_author_string,
    parse_date_string,
    ENGLISH_STOPWORDS,
    clean_and_normalize_text
)

logger = logging.getLogger(__name__)

try:
    import logfire
except ImportError:
    logfire = None


class ArticleSelectors(BaseModel):
    title: str
    author: str
    date: str
    body: str

class CriticFeedback(BaseModel):
    is_valid: bool
    issues: List[str]


def validate_field(field: str, value: Any, gt: Dict[str, Any], body_element: Optional[Any] = None) -> Tuple[bool, str]:
    if field == "title":
        ext_title = value or ""
        gt_headline = gt.get("headline")
        if gt_headline:
            if not ext_title.strip():
                return False, "Extracted title was empty."
            ratio = edit_distance_ratio(
                clean_and_normalize_text(ext_title).lower(),
                clean_and_normalize_text(gt_headline).lower()
            )
            if ratio < 0.90:
                return False, f"Title mismatch: ratio {ratio:.3f} < 0.90 ('{ext_title}' vs '{gt_headline}')"
        return True, ""

    elif field == "author":
        ext_author_raw = value or ""
        gt_authors = gt.get("authors")
        if gt_authors:
            if not ext_author_raw.strip():
                return False, "Extracted author was empty."
            normalized_gt = []
            for a in gt_authors:
                normalized_gt.extend(normalize_author_string(a))
            normalized_ext = normalize_author_string(ext_author_raw)
            for gt_a in normalized_gt:
                matched = False
                for ext_a in normalized_ext:
                    if edit_distance_ratio(gt_a, ext_a) >= 0.90:
                        matched = True
                        break
                if not matched:
                    return False, f"Author mismatch: JSON-LD author '{gt_a}' not matched in CSS extraction '{ext_author_raw}'"
        return True, ""

    elif field == "date":
        ext_date_raw = value
        gt_date_raw = gt.get("datePublished")
        if gt_date_raw:
            if not ext_date_raw:
                return False, "Extracted date was empty."
            gt_dt = parse_date_string(gt_date_raw)
            ext_dt = parse_date_string(ext_date_raw)
            if not gt_dt or not ext_dt:
                return False, f"Date parsing failed: JSON-LD date '{gt_date_raw}' parsed as {gt_dt}, Extracted date '{ext_date_raw}' parsed as {ext_dt}"
            else:
                gt_day = gt_dt.astimezone(timezone.utc).date()
                ext_day = ext_dt.astimezone(timezone.utc).date()
                if gt_day != ext_day:
                    return False, f"Date mismatch: JSON-LD date '{gt_day}' != Extracted date '{ext_day}'"
        return True, ""

    elif field == "body":
        ext_body = value or ""
        gt_word_count = gt.get("wordCount")
        if gt_word_count is not None:
            if gt_word_count > 0:
                if not ext_body.strip():
                    return False, "Extracted body was empty."
                ext_word_count = len(ext_body.split())
                ratio = ext_word_count / gt_word_count
                if ratio < 0.9 or ratio > 1.1:
                    return False, f"Body word count ratio {ratio:.3f} outside [0.9, 1.1] ({ext_word_count} vs {gt_word_count})"
        else:
            if not ext_body.strip():
                return False, "Extracted body was empty."
            if body_element:
                total_text = body_element.get_text()
                total_chars = len(total_text)
                anchor_chars = sum(len(a.get_text()) for a in body_element.find_all('a'))
                link_density = anchor_chars / total_chars if total_chars > 0 else 0.0
                if link_density >= 0.15:
                    return False, f"Fallback link density failure: {link_density:.3f} >= 0.15"
                cleaned_words = [w.strip(".,!?;:()[]{}'\"").lower() for w in total_text.split()]
                cleaned_words = [w for w in cleaned_words if w]
                if not cleaned_words:
                    return False, "Fallback stopword ratio failure: No words found in body"
                else:
                    stopword_count = sum(1 for w in cleaned_words if w in ENGLISH_STOPWORDS)
                    stopword_ratio = stopword_count / len(cleaned_words)
                    if stopword_ratio <= 0.25:
                        return False, f"Fallback stopword ratio failure: {stopword_ratio:.3f} <= 0.25"
            else:
                return False, "No body element found for fallback checks"
        return True, ""

    return False, "Unknown field"


def preprocess_html(html: str) -> str:
    """
    Cleans raw HTML by first attempting to grab an article element, then
    stripping non-article tags and removing all attributes except 'class'
    and 'id' to reduce token consumption and noise.
    """
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    
    # Try to grab the first article element
    article = soup.find("article")
    root = article if article else soup

    # Strip specified tags
    for tag in root(["head", "script", "style", "svg", "noscript", "footer", "nav", "iframe", "img", "header", "aside", "figure"]):
        tag.decompose()
        
    # Strip all attributes except class and id
    elements = root.find_all(True)
    if isinstance(root, Tag) and root.name != "[document]":
        elements = [root] + elements
        
    for tag in elements:
        new_attrs = {}
        if tag.has_attr("id"):
            new_attrs["id"] = tag["id"]
        if tag.has_attr("class"):
            new_attrs["class"] = tag["class"]
        tag.attrs = new_attrs
        
    return str(root)


def _get_model():
    load_dotenv()
    ollama_base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
    ollama_model = os.environ.get("OLLAMA_MODEL", "32k-gemma-e4b")
    
    base_url = ollama_base_url
    if not base_url.endswith("/v1"):
        base_url = f"{base_url}/v1"
        
    provider = OllamaProvider(base_url=base_url)
    return OllamaModel(model_name=ollama_model, provider=provider)


def get_generator_agent(defer_check: bool = True) -> Agent:
    model = _get_model()
    instructions = (
        "You are an expert web scraping agent.\n"
        "Your task is to analyze the cleaned HTML structure of a news article page and propose CSS selectors to extract four specific fields:\n"
        "1. title: The article's headline/title.\n"
        "2. author: The author(s) name(s).\n"
        "3. date: The publication date.\n"
        "4. body: The main body text of the article (excluding sidebars, ads, headers, footers, and other navigation).\n\n"
        "You will be provided with the target ground-truth metadata (which may have headline, datePublished, authors) to help you match elements.\n"
        "Output the selectors as CSS selectors in the structured format matching the output schema.\n"
        "Ensure the selectors are precise and resilient. Avoid overly specific structures like absolute XPath-style CSS (e.g. 'div > div > span') if simpler class-based selectors work."
    )
    return Agent(
        model,
        output_type=ArticleSelectors,
        instructions=instructions,
        defer_model_check=defer_check,
    )


def get_critic_agent(defer_check: bool = True) -> Agent:
    model = _get_model()
    instructions = (
        "You are an expert QA Web Scraping Critic.\n"
        "Your task is to validate the CSS selectors proposed by the Generator.\n"
        "You will be provided with:\n"
        "- The cleaned HTML structure of the article.\n"
        "- The ground-truth target metadata (headline, datePublished, authors, wordCount).\n"
        "- The proposed CSS selectors.\n"
        "- The content extracted from the cleaned HTML using the proposed CSS selectors.\n\n"
        "Validate the proposed selectors and extracted content against the following criteria:\n"
        "1. Presence: Check that title, author, date, and body selectors successfully extracted non-empty content.\n"
        "2. Cleanliness: Check that the extracted title, author, date, and body do not contain HTML, navigation links, header/footer boilerplate, or ad text.\n"
        "3. Length and Coverage: The body text must contain actual paragraphs of the article and have a length consistent with a full news article (if ground-truth wordCount is present, check that the extracted body word count is close/reasonable, usually within 80-120% ratio).\n\n"
        "Return structured feedback:\n"
        "- is_valid: True if selectors successfully extract clean, correct content. False otherwise.\n"
        "- issues: A list of specific issues found if is_valid is False (e.g. 'Extracted title was empty', 'Extracted body contained header links'). If is_valid is True, this must be empty."
    )
    return Agent(
        model,
        output_type=CriticFeedback,
        instructions=instructions,
        defer_model_check=defer_check,
    )


async def run_selector_healing_flow(
    publication_id: str,
    tripping_article_url: str,
    db_path: str = DEFAULT_DB_PATH,
    custom_context: Optional[str] = None,
    retry_negative_selectors: Optional[str] = None,
    bypass_guards: bool = False,
    generator_agent: Optional[Agent] = None,
    critic_agent: Optional[Agent] = None
) -> None:
    """
    Runs the iterative Selector Healing Generator/Critic loop on the tripping article.
    """
    # 1. Concurrency checks
    if not bypass_guards:
        if has_unresolved_selector_proposal(publication_id, db_path=db_path):
            logger.info(f"Skipping healing trigger for '{publication_id}': unresolved proposal exists.")
            return
        pub = get_publication(publication_id, db_path=db_path)
        if pub and pub.get("healing_in_progress"):
            logger.info(f"Skipping healing trigger for '{publication_id}': healing already in progress.")
            return

    # Set healing_in_progress flag
    set_publication_healing_in_progress(publication_id, True, db_path=db_path)

    span = logfire.span("heal_selectors", publication_id=publication_id, trigger_article_url=tripping_article_url) if logfire else None
    if span:
        span.__enter__()

    try:
        # Load raw HTML from cache
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT raw_html FROM scraped_html_cache WHERE url = ?", (tripping_article_url,))
        row = cursor.fetchone()
        conn.close()

        if not row or not row["raw_html"]:
            logger.error(f"Cannot run selector healing: raw HTML for '{tripping_article_url}' not found in cache.")
            return

        raw_html = row["raw_html"]
        # Extract ground truth from HTML
        from knowledge_map.core.validation import extract_json_ld_ground_truth
        gt = extract_json_ld_ground_truth(raw_html)
        if not gt:
            logger.warning(f"No JSON-LD ground truth found for tripping article '{tripping_article_url}'. Using default empty targets.")
            gt = {
                "headline": "",
                "datePublished": "",
                "authors": [],
                "wordCount": None
            }

        # Preprocess HTML
        cleaned_html = preprocess_html(raw_html)

        # Initialize Agents
        generator = generator_agent or get_generator_agent()
        critic = critic_agent or get_critic_agent()

        # Prepare negative selectors context if available
        negative_selectors_str = ""
        if retry_negative_selectors:
            negative_selectors_str = f"Avoid using these previously failing selectors: {retry_negative_selectors}\n"

        custom_context_str = ""
        if custom_context:
            custom_context_str = f"Developer Guidance/Hint: {custom_context}\n"

        # Initial prompt for generator
        prompt = (
            f"Generate CSS selectors for the article at {tripping_article_url}.\n"
            f"Cleaned HTML:\n{cleaned_html}\n\n"
            f"Target Metadata (Ground Truth):\n"
            f"- Headline: {gt.get('headline', '')}\n"
            f"- Publication Date: {gt.get('datePublished', '')}\n"
            f"- Authors: {', '.join(gt.get('authors', []))}\n"
            f"- Expected Word Count: {gt.get('wordCount', '')}\n\n"
            f"{negative_selectors_str}"
            f"{custom_context_str}"
        )

        confirmed_selectors = {
            "title": None,
            "author": None,
            "date": None,
            "body": None,
        }

        run_result = None
        iteration = 0
        max_iterations = 3
        last_selectors = None
        approved = False

        while iteration < max_iterations:
            iteration += 1
            
            # Construct prompt for the current iteration
            current_prompt = prompt
            
            # If we have confirmed selectors, instruct the generator to retain them
            if any(confirmed_selectors.values()):
                locked_selectors_str = (
                    "\n\nIMPORTANT: The following selectors have already been VERIFIED AS CORRECT. "
                    "You MUST keep these selectors EXACTLY as they are in your output:\n"
                    + "\n".join(f"- {field}: '{sel}'" for field, sel in confirmed_selectors.items() if sel)
                )
                current_prompt += locked_selectors_str

            if iteration == 1:
                run_result = await generator.run(current_prompt)
            else:
                run_result = await generator.run(current_prompt, message_history=run_result.all_messages())

            last_selectors = run_result.output

            # Programmatically override any confirmed selectors
            for field, confirmed_sel in confirmed_selectors.items():
                if confirmed_sel:
                    setattr(last_selectors, field, confirmed_sel)

            # Extract content from HTML using proposed selectors
            extracted_title = ""
            extracted_author = ""
            extracted_date = ""
            extracted_body = ""
            body_el = None
            try:
                soup = BeautifulSoup(cleaned_html, "html.parser")
                if last_selectors.title:
                    el = soup.select_one(last_selectors.title)
                    extracted_title = el.get_text().strip() if el else ""
                if last_selectors.author:
                    el = soup.select_one(last_selectors.author)
                    extracted_author = el.get_text().strip() if el else ""
                if last_selectors.date:
                    el = soup.select_one(last_selectors.date)
                    if el:
                        if el.name == "time" and el.has_attr("datetime"):
                            extracted_date = el["datetime"].strip()
                        else:
                            extracted_date = el.get_text().strip()
                if last_selectors.body:
                    body_el = soup.select_one(last_selectors.body)
                    extracted_body = body_el.get_text().strip() if body_el else ""
            except Exception as e:
                prompt = f"An error occurred when parsing with your selectors: {e}. Please correct them and try again."
                continue

            # Run programmatic validation for each field
            field_validity = {}
            field_errors = {}
            for field in ["title", "author", "date", "body"]:
                val = {
                    "title": extracted_title,
                    "author": extracted_author,
                    "date": extracted_date,
                    "body": extracted_body
                }[field]
                is_valid_field, err = validate_field(field, val, gt, body_element=body_el)
                field_validity[field] = is_valid_field
                field_errors[field] = err

            # Run Critic Validation
            critic_input = (
                f"Validation request:\n"
                f"Proposed Selectors:\n"
                f"- title selector: {last_selectors.title}\n"
                f"- author selector: {last_selectors.author}\n"
                f"- date selector: {last_selectors.date}\n"
                f"- body selector: {last_selectors.body}\n\n"
                f"Extracted Content:\n"
                f"- Extracted Title: '{extracted_title}'\n"
                f"- Extracted Author: '{extracted_author}'\n"
                f"- Extracted Date: '{extracted_date}'\n"
                f"- Extracted Body: '{extracted_body}'\n\n"
                f"Ground-Truth Metadata:\n"
                f"- Headline: {gt.get('headline', '')}\n"
                f"- Publication Date: {gt.get('datePublished', '')}\n"
                f"- Authors: {', '.join(gt.get('authors', []))}\n"
                f"- Expected Word Count: {gt.get('wordCount', '')}\n"
            )

            critic_result = await critic.run(critic_input)
            validation = critic_result.output

            # Determine overall success: must pass both programmatic and critic checks
            all_programmatic_passed = all(field_validity.values())
            if all_programmatic_passed and validation.is_valid:
                approved = True
                break
            else:
                # Lock in verified selectors that passed both programmatic and critic checks
                critic_issues = validation.issues or []
                for field in ["title", "author", "date", "body"]:
                    has_prog_error = not field_validity[field]
                    has_crit_issue = any(field in issue.lower() for issue in critic_issues)
                    if not has_prog_error and not has_crit_issue:
                        confirmed_selectors[field] = getattr(last_selectors, field)

                # Construct feedback prompt for the next iteration
                feedback_messages = []
                for field, err in field_errors.items():
                    if err:
                        feedback_messages.append(f"- Programmatic validation error for '{field}': {err}")
                for issue in critic_issues:
                    feedback_messages.append(f"- Critic feedback: {issue}")

                prompt = (
                    "Some proposed selectors failed validation. Please adjust the CSS selectors and try again.\n"
                    "Errors encountered:\n"
                    + "\n".join(feedback_messages)
                )

        if approved and last_selectors:
            # Save as PENDING_REVIEW
            selectors_dict = last_selectors.model_dump()
            insert_selector_proposal(
                publication_id=publication_id,
                selectors_json=json.dumps(selectors_dict),
                trigger_article_url=tripping_article_url,
                status="PENDING_REVIEW",
                critic_iterations=iteration,
                db_path=db_path
            )
            logger.info(f"Selector healing completed successfully for '{publication_id}' after {iteration} iterations.")
        else:
            # Loop exhausted, save as HEALING_FAILED
            selectors_dict = last_selectors.model_dump() if last_selectors else {"title": "", "author": "", "date": "", "body": ""}
            insert_selector_proposal(
                publication_id=publication_id,
                selectors_json=json.dumps(selectors_dict),
                trigger_article_url=tripping_article_url,
                status="HEALING_FAILED",
                critic_iterations=iteration,
                db_path=db_path
            )
            warning_msg = f"Selector healing loop exhausted after {iteration} iterations without approval."
            logger.critical(f"[{publication_id.upper()}] {warning_msg}")
            
            # Dispatch console alert
            from knowledge_map.utils.console import ConsoleNotifier
            ConsoleNotifier.notify_critical_failure(
                error_title="Selector Healing Exhausted",
                message=warning_msg,
                details={
                    "Publication ID": publication_id,
                    "Tripping Article": tripping_article_url,
                    "Last Attempted Selectors": json.dumps(selectors_dict)
                }
            )

    except Exception as e:
        logger.error(f"Error during selector healing loop: {e}", exc_info=True)
    finally:
        set_publication_healing_in_progress(publication_id, False, db_path=db_path)
        if span:
            span.__exit__(None, None, None)
