import json
import logging
import asyncio
from typing import List, Optional, Dict, Any
from urllib.parse import urlparse

from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, CacheMode
from knowledge_map.adapters.sqlite_db import is_url_known, cache_scraped_html, DEFAULT_DB_PATH
from knowledge_map.config import settings

logger = logging.getLogger(__name__)

class PolitenessLimiter:
    """
    Limits the crawl rate and concurrency for a publication.
    Enforces maximum concurrency using a semaphore, and spacing between request
    initiations using a lock and crawl delay sleep.
    """
    def __init__(self, crawl_delay: float, max_concurrency: int):
        self.crawl_delay = crawl_delay
        self.semaphore = asyncio.Semaphore(max_concurrency)
        self.last_request_time = 0.0
        self.lock = asyncio.Lock()

    async def __aenter__(self):
        # 1. Respect concurrency limits
        await self.semaphore.acquire()
        
        # 2. Respect crawl delay spacing
        if self.crawl_delay > 0:
            async with self.lock:
                now = asyncio.get_event_loop().time()
                elapsed = now - self.last_request_time
                if elapsed < self.crawl_delay:
                    sleep_time = self.crawl_delay - elapsed
                    await asyncio.sleep(sleep_time)
                self.last_request_time = asyncio.get_event_loop().time()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self.semaphore.release()


def should_keep_url(
    url: str,
    anchor_text: Optional[str],
    blocklist: List[str],
    apply_anchor_heuristics: bool = True
) -> bool:
    """
    Applies path blocklist filters and anchor text heuristics to candidate URLs.
    
    Anchor text heuristics:
    - Only follow links with anchor text >= 5 words and >= 25 characters.
    - Bypassed if apply_anchor_heuristics is False.
    """
    # 1. Path blocklist check
    try:
        parsed = urlparse(url)
        path = parsed.path
        for segment in blocklist:
            if segment in path:
                return False
    except Exception as e:
        logger.error(f"Error parsing URL '{url}' for path blocklist: {e}")
        return False

    # 2. Anchor text heuristics check
    if apply_anchor_heuristics:
        if not anchor_text:
            return False
        
        cleaned_text = anchor_text.strip()
        words = cleaned_text.split()
        if len(words) < 5 or len(cleaned_text) < 25:
            return False

    return True


class ListingPageDiscoveryService:
    """
    Crawls listing pages, extracts and filters links using blocklists and heuristics,
    and caches new raw article HTMLs under scraped_html_cache as PENDING.
    """
    def __init__(self, db_path: str = None):
        self.db_path = db_path or settings.batch_ingestion.db_path

    def _get_blocklist(self, pub: Dict[str, Any]) -> List[str]:
        discovery_config_json = pub.get("discovery_config_json")
        if discovery_config_json:
            try:
                config = json.loads(discovery_config_json)
                if "url_path_blocklist" in config and isinstance(config["url_path_blocklist"], list):
                    return config["url_path_blocklist"]
            except Exception:
                pass
        return settings.batch_ingestion.url_path_blocklist

    def _get_listing_urls(self, pub: Dict[str, Any]) -> List[str]:
        discovery_config_json = pub.get("discovery_config_json")
        if discovery_config_json:
            try:
                config = json.loads(discovery_config_json)
                if "listing_urls" in config and isinstance(config["listing_urls"], list):
                    return config["listing_urls"]
            except Exception:
                pass
        return []

    def _is_same_domain(self, base_url: str, target_url: str) -> bool:
        try:
            base_netloc = urlparse(base_url).netloc.lower()
            target_netloc = urlparse(target_url).netloc.lower()
            if base_netloc.startswith("www."):
                base_netloc = base_netloc[4:]
            if target_netloc.startswith("www."):
                target_netloc = target_netloc[4:]
            return base_netloc == target_netloc or target_netloc.endswith("." + base_netloc)
        except Exception:
            return False

    async def discover_and_scrape_for_publication(self, pub: Dict[str, Any]) -> List[str]:
        pub_id = pub["id"]
        base_url = pub["base_url"]
        crawl_delay = pub.get("crawl_delay", 2.0)
        max_concurrency = pub.get("max_concurrency", 2)
        use_robots_txt = pub.get("use_robots_txt", True)

        listing_urls = self._get_listing_urls(pub)
        if not listing_urls:
            logger.warning(f"No listing_urls configured for publication '{pub_id}'")
            return []

        blocklist = self._get_blocklist(pub)
        limiter = PolitenessLimiter(crawl_delay=crawl_delay, max_concurrency=max_concurrency)

        run_config = CrawlerRunConfig(
            cache_mode=CacheMode.BYPASS,
            check_robots_txt=use_robots_txt
        )

        candidate_urls = []
        async with AsyncWebCrawler() as crawler:
            for url in listing_urls:
                async with limiter:
                    logger.info(f"Crawling listing page '{url}' for publication '{pub_id}'")
                    result = await crawler.arun(url=url, config=run_config)
                    if not result.success:
                        logger.error(f"Failed to crawl listing page '{url}': {result.error_message}")
                        continue
                    
                    # Extract links
                    links_dict = getattr(result, "links", {}) or {}
                    internal_links = links_dict.get("internal", [])
                    external_links = links_dict.get("external", [])
                    all_links = internal_links + external_links
                    
                    for link in all_links:
                        href = link.get("href")
                        text = link.get("text")
                        if not href:
                            continue
                        
                        from knowledge_map.utils.scraper import clean_and_resolve_url
                        resolved_url = clean_and_resolve_url(base_url, href)
                        if not resolved_url:
                            continue
                        
                        if not self._is_same_domain(base_url, resolved_url):
                            continue

                        if not should_keep_url(resolved_url, text, blocklist, apply_anchor_heuristics=True):
                            continue
                        
                        if is_url_known(resolved_url, db_path=self.db_path):
                            continue
                            
                        if resolved_url not in candidate_urls:
                            candidate_urls.append(resolved_url)

        # Fetch candidate URLs
        scraped_urls = []
        if candidate_urls:
            logger.info(f"Discovered {len(candidate_urls)} candidate articles for '{pub_id}'")
            async with AsyncWebCrawler() as crawler:
                async def fetch_and_cache(url: str):
                    async with limiter:
                        logger.info(f"Fetching candidate article '{url}' for '{pub_id}'")
                        res = await crawler.arun(url=url, config=run_config)
                        if res.success:
                            raw_html = getattr(res, "html", "") or getattr(res, "cleaned_html", "") or ""
                            cache_scraped_html(url, pub_id, raw_html, validation="PENDING", db_path=self.db_path)
                            scraped_urls.append(url)
                        else:
                            logger.error(f"Failed to fetch candidate '{url}': {res.error_message}")

                await asyncio.gather(*(fetch_and_cache(url) for url in candidate_urls))
                
        return scraped_urls

    async def discover_and_scrape_all(self) -> Dict[str, List[str]]:
        from knowledge_map.adapters.sqlite_db import get_all_publications
        publications = get_all_publications(db_path=self.db_path)
        results = {}
        for pub in publications:
            try:
                scraped = await self.discover_and_scrape_for_publication(pub)
                results[pub["id"]] = scraped
            except Exception as e:
                logger.error(f"Error scraping publication '{pub['id']}': {e}")
                results[pub["id"]] = []
        return results
