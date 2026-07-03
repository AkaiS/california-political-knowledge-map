import os
import json
import logging
import sqlite3
from typing import Optional, List, Dict, Any
from bs4 import BeautifulSoup
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

logger = logging.getLogger(__name__)

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
    Cleans raw HTML by stripping non-article tags and removing all attributes
    except 'class' and 'id' to reduce token consumption and noise.
    """
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    # Strip specified tags
    for tag in soup(["head", "script", "style", "svg", "noscript", "footer", "nav", "iframe", "img"]):
        tag.decompose()
    # Strip all attributes except class and id
    for tag in soup.find_all(True):
        new_attrs = {}
        if tag.has_attr("id"):
            new_attrs["id"] = tag["id"]
        if tag.has_attr("class"):
            new_attrs["class"] = tag["class"]
        tag.attrs = new_attrs
    return str(soup)


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

        run_result = None
        iteration = 0
        max_iterations = 3
        last_selectors = None
        approved = False

        while iteration < max_iterations:
            iteration += 1
            if iteration == 1:
                run_result = await generator.run(prompt)
            else:
                run_result = await generator.run(prompt, message_history=run_result.all_messages())

            last_selectors = run_result.output

            # Extract content from HTML using proposed selectors
            extracted_title = ""
            extracted_author = ""
            extracted_date = ""
            extracted_body = ""
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
                    extracted_date = el.get_text().strip() if el else ""
                if last_selectors.body:
                    el = soup.select_one(last_selectors.body)
                    extracted_body = el.get_text().strip() if el else ""
            except Exception as e:
                prompt = f"An error occurred when parsing with your selectors: {e}. Please correct them and try again."
                continue

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

            if validation.is_valid:
                approved = True
                break
            else:
                prompt = (
                    f"The Critic rejected your proposed selectors due to these issues:\n"
                    + "\n".join(f"- {issue}" for issue in validation.issues)
                    + "\n\nPlease adjust the CSS selectors and try again."
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
