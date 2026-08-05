from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class ArticleFetchResult:
    raw_html: Optional[str]
    fetch_status: Optional[int]
    error_message: str = ""

    @property
    def has_raw_html(self) -> bool:
        return self.raw_html is not None


def effective_fetch_status(result: Any) -> Optional[int]:
    """Return the final HTTP response status reported by Crawl4AI."""
    for candidate in (
        getattr(result, "redirected_status_code", None),
        getattr(result, "status_code", None),
    ):
        if isinstance(candidate, int):
            return candidate
    return None


def holds_article_content(fetch_status: Optional[int]) -> bool:
    """Return whether a fetch status can represent article content."""
    return fetch_status is None or 200 <= fetch_status < 300


async def fetch_article(crawler: Any, url: str, run_config: Any) -> ArticleFetchResult:
    """Fetch one article and normalize Crawl4AI's response contract."""
    try:
        result = await crawler.arun(url=url, config=run_config)
    except Exception as exc:
        return ArticleFetchResult(raw_html=None, fetch_status=None, error_message=str(exc))

    fetch_status = effective_fetch_status(result)
    if not result.success or not holds_article_content(fetch_status):
        return ArticleFetchResult(
            raw_html=None,
            fetch_status=fetch_status,
            error_message=getattr(result, "error_message", "") or "",
        )

    raw_html = getattr(result, "html", "") or getattr(result, "cleaned_html", "") or ""
    return ArticleFetchResult(raw_html=raw_html, fetch_status=fetch_status)
