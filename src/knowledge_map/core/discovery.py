import json
import logging
import asyncio
from typing import List, Optional, Dict, Any
from urllib.parse import urlparse
from datetime import datetime, timezone, timedelta
import dateutil.parser
from bs4 import BeautifulSoup

from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, CacheMode, DomainMapper
from knowledge_map.adapters.sqlite_db import (
    is_url_known,
    cache_scraped_html,
    record_failed_fetch,
    DEFAULT_DB_PATH,
)
from knowledge_map.config import settings

logger = logging.getLogger(__name__)


def effective_fetch_status(res: Any) -> Optional[int]:
    """
    The status of the final response of a fetch, or None when the crawler
    reported none.

    Crawl4AI reports the *first* hop of a redirect chain in `status_code` and the
    last in `redirected_status_code`, so an article reached through a 301 has a
    `status_code` of 301. The last hop is what says whether we got the article.
    """
    for candidate in (
        getattr(res, "redirected_status_code", None),
        getattr(res, "status_code", None),
    ):
        if isinstance(candidate, int):
            return candidate
    return None


def holds_article_content(fetch_status: Optional[int]) -> bool:
    """
    Whether a fetch delivered the article itself rather than an error page.

    An unreported status is treated as content: the crawler substitutes 200 for
    the responseless cases it handles (raw and file URLs, aborted downloads), so
    a missing status means unknown, not failed.
    """
    return fetch_status is None or 200 <= fetch_status < 300

try:
    import logfire
except ImportError:
    logfire = None


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


def matches_category(url: str, valid_categories: Optional[List[str]]) -> bool:
    """
    Checks if any path segment (excluding the last segment) matches the valid categories list.
    If valid_categories is empty or None, the check is bypassed.
    """
    if not valid_categories:
        return True
    try:
        parsed = urlparse(url)
        segments = [s for s in parsed.path.split('/') if s]
        if not segments:
            return False
        remaining = segments[:-1]
        valid_set = {cat.lower() for cat in valid_categories}
        for segment in remaining:
            if segment.lower() in valid_set:
                return True
        return False
    except Exception as e:
        logger.error(f"Error checking category filter for URL '{url}': {e}")
        return False



def _find_date_recursive(data: Any) -> Optional[str]:
    """
    Recursively search for date keys in a JSON-like structure.
    """
    date_keys = {"datepublished", "datemodified", "datecreated", "uploaddate"}
    if isinstance(data, dict):
        for k, v in data.items():
            if k.lower() in date_keys and isinstance(v, str):
                return v
        for v in data.values():
            res = _find_date_recursive(v)
            if res is not None:
                return res
    elif isinstance(data, list):
        for item in data:
            res = _find_date_recursive(item)
            if res is not None:
                return res
    return None


def extract_published_date(html: str) -> Optional[datetime]:
    """
    Extracts the publish date from raw HTML.
    Looks in JSON-LD blocks first, then falls back to meta tags and time tags.
    Returns a timezone-aware UTC datetime.
    """
    soup = BeautifulSoup(html, "html.parser")
    
    # 1. Parse JSON-LD blocks
    json_ld_scripts = soup.find_all("script", type="application/ld+json")
    for script in json_ld_scripts:
        if not script.string:
            continue
        try:
            data = json.loads(script.string.strip())
            date_str = _find_date_recursive(data)
            if date_str:
                dt = dateutil.parser.parse(date_str)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(timezone.utc)
        except Exception:
            continue
            
    # 2. Fallback to meta tags
    meta_names = [
        "article:published_time",
        "publish-date",
        "pubdate",
        "date",
        "og:pubdate",
        "og:article:published_time",
        "sailthru.date",
        "parsely-pub-date",
        "dc.date.issued",
        "cxenseparse:repubdate"
    ]
    for meta_name in meta_names:
        meta = soup.find("meta", attrs={"name": meta_name}) or soup.find("meta", attrs={"property": meta_name})
        if meta and meta.get("content"):
            try:
                dt = dateutil.parser.parse(meta.get("content").strip())
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(timezone.utc)
            except Exception:
                continue

    # 3. Fallback to time tag
    time_tag = soup.find("time")
    if time_tag and time_tag.get("datetime"):
        try:
            dt = dateutil.parser.parse(time_tag.get("datetime").strip())
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            pass
            
    return None


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

    def _get_valid_categories(self, pub: Dict[str, Any]) -> Optional[List[str]]:
        discovery_config_json = pub.get("discovery_config_json")
        if discovery_config_json:
            try:
                config = json.loads(discovery_config_json)
                if "valid_categories" in config and isinstance(config["valid_categories"], list):
                    return config["valid_categories"]
            except Exception:
                pass
        return None

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
        from contextlib import nullcontext
        pub_id = pub["id"]
        
        span_ctx = logfire.span("scrape_publication", publication_id=pub_id, crawl_type="incremental") if logfire else nullcontext()
        with span_ctx:
            base_url = pub["base_url"]
            crawl_delay = pub.get("crawl_delay", 2.0)
            max_concurrency = pub.get("max_concurrency", 2)
            use_robots_txt = pub.get("use_robots_txt", True)

            listing_urls = self._get_listing_urls(pub)
            if not listing_urls:
                logger.warning(f"No listing_urls configured for publication '{pub_id}'")
                return []

            blocklist = self._get_blocklist(pub)
            valid_categories = self._get_valid_categories(pub)
            limiter = PolitenessLimiter(crawl_delay=crawl_delay, max_concurrency=max_concurrency)

            run_config = CrawlerRunConfig(
                cache_mode=CacheMode.BYPASS,
                check_robots_txt=use_robots_txt
            )

            candidate_urls = []
            links_found_count = 0
            blocklist_filtered_count = 0
            category_filtered_count = 0
            anchor_filtered_count = 0
            
            has_successful_response = False

            async with AsyncWebCrawler() as crawler:
                for url in listing_urls:
                    async with limiter:
                        logger.info(f"Crawling listing page '{url}' for publication '{pub_id}'")
                        result = await crawler.arun(url=url, config=run_config)
                        if not result.success:
                            logger.error(f"Failed to crawl listing page '{url}': {result.error_message}")
                            continue
                        
                        status_code = getattr(result, "status_code", None)
                        if status_code is None or status_code == 200:
                            has_successful_response = True
                        
                        # Parse HTML using BeautifulSoup to build an href-to-text fallback map.
                        # This works around cases where Crawl4AI does not capture anchor text inside nested elements.
                        href_to_text = {}
                        raw_html = getattr(result, "html", None) or getattr(result, "cleaned_html", None)
                        if raw_html:
                            try:
                                html_soup = BeautifulSoup(raw_html, "html.parser")
                                from knowledge_map.utils.urls import clean_and_resolve_url
                                for a_tag in html_soup.find_all("a", href=True):
                                    raw_href = a_tag["href"]
                                    a_text = a_tag.get_text(separator=" ", strip=True)
                                    if a_text:
                                        if raw_href not in href_to_text or len(a_text) > len(href_to_text[raw_href]):
                                            href_to_text[raw_href] = a_text
                                        resolved_raw = clean_and_resolve_url(base_url, raw_href)
                                        if resolved_raw:
                                            if resolved_raw not in href_to_text or len(a_text) > len(href_to_text[resolved_raw]):
                                                href_to_text[resolved_raw] = a_text
                            except Exception as e:
                                logger.warning(f"Failed to parse listing page HTML for link text fallback: {e}")

                        # Extract links
                        links_dict = getattr(result, "links", {}) or {}
                        internal_links = links_dict.get("internal", [])
                        external_links = links_dict.get("external", [])
                        all_links = internal_links + external_links
                        
                        links_found_count += len(all_links)
                        
                        for link in all_links:
                            href = link.get("href")
                            text = link.get("text")
                            if not href:
                                continue
                            
                            from knowledge_map.utils.urls import clean_and_resolve_url
                            resolved_url = clean_and_resolve_url(base_url, href)
                            if not resolved_url:
                                continue

                            # Fallback to BeautifulSoup extracted text if crawler text is empty or too short
                            if not text or len(text.strip()) < 25:
                                bs_text = href_to_text.get(href) or href_to_text.get(resolved_url)
                                if bs_text:
                                    text = bs_text
                            
                            if not self._is_same_domain(base_url, resolved_url):
                                logger.info("URL discarded: %s because of external domain", resolved_url, extra={
                                    "url": resolved_url,
                                    "publication_id": pub_id,
                                    "filter_reason": "external_domain"
                                })
                                continue

                            # Check blocklist first
                            is_blocklist_hit = False
                            try:
                                parsed = urlparse(resolved_url)
                                path = parsed.path
                                for segment in blocklist:
                                    if segment in path:
                                        is_blocklist_hit = True
                                        break
                            except Exception as e:
                                logger.error(f"Error parsing URL '{resolved_url}' for path blocklist: {e}")
                                continue

                            if is_blocklist_hit:
                                blocklist_filtered_count += 1
                                logger.info("URL discarded: %s because of URL path blocklist", resolved_url, extra={
                                    "url": resolved_url,
                                    "publication_id": pub_id,
                                    "filter_reason": "blocklist_hit"
                                })
                                continue

                            # Check category path matching
                            if not matches_category(resolved_url, valid_categories):
                                category_filtered_count += 1
                                logger.info("URL discarded: %s because of category mismatch", resolved_url, extra={
                                    "url": resolved_url,
                                    "publication_id": pub_id,
                                    "filter_reason": "category_mismatch"
                                })
                                continue

                            # Check anchor heuristics next
                            is_anchor_heuristic_dropped = False
                            if not text:
                                is_anchor_heuristic_dropped = True
                            else:
                                cleaned_text = text.strip()
                                words = cleaned_text.split()
                                if len(words) < 5 or len(cleaned_text) < 25:
                                    is_anchor_heuristic_dropped = True

                            if is_anchor_heuristic_dropped:
                                anchor_filtered_count += 1
                                logger.info("URL discarded: %s because link anchor text is too short. Text: '%s'", resolved_url, text or "", extra={
                                    "url": resolved_url,
                                    "publication_id": pub_id,
                                    "filter_reason": "anchor_heuristic_dropped",
                                    "anchor_text": text
                                })
                                continue
                            
                            if is_url_known(resolved_url, db_path=self.db_path):
                                logger.info("URL discarded: %s because it is already known", resolved_url, extra={
                                    "url": resolved_url,
                                    "publication_id": pub_id,
                                    "filter_reason": "already_known"
                                })
                                continue
                                
                            if resolved_url not in candidate_urls:
                                candidate_urls.append(resolved_url)

            # Discovery stats logging
            new_candidates_found_count = len(candidate_urls)
            logger.info("Discovery stats for publication %s: links_found=%d, blocklist_filtered=%d, category_filtered=%d, anchor_filtered=%d, new_candidates=%d",
                        pub_id, links_found_count, blocklist_filtered_count, category_filtered_count, anchor_filtered_count, new_candidates_found_count,
                        extra={
                            "publication_id": pub_id,
                            "links_found": links_found_count,
                            "blocklist_filtered": blocklist_filtered_count,
                            "category_filtered": category_filtered_count,
                            "anchor_filtered": anchor_filtered_count,
                            "new_candidates_found": new_candidates_found_count
                        })

            # Check for discovery drift warning
            if has_successful_response and not candidate_urls:
                from knowledge_map.utils.console import ConsoleNotifier
                ConsoleNotifier.notify_discovery_drift(pub_id, listing_urls[0] if listing_urls else base_url)

            # Fetch candidate URLs
            scraped_urls = []
            if candidate_urls:
                logger.info(f"Discovered {len(candidate_urls)} candidate articles for '{pub_id}'")
                async with AsyncWebCrawler() as crawler:
                    async def fetch_and_cache(url: str):
                        async with limiter:
                            logger.info(f"Fetching candidate article '{url}' for '{pub_id}'")
                            res = await crawler.arun(url=url, config=run_config)
                            fetch_status = effective_fetch_status(res)
                            if not res.success or not holds_article_content(fetch_status):
                                error_msg = getattr(res, "error_message", "")
                                logger.error(
                                    f"Failed to fetch candidate '{url}': {error_msg}",
                                    extra={
                                        "url": url,
                                        "publication_id": pub_id,
                                        "fetch_status": fetch_status
                                    }
                                )
                                record_failed_fetch(url, pub_id, fetch_status, db_path=self.db_path)
                                return
                            raw_html = getattr(res, "html", "") or getattr(res, "cleaned_html", "") or ""
                            cache_scraped_html(
                                url, pub_id, raw_html, validation="PENDING",
                                relevance_status="PENDING", fetch_status=fetch_status,
                                db_path=self.db_path
                            )
                            scraped_urls.append(url)
                            logger.info(f"Cached candidate article '{url}' with status 'PENDING'")

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


class ArchiveDiscoveryService(ListingPageDiscoveryService):
    """
    Crawls publication historical archives using DomainMapper to discover all URLs,
    filters them, and resumes progress from a persisted Discovery State.
    """
    async def run_archive_crawl(self, pub: Dict[str, Any]) -> List[str]:
        from contextlib import nullcontext
        from knowledge_map.adapters.sqlite_db import (
            get_discovery_state,
            save_discovery_state
        )
        
        pub_id = pub["id"]
        
        span_ctx = logfire.span("scrape_publication", publication_id=pub_id, crawl_type="archive") if logfire else nullcontext()
        with span_ctx:
            base_url = pub["base_url"]
            crawl_delay = pub.get("crawl_delay", 2.0)
            max_concurrency = pub.get("max_concurrency", 2)
            use_robots_txt = pub.get("use_robots_txt", True)

            # 1. Try to load existing discovery state
            state = get_discovery_state(pub_id, db_path=self.db_path)
            
            links_found_count = 0
            blocklist_filtered_count = 0
            category_filtered_count = 0
            anchor_filtered_count = 0
            new_candidates_found_count = 0

            if not state:
                logger.info(f"No existing discovery state for '{pub_id}'. Initializing DomainMapper scan...")
                
                # Extract domain from base_url
                parsed_base = urlparse(base_url)
                domain = parsed_base.netloc
                if domain.startswith("www."):
                    domain = domain[4:]
                    
                # Perform DomainMapper scan
                mapper = DomainMapper()
                try:
                    results = await mapper.scan(domain=domain)
                    discovered_urls = [r["url"] for r in results if r.get("url")]
                finally:
                    await mapper.close()

                links_found_count = len(discovered_urls)

                # Filter discovered URLs
                blocklist = self._get_blocklist(pub)
                valid_categories = self._get_valid_categories(pub)
                filtered_urls = []
                for url in discovered_urls:
                    if not self._is_same_domain(base_url, url):
                        logger.info("URL discarded: %s", url, extra={
                            "url": url,
                            "publication_id": pub_id,
                            "filter_reason": "external_domain"
                        })
                        continue
                    
                    is_blocklist_hit = False
                    try:
                        parsed = urlparse(url)
                        path = parsed.path
                        for segment in blocklist:
                            if segment in path:
                                is_blocklist_hit = True
                                break
                    except Exception:
                        pass

                    if is_blocklist_hit:
                        blocklist_filtered_count += 1
                        logger.info("URL discarded: %s", url, extra={
                            "url": url,
                            "publication_id": pub_id,
                            "filter_reason": "blocklist_hit"
                        })
                        continue

                    # Check category path matching
                    if not matches_category(url, valid_categories):
                        category_filtered_count += 1
                        logger.info("URL discarded: %s because of category mismatch", url, extra={
                            "url": url,
                            "publication_id": pub_id,
                            "filter_reason": "category_mismatch"
                        })
                        continue
                    
                    filtered_urls.append(url)

                state = {
                    "urls": filtered_urls,
                    "current_index": 0,
                    "cutoff_reached": False
                }
                save_discovery_state(pub_id, state, db_path=self.db_path)
            else:
                links_found_count = len(state.get("urls", []))

            # 2. Process URLs from current_index
            scraped_urls = []
            if state.get("cutoff_reached", False):
                logger.info(f"Archive crawl for '{pub_id}' already hit the historical cutoff.")
                return scraped_urls

            # Calculate cutoff date
            cutoff_years = pub.get("archive_cutoff_years", 5)
            now = datetime.now(timezone.utc)
            cutoff_date = now - timedelta(days=365 * cutoff_years)

            limiter = PolitenessLimiter(crawl_delay=crawl_delay, max_concurrency=max_concurrency)
            run_config = CrawlerRunConfig(
                cache_mode=CacheMode.BYPASS,
                check_robots_txt=use_robots_txt
            )

            chunk_size = max(1, max_concurrency)
            
            async with AsyncWebCrawler() as crawler:
                while state["current_index"] < len(state["urls"]):
                    if state.get("cutoff_reached", False):
                        break

                    # Get next chunk
                    chunk = state["urls"][state["current_index"] : state["current_index"] + chunk_size]
                    
                    async def process_url(url: str) -> bool:
                        nonlocal new_candidates_found_count
                        # Return True if cutoff is reached
                        if is_url_known(url, db_path=self.db_path):
                            logger.info("URL discarded: %s", url, extra={
                                "url": url,
                                "publication_id": pub_id,
                                "filter_reason": "already_known"
                            })
                            return False
                        
                        new_candidates_found_count += 1
                        async with limiter:
                            logger.info(f"Archive crawl: fetching candidate '{url}' for '{pub_id}'")
                            res = await crawler.arun(url=url, config=run_config)
                            fetch_status = effective_fetch_status(res)
                            if not res.success or not holds_article_content(fetch_status):
                                logger.error(
                                    f"Archive crawl: failed to fetch '{url}': {res.error_message}",
                                    extra={
                                        "url": url,
                                        "publication_id": pub_id,
                                        "fetch_status": fetch_status
                                    }
                                )
                                record_failed_fetch(url, pub_id, fetch_status, db_path=self.db_path)
                                return False

                            raw_html = getattr(res, "html", "") or getattr(res, "cleaned_html", "") or ""

                            # Check historical cutoff
                            pub_date = extract_published_date(raw_html)
                            if pub_date and pub_date < cutoff_date:
                                logger.info(f"Archive crawl: met article older than cutoff ({pub_date} < {cutoff_date}). Reached cutoff.")
                                return True

                            # Cache candidate article immediately
                            cache_scraped_html(
                                url, pub_id, raw_html, validation="PENDING",
                                relevance_status="PENDING", fetch_status=fetch_status,
                                db_path=self.db_path
                            )
                            scraped_urls.append(url)
                            logger.info(f"Archive crawl: Cached candidate article '{url}' with status 'PENDING'")

                        return False

                    # Process the chunk concurrently
                    results = await asyncio.gather(*(process_url(url) for url in chunk))

                    # Increment index and save state
                    state["current_index"] += len(chunk)
                    if any(results):
                        state["cutoff_reached"] = True
                    
                    save_discovery_state(pub_id, state, db_path=self.db_path)

            # Discovery stats logging
            logger.info("Discovery stats for publication %s (archive): links_found=%d, blocklist_filtered=%d, category_filtered=%d, anchor_filtered=%d, new_candidates=%d",
                        pub_id, links_found_count, blocklist_filtered_count, category_filtered_count, anchor_filtered_count, new_candidates_found_count,
                        extra={
                            "publication_id": pub_id,
                            "links_found": links_found_count,
                            "blocklist_filtered": blocklist_filtered_count,
                            "category_filtered": category_filtered_count,
                            "anchor_filtered": anchor_filtered_count,
                            "new_candidates_found": new_candidates_found_count
                        })

            return scraped_urls
