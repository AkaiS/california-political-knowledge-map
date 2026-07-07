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
    clean_and_normalize_text,
    extract_fields,
    validate_extraction,
    count_words
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





def preprocess_html(html: str) -> str:
    """
    Cleans raw HTML by first attempting to grab an article element, then
    stripping non-article tags and removing all attributes except 'class'
    and 'id' to reduce token consumption and noise.
    """
    if not html:
        return ""
    root = BeautifulSoup(html, "html.parser")
    
    # Try to grab the first article element
    # article = soup.find("article")
    # root = article if article else soup

    # Strip specified tags
    for tag in root(["head", "script", "style", "svg", "noscript", "footer", "nav", "iframe", "img", "aside", "figure"]):
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


def _annotate_title(soup: BeautifulSoup, gt_title: str) -> None:
    if not gt_title:
        return
    gt_clean = clean_and_normalize_text(gt_title).lower()
    if not gt_clean:
        return

    best_tag = None
    best_ratio = 0.0

    for tag in soup.find_all(True):
        if tag.name in ["script", "style", "html", "body"]:
            continue
        text = clean_and_normalize_text(tag.get_text())
        if not text:
            continue
        ratio = edit_distance_ratio(text.lower(), gt_clean)
        if ratio >= 0.90:
            if ratio > best_ratio:
                best_ratio = ratio
                best_tag = tag
            elif ratio == best_ratio and best_tag:
                if best_tag in tag.parents:
                    best_tag = tag

    if best_tag:
        best_tag["data-is-title-gt"] = "true"


def _annotate_date(soup: BeautifulSoup, gt_date_raw: str) -> None:
    if not gt_date_raw:
        return
    gt_dt = parse_date_string(gt_date_raw)
    if not gt_dt:
        return
    gt_day = gt_dt.astimezone(timezone.utc).date()

    best_tag = None

    for tag in soup.find_all(True):
        if tag.name in ["script", "style", "html", "body"]:
            continue

        if tag.name == "time" and tag.has_attr("datetime"):
            dt_attr = parse_date_string(tag["datetime"])
            if dt_attr and dt_attr.astimezone(timezone.utc).date() == gt_day:
                best_tag = tag
                break

        text = tag.get_text().strip()
        if text and len(text) < 100:
            import re
            cleaned_text = re.sub(
                r'^(published|posted|updated|date|on|at|modified|created)\b\s*(on|at)?\s*:?\s*',
                '',
                text,
                flags=re.IGNORECASE
            ).strip()
            dt_text = parse_date_string(cleaned_text)
            if dt_text and dt_text.astimezone(timezone.utc).date() == gt_day:
                if not best_tag or tag in best_tag.descendants or (best_tag not in tag.descendants):
                    best_tag = tag

    if best_tag:
        best_tag["data-is-date-gt"] = "true"


def _annotate_authors(soup: BeautifulSoup, gt_authors: List[str]) -> None:
    if not gt_authors:
        return

    normalized_gts = []
    for a in gt_authors:
        normalized_gts.extend(normalize_author_string(a))

    for gt_author in normalized_gts:
        best_tag = None
        best_ratio = 0.0
        for tag in soup.find_all(True):
            if tag.name in ["script", "style", "html", "body"]:
                continue
            text = tag.get_text().strip()
            if not text:
                continue
            normalized_exts = normalize_author_string(text)
            for ext in normalized_exts:
                ratio = edit_distance_ratio(ext, gt_author)
                if ratio >= 0.90:
                    if ratio > best_ratio:
                        best_ratio = ratio
                        best_tag = tag
                    elif ratio == best_ratio and best_tag:
                        if best_tag in tag.parents:
                            best_tag = tag
        if best_tag:
            best_tag["data-is-author-gt"] = "true"


def annotate_ground_truth(soup: BeautifulSoup, gt: Dict[str, Any]) -> None:
    """
    Finds and annotates the ground truth title, author, and date elements in the soup
    with special data attributes:
      - data-is-title-gt="true"
      - data-is-author-gt="true"
      - data-is-date-gt="true"
    This makes it easier for the generator LLM to identify the target elements.
    """
    # 1. Title
    headline = gt.get("headline")
    if headline:
        _annotate_title(soup, headline)

    # 2. Date
    date_pub = gt.get("datePublished")
    if date_pub:
        _annotate_date(soup, date_pub)

    # 3. Authors
    authors = gt.get("authors")
    if authors:
        _annotate_authors(soup, authors)


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
        "To guide you, we have programmatically located the ground-truth elements in the HTML and annotated them with helper attributes:\n"
        "- 'data-is-title-gt=\"true\"' marks the article title.\n"
        "- 'data-is-author-gt=\"true\"' marks the author byline.\n"
        "- 'data-is-date-gt=\"true\"' marks the publication date.\n\n"
        "You MUST prioritize targeting these annotated elements when generating selectors for title, author, and date. However, YOU MAY NOT hardcode any of these attributes into your selectors. "
        "Keep your selectors simple, precise, and resilient, avoiding overly specific structures like absolute XPath-style CSS (e.g. 'div > div > span') if simpler class-based or ID selectors work.\n"
        "Output the selectors as CSS selectors in the structured format matching the output schema."
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
        "3. Length and Coverage: The body text must contain actual paragraphs of the article and have a length consistent with a full news article (if ground-truth wordCount is present, check that the extracted body word count is close/reasonable, usually within 90-110% ratio).\n\n"
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
        if cleaned_html:
            cleaned_soup = BeautifulSoup(cleaned_html, "html.parser")
            annotate_ground_truth(cleaned_soup, gt)
            cleaned_html = str(cleaned_soup)

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
            try:
                extracted = extract_fields(cleaned_html, last_selectors)
            except Exception as e:
                prompt = f"An error occurred when parsing with your selectors: {e}. Please correct them and try again."
                continue

            # Run programmatic validation
            is_valid_extraction, field_errors, points = validate_extraction(extracted, gt)
            
            # Map back to field_validity
            field_validity = {
                field: field not in field_errors
                for field in ["title", "author", "date", "body"]
            }

            # Run Critic Validation
            ext_body = extracted.get("body") or ""
            ext_word_count = count_words(ext_body)
            gt_word_count = gt.get("wordCount")
            ratio_str = ""
            if gt_word_count and gt_word_count > 0:
                ratio_str = f" ({ext_word_count / gt_word_count * 100:.1f}% of expected)"

            critic_input = (
                f"Validation request:\n"
                f"Proposed Selectors:\n"
                f"- title selector: {last_selectors.title}\n"
                f"- author selector: {last_selectors.author}\n"
                f"- date selector: {last_selectors.date}\n"
                f"- body selector: {last_selectors.body}\n\n"
                f"Extracted Content:\n"
                f"- Extracted Title: '{extracted.get('title', '')}'\n"
                f"- Extracted Author: '{extracted.get('author', '')}'\n"
                f"- Extracted Date: '{extracted.get('date', '')}'\n"
                f"- Extracted Body: '{ext_body}'\n"
                f"- Extracted Word Count: {ext_word_count}{ratio_str}\n\n"
                f"Ground-Truth Metadata:\n"
                f"- Headline: {gt.get('headline', '')}\n"
                f"- Publication Date: {gt.get('datePublished', '')}\n"
                f"- Authors: {', '.join(gt.get('authors', []))}\n"
                f"- Expected Word Count: {gt_word_count or 'N/A'}\n"
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
