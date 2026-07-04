import pytest
import json
from unittest.mock import AsyncMock, patch, MagicMock
from knowledge_map.utils.scraper import fetch_last_5_politics_stories

# We will test clean_and_resolve_url if exported, or verify it indirectly.
# Let's import it if we place it in scraper.py, or define it in scraper.py.
# To make it testable, we'll design scraper.py to expose it.
from knowledge_map.utils.scraper import clean_and_resolve_url

def test_clean_and_resolve_url():
    base_url = "https://calmatters.org/politics/some-story/"
    
    # 1. Absolute URLs
    assert clean_and_resolve_url(base_url, "https://example.com/target") == "https://example.com/target"
    assert clean_and_resolve_url(base_url, "http://example.com/target?query=1") == "http://example.com/target?query=1"
    
    # 2. Relative URLs
    assert clean_and_resolve_url(base_url, "/politics/news") == "https://calmatters.org/politics/news"
    assert clean_and_resolve_url(base_url, "relative-page") == "https://calmatters.org/politics/some-story/relative-page"
    
    # 3. Fragment removal
    assert clean_and_resolve_url(base_url, "https://example.com/target#heading-1") == "https://example.com/target"
    assert clean_and_resolve_url(base_url, "/politics/news#comment-section") == "https://calmatters.org/politics/news"
    
    # 4. Invalid schemes/non-HTTP
    assert clean_and_resolve_url(base_url, "mailto:info@calmatters.org") is None
    assert clean_and_resolve_url(base_url, "tel:1234567") is None
    assert clean_and_resolve_url(base_url, "#only-hash") is None
    assert clean_and_resolve_url(base_url, "javascript:void(0)") is None


def test_clean_and_resolve_url_tracking_parameters():
    base_url = "https://calmatters.org/politics/some-story/"
    assert clean_and_resolve_url(base_url, "https://example.com/target?utm_source=feed&utm_medium=email") == "https://example.com/target"
    assert clean_and_resolve_url(base_url, "https://example.com/target?fbclid=123&gclid=456") == "https://example.com/target"
    assert clean_and_resolve_url(base_url, "https://example.com/target?ref=789&amp=abc") == "https://example.com/target"
    
    # Verify preservation of routing parameters
    assert clean_and_resolve_url(base_url, "https://example.com/target?id=123") == "https://example.com/target?id=123"
    assert clean_and_resolve_url(base_url, "https://example.com/target?p=politics&v=2&article_id=xyz") == "https://example.com/target?p=politics&v=2&article_id=xyz"
    
    # Verify fragment/hash components are stripped
    assert clean_and_resolve_url(base_url, "https://example.com/target?id=123#comments") == "https://example.com/target?id=123"
    assert clean_and_resolve_url(base_url, "https://example.com/target?utm_source=feed&id=123#ref") == "https://example.com/target?id=123"
    
    # Verify case-insensitive tracking parameter names
    assert clean_and_resolve_url(base_url, "https://example.com/target?UTM_SOURCE=feed&FbClId=123&AMP=true") == "https://example.com/target"
    
    # Verify mixed routing and tracking parameters (from acceptance criteria)
    assert clean_and_resolve_url(base_url, "https://test.com/path?utm_source=feed&id=456#anchor") == "https://test.com/path?id=456"


@pytest.mark.anyio
async def test_fetch_last_5_politics_stories_success():
    # Mocking the listing crawler result
    mock_listing_result = MagicMock()
    mock_listing_result.success = True
    
    # Return 2 stories in the listing
    stories_json = [
        {
            "title": "Story Title 1",
            "url": "https://calmatters.org/politics/story-1",
            "category": "Politics",
            "meta": "By Jane Doe • June 26, 2026",
            "summary": "Summary 1"
        },
        {
            "title": "Story Title 2",
            "url": "https://calmatters.org/politics/story-2",
            "category": "Politics",
            "meta": "By John Smith • June 25, 2026",
            "summary": "Summary 2"
        }
    ]
    mock_listing_result.extracted_content = json.dumps(stories_json)

    # Mocking the article body crawler results
    mock_article_result_1 = MagicMock()
    mock_article_result_1.success = True
    mock_article_result_1.markdown = "This is body 1 content."
    mock_article_result_1.cleaned_html = """
    <div class="entry-content">
        <p>This is article 1. Read more at <a href="/politics/story-2">Story 2</a>.</p>
        <p>Also check out <a href="https://calmatters.org/politics/story-1">Story 1 itself</a>.</p>
        <p>Invalid link <a href="mailto:contact@calmatters.org">Email Us</a>.</p>
    </div>
    """

    mock_article_result_2 = MagicMock()
    mock_article_result_2.success = True
    mock_article_result_2.markdown = "This is body 2 content."
    mock_article_result_2.cleaned_html = """
    <div class="entry-content">
        <p>This is article 2. References <a href="https://example.com/external-info#ref">External Info</a>.</p>
        <p>Duplicate reference <a href="https://example.com/external-info">External Info Duplicate</a>.</p>
    </div>
    """

    # Mock AsyncWebCrawler instance
    mock_crawler_instance = AsyncMock()
    mock_crawler_instance.arun.return_value = mock_listing_result
    mock_crawler_instance.arun_many.return_value = [mock_article_result_1, mock_article_result_2]

    # Patch AsyncWebCrawler context manager
    with patch("knowledge_map.utils.scraper.AsyncWebCrawler") as MockCrawlerClass:
        # Mocking the async context manager protocol:
        # async with AsyncWebCrawler() as crawler:
        MockCrawlerClass.return_value.__aenter__.return_value = mock_crawler_instance
        
        stories = await fetch_last_5_politics_stories()
        
        # Verify arun was called with calmatters politics URL
        mock_crawler_instance.arun.assert_called_once()
        assert "https://calmatters.org/category/politics/" in mock_crawler_instance.arun.call_args[1]["url"]
        
        # Verify arun_many was called with correct story URLs
        mock_crawler_instance.arun_many.assert_called_once()
        called_urls = mock_crawler_instance.arun_many.call_args[1]["urls"]
        assert called_urls == ["https://calmatters.org/politics/story-1", "https://calmatters.org/politics/story-2"]
        
        # Assert extracted data structure and link extraction
        assert len(stories) == 2
        
        # Story 1 checks
        story1 = stories[0]
        assert story1["title"] == "Story Title 1"
        assert story1["url"] == "https://calmatters.org/politics/story-1"
        assert story1["content"] == "This is body 1 content."
        assert "links" in story1
        # Links should have:
        # 1. '/politics/story-2' resolved to 'https://calmatters.org/politics/story-2'
        # Note: 'https://calmatters.org/politics/story-1' is a self-link and should be excluded.
        # Email mailto link should be excluded
        assert len(story1["links"]) == 1
        assert story1["links"][0] == {"text": "Story 2", "url": "https://calmatters.org/politics/story-2"}

        # Story 2 checks
        story2 = stories[1]
        assert story2["title"] == "Story Title 2"
        assert story2["content"] == "This is body 2 content."
        assert "links" in story2
        # Links should have:
        # 1. 'https://example.com/external-info' (fragment stripped from '#ref')
        # Duplicate url should be filtered out
        assert len(story2["links"]) == 1
        assert story2["links"][0] == {"text": "External Info", "url": "https://example.com/external-info"}
