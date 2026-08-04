import asyncio
import sqlite3
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from knowledge_map.adapters.sqlite_db import (
    cache_scraped_html,
    get_articles_needing_html_refetch,
    get_cached_html,
    get_all_stories,
    init_db,
    register_publication,
    store_refetched_html,
    save_story,
)
from knowledge_map.core.html_refetch import HtmlRefetchService
from knowledge_map.schemas.stories import Story


def _register_publication(db_path: str) -> None:
    register_publication(
        "testpub",
        "Test Publication",
        "https://test.example",
        crawl_delay=0,
        max_concurrency=2,
        db_path=db_path,
    )


def test_refetch_selection_requires_relevant_missing_html_without_story(tmp_path):
    db_path = str(tmp_path / "refetch_selection.db")
    init_db(db_path)
    _register_publication(db_path)

    selected_urls = {
        "https://test.example/absent-status",
        "https://test.example/server-error",
    }
    for url, relevance_status, raw_html, fetch_status in (
        ("https://test.example/absent-status", "RELEVANT", None, None),
        ("https://test.example/server-error", "RELEVANT", None, 503),
        ("https://test.example/not-found", "RELEVANT", None, 404),
        ("https://test.example/gone", "RELEVANT", None, 410),
        ("https://test.example/irrelevant", "IRRELEVANT", None, None),
        ("https://test.example/has-html", "RELEVANT", "<html></html>", 200),
        ("https://test.example/has-story", "RELEVANT", None, None),
    ):
        cache_scraped_html(
            url,
            "testpub",
            raw_html,
            relevance_status=relevance_status,
            relevance_label_source="HUMAN",
            fetch_status=fetch_status,
            db_path=db_path,
        )

    save_story(
        Story(
            title="Already extracted",
            url="https://test.example/has-story",
            content="Stored content",
        ),
        db_path=db_path,
    )

    candidates = get_articles_needing_html_refetch(db_path=db_path)

    assert {candidate["url"] for candidate in candidates} == selected_urls


def test_refetch_writer_preserves_relevance_and_metadata(tmp_path):
    db_path = str(tmp_path / "refetch_writer.db")
    init_db(db_path)
    _register_publication(db_path)
    url = "https://test.example/preserved"
    embedding = [0.25, 0.5, 0.75]
    cache_scraped_html(
        url,
        "testpub",
        None,
        validation="PENDING",
        headline="Preserved headline",
        description="Preserved description",
        embedding=embedding,
        relevance_status="RELEVANT",
        relevance_label_source="HUMAN",
        raw_metadata_json={"source": "preserved"},
        fetch_status=503,
        db_path=db_path,
    )
    old_scraped_at = "2026-01-01 00:00:00"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE scraped_html_cache SET scraped_at = ? WHERE url = ?",
            (old_scraped_at, url),
        )

    store_refetched_html(url, "<html>refetched</html>", 200, db_path=db_path)

    cached = get_cached_html(url, db_path=db_path)
    assert cached["raw_html"] == "<html>refetched</html>"
    assert cached["fetch_status"] == 200
    assert cached["scraped_at"] != old_scraped_at
    assert cached["validation"] == "PENDING"
    assert cached["relevance_status"] == "RELEVANT"
    assert cached["relevance_label_source"] == "HUMAN"
    assert cached["headline"] == "Preserved headline"
    assert cached["description"] == "Preserved description"
    assert cached["embedding"] == pytest.approx(embedding)
    assert cached["raw_metadata_json"] == {"source": "preserved"}

    store_refetched_html(url, "<html>refetched again</html>", None, db_path=db_path)
    assert get_cached_html(url, db_path=db_path)["fetch_status"] == 200


def test_refetch_records_success_and_failure_statuses(tmp_path):
    db_path = str(tmp_path / "refetch_statuses.db")
    init_db(db_path)
    _register_publication(db_path)
    success_url = "https://test.example/success"
    failure_url = "https://test.example/failure"
    for url in (success_url, failure_url):
        cache_scraped_html(
            url,
            "testpub",
            None,
            relevance_status="RELEVANT",
            relevance_label_source="HUMAN",
            db_path=db_path,
        )

    success_result = MagicMock(
        success=True,
        status_code=200,
        redirected_status_code=None,
        html="<html>success</html>",
    )
    failure_result = MagicMock(
        success=False,
        status_code=503,
        redirected_status_code=None,
        error_message="unavailable",
    )
    crawler = AsyncMock()
    async def fetch(url, config=None):
        return success_result if url == success_url else failure_result

    crawler.arun.side_effect = fetch

    with patch("knowledge_map.core.html_refetch.AsyncWebCrawler") as crawler_class:
        crawler_class.return_value.__aenter__.return_value = crawler
        refetched_urls = asyncio.run(
            HtmlRefetchService(db_path=db_path).refetch_relevant_articles()
        )

    assert refetched_urls == [success_url]
    assert get_cached_html(success_url, db_path=db_path)["fetch_status"] == 200
    failed = get_cached_html(failure_url, db_path=db_path)
    assert failed["raw_html"] is None
    assert failed["fetch_status"] == 503
    assert {row["url"] for row in get_articles_needing_html_refetch(db_path=db_path)} == {
        failure_url
    }


def test_discovery_and_refetch_share_article_fetcher():
    from knowledge_map.core import crawling, discovery, html_refetch

    assert discovery.fetch_article is crawling.fetch_article
    assert html_refetch.fetch_article is crawling.fetch_article


def test_refetch_html_cli_is_standalone(tmp_path, monkeypatch):
    from knowledge_map.cli.main import main

    db_path = str(tmp_path / "refetch_cli.db")
    monkeypatch.setenv("SQLITE_DB_PATH", db_path)

    with patch("knowledge_map.core.html_refetch.HtmlRefetchService") as service_class:
        service_class.return_value.refetch_relevant_articles = AsyncMock(
            return_value=["https://test.example/refetched"]
        )
        with pytest.raises(SystemExit) as exit_info:
            main(["refetch-html"])

    assert exit_info.value.code == 0
    service_class.return_value.refetch_relevant_articles.assert_awaited_once()


def test_validate_cli_refetches_then_validates_in_one_invocation(tmp_path, monkeypatch):
    from knowledge_map.cli.main import main
    from knowledge_map.core.selectors import add_selector_version
    from knowledge_map.schemas.selectors import ArticleSelectors

    db_path = str(tmp_path / "refetch_then_validate.db")
    init_db(db_path)
    _register_publication(db_path)
    url = "https://test.example/recovered"
    cache_scraped_html(
        url,
        "testpub",
        None,
        validation="PENDING",
        headline="Recovered article",
        description="Existing description",
        embedding=[0.1] * 768,
        relevance_status="RELEVANT",
        relevance_label_source="HUMAN",
        fetch_status=503,
        db_path=db_path,
    )
    now = datetime.now(timezone.utc)
    add_selector_version(
        publication_id="testpub",
        selectors=ArticleSelectors(
            title="h1.entry-title",
            author="span.author",
            date="time",
            body="div.entry-content",
        ),
        earliest_success_date=now - timedelta(days=1),
        latest_success_date=now + timedelta(days=1),
        db_path=db_path,
    )
    refetched_html = """
    <html>
      <head>
        <script type="application/ld+json">
        {
          "@type": "NewsArticle",
          "headline": "Recovered article",
          "datePublished": "2026-08-03T12:00:00Z",
          "author": {"name": "Alex Reporter"}
        }
        </script>
      </head>
      <body>
        <h1 class="entry-title">Recovered article</h1>
        <span class="author">By Alex Reporter</span>
        <time datetime="2026-08-03T12:00:00Z"></time>
        <div class="entry-content">
          California lawmakers considered a detailed public policy proposal with
          enough reporting context for the article extraction checks to succeed.
        </div>
      </body>
    </html>
    """
    crawler_result = MagicMock(
        success=True,
        status_code=200,
        redirected_status_code=None,
        html=refetched_html,
    )
    crawler = AsyncMock()
    crawler.arun.return_value = crawler_result
    monkeypatch.setenv("SQLITE_DB_PATH", db_path)

    with patch("knowledge_map.core.html_refetch.AsyncWebCrawler") as crawler_class:
        crawler_class.return_value.__aenter__.return_value = crawler
        with pytest.raises(SystemExit) as exit_info:
            main(["validate-articles"])

    assert exit_info.value.code == 0
    stories = get_all_stories(db_path=db_path)
    assert [story["url"] for story in stories] == [url]
    cached = get_cached_html(url, db_path=db_path)
    assert cached["validation"] == "VALIDATED"
    assert cached["relevance_status"] == "RELEVANT"
    assert cached["relevance_label_source"] == "HUMAN"
    assert cached["fetch_status"] == 200
