import json
import logging
from typing import List, Dict, Any
from urllib.parse import urljoin, urlparse, parse_qsl, urlencode
from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, CacheMode, JsonCssExtractionStrategy
from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator

# Set up basic logging
logger = logging.getLogger(__name__)


def _normalize_url(url: str) -> str:
    """
    Strips fragment/hash components and standard tracking parameters from a URL.
    """
    try:
        parsed = urlparse(url)
        query_params = parse_qsl(parsed.query, keep_blank_values=True)
        filtered_params = []
        for k, v in query_params:
            kl = k.lower()
            if kl.startswith("utm_") or kl in {"fbclid", "gclid", "ref", "amp"}:
                continue
            filtered_params.append((k, v))
        new_query = urlencode(filtered_params) if filtered_params else ""
        return parsed._replace(fragment="", query=new_query).geturl()
    except Exception:
        return url


def clean_and_resolve_url(base_url: str, link_url: str) -> str | None:
    """
    Cleans and resolves a hyperlink URL relative to a base URL.
    Only allows http/https schemes, removes fragments/anchors, and skips self-links.
    """
    try:
        link_stripped = link_url.strip()
        if link_stripped.startswith("#") or not link_stripped:
            return None
            
        resolved = urljoin(base_url, link_stripped)
        parsed = urlparse(resolved)
        if parsed.scheme in ("http", "https"):
            cleaned = _normalize_url(resolved)
            
            # Skip self-links
            base_cleaned = _normalize_url(base_url)
            if cleaned == base_cleaned:
                return None
                
            return cleaned
    except Exception:
        pass
    return None


# CSS selector schema for CalMatters stories on category pages
CALMATTERS_LISTING_SCHEMA = {
    "name": "CalMatters Politics Stories",
    "baseSelector": "article.archive-stories",
    "fields": [
        {
            "name": "title",
            "selector": "a.story-title",
            "type": "text"
        },
        {
            "name": "url",
            "selector": "a.story-title",
            "type": "attribute",
            "attribute": "href"
        },
        {
            "name": "category",
            "selector": "div.story-dtl",
            "type": "text"
        },
        {
            "name": "summary",
            "selector": "div.story-excerpt",
            "type": "text"
        },
        {
            "name": "meta",
            "selector": "div.story-meta",
            "type": "text"
        }
    ]
}
CALMATTERS_ARTICLE_LINKS_SCHEMA = {
    "name": "CalMatters Article Holistic",
    "baseSelector": "div.entry-content",
    "fields": [
        {
            "name": "links",
            "selector": "a",
            "type": "nested_list",
            "fields": [
                {
                    "name": "text",
                    "type": "text"
                },
                {
                    "name": "url",
                    "type": "attribute",
                    "attribute": "href"
                }
            ]
        }
    ]
}


# eventually rewrite to retrieve the most recent data in DB and retrieve newer than that
# additionally, make this more news organization agnostic
async def fetch_last_5_politics_stories() -> List[Dict[str, Any]]:
    """
    Fetches the 5 most recent political stories from CalMatters using Crawl4AI.
    """
    url = "https://calmatters.org/category/politics/"
    
    # 1. Define the extraction strategy
    listing_extraction_strategy = JsonCssExtractionStrategy(CALMATTERS_LISTING_SCHEMA, verbose=False)
    
    # 2. Configure the crawler run parameters
    run_config = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,  # Get fresh content
        extraction_strategy=listing_extraction_strategy
    )
    
    logger.info(f"Crawling CalMatters politics page: {url}")
    
    async with AsyncWebCrawler() as crawler:
        result = await crawler.arun(url=url, config=run_config)
        
        if not result.success:
            logger.error(f"Failed to crawl CalMatters: {result.error_message}")
            return []
            
        # Parse extracted structured content
        try:
            raw_stories = json.loads(result.extracted_content)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to decode extracted content JSON: {e}")
            return []
            
        logger.info(f"Extracted {len(raw_stories)} raw stories from CalMatters.")
        
        processed_stories = []
        for item in raw_stories:
            # Skip empty entries if any
            title = (item.get("title") or "").strip()
            story_url = (item.get("url") or "").strip()
            if not title or not story_url:
                continue
                
            # Parse author and date from the metadata field
            # e.g., "By Ana B. Ibarra • June 18, 2026"
            meta_text = (item.get("meta") or "").strip()
            author = ""
            published_date = ""
            
            if "•" in meta_text:
                parts = [part.strip() for part in meta_text.split("•")]
                if len(parts) >= 1:
                    author = parts[0].replace("By", "").strip()
                if len(parts) >= 2:
                    published_date = parts[1].strip()
            elif "By" in meta_text:
                author = meta_text.replace("By", "").strip()
            else:
                published_date = meta_text
                
            processed_stories.append({
                "title": title,
                "url": story_url,
                "category": (item.get("category") or "").strip(),
                "author": author,
                "published_date": published_date,
                "summary": (item.get("summary") or "").strip()
            })
            
        # Return the 5 most recent stories (the page list starts with the newest first)
        top_stories = processed_stories[:5]
        
        if top_stories:
            story_urls = [story["url"] for story in top_stories]
            logger.info(f"Crawling {len(story_urls)} article bodies concurrently...")

            article_extraction_strategy = JsonCssExtractionStrategy(CALMATTERS_ARTICLE_LINKS_SCHEMA, verbose=False)

            # Configure crawl run for article bodies
            article_config = CrawlerRunConfig(
                cache_mode=CacheMode.BYPASS,
                css_selector="div.entry-content",
                markdown_generator=DefaultMarkdownGenerator(
                    options={
                        "ignore_links": True
                    }
                ),
                excluded_tags=['aside', 'figure'],
                excluded_selector=(
                    "div.wp-block-newspack-blocks-wp-block-newspack-ads-blocks-ad-unit, "
                    "div.newspack_global_ad, "
                    "section.below-content, "
                    ".wp-block-newspack-blocks-homepage-articles, "
                    ".after-article-engagement, "
                    ".cm-read-next-eoa, "
                    ".calmatters-summary"
                )
            )
            
            # Crawl all URLs in parallel
            article_results = await crawler.arun_many(urls=story_urls, config=article_config)

            # Map content back to stories correctly matching URLs
            results_by_url = {}
            for res in article_results:
                url_str = str(res.url) if hasattr(res, "url") and res.url else ""
                results_by_url[url_str.rstrip('/')] = res

            for story in top_stories:
                story_url_key = story["url"].rstrip('/')
                article_result = results_by_url.get(story_url_key)
                if not article_result:
                    # Fallback to index-based matching if URL lookup fails
                    try:
                        idx = top_stories.index(story)
                        if idx < len(article_results):
                            article_result = article_results[idx]
                    except ValueError:
                        pass

                if article_result and article_result.success:
                    story["content"] = (article_result.markdown or "").strip()
                    
                    # Extract links using JsonCssExtractionStrategy
                    html_content = article_result.cleaned_html or article_result.html or ""
                    try:
                        raw_data = article_extraction_strategy.extract(story["url"], html_content)
                        if isinstance(raw_data, str):
                            extracted = json.loads(raw_data)
                        else:
                            extracted = raw_data
                            
                        raw_links = []
                        if extracted and isinstance(extracted, list) and len(extracted) > 0:
                            raw_links = extracted[0].get("links", [])
                    except Exception as e:
                        logger.error(f"Failed to extract links using JsonCssExtractionStrategy: {e}")
                        raw_links = []
                        
                    links = []
                    seen_urls = set()
                    for link in raw_links:
                        text = (link.get("text") or "").strip()
                        url = (link.get("url") or "").strip()
                        resolved_url = clean_and_resolve_url(story["url"], url)
                        if resolved_url and resolved_url not in seen_urls:
                            seen_urls.add(resolved_url)
                            links.append({
                                "text": text,
                                "url": resolved_url
                            })
                    story["links"] = links
                else:
                    logger.warning(f"Failed to crawl article content for {story['url']}: {article_result.error_message}")
                    story["content"] = ""
                    story["links"] = []
        else:
            logger.warning("No politics stories found to crawl.")
            
        return top_stories