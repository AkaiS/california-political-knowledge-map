import asyncio
import logging
from collections import defaultdict
from typing import Any, Dict, List

from crawl4ai import AsyncWebCrawler, CacheMode, CrawlerRunConfig

from knowledge_map.adapters.sqlite_db import (
    get_articles_needing_html_refetch,
    store_refetched_html,
)
from knowledge_map.config import settings
from knowledge_map.core.crawling import fetch_article
from knowledge_map.core.discovery import PolitenessLimiter

logger = logging.getLogger(__name__)


class HtmlRefetchService:
    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or settings.batch_ingestion.db_path

    async def refetch_relevant_articles(self) -> List[str]:
        candidates = get_articles_needing_html_refetch(db_path=self.db_path)
        if not candidates:
            logger.info("No articles need a raw HTML refetch.")
            return []

        candidates_by_publication: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for candidate in candidates:
            candidates_by_publication[candidate["publication_id"]].append(candidate)

        refetched_urls: List[str] = []
        async with AsyncWebCrawler() as crawler:
            for publication_candidates in candidates_by_publication.values():
                refetched_urls.extend(
                    await self._refetch_publication(crawler, publication_candidates)
                )

        return refetched_urls

    async def _refetch_publication(
        self,
        crawler: AsyncWebCrawler,
        publication_candidates: List[Dict[str, Any]],
    ) -> List[str]:
        publication = publication_candidates[0]
        limiter = PolitenessLimiter(
            crawl_delay=publication["crawl_delay"],
            max_concurrency=publication["max_concurrency"],
        )
        run_config = CrawlerRunConfig(
            cache_mode=CacheMode.BYPASS,
            check_robots_txt=bool(publication["use_robots_txt"]),
        )

        refetched_urls: List[str] = []

        async def refetch(candidate: Dict[str, Any]) -> None:
            async with limiter:
                result = await fetch_article(crawler, candidate["url"], run_config)
                store_refetched_html(
                    candidate["url"],
                    result.raw_html,
                    result.fetch_status,
                    db_path=self.db_path,
                )
                if result.has_raw_html:
                    refetched_urls.append(candidate["url"])
                else:
                    logger.error(
                        "Failed to refetch '%s': %s",
                        candidate["url"],
                        result.error_message,
                        extra={
                            "url": candidate["url"],
                            "publication_id": candidate["publication_id"],
                            "fetch_status": result.fetch_status,
                        },
                    )

        await asyncio.gather(*(refetch(candidate) for candidate in publication_candidates))
        return refetched_urls
