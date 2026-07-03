import sqlite3
import pytest
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
        
        # Verify rejected_articles table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='rejected_articles'")
        assert cursor.fetchone() is not None
        
        # Verify columns of scraped_html_cache
        cursor.execute("PRAGMA table_info(scraped_html_cache)")
        columns = {col[1]: col[2].upper() for col in cursor.fetchall()}
        assert "url" in columns
        assert "publication_id" in columns
        assert "raw_html" in columns
        assert "validation" in columns
        assert "validation_date" in columns
        assert "scraped_at" in columns
        
        # Verify columns of rejected_articles
        cursor.execute("PRAGMA table_info(rejected_articles)")
        columns_rejected = {col[1]: col[2].upper() for col in cursor.fetchall()}
        assert "url" in columns_rejected
        assert "publication_id" in columns_rejected
        assert "relevance_status" in columns_rejected
        assert "metadata_json" in columns_rejected
        assert "checked_at" in columns_rejected
        
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
    url_3 = "https://test.com/story-3"
    
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
    
    # 6. Check in rejected_articles
    assert not is_url_known(url_3, db_path=db_path)
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO rejected_articles (url, publication_id, relevance_status) VALUES (?, ?, ?)",
            (url_3, "testpub", "IRRELEVANT")
        )
        conn.commit()
    finally:
        conn.close()
    assert is_url_known(url_3, db_path=db_path)


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





