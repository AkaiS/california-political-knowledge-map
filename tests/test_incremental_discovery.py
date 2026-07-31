import sqlite3
import pytest
import logging
from knowledge_map.adapters.sqlite_db import init_db

def test_db_schema_initialization(tmp_path):
    db_file = tmp_path / "test_discovery.db"
    db_path = str(db_file)
    
    init_db(db_path)
    
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        
        # Verify scraped_html_cache table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='scraped_html_cache'")
        assert cursor.fetchone() is not None
        
        # Verify rejected_articles table does NOT exist
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='rejected_articles'")
        assert cursor.fetchone() is None
        
        # Verify columns of scraped_html_cache
        cursor.execute("PRAGMA table_info(scraped_html_cache)")
        columns = {col[1]: col[2].upper() for col in cursor.fetchall()}
        assert "url" in columns
        assert "publication_id" in columns
        assert "raw_html" in columns
        assert "validation" in columns
        assert "validation_date" in columns
        assert "scraped_at" in columns
        assert "headline" in columns
        assert "description" in columns
        assert "embedding" in columns
        assert "relevance_status" in columns
        assert columns["fetch_status"] == "INTEGER"
        assert "raw_metadata_json" in columns
        
    finally:
        conn.close()


def test_database_helpers(tmp_path):
    from knowledge_map.adapters.sqlite_db import (
        register_publication,
        cache_scraped_html,
        get_cached_html,
        update_cached_html_status,
        is_url_known,
        save_story
    )
    
    db_file = tmp_path / "test_discovery.db"
    db_path = str(db_file)
    init_db(db_path)
    
    # 1. Register a publication to avoid foreign key constraints (if enforced, though SQLite doesn't by default unless enabled, it's good practice)
    register_publication(
        pub_id="testpub",
        name="Test Publication",
        base_url="https://test.com",
        db_path=db_path
    )
    
    url_1 = "https://test.com/story-1"
    url_2 = "https://test.com/story-2"
    # 2. Check is_url_known is False initially
    assert not is_url_known(url_1, db_path=db_path)
    
    # 3. Cache raw HTML
    cache_scraped_html(url_1, "testpub", "<html>story 1</html>", db_path=db_path)
    assert is_url_known(url_1, db_path=db_path)
    
    # Verify get_cached_html
    cached = get_cached_html(url_1, db_path=db_path)
    assert cached is not None
    assert cached["url"] == url_1
    assert cached["publication_id"] == "testpub"
    assert cached["raw_html"] == "<html>story 1</html>"
    assert cached["validation"] == "PENDING"
    assert cached["relevance_status"] == "PENDING"
    assert cached["fetch_status"] == 200
    
    # 4. Update validation status
    update_cached_html_status(url_1, "VALIDATED", db_path=db_path)
    cached = get_cached_html(url_1, db_path=db_path)
    assert cached["validation"] == "VALIDATED"
    
    # 5. Check in stories
    assert not is_url_known(url_2, db_path=db_path)
    story = {
        "title": "Story 2",
        "url": url_2,
        "content": "This is content"
    }
    save_story(story, db_path=db_path)
    assert is_url_known(url_2, db_path=db_path)


def test_url_filtering():
    from knowledge_map.core.discovery import should_keep_url
    
    blocklist = ["/sports/", "/recipes/", "/obituaries/", "/author/", "/category/", "/tag/", "/search/"]
    
    # 1. Blocklist matches (should return False)
    assert not should_keep_url("https://calmatters.org/sports/story-1", "Valid anchor text with enough words", blocklist)
    assert not should_keep_url("https://calmatters.org/recipes/pancakes", "Valid anchor text with enough words", blocklist)
    assert not should_keep_url("https://calmatters.org/news/tag/politics", "Valid anchor text with enough words", blocklist)
    
    # 2. Blocklist does not match (should return True if anchor text is valid)
    assert should_keep_url("https://calmatters.org/politics/new-bill", "Valid anchor text with enough words", blocklist)
    
    # 3. Anchor heuristics (apply_anchor_heuristics = True)
    # - >= 5 words and >= 25 characters
    # Valid: 5 words, 25 characters
    assert should_keep_url("https://calmatters.org/politics/bill", "Five words but short text", blocklist)
    # Invalid: 5 words, 24 characters
    assert not should_keep_url("https://calmatters.org/politics/bill", "Five words but short txt", blocklist)
    # Invalid: 4 words, 25 characters
    assert not should_keep_url("https://calmatters.org/politics/bill", "Four words enough chars!!", blocklist)
    # Invalid: empty or None anchor text
    assert not should_keep_url("https://calmatters.org/politics/bill", "", blocklist)
    assert not should_keep_url("https://calmatters.org/politics/bill", None, blocklist)
    
    # 4. Anchor heuristics bypassed (apply_anchor_heuristics = False)
    assert should_keep_url("https://calmatters.org/politics/bill", "", blocklist, apply_anchor_heuristics=False)
    assert should_keep_url("https://calmatters.org/politics/bill", None, blocklist, apply_anchor_heuristics=False)
    # Blocklist should still be active even if heuristics are bypassed
    assert not should_keep_url("https://calmatters.org/sports/story-1", None, blocklist, apply_anchor_heuristics=False)


@pytest.mark.anyio
async def test_politeness_limiter():
    import asyncio
    import time
    from knowledge_map.core.discovery import PolitenessLimiter
    
    # crawl_delay = 0.05, max_concurrency = 2
    limiter = PolitenessLimiter(crawl_delay=0.05, max_concurrency=2)
    
    start_time = asyncio.get_event_loop().time()
    call_times = []
    
    async def worker(worker_id):
        async with limiter:
            now = asyncio.get_event_loop().time()
            call_times.append(now - start_time)
            # Simulate a request taking 0.02s
            await asyncio.sleep(0.02)
            
    # Spawn 3 workers
    await asyncio.gather(worker(1), worker(2), worker(3))
    
    assert len(call_times) == 3
    # Sort just in case of slight event loop scheduling differences
    call_times.sort()
    
    # First request starts at ~0.0
    # Second request must be spaced by at least 0.05s (delay limit)
    # Third request must be spaced by at least 0.1s
    assert call_times[1] - call_times[0] >= 0.045
    assert call_times[2] - call_times[1] >= 0.045


@pytest.mark.anyio
async def test_listing_page_discovery_service(tmp_path):
    from unittest.mock import AsyncMock, patch, MagicMock
    from knowledge_map.adapters.sqlite_db import (
        init_db,
        register_publication,
        save_story,
        get_cached_html,
        is_url_known
    )
    from knowledge_map.core.discovery import ListingPageDiscoveryService
    
    db_file = tmp_path / "test_discovery_service.db"
    db_path = str(db_file)
    init_db(db_path)
    
    # 1. Register a test publication
    # Blocklist configured: custom blocklist contains "/ignore/"
    register_publication(
        pub_id="testpub",
        name="Test Pub",
        base_url="https://test.com",
        crawl_delay=0.01,
        max_concurrency=2,
        use_robots_txt=True,
        discovery_config_json='{"listing_urls": ["https://test.com/news"], "url_path_blocklist": ["/ignore/"]}',
        db_path=db_path
    )
    
    # Register an already scraped story to test skip-existing logic
    already_scraped_url = "https://test.com/politics/already-scraped"
    save_story({
        "title": "Already Scraped Story",
        "url": already_scraped_url,
        "content": "some content"
    }, db_path=db_path)
    
    # 2. Mock CrawlResult for listing page
    mock_listing_result = MagicMock()
    mock_listing_result.success = True
    mock_listing_result.links = {
        "internal": [
            # Candidate 1: Valid (should be fetched)
            {"href": "https://test.com/politics/valid-story-1", "text": "This is a valid long link text description"},
            # Candidate 2: Blocklisted path
            {"href": "https://test.com/ignore/blocked-story", "text": "This is a valid long link text description"},
            # Candidate 3: Short anchor text (failed heuristics)
            {"href": "https://test.com/politics/short-anchor", "text": "Click"},
            # Candidate 4: Already scraped (should be skipped)
            {"href": already_scraped_url, "text": "This is a valid long link text description"},
            # Candidate 5: External link (should be skipped or filtered if outside base_url domain)
            {"href": "https://external.com/politics/other-story", "text": "This is a valid long link text description"}
        ]
    }
    
    # 3. Mock CrawlResult for article page
    mock_article_result = MagicMock()
    mock_article_result.success = True
    mock_article_result.status_code = 206
    mock_article_result.html = """
    <html>
    <head>
        <script type="application/ld+json">
        {
            "headline": "California Senate approves Newsom nominee"
        }
        </script>
    </head>
    <body>scraped raw content</body>
    </html>
    """
    
    # 4. Patch AsyncWebCrawler
    mock_crawler_instance = AsyncMock()
    
    async def mock_arun(url, config=None):
        if url == "https://test.com/news":
            return mock_listing_result
        elif url == "https://test.com/politics/valid-story-1":
            return mock_article_result
        else:
            raise ValueError(f"Unexpected crawled URL: {url}")
            
    mock_crawler_instance.arun.side_effect = mock_arun
    
    with patch("knowledge_map.core.discovery.AsyncWebCrawler") as MockCrawlerClass:
        MockCrawlerClass.return_value.__aenter__.return_value = mock_crawler_instance
        
        service = ListingPageDiscoveryService(db_path=db_path)
        # Execute for testpub
        pub = get_cached_html(already_scraped_url, db_path=db_path) # wait, we get publication row
        from knowledge_map.adapters.sqlite_db import get_publication
        pub = get_publication("testpub", db_path=db_path)
        
        scraped_urls = await service.discover_and_scrape_for_publication(pub)
        
        # Verify only valid-story-1 was scraped
        assert scraped_urls == ["https://test.com/politics/valid-story-1"]
        
        # Verify it was cached in scraped_html_cache as PENDING
        cached = get_cached_html("https://test.com/politics/valid-story-1", db_path=db_path)
        assert cached is not None
        assert cached["publication_id"] == "testpub"
        assert "scraped raw content" in cached["raw_html"]
        assert cached["validation"] == "PENDING"
        assert cached["relevance_status"] == "PENDING"
        assert cached["fetch_status"] == 206
        
        # Verify check_robots_txt config was passed as True because use_robots_txt is True
        # Let's inspect arun calls
        assert mock_crawler_instance.arun.call_count == 2


def test_cli_update_sources(tmp_path, monkeypatch):
    from unittest.mock import AsyncMock, patch
    from knowledge_map.adapters.sqlite_db import init_db
    from knowledge_map.cli.main import main
    
    db_file = tmp_path / "test_cli_update.db"
    db_path = str(db_file)
    init_db(db_path)
    
    monkeypatch.setenv("SQLITE_DB_PATH", db_path)
    
    with patch("knowledge_map.cli.main.ListingPageDiscoveryService") as MockServiceClass:
        mock_service_instance = AsyncMock()
        mock_service_instance.discover_and_scrape_all.return_value = {"testpub": ["https://test.com/story-1"]}
        MockServiceClass.return_value = mock_service_instance
        
        try:
            main(["update-sources"])
        except SystemExit as e:
            assert e.code == 0
            
        mock_service_instance.discover_and_scrape_all.assert_called_once()


def test_matches_category_simple():
    from knowledge_map.core.discovery import matches_category
    
    # 1. Exact match with a single valid category
    assert matches_category("https://calmatters.org/politics/some-slug", ["politics"]) is True
    assert matches_category("https://calmatters.org/housing/some-slug", ["politics"]) is False


def test_matches_category_multiple_and_case_insensitive():
    from knowledge_map.core.discovery import matches_category
    
    # Verify case-insensitive match
    assert matches_category("https://calmatters.org/Politics/some-slug", ["politics"]) is True
    # Verify multiple categories
    assert matches_category("https://calmatters.org/housing/some-slug", ["politics", "housing"]) is True
    # Verify case-insensitivity on configuration array
    assert matches_category("https://calmatters.org/housing/some-slug", ["POLITICS", "HOUSING"]) is True


def test_matches_category_segment_exclusion():
    from knowledge_map.core.discovery import matches_category
    
    # 1. Final segment (article name slug) must be ignored:
    # URL has "politics" only at the end - shouldn't match "politics"
    assert matches_category("https://calmatters.org/politics", ["politics"]) is False
    assert matches_category("https://calmatters.org/news/politics", ["politics"]) is False
    
    # 2. Exact segment match (preceding segments match exactly):
    # "/sports/.../immigration-officer/" does not match "immigration"
    assert matches_category("https://calmatters.org/sports/immigration-officer", ["immigration"]) is False
    assert matches_category("https://calmatters.org/sports/immigration/some-slug", ["immigration"]) is True


def test_matches_category_bypass():
    from knowledge_map.core.discovery import matches_category
    
    # Bypass when valid_categories is empty list or None
    assert matches_category("https://calmatters.org/sports/immigration-officer", []) is True
    assert matches_category("https://calmatters.org/sports/immigration-officer", None) is True
    assert matches_category("https://calmatters.org/flat-slug", []) is True
    assert matches_category("https://calmatters.org/flat-slug", None) is True


@pytest.mark.anyio
async def test_discovery_service_category_filtering(tmp_path, caplog):
    from unittest.mock import AsyncMock, patch, MagicMock
    from knowledge_map.adapters.sqlite_db import (
        init_db,
        register_publication,
        get_publication
    )
    from knowledge_map.core.discovery import ListingPageDiscoveryService
    
    db_file = tmp_path / "test_discovery_category.db"
    db_path = str(db_file)
    init_db(db_path)
    
    # Register publication with valid_categories configured
    register_publication(
        pub_id="testpub_cat",
        name="Test Category Pub",
        base_url="https://test.com",
        crawl_delay=0.01,
        max_concurrency=2,
        use_robots_txt=True,
        discovery_config_json='{"listing_urls": ["https://test.com/news"], "url_path_blocklist": ["/ignore/"], "valid_categories": ["politics", "housing"]}',
        db_path=db_path
    )
    
    # Mock listing page links
    mock_listing_result = MagicMock()
    mock_listing_result.success = True
    mock_listing_result.links = {
        "internal": [
            # 1. Valid politics category
            {"href": "https://test.com/politics/valid-politics-story", "text": "This is a valid long link text description"},
            # 2. Valid housing category
            {"href": "https://test.com/housing/valid-housing-story", "text": "This is a valid long link text description"},
            # 3. Invalid sports category (should mismatch)
            {"href": "https://test.com/sports/invalid-sports-story", "text": "This is a valid long link text description"},
            # 4. Blocklisted (blocklist checks first)
            {"href": "https://test.com/ignore/politics/blocked-story", "text": "This is a valid long link text description"},
            # 5. Politics as final slug only (should mismatch)
            {"href": "https://test.com/politics", "text": "This is a valid long link text description"},
            # 6. Flat URL structure (should mismatch since categories are configured)
            {"href": "https://test.com/about-us", "text": "This is a valid long link text description"}
        ]
    }
    
    # Mock article results
    mock_article_result = MagicMock()
    mock_article_result.success = True
    mock_article_result.html = "<html><body>Relevant content</body></html>"
    
    mock_crawler_instance = AsyncMock()
    async def mock_arun(url, config=None):
        if url == "https://test.com/news":
            return mock_listing_result
        else:
            return mock_article_result
            
    mock_crawler_instance.arun.side_effect = mock_arun
    
    with patch("knowledge_map.core.discovery.AsyncWebCrawler") as MockCrawlerClass, \
         caplog.at_level(logging.INFO):
        MockCrawlerClass.return_value.__aenter__.return_value = mock_crawler_instance
        
        service = ListingPageDiscoveryService(db_path=db_path)
        pub = get_publication("testpub_cat", db_path=db_path)
        
        scraped_urls = await service.discover_and_scrape_for_publication(pub)
        
        # Verify only valid categories stories were scraped
        assert set(scraped_urls) == {
            "https://test.com/politics/valid-politics-story",
            "https://test.com/housing/valid-housing-story"
        }
        
        # Verify they were cached with PENDING relevance
        from knowledge_map.adapters.sqlite_db import get_cached_html
        for url in scraped_urls:
            cached = get_cached_html(url, db_path=db_path)
            assert cached is not None
            assert cached["relevance_status"] == "PENDING"
        
        # Verify that blocklist is checked before category filter:
        # https://test.com/ignore/politics/blocked-story contains politics, but is blocklisted first.
        # Check logs for reasons
        mismatch_logs = [r for r in caplog.records if getattr(r, "filter_reason", None) == "category_mismatch"]
        blocklist_logs = [r for r in caplog.records if getattr(r, "filter_reason", None) == "blocklist_hit"]
        
        # The blocklisted URL should be in blocklist_logs
        assert any("blocked-story" in log.url for log in blocklist_logs)
        # Verify blocklisted url was not checked as category mismatch
        assert not any("blocked-story" in log.url for log in mismatch_logs)
        
        # 3 urls should be in mismatch_logs: sports story, flat about-us URL, and politics final segment URL
        assert len(mismatch_logs) == 3
        mismatched_urls = {log.url for log in mismatch_logs}
        assert "https://test.com/sports/invalid-sports-story" in mismatched_urls
        assert "https://test.com/politics" in mismatched_urls
        assert "https://test.com/about-us" in mismatched_urls
        
        # Check the discovery stats log
        stats_log = [r for r in caplog.records if "Discovery stats for publication" in r.message]
        assert len(stats_log) == 1
        assert getattr(stats_log[0], "category_filtered", 0) == 3
        assert getattr(stats_log[0], "blocklist_filtered", 0) == 1
        assert getattr(stats_log[0], "new_candidates_found", 0) == 2


@pytest.mark.anyio
async def test_listing_page_discovery_soup_fallback_text(tmp_path):
    from unittest.mock import AsyncMock, patch, MagicMock
    from knowledge_map.adapters.sqlite_db import init_db, register_publication
    from knowledge_map.core.discovery import ListingPageDiscoveryService
    
    db_file = tmp_path / "test_soup_fallback.db"
    db_path = str(db_file)
    init_db(db_path)
    
    register_publication(
        pub_id="testpub",
        name="Test Pub",
        base_url="https://test.com",
        discovery_config_json='{"listing_urls": ["https://test.com"]}',
        db_path=db_path
    )
    
    # Mock listing result: the Crawl4AI result has empty text in its links,
    # but the html has a tags with rich nested text.
    mock_listing_result = MagicMock()
    mock_listing_result.success = True
    mock_listing_result.links = {
        "internal": [
            # Candidate 1: Crawl4AI says text is empty, but HTML contains rich nested text.
            # (Heuristic requires at least 25 characters / 5 words)
            {"href": "https://test.com/politics/nested-text-story", "text": ""}
        ]
    }
    mock_listing_result.html = """
    <html>
    <body>
        <a href="https://test.com/politics/nested-text-story">
            <h3>California Senate Approves Newsom Nominee for High Court</h3>
        </a>
    </body>
    </html>
    """
    
    mock_article_result = MagicMock()
    mock_article_result.success = True
    mock_article_result.html = """
    <html>
    <head>
        <script type="application/ld+json">
        {
            "headline": "California Senate approves Newsom nominee"
        }
        </script>
    </head>
    <body>scraped raw content</body>
    </html>
    """
    
    mock_crawler_instance = AsyncMock()
    async def mock_arun(url, config=None):
        if url == "https://test.com":
            return mock_listing_result
        else:
            return mock_article_result
    mock_crawler_instance.arun.side_effect = mock_arun
    
    with patch("knowledge_map.core.discovery.AsyncWebCrawler") as MockCrawlerClass:
        MockCrawlerClass.return_value.__aenter__.return_value = mock_crawler_instance
        
        service = ListingPageDiscoveryService(db_path=db_path)
        from knowledge_map.adapters.sqlite_db import get_publication
        pub = get_publication("testpub", db_path=db_path)
        
        scraped_urls = await service.discover_and_scrape_for_publication(pub)
        # Should be scraped because the fallback gets the text "California Senate Approves Newsom Nominee for High Court" (>= 25 chars and >= 5 words)
        assert scraped_urls == ["https://test.com/politics/nested-text-story"]








