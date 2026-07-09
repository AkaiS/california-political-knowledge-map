import pytest
from knowledge_map.utils.urls import clean_and_resolve_url

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
