import sqlite3
import pytest
from knowledge_map.adapters.sqlite_db import (
    init_db,
    register_publication,
    get_discovery_state,
    save_discovery_state
)

def test_db_schema_initialization_discovery_state(tmp_path):
    db_file = tmp_path / "test_discovery_state.db"
    db_path = str(db_file)
    
    init_db(db_path)
    
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        
        # Verify publication_discovery_state table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='publication_discovery_state'")
        assert cursor.fetchone() is not None
        
        # Verify columns of publication_discovery_state
        cursor.execute("PRAGMA table_info(publication_discovery_state)")
        columns = {col[1]: col[2].upper() for col in cursor.fetchall()}
        assert "publication_id" in columns
        assert "state_json" in columns
        assert "updated_at" in columns
    finally:
        conn.close()


def test_discovery_state_helpers(tmp_path):
    db_file = tmp_path / "test_discovery_state_helpers.db"
    db_path = str(db_file)
    init_db(db_path)
    
    # Register publication
    register_publication(
        pub_id="testpub",
        name="Test Pub",
        base_url="https://test.com",
        db_path=db_path
    )
    
    # Verify initially no state exists
    assert get_discovery_state("testpub", db_path=db_path) is None
    
    # Save discovery state
    test_state = {
        "urls": ["https://test.com/1", "https://test.com/2"],
        "current_index": 1,
        "cutoff_reached": False
    }
    save_discovery_state("testpub", test_state, db_path=db_path)
    
    # Verify state retrieved is equal to saved state
    retrieved = get_discovery_state("testpub", db_path=db_path)
    assert retrieved == test_state


def test_extract_published_date():
    from knowledge_map.core.discovery import extract_published_date
    from datetime import datetime, timezone
    
    # 1. JSON-LD datePublished
    html_json_ld = """
    <html>
    <head>
        <script type="application/ld+json">
        {
            "@context": "https://schema.org",
            "@type": "NewsArticle",
            "datePublished": "2026-07-02T15:30:00Z"
        }
        </script>
    </head>
    </html>
    """
    dt = extract_published_date(html_json_ld)
    assert dt == datetime(2026, 7, 2, 15, 30, 0, tzinfo=timezone.utc)

    # 2. HTML meta tag (article:published_time)
    html_meta = """
    <html>
    <head>
        <meta property="article:published_time" content="2026-07-01T12:00:00-07:00" />
    </head>
    </html>
    """
    dt = extract_published_date(html_meta)
    # 12:00:00-07:00 is 19:00:00 UTC
    assert dt == datetime(2026, 7, 1, 19, 0, 0, tzinfo=timezone.utc)

    # 3. HTML time tag
    html_time = """
    <html>
    <body>
        <time datetime="2026-06-30"></time>
    </body>
    </html>
    """
    dt = extract_published_date(html_time)
    assert dt == datetime(2026, 6, 30, 0, 0, 0, tzinfo=timezone.utc)

    # 4. None / missing date
    html_missing = "<html><body>No date here</body></html>"
    assert extract_published_date(html_missing) is None


@pytest.mark.anyio
async def test_archive_crawl_first_run(tmp_path):
    from unittest.mock import AsyncMock, patch, MagicMock
    from knowledge_map.adapters.sqlite_db import (
        init_db,
        register_publication,
        get_cached_html,
        get_rejected_article,
        get_publication,
        get_discovery_state
    )
    from knowledge_map.core.discovery import ArchiveDiscoveryService

    db_file = tmp_path / "test_archive_first_run.db"
    db_path = str(db_file)
    init_db(db_path)

    register_publication(
        pub_id="testpub",
        name="Test Pub",
        base_url="https://test.com",
        crawl_delay=0.01,
        max_concurrency=2,
        use_robots_txt=False,
        discovery_config_json='{"url_path_blocklist": ["/ignore/"]}',
        db_path=db_path
    )

    # 1. Mock DomainMapper scan return value
    mock_scan_results = [
        {"url": "https://test.com/politics/relevant-1"},
        {"url": "https://test.com/ignore/blocked-story"},
        {"url": "https://test.com/politics/irrelevant-2"}
    ]
    # We will patch DomainMapper
    mock_mapper_instance = AsyncMock()
    mock_mapper_instance.scan.return_value = mock_scan_results

    # 2. Mock CrawlResult for article pages
    # Article 1: Relevant (Governor Newsom signs bill)
    mock_res_relevant = MagicMock()
    mock_res_relevant.success = True
    mock_res_relevant.html = """
    <html>
    <head>
        <script type="application/ld+json">
        {
            "headline": "Newsom Signs New Bill",
            "description": "Governor Newsom makes a statement.",
            "datePublished": "2026-07-02T12:00:00Z"
        }
        </script>
    </head>
    </html>
    """

    # Article 2: Irrelevant (Sports Baking)
    mock_res_irrelevant = MagicMock()
    mock_res_irrelevant.success = True
    mock_res_irrelevant.html = """
    <html>
    <head>
        <script type="application/ld+json">
        {
            "headline": "Sports Baking Special",
            "description": "A recipe for sports fans.",
            "datePublished": "2026-07-02T12:00:00Z"
        }
        </script>
    </head>
    </html>
    """

    mock_crawler_instance = AsyncMock()
    async def mock_arun(url, config=None):
        if url == "https://test.com/politics/relevant-1":
            return mock_res_relevant
        elif url == "https://test.com/politics/irrelevant-2":
            return mock_res_irrelevant
        else:
            raise ValueError(f"Unexpected crawled URL: {url}")
    mock_crawler_instance.arun.side_effect = mock_arun

    with patch("knowledge_map.core.discovery.DomainMapper") as MockMapperClass, \
         patch("knowledge_map.core.discovery.AsyncWebCrawler") as MockCrawlerClass:
        
        MockMapperClass.return_value = mock_mapper_instance
        MockCrawlerClass.return_value.__aenter__.return_value = mock_crawler_instance

        service = ArchiveDiscoveryService(db_path=db_path)
        pub = get_publication("testpub", db_path=db_path)

        scraped_urls = await service.run_archive_crawl(pub)

        # Verify output
        assert scraped_urls == ["https://test.com/politics/relevant-1"]

        # Verify blocklist excluded '/ignore/blocked-story' from the state URLs
        state = get_discovery_state("testpub", db_path=db_path)
        assert state is not None
        assert "/ignore/blocked-story" not in state["urls"]
        assert state["urls"] == ["https://test.com/politics/relevant-1", "https://test.com/politics/irrelevant-2"]
        assert state["current_index"] == 2
        assert state["cutoff_reached"] is False

        # Verify relevant article is cached
        cached = get_cached_html("https://test.com/politics/relevant-1", db_path=db_path)
        assert cached is not None
        assert cached["validation"] == "PENDING"

        # Verify irrelevant article is rejected
        rejected = get_rejected_article("https://test.com/politics/irrelevant-2", db_path=db_path)
        assert rejected is not None
        assert rejected["relevance_status"] == "IRRELEVANT"


@pytest.mark.anyio
async def test_archive_crawl_resumption(tmp_path):
    from unittest.mock import AsyncMock, patch, MagicMock
    from knowledge_map.adapters.sqlite_db import (
        init_db,
        register_publication,
        get_publication,
        save_discovery_state,
        get_discovery_state
    )
    from knowledge_map.core.discovery import ArchiveDiscoveryService

    db_file = tmp_path / "test_archive_resumption.db"
    db_path = str(db_file)
    init_db(db_path)

    register_publication(
        pub_id="testpub",
        name="Test Pub",
        base_url="https://test.com",
        crawl_delay=0.01,
        max_concurrency=2,
        use_robots_txt=False,
        db_path=db_path
    )

    # Pre-populate state: url1 was already processed, url2 and url3 are left
    initial_state = {
        "urls": ["https://test.com/politics/url1", "https://test.com/politics/url2", "https://test.com/politics/url3"],
        "current_index": 1,
        "cutoff_reached": False
    }
    save_discovery_state("testpub", initial_state, db_path=db_path)

    mock_res = MagicMock()
    mock_res.success = True
    mock_res.html = """
    <html>
    <head>
        <script type="application/ld+json">
        {
            "headline": "Newsom Signs New Bill",
            "description": "Governor Newsom makes a statement.",
            "datePublished": "2026-07-02T12:00:00Z"
        }
        </script>
    </head>
    </html>
    """

    mock_crawler_instance = AsyncMock()
    async def mock_arun(url, config=None):
        if url in ("https://test.com/politics/url2", "https://test.com/politics/url3"):
            return mock_res
        else:
            raise ValueError(f"Should not crawl url1: {url}")
    mock_crawler_instance.arun.side_effect = mock_arun

    with patch("knowledge_map.core.discovery.DomainMapper") as MockMapperClass, \
         patch("knowledge_map.core.discovery.AsyncWebCrawler") as MockCrawlerClass:
        
        MockCrawlerClass.return_value.__aenter__.return_value = mock_crawler_instance

        service = ArchiveDiscoveryService(db_path=db_path)
        pub = get_publication("testpub", db_path=db_path)

        scraped_urls = await service.run_archive_crawl(pub)

        # Both url2 and url3 should be crawled and returned (they match relevance)
        assert len(scraped_urls) == 2
        assert "https://test.com/politics/url2" in scraped_urls
        assert "https://test.com/politics/url3" in scraped_urls

        # Verify state is updated to index 3
        state = get_discovery_state("testpub", db_path=db_path)
        assert state["current_index"] == 3
        assert state["cutoff_reached"] is False

        # DomainMapper should NOT be called at all
        MockMapperClass.assert_not_called()


@pytest.mark.anyio
async def test_archive_crawl_cutoff(tmp_path):
    from unittest.mock import AsyncMock, patch, MagicMock
    from knowledge_map.adapters.sqlite_db import (
        init_db,
        register_publication,
        get_publication,
        get_discovery_state
    )
    from knowledge_map.core.discovery import ArchiveDiscoveryService

    db_file = tmp_path / "test_archive_cutoff.db"
    db_path = str(db_file)
    init_db(db_path)

    # cutoff is 1 year
    register_publication(
        pub_id="testpub",
        name="Test Pub",
        base_url="https://test.com",
        crawl_delay=0.01,
        max_concurrency=1,
        use_robots_txt=False,
        archive_cutoff_years=1,
        db_path=db_path
    )

    # 1. Mock DomainMapper scan return value (3 URLs)
    mock_scan_results = [
        {"url": "https://test.com/politics/new-1"},  # New
        {"url": "https://test.com/politics/old-2"},  # Old (cutoff!)
        {"url": "https://test.com/politics/ignored-3"} # Should not be crawled
    ]
    mock_mapper_instance = AsyncMock()
    mock_mapper_instance.scan.return_value = mock_scan_results

    # 2. Mock CrawlResult for article pages
    # Article 1: New (datePublished = today)
    mock_res_new = MagicMock()
    mock_res_new.success = True
    mock_res_new.html = """
    <html>
    <head>
        <script type="application/ld+json">
        {
            "headline": "Newsom Signs New Bill",
            "description": "Governor Newsom makes a statement.",
            "datePublished": "2026-07-02T12:00:00Z"
        }
        </script>
    </head>
    </html>
    """

    # Article 2: Old (datePublished = 2 years ago)
    mock_res_old = MagicMock()
    mock_res_old.success = True
    mock_res_old.html = """
    <html>
    <head>
        <script type="application/ld+json">
        {
            "headline": "Newsom Signs Old Bill",
            "description": "Governor Newsom makes a statement.",
            "datePublished": "2024-07-02T12:00:00Z"
        }
        </script>
    </head>
    </html>
    """

    mock_crawler_instance = AsyncMock()
    async def mock_arun(url, config=None):
        if url == "https://test.com/politics/new-1":
            return mock_res_new
        elif url == "https://test.com/politics/old-2":
            return mock_res_old
        else:
            raise ValueError(f"Should not crawl ignored-3: {url}")
    mock_crawler_instance.arun.side_effect = mock_arun

    with patch("knowledge_map.core.discovery.DomainMapper") as MockMapperClass, \
         patch("knowledge_map.core.discovery.AsyncWebCrawler") as MockCrawlerClass:
        
        MockMapperClass.return_value = mock_mapper_instance
        MockCrawlerClass.return_value.__aenter__.return_value = mock_crawler_instance

        service = ArchiveDiscoveryService(db_path=db_path)
        pub = get_publication("testpub", db_path=db_path)

        scraped_urls = await service.run_archive_crawl(pub)

        # Only new-1 is successfully scraped. old-2 is fetched but triggers cutoff.
        assert scraped_urls == ["https://test.com/politics/new-1"]

        # Verify state is updated: current_index=2, cutoff_reached=True
        state = get_discovery_state("testpub", db_path=db_path)
        assert state["current_index"] == 2
        assert state["cutoff_reached"] is True


def test_cli_scrape_archive(tmp_path, monkeypatch):
    from unittest.mock import AsyncMock, patch
    from knowledge_map.adapters.sqlite_db import init_db, register_publication
    from knowledge_map.cli.main import main
    
    db_file = tmp_path / "test_cli_archive.db"
    db_path = str(db_file)
    init_db(db_path)
    
    register_publication(
        pub_id="testpub",
        name="Test Pub",
        base_url="https://test.com",
        db_path=db_path
    )
    
    monkeypatch.setenv("SQLITE_DB_PATH", db_path)
    
    with patch("knowledge_map.cli.main.ArchiveDiscoveryService") as MockServiceClass:
        mock_service_instance = AsyncMock()
        mock_service_instance.run_archive_crawl.return_value = ["https://test.com/story-1"]
        MockServiceClass.return_value = mock_service_instance
        
        try:
            main(["scrape-archive", "--publication-id", "testpub"])
        except SystemExit as e:
            assert e.code == 0
            
        mock_service_instance.run_archive_crawl.assert_called_once()


def test_cli_scrape_archive_missing_pub(tmp_path, monkeypatch):
    from knowledge_map.adapters.sqlite_db import init_db
    from knowledge_map.cli.main import main
    
    db_file = tmp_path / "test_cli_archive_missing.db"
    db_path = str(db_file)
    init_db(db_path)
    
    monkeypatch.setenv("SQLITE_DB_PATH", db_path)
    
    with pytest.raises(SystemExit) as exc_info:
        main(["scrape-archive", "--publication-id", "nonexistent"])
    assert exc_info.value.code == 1


@pytest.mark.anyio
async def test_archive_crawl_category_filtering(tmp_path, caplog):
    import logging
    from unittest.mock import AsyncMock, patch, MagicMock
    from knowledge_map.adapters.sqlite_db import (
        init_db,
        register_publication,
        get_publication,
        get_discovery_state
    )
    from knowledge_map.core.discovery import ArchiveDiscoveryService

    db_file = tmp_path / "test_archive_cat.db"
    db_path = str(db_file)
    init_db(db_path)

    register_publication(
        pub_id="testpub_cat",
        name="Test Category Pub",
        base_url="https://test.com",
        crawl_delay=0.01,
        max_concurrency=2,
        use_robots_txt=False,
        discovery_config_json='{"valid_categories": ["politics"]}',
        db_path=db_path
    )

    # 1. Mock DomainMapper scan return value
    mock_scan_results = [
        {"url": "https://test.com/politics/relevant-1"}, # matches
        {"url": "https://test.com/opinion/blocked-story"}, # mismatched segment
        {"url": "https://test.com/about-us"}            # flat structure (mismatch)
    ]
    mock_mapper_instance = AsyncMock()
    mock_mapper_instance.scan.return_value = mock_scan_results

    # 2. Mock CrawlResult for article pages
    mock_res = MagicMock()
    mock_res.success = True
    mock_res.html = """
    <html>
    <head>
        <script type="application/ld+json">
        {
            "headline": "Governor Newsom Signs Bill",
            "description": "Politics details.",
            "datePublished": "2026-07-02T12:00:00Z"
        }
        </script>
    </head>
    </html>
    """

    mock_crawler_instance = AsyncMock()
    mock_crawler_instance.arun.return_value = mock_res

    with patch("knowledge_map.core.discovery.DomainMapper") as MockMapperClass, \
         patch("knowledge_map.core.discovery.AsyncWebCrawler") as MockCrawlerClass, \
         patch("knowledge_map.core.relevance.check_relevance") as MockCheckRelevance, \
         caplog.at_level(logging.INFO):
        
        MockMapperClass.return_value = mock_mapper_instance
        MockCrawlerClass.return_value.__aenter__.return_value = mock_crawler_instance
        MockCheckRelevance.return_value = ("RELEVANT", {"headline": "A", "description": "B"})

        service = ArchiveDiscoveryService(db_path=db_path)
        pub = get_publication("testpub_cat", db_path=db_path)

        scraped_urls = await service.run_archive_crawl(pub)

        # Verify only matched URL was scraped
        assert scraped_urls == ["https://test.com/politics/relevant-1"]

        # Verify blocklist and category filtering excluded mismatched URLs from discovery state
        state = get_discovery_state("testpub_cat", db_path=db_path)
        assert state is not None
        assert state["urls"] == ["https://test.com/politics/relevant-1"]
        assert state["current_index"] == 1

        # Check logs for mismatch reason
        mismatch_logs = [r for r in caplog.records if getattr(r, "filter_reason", None) == "category_mismatch"]
        assert len(mismatch_logs) == 2
        mismatched_urls = {log.url for log in mismatch_logs}
        assert "https://test.com/opinion/blocked-story" in mismatched_urls
        assert "https://test.com/about-us" in mismatched_urls

        # Check stats log
        stats_log = [r for r in caplog.records if "Discovery stats for publication" in r.message]
        assert len(stats_log) == 1
        assert getattr(stats_log[0], "category_filtered", 0) == 2
        assert getattr(stats_log[0], "new_candidates_found", 0) == 1

