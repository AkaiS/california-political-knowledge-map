import json
import logging
import sqlite3
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from knowledge_map.adapters.sqlite_db import (
    init_db,
    register_publication,
    save_story,
    get_publication
)
from knowledge_map.utils.console import ConsoleNotifier
from knowledge_map.core.discovery import ListingPageDiscoveryService, ArchiveDiscoveryService
from knowledge_map.core.validation import ArticleValidatorService, run_recovery_check
from knowledge_map.core.healing import run_selector_healing_flow, ArticleSelectors, CriticFeedback

@pytest.fixture
def test_db(tmp_path):
    db_file = tmp_path / "test_observability.db"
    db_path = str(db_file)
    init_db(db_path)
    return db_path

def test_console_notifier_discovery_drift(capsys, caplog):
    """
    Test that notify_discovery_drift outputs to stderr with layout drift warning.
    """
    with caplog.at_level(logging.CRITICAL):
        ConsoleNotifier.notify_discovery_drift(
            publication_id="testpub",
            url="https://test.com/news"
        )
    assert len(caplog.records) == 1
    assert "DISCOVERY DRIFT WARNING" in caplog.records[0].message
    assert "Possible layout drift" in caplog.records[0].message


@pytest.mark.anyio
async def test_listing_discovery_stats_and_drift_warning(test_db, caplog, capsys):
    """
    Test discovery stats logging, discarded URL details logging, and drift warning banner.
    """
    # 1. Register publication
    register_publication(
        pub_id="testpub",
        name="Test Pub",
        base_url="https://test.com",
        crawl_delay=0.01,
        max_concurrency=2,
        use_robots_txt=True,
        discovery_config_json='{"listing_urls": ["https://test.com/news"], "url_path_blocklist": ["/ignore/"]}',
        db_path=test_db
    )

    # 2. Mock CrawlResult for listing page (successful, 200 OK, but returns 0 candidate links)
    mock_listing_result = MagicMock()
    mock_listing_result.success = True
    mock_listing_result.status_code = 200
    mock_listing_result.links = {
        "internal": [
            # Discarded URL due to blocklist
            {"href": "https://test.com/ignore/blocked-story", "text": "This is a valid long link text description"},
            # Discarded URL due to anchor heuristics
            {"href": "https://test.com/politics/short-anchor", "text": "Click"},
            # Discarded URL due to external domain
            {"href": "https://external.com/politics/other-story", "text": "This is a valid long link text description"}
        ]
    }

    mock_crawler_instance = AsyncMock()
    mock_crawler_instance.arun.return_value = mock_listing_result

    with patch("knowledge_map.core.discovery.AsyncWebCrawler") as MockCrawlerClass, \
         patch("knowledge_map.core.discovery.logfire", create=True) as mock_logfire, \
         caplog.at_level(logging.INFO):
        
        MockCrawlerClass.return_value.__aenter__.return_value = mock_crawler_instance
        
        service = ListingPageDiscoveryService(db_path=test_db)
        pub = get_publication("testpub", db_path=test_db)
        
        scraped_urls = await service.discover_and_scrape_for_publication(pub)
        
        # Verify 0 candidates found
        assert len(scraped_urls) == 0

        # Verify logfire span was called
        assert mock_logfire.span.call_count >= 1
        mock_logfire.span.assert_any_call("scrape_publication", publication_id="testpub", crawl_type="incremental")

        # Verify stats log
        stats_log_found = False
        discard_reasons = {}
        for record in caplog.records:
            if hasattr(record, "links_found") or getattr(record, "links_found", None) is not None:
                stats_log_found = True
                assert getattr(record, "links_found") == 3
                assert getattr(record, "blocklist_filtered") == 1
                assert getattr(record, "anchor_filtered") == 1
                assert getattr(record, "new_candidates_found") == 0
            
            if hasattr(record, "filter_reason") or getattr(record, "filter_reason", None) is not None:
                url = getattr(record, "url", None)
                reason = getattr(record, "filter_reason", None)
                if url and reason:
                    discard_reasons[url] = reason

        assert stats_log_found
        # Verify discarded reasons
        assert "https://test.com/ignore/blocked-story" in discard_reasons
        assert discard_reasons["https://test.com/ignore/blocked-story"] == "blocklist_hit"
        assert "https://test.com/politics/short-anchor" in discard_reasons
        assert discard_reasons["https://test.com/politics/short-anchor"] == "anchor_heuristic_dropped"
        assert "https://external.com/politics/other-story" in discard_reasons
        assert discard_reasons["https://external.com/politics/other-story"] == "external_domain"

        # Assert console drift warning is emitted
        drift_warnings = [r.message for r in caplog.records if r.levelname == "CRITICAL" and "DISCOVERY DRIFT WARNING" in r.message]
        assert len(drift_warnings) == 1
        assert "Possible layout drift" in drift_warnings[0]


@pytest.mark.anyio
async def test_relevance_outcomes_logging(test_db, caplog):
    """
    Verify that relevance checks emit structured log fields.
    """
    register_publication(
        pub_id="testpub",
        name="Test Pub",
        base_url="https://test.com",
        crawl_delay=0.01,
        max_concurrency=2,
        use_robots_txt=True,
        discovery_config_json='{"listing_urls": ["https://test.com/news"]}',
        db_path=test_db
    )

    mock_listing_result = MagicMock()
    mock_listing_result.success = True
    mock_listing_result.links = {
        "internal": [{"href": "https://test.com/politics/valid-story-1", "text": "This is a valid long link text description"}]
    }

    mock_article_result = MagicMock()
    mock_article_result.success = True
    mock_article_result.html = """
    <html>
    <head>
        <script type="application/ld+json">
        {
            "headline": "California Senate approves Newsom nominee",
            "description": "State Senate votes to confirm the governor's appointee."
        }
        </script>
    </head>
    <body>scraped raw content</body>
    </html>
    """

    mock_crawler_instance = AsyncMock()
    async def mock_arun(url, config=None):
        if url == "https://test.com/news":
            return mock_listing_result
        return mock_article_result
    mock_crawler_instance.arun.side_effect = mock_arun

    with patch("knowledge_map.core.discovery.AsyncWebCrawler") as MockCrawlerClass, \
         caplog.at_level(logging.INFO):
        
        MockCrawlerClass.return_value.__aenter__.return_value = mock_crawler_instance
        service = ListingPageDiscoveryService(db_path=test_db)
        pub = get_publication("testpub", db_path=test_db)
        await service.discover_and_scrape_for_publication(pub)
 
        # Check for cached logging
        cached_logged = False
        for record in caplog.records:
            if "Cached candidate article" in record.message:
                cached_logged = True
                assert "https://test.com/politics/valid-story-1" in record.message
                assert "PENDING" in record.message
        
        assert cached_logged

        # Check database side effects
        from knowledge_map.adapters.sqlite_db import get_cached_html
        cached = get_cached_html("https://test.com/politics/valid-story-1", db_path=test_db)
        assert cached is not None
        assert cached["validation"] == "PENDING"
        assert cached["relevance_status"] == "PENDING"

@pytest.mark.anyio
async def test_validation_outcomes_and_circuit_breaker(test_db, caplog, capsys):
    """
    Test validation outcomes logging, circuit breaker state changes logging,
    and circuit-breaker trip warning banner.
    """
    # Register publication
    register_publication(
        pub_id="testpub",
        name="Test Pub",
        base_url="https://test.com",
        crawl_delay=0.01,
        max_concurrency=2,
        db_path=test_db
    )
    # Register selector version
    conn = sqlite3.connect(test_db)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO publication_selectors (publication_id, selectors_json, earliest_success_date, latest_success_date)
        VALUES ('testpub', '{"title": "h1", "author": ".author", "date": ".date", "body": ".content"}', '2026-07-01T00:00:00Z', '2026-07-02T00:00:00Z')
    """)
    conn.commit()
    conn.close()

    validator = ArticleValidatorService(db_path=test_db)

    with patch("knowledge_map.core.validation.logfire", create=True) as mock_logfire, \
         patch("knowledge_map.core.healing.trigger_selector_healing_stub") as mock_healing, \
         caplog.at_level(logging.INFO):

        
        # We need to run validation 4 times to accumulate 12 points (>= 10 threshold).
        for i in range(4):
            url = f"https://test.com/politics/fail-{i}"
            from knowledge_map.adapters.sqlite_db import cache_scraped_html
            cache_scraped_html(
                url,
                "testpub",
                """
                <html>
                <head>
                    <script type="application/ld+json">
                    {
                        "headline": "Target Headline",
                        "datePublished": "2026-07-03T12:00:00Z",
                        "authors": ["John Doe"]
                    }
                    </script>
                </head>
                <body>No matching css elements</body>
                </html>
                """,
                validation="PENDING",
                db_path=test_db
            )
            await validator.validate_pending_articles()

        # Check validation outcomes logs
        validation_logged = False
        breaker_tripped_logged = False
        for record in caplog.records:
            if hasattr(record, "validation_status") or getattr(record, "validation_status", None) is not None:
                validation_logged = True
                assert getattr(record, "publication_id") == "testpub"
                assert getattr(record, "validation_status") == "VALIDATION_FAILED"
                assert getattr(record, "failure_points") == 3
                assert len(getattr(record, "errors")) > 0
            
            if (hasattr(record, "new_state") or getattr(record, "new_state", None) is not None) and getattr(record, "new_state") == "PAUSED":
                breaker_tripped_logged = True
                assert getattr(record, "publication_id") == "testpub"
                assert getattr(record, "previous_state") == "ACTIVE"
                assert getattr(record, "reason") == "failure_points_reached"
                assert getattr(record, "tripping_url") is not None

        assert validation_logged
        assert breaker_tripped_logged

        # Check warning banner output for circuit-breaker trip
        breaker_warnings = [r.message for r in caplog.records if r.levelname == "CRITICAL" and "CIRCUIT BREAKER TRIPPED" in r.message]
        assert len(breaker_warnings) == 1
        assert "paused" in breaker_warnings[0].lower()


@pytest.mark.anyio
async def test_selector_healing_span_wrapping(test_db):
    """
    Verify that the heal_selectors Logfire span is created and entered.
    """
    # Register publication
    register_publication(
        pub_id="testpub",
        name="Test Pub",
        base_url="https://test.com",
        crawl_delay=0.01,
        max_concurrency=2,
        db_path=test_db
    )
    # Cache html
    from knowledge_map.adapters.sqlite_db import cache_scraped_html
    cache_scraped_html(
        "https://test.com/politics/tripping",
        "testpub",
        "<html></html>",
        validation="VALIDATION_FAILED",
        db_path=test_db
    )

    # Mock Generator/Critic agent calls
    generator_agent = MagicMock()
    mock_gen_result = MagicMock()
    mock_gen_result.output = ArticleSelectors(title="h1", author="span", date="time", body="div")
    mock_gen_result.all_messages = MagicMock(return_value=[])
    async def mock_gen_run(*args, **kwargs):
        return mock_gen_result
    generator_agent.run = mock_gen_run

    critic_agent = MagicMock()
    mock_crit_result = MagicMock()
    mock_crit_result.output = CriticFeedback(is_valid=True, issues=[])
    async def mock_crit_run(*args, **kwargs):
        return mock_crit_result
    critic_agent.run = mock_crit_run

    with patch("knowledge_map.core.healing.logfire", create=True) as mock_logfire:
        await run_selector_healing_flow(
            publication_id="testpub",
            tripping_article_url="https://test.com/politics/tripping",
            db_path=test_db,
            generator_agent=generator_agent,
            critic_agent=critic_agent
        )

        mock_logfire.span.assert_called_once_with(
            "heal_selectors",
            publication_id="testpub",
            trigger_article_url="https://test.com/politics/tripping"
        )
