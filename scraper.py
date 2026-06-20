import json
import logging
from typing import List, Dict, Any
from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, CacheMode, JsonCssExtractionStrategy

# Set up basic logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# CSS selector schema for CalMatters stories on category pages
CALMATTERS_SCHEMA = {
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

async def fetch_last_5_politics_stories() -> List[Dict[str, Any]]:
    """
    Fetches the 5 most recent political stories from CalMatters using Crawl4AI.
    """
    url = "https://calmatters.org/category/politics/"
    
    # 1. Define the extraction strategy
    extraction_strategy = JsonCssExtractionStrategy(CALMATTERS_SCHEMA, verbose=False)
    
    # 2. Configure the crawler run parameters
    run_config = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,  # Get fresh content
        extraction_strategy=extraction_strategy
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
        return processed_stories[:5]
