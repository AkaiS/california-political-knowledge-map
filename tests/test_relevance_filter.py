import sqlite3
import pytest
from knowledge_map.adapters.sqlite_db import (
    init_db,
    register_publication,
    save_rejected_article,
    get_rejected_article,
    is_url_known
)

def test_save_and_get_rejected_article(tmp_path):
    db_file = tmp_path / "test_relevance.db"
    db_path = str(db_file)
    init_db(db_path)
    
    # Register publication
    register_publication(
        pub_id="testpub",
        name="Test Pub",
        base_url="https://test.com",
        db_path=db_path
    )
    
    url = "https://test.com/irrelevant-story"
    metadata = {"headline": "Pancakes are tasty", "description": "Here is a recipe"}
    
    # Initially not known
    assert not is_url_known(url, db_path=db_path)
    assert get_rejected_article(url, db_path=db_path) is None
    
    # Save as rejected
    save_rejected_article(
        url=url,
        publication_id="testpub",
        relevance_status="IRRELEVANT",
        metadata_json=metadata,
        db_path=db_path
    )
    
    # Now it should be known
    assert is_url_known(url, db_path=db_path)
    
    # Verify retrieved record
    record = get_rejected_article(url, db_path=db_path)
    assert record is not None
    assert record["url"] == url
    assert record["publication_id"] == "testpub"
    assert record["relevance_status"] == "IRRELEVANT"
    assert record["metadata_json"] == metadata


def test_extract_metadata():
    from knowledge_map.core.relevance import extract_metadata
    
    # 1. Simple JSON-LD
    html_json_ld = """
    <html>
    <head>
        <script type="application/ld+json">
        {
            "@context": "https://schema.org",
            "@type": "NewsArticle",
            "headline": "Governor Newsom Signs New Housing Bill",
            "description": "A landmark legislation targeting housing construction delays."
        }
        </script>
    </head>
    <body></body>
    </html>
    """
    meta = extract_metadata(html_json_ld)
    assert meta["headline"] == "Governor Newsom Signs New Housing Bill"
    assert meta["description"] == "A landmark legislation targeting housing construction delays."

    # 2. Nested JSON-LD in @graph
    html_nested_ld = """
    <html>
    <head>
        <script type="application/ld+json">
        {
            "@context": "https://schema.org",
            "@graph": [
                {
                    "@type": "WebPage",
                    "name": "Ignored name"
                },
                {
                    "@type": "NewsArticle",
                    "headline": "Legislature Approves Budget Deal",
                    "description": "Lawmakers agree on a $300 billion budget."
                }
            ]
        }
        </script>
    </head>
    </html>
    """
    meta = extract_metadata(html_nested_ld)
    assert meta["headline"] == "Legislature Approves Budget Deal"
    assert meta["description"] == "Lawmakers agree on a $300 billion budget."

    # 3. Fallback to meta tags
    html_meta_fallback = """
    <html>
    <head>
        <meta property="og:title" content="Meta Title Here" />
        <meta name="description" content="Meta description here." />
    </head>
    </html>
    """
    meta = extract_metadata(html_meta_fallback)
    assert meta["headline"] == "Meta Title Here"
    assert meta["description"] == "Meta description here."

    # 4. Mix of JSON-LD (headline) and meta tag (description)
    html_mix = """
    <html>
    <head>
        <script type="application/ld+json">
        {
            "headline": "JSON-LD Headline Only"
        }
        </script>
        <meta property="og:description" content="Meta description fallback" />
    </head>
    </html>
    """
    meta = extract_metadata(html_mix)
    assert meta["headline"] == "JSON-LD Headline Only"
    assert meta["description"] == "Meta description fallback"

    # 5. Title tag fallback
    html_title_only = """
    <html>
    <head>
        <title>Plain Page Title</title>
    </head>
    </html>
    """
    meta = extract_metadata(html_title_only)
    assert meta["headline"] == "Plain Page Title"
    assert meta["description"] is None


def test_classify_article():
    from knowledge_map.core.relevance import classify_article
    
    # 1. High-confidence political relevance
    assert classify_article("Governor Newsom signs budget bill", "California legislature agrees to a new budget.") == "RELEVANT"
    assert classify_article("Assembly candidate wins race", "Sacramento election update.") == "RELEVANT"
    assert classify_article("New prop on the ballot", "Voters to decide on Proposition 1A.") == "RELEVANT"

    # 2. Irrelevant: Negative keyword match
    # Even if political terms are present, negative keyword matches make it IRRELEVANT
    assert classify_article("Newsom plays sports at Sacramento school", "Governor Newsom discusses his favorite sports teams.") == "IRRELEVANT"
    assert classify_article("GOP leader shares favorite recipe", "A guide to the politician's baking recipe.") == "IRRELEVANT"

    # 3. Irrelevant: Zero political/secondary matches
    assert classify_article("Unrelated article headline", "A description about a new smartphone release in Tokyo.") == "IRRELEVANT"

    # 4. Inconclusive: Secondary local/state terms, no negatives, no high-confidence
    # "supervisors" would make it RELEVANT, so let's choose non-political local terms:
    assert classify_article("Local community center opens", "The county transit system discusses traffic in the regional area.") == "INCONCLUSIVE"

    # 5. Regex word boundaries verification
    # "gop" in "gopher" or "prop" in "properly" or "veto" in "velveto" should NOT match as keywords
    assert classify_article("Gopher infestation at properly maintained park", "A local community transit issue.") == "INCONCLUSIVE" # "local" and "transit" make it inconclusive
    assert classify_article("Gopher infestation at properly maintained park", "No keywords here at all.") == "IRRELEVANT" # "properly" has "prop", "gopher" has "gop", but no word boundaries. Should be IRRELEVANT.


@pytest.mark.anyio
async def test_listing_page_discovery_with_relevance_filter(tmp_path):
    from unittest.mock import AsyncMock, patch, MagicMock
    from knowledge_map.adapters.sqlite_db import (
        init_db,
        register_publication,
        get_cached_html,
        get_rejected_article,
        get_publication
    )
    from knowledge_map.core.discovery import ListingPageDiscoveryService

    db_file = tmp_path / "test_discovery_relevance.db"
    db_path = str(db_file)
    init_db(db_path)

    register_publication(
        pub_id="testpub",
        name="Test Pub",
        base_url="https://test.com",
        crawl_delay=0.01,
        max_concurrency=2,
        use_robots_txt=False,
        discovery_config_json='{"listing_urls": ["https://test.com/news"]}',
        db_path=db_path
    )

    # 1. Listing page contains 3 candidates
    mock_listing_result = MagicMock()
    mock_listing_result.success = True
    mock_listing_result.links = {
        "internal": [
            {"href": "https://test.com/politics/relevant-1", "text": "This is a valid long link text description for newsom"},
            {"href": "https://test.com/politics/irrelevant-2", "text": "This is a valid long link text description for sports"},
            {"href": "https://test.com/local/inconclusive-3", "text": "This is a valid long link text description for community"}
        ]
    }

    # 2. Article page contents:
    # Article 1: Relevant (Governor Newsom signs bill)
    mock_res_relevant = MagicMock()
    mock_res_relevant.success = True
    mock_res_relevant.html = """
    <html>
    <head>
        <script type="application/ld+json">
        {
            "headline": "Newsom Signs New Bill",
            "description": "Governor Newsom makes a statement."
        }
        </script>
    </head>
    </html>
    """

    # Article 2: Irrelevant (Baking sports recipe)
    mock_res_irrelevant = MagicMock()
    mock_res_irrelevant.success = True
    mock_res_irrelevant.html = """
    <html>
    <head>
        <script type="application/ld+json">
        {
            "headline": "Sports Baking Special",
            "description": "A recipe for sports fans."
        }
        </script>
    </head>
    </html>
    """

    # Article 3: Inconclusive (Local transit)
    mock_res_inconclusive = MagicMock()
    mock_res_inconclusive.success = True
    mock_res_inconclusive.html = """
    <html>
    <head>
        <script type="application/ld+json">
        {
            "headline": "Local transit update",
            "description": "A community discussion."
        }
        </script>
    </head>
    </html>
    """

    # 3. Patch AsyncWebCrawler
    mock_crawler_instance = AsyncMock()
    
    async def mock_arun(url, config=None):
        if url == "https://test.com/news":
            return mock_listing_result
        elif url == "https://test.com/politics/relevant-1":
            return mock_res_relevant
        elif url == "https://test.com/politics/irrelevant-2":
            return mock_res_irrelevant
        elif url == "https://test.com/local/inconclusive-3":
            return mock_res_inconclusive
        else:
            raise ValueError(f"Unexpected crawled URL: {url}")
            
    mock_crawler_instance.arun.side_effect = mock_arun

    with patch("knowledge_map.core.discovery.AsyncWebCrawler") as MockCrawlerClass:
        MockCrawlerClass.return_value.__aenter__.return_value = mock_crawler_instance
        
        service = ListingPageDiscoveryService(db_path=db_path)
        pub = get_publication("testpub", db_path=db_path)
        
        scraped_urls = await service.discover_and_scrape_for_publication(pub)

        # A. Verify returned scraped_urls contains all successfully crawled candidate URLs
        assert set(scraped_urls) == {
            "https://test.com/politics/relevant-1",
            "https://test.com/politics/irrelevant-2",
            "https://test.com/local/inconclusive-3"
        }

        # B. Verify relevant-1 is cached in scraped_html_cache as PENDING validation/relevance
        cached = get_cached_html("https://test.com/politics/relevant-1", db_path=db_path)
        assert cached is not None
        assert cached["validation"] == "PENDING"
        assert cached["relevance_status"] == "PENDING"
        assert "Newsom Signs New Bill" in cached["raw_html"]

        # C. Verify irrelevant-2 is cached in scraped_html_cache as PENDING validation/relevance
        cached_irrelevant = get_cached_html("https://test.com/politics/irrelevant-2", db_path=db_path)
        assert cached_irrelevant is not None
        assert cached_irrelevant["validation"] == "PENDING"
        assert cached_irrelevant["relevance_status"] == "PENDING"
        assert "Sports Baking Special" in cached_irrelevant["raw_html"]

        # D. Verify inconclusive-3 is cached in scraped_html_cache as PENDING validation/relevance
        cached_inconclusive = get_cached_html("https://test.com/local/inconclusive-3", db_path=db_path)
        assert cached_inconclusive is not None
        assert cached_inconclusive["validation"] == "PENDING"
        assert cached_inconclusive["relevance_status"] == "PENDING"
        assert "Local transit update" in cached_inconclusive["raw_html"]

        # Verify no rejected article is saved at this stage
        assert get_rejected_article("https://test.com/politics/irrelevant-2", db_path=db_path) is None
        assert get_rejected_article("https://test.com/local/inconclusive-3", db_path=db_path) is None

        # E. Second run: listing page contains only the previously rejected/inconclusive URLs
        # They should be skipped and NOT fetched by crawl4ai again (using is_url_known)
        mock_listing_result_2 = MagicMock()
        mock_listing_result_2.success = True
        mock_listing_result_2.links = {
            "internal": [
                {"href": "https://test.com/politics/irrelevant-2", "text": "This is a valid long link text description for sports"},
                {"href": "https://test.com/local/inconclusive-3", "text": "This is a valid long link text description for community"}
            ]
        }

        mock_crawler_instance.arun.reset_mock()
        
        async def mock_arun_2(url, config=None):
            if url == "https://test.com/news":
                return mock_listing_result_2
            else:
                raise ValueError(f"Should not fetch already rejected URL: {url}")
                
        mock_crawler_instance.arun.side_effect = mock_arun_2

        scraped_urls_2 = await service.discover_and_scrape_for_publication(pub)
        assert scraped_urls_2 == []
        
        # Verify arun was only called for the news listing page, not the individual articles
        assert mock_crawler_instance.arun.call_count == 1




