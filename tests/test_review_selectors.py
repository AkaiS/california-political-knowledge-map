import pytest
import sqlite3
import json
import os
import datetime
from unittest.mock import patch, MagicMock
from datetime import timezone

from knowledge_map.adapters.sqlite_db import (
    init_db,
    register_publication,
    cache_scraped_html,
    get_publication,
    insert_selector_proposal,
    pause_publication_validation,
    get_selector_versions
)
from knowledge_map.core.selectors import add_selector_version
from knowledge_map.core.relevance_agent import RelevanceClassification
from knowledge_map.schemas.selectors import ArticleSelectors
from knowledge_map.core.validation import run_recovery_check, ArticleValidatorService
from knowledge_map.cli.main import main


def test_get_unresolved_proposals_and_resolve(tmp_path):
    db_path = str(tmp_path / "test_proposals.db")
    init_db(db_path)
    
    register_publication("pub1", "Pub 1", "https://pub1.com", db_path=db_path)
    
    # Insert a proposal
    insert_selector_proposal(
        publication_id="pub1",
        selectors_json='{"title": "h1"}',
        trigger_article_url="https://pub1.com/art1",
        status="PENDING_REVIEW",
        critic_iterations=1,
        db_path=db_path
    )
    
    from knowledge_map.adapters.sqlite_db import get_unresolved_proposals, resolve_selector_proposal
    
    unresolved = get_unresolved_proposals(db_path=db_path)
    assert len(unresolved) == 1
    assert unresolved[0]["publication_id"] == "pub1"
    assert unresolved[0]["status"] == "PENDING_REVIEW"
    
    # Resolve the proposal
    resolve_selector_proposal(unresolved[0]["id"], "APPROVED", db_path=db_path)
    
    unresolved_after = get_unresolved_proposals(db_path=db_path)
    assert len(unresolved_after) == 0


def test_recovery_check_success_path(tmp_path):
    db_path = str(tmp_path / "test_recovery_success.db")
    init_db(db_path)
    
    register_publication("testpub", "Test Pub", "https://testpub.com", db_path=db_path)
    
    html = """
    <html>
    <head>
        <script type="application/ld+json">
        {
            "@type": "NewsArticle",
            "headline": "Expected Title",
            "datePublished": "2026-07-02T18:11:34-07:00",
            "author": {"name": "John Doe"}
        }
        </script>
    </head>
    <body>
        <h1 class="entry-title">Expected Title</h1>
        <span class="author">By John Doe</span>
        <time datetime="2026-07-02T18:11:34-07:00"></time>
        <div class="entry-content">
            This is a very long article with lots of words and stopwords.
            The weather in California is beautiful today, Newsom says.
            This is a very long article with lots of words and stopwords.
            The weather in California is beautiful today, Newsom says.
        </div>
    </body>
    </html>
    """
    
    cache_scraped_html("https://testpub.com/recovery-art", "testpub", html, validation="PENDING", db_path=db_path)
    pause_publication_validation("testpub", "https://testpub.com/recovery-art", db_path=db_path)
    
    # Set points to 10
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE publications SET failure_points = 10 WHERE id = 'testpub'")
    conn.commit()
    conn.close()
    
    # Ensure it is paused and points are 10
    pub = get_publication("testpub", db_path=db_path)
    assert pub["validation_paused"] == 1
    assert pub["failure_points"] == 10
    
    # Add a selector version
    selectors = ArticleSelectors(
        title="h1.entry-title",
        author="span.author",
        date="time",
        body="div.entry-content"
    )
    now = datetime.datetime.now(timezone.utc)
    add_selector_version("testpub", selectors, now, now, db_path=db_path)
    
    # Run Recovery Check
    success = run_recovery_check("testpub", "https://testpub.com/recovery-art", db_path=db_path)
    assert success is True
    
    # Verify unpaused and points reset
    pub_after = get_publication("testpub", db_path=db_path)
    assert pub_after["validation_paused"] == 0
    assert pub_after["failure_points"] == 0
    assert pub_after["tripping_article_url"] is None
    
    # Verify status in cache is VALIDATED
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT validation FROM scraped_html_cache WHERE url = 'https://testpub.com/recovery-art'")
    row = cursor.fetchone()
    assert row["validation"] == "VALIDATED"
    conn.close()


def test_recovery_check_failure_path(tmp_path):
    db_path = str(tmp_path / "test_recovery_fail.db")
    init_db(db_path)
    
    register_publication("testpub", "Test Pub", "https://testpub.com", db_path=db_path)
    
    html = """
    <html>
    <head>
        <script type="application/ld+json">
        {
            "@type": "NewsArticle",
            "headline": "Expected Title",
            "datePublished": "2026-07-02T18:11:34-07:00",
            "author": {"name": "John Doe"}
        }
        </script>
    </head>
    <body>
        <h1 class="entry-title">Mismatched Title</h1>
        <span class="author">By John Doe</span>
        <time datetime="2026-07-02T18:11:34-07:00"></time>
        <div class="entry-content">
            This is a very long article with lots of words and stopwords.
        </div>
    </body>
    </html>
    """
    
    cache_scraped_html("https://testpub.com/recovery-art", "testpub", html, validation="PENDING", db_path=db_path)
    pause_publication_validation("testpub", "https://testpub.com/recovery-art", db_path=db_path)
    
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE publications SET failure_points = 10 WHERE id = 'testpub'")
    conn.commit()
    conn.close()
    
    # Add a selector version (which will extract "Mismatched Title" instead of "Expected Title" -> fail validation)
    selectors = ArticleSelectors(
        title="h1.entry-title",
        author="span.author",
        date="time",
        body="div.entry-content"
    )
    now = datetime.datetime.now(timezone.utc)
    add_selector_version("testpub", selectors, now, now, db_path=db_path)
    
    # Run Recovery Check
    success = run_recovery_check("testpub", "https://testpub.com/recovery-art", db_path=db_path)
    assert success is False
    
    # Verify remains paused and failure points unchanged (or rather not reset to 0)
    pub_after = get_publication("testpub", db_path=db_path)
    assert pub_after["validation_paused"] == 1
    assert pub_after["failure_points"] == 10
    
    # Verify status in cache is VALIDATION_FAILED
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT validation FROM scraped_html_cache WHERE url = 'https://testpub.com/recovery-art'")
    row = cursor.fetchone()
    assert row["validation"] == "VALIDATION_FAILED"
    conn.close()


@patch("builtins.input")
def test_cli_review_selectors_interactive_approve(mock_input, tmp_path):
    db_path = str(tmp_path / "test_cli_approve.db")
    init_db(db_path)
    
    register_publication("testpub", "Test Pub", "https://testpub.com", db_path=db_path)
    pause_publication_validation("testpub", "https://testpub.com/recovery-art", db_path=db_path)
    
    # Add to HTML cache
    html = """
    <html>
    <head>
        <script type="application/ld+json">
        {
            "@type": "NewsArticle",
            "headline": "Expected Title",
            "datePublished": "2026-07-02T18:11:34-07:00",
            "author": {"name": "John Doe"}
        }
        </script>
    </head>
    <body>
        <h1 class="entry-title">Expected Title</h1>
        <span class="author">By John Doe</span>
        <time datetime="2026-07-02T18:11:34-07:00"></time>
        <div class="entry-content">
            This is a very long article with lots of words and stopwords.
            The weather in California is beautiful today, Newsom says.
            This is a very long article with lots of words and stopwords.
            The weather in California is beautiful today, Newsom says.
        </div>
    </body>
    </html>
    """
    cache_scraped_html("https://testpub.com/recovery-art", "testpub", html, validation="VALIDATION_FAILED", db_path=db_path)
    
    # Insert proposal
    selectors_json = json.dumps({
        "title": "h1.entry-title",
        "author": "span.author",
        "date": "time",
        "body": "div.entry-content"
    })
    insert_selector_proposal(
        publication_id="testpub",
        selectors_json=selectors_json,
        trigger_article_url="https://testpub.com/recovery-art",
        status="PENDING_REVIEW",
        critic_iterations=1,
        db_path=db_path
    )
    
    mock_input.return_value = "y"
    
    with patch.dict(os.environ, {"SQLITE_DB_PATH": db_path}):
        with pytest.raises(SystemExit) as excinfo:
            main(["review-selectors"])
        assert excinfo.value.code == 0
        
    # Verify proposal is approved
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT status FROM selector_proposals WHERE publication_id = 'testpub'")
    row = cursor.fetchone()
    assert row["status"] == "APPROVED"
    conn.close()
    
    # Verify publication is active
    pub = get_publication("testpub", db_path=db_path)
    assert pub["validation_paused"] == 0
    assert pub["failure_points"] == 0


@patch("builtins.input")
def test_cli_review_selectors_interactive_reject(mock_input, tmp_path):
    db_path = str(tmp_path / "test_cli_reject.db")
    init_db(db_path)
    
    register_publication("testpub", "Test Pub", "https://testpub.com", db_path=db_path)
    pause_publication_validation("testpub", "https://testpub.com/recovery-art", db_path=db_path)
    
    html = "<html></html>"
    cache_scraped_html("https://testpub.com/recovery-art", "testpub", html, validation="VALIDATION_FAILED", db_path=db_path)
    
    # Insert proposal
    selectors_json = json.dumps({
        "title": "h1.entry-title",
        "author": "span.author",
        "date": "time",
        "body": "div.entry-content"
    })
    insert_selector_proposal(
        publication_id="testpub",
        selectors_json=selectors_json,
        trigger_article_url="https://testpub.com/recovery-art",
        status="PENDING_REVIEW",
        critic_iterations=1,
        db_path=db_path
    )
    
    mock_input.return_value = "n"
    
    with patch.dict(os.environ, {"SQLITE_DB_PATH": db_path}):
        with pytest.raises(SystemExit) as excinfo:
            main(["review-selectors"])
        assert excinfo.value.code == 0
        
    # Verify proposal is rejected
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT status FROM selector_proposals WHERE publication_id = 'testpub'")
    row = cursor.fetchone()
    assert row["status"] == "REJECTED"
    conn.close()
    
    # Verify publication remains paused
    pub = get_publication("testpub", db_path=db_path)
    assert pub["validation_paused"] == 1


def test_cli_review_selectors_manual_success(tmp_path):
    db_path = str(tmp_path / "test_cli_manual_success.db")
    init_db(db_path)
    
    register_publication("testpub", "Test Pub", "https://testpub.com", db_path=db_path)
    pause_publication_validation("testpub", "https://testpub.com/recovery-art", db_path=db_path)
    
    html = """
    <html>
    <head>
        <script type="application/ld+json">
        {
            "@type": "NewsArticle",
            "headline": "Expected Title",
            "datePublished": "2026-07-02T18:11:34-07:00",
            "author": {"name": "John Doe"}
        }
        </script>
    </head>
    <body>
        <h1 class="entry-title">Expected Title</h1>
        <span class="author">By John Doe</span>
        <time datetime="2026-07-02T18:11:34-07:00"></time>
        <div class="entry-content">
            This is a very long article with lots of words and stopwords.
            The weather in California is beautiful today, Newsom says.
            This is a very long article with lots of words and stopwords.
            The weather in California is beautiful today, Newsom says.
        </div>
    </body>
    </html>
    """
    cache_scraped_html("https://testpub.com/recovery-art", "testpub", html, validation="VALIDATION_FAILED", db_path=db_path)
    
    # Create manual json file
    manual_config = {
        "url": "https://testpub.com/recovery-art",
        "selectors": {
            "title": "h1.entry-title",
            "author": "span.author",
            "date": "time",
            "body": "div.entry-content"
        }
    }
    config_file = tmp_path / "selectors.json"
    with open(config_file, "w") as f:
        json.dump(manual_config, f)
        
    with patch.dict(os.environ, {"SQLITE_DB_PATH": db_path}):
        with pytest.raises(SystemExit) as excinfo:
            main(["review-selectors", "--manual", str(config_file)])
        assert excinfo.value.code == 0
        
    # Verify selector version registered
    versions = get_selector_versions("testpub", db_path=db_path)
    assert len(versions) == 1
    assert json.loads(versions[0]["selectors_json"])["title"] == "h1.entry-title"
    
    # Verify publication active
    pub = get_publication("testpub", db_path=db_path)
    assert pub["validation_paused"] == 0


def test_cli_review_selectors_manual_failure(tmp_path):
    db_path = str(tmp_path / "test_cli_manual_fail.db")
    init_db(db_path)
    
    register_publication("testpub", "Test Pub", "https://testpub.com", db_path=db_path)
    pause_publication_validation("testpub", "https://testpub.com/recovery-art", db_path=db_path)
    
    html = """
    <html>
    <head>
        <script type="application/ld+json">
        {
            "@type": "NewsArticle",
            "headline": "Expected Title",
            "datePublished": "2026-07-02T18:11:34-07:00",
            "author": {"name": "John Doe"}
        }
        </script>
    </head>
    <body>
        <h1 class="entry-title">Mismatched Title</h1>
        <span class="author">By John Doe</span>
        <time datetime="2026-07-02T18:11:34-07:00"></time>
        <div class="entry-content">
            This is a very long article with lots of words and stopwords.
        </div>
    </body>
    </html>
    """
    cache_scraped_html("https://testpub.com/recovery-art", "testpub", html, validation="VALIDATION_FAILED", db_path=db_path)
    
    # Create manual json file
    manual_config = {
        "url": "https://testpub.com/recovery-art",
        "selectors": {
            "title": "h1.entry-title",
            "author": "span.author",
            "date": "time",
            "body": "div.entry-content"
        }
    }
    config_file = tmp_path / "selectors.json"
    with open(config_file, "w") as f:
        json.dump(manual_config, f)
        
    with patch.dict(os.environ, {"SQLITE_DB_PATH": db_path}):
        with pytest.raises(SystemExit) as excinfo:
            main(["review-selectors", "--manual", str(config_file)])
        assert excinfo.value.code == 1
        
    # Verify publication remains paused
    pub = get_publication("testpub", db_path=db_path)
    assert pub["validation_paused"] == 1


@pytest.mark.anyio
async def test_post_recovery_prioritization(tmp_path):
    db_path = str(tmp_path / "test_prioritization.db")
    init_db(db_path)
    
    register_publication("testpub", "Test Pub", "https://testpub.com", db_path=db_path)
    
    # Ground truth HTML for testing
    html = """
    <html>
    <head>
        <script type="application/ld+json">
        {
            "@type": "NewsArticle",
            "headline": "Expected Title",
            "datePublished": "2026-07-02T18:11:34-07:00",
            "author": {"name": "John Doe"}
        }
        </script>
    </head>
    <body>
        <h1 class="entry-title">Expected Title</h1>
        <span class="author">By John Doe</span>
        <time datetime="2026-07-02T18:11:34-07:00"></time>
        <div class="entry-content">
            This is a very long article with lots of words and stopwords.
            The weather in California is beautiful today, Newsom says.
            This is a very long article with lots of words and stopwords.
            The weather in California is beautiful today, Newsom says.
        </div>
    </body>
    </html>
    """
    
    # 1. Cache a validation failed article (older date)
    cache_scraped_html("https://testpub.com/failed-art", "testpub", html, validation="VALIDATION_FAILED", db_path=db_path)
    
    # 2. Cache a pending article (newer date)
    cache_scraped_html("https://testpub.com/pending-art", "testpub", html, validation="PENDING", db_path=db_path)
    
    # Set mock validation dates/scraped dates to check ordering
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE scraped_html_cache SET scraped_at = '2026-07-01 12:00:00', validation_date = '2026-07-01 12:01:00' WHERE url = 'https://testpub.com/failed-art'")
    conn.execute("UPDATE scraped_html_cache SET scraped_at = '2026-07-02 12:00:00' WHERE url = 'https://testpub.com/pending-art'")
    conn.commit()
    conn.close()
    
    # Add selector version
    selectors = ArticleSelectors(
        title="h1.entry-title",
        author="span.author",
        date="time",
        body="div.entry-content"
    )
    now = datetime.datetime.now(timezone.utc)
    # The selector version created_at will be current_timestamp (now), which is newer than the validation_date of failed-art.
    add_selector_version("testpub", selectors, now, now, db_path=db_path)
    
    # Call validate_pending_articles
    validator = ArticleValidatorService(db_path=db_path)
    
    # We will patch validate_article to track the order in which URLs are validated.
    validated_urls = []
    original_validate = validator.validate_article
    
    def mock_validate(url, pub_id, raw_html, scraped_at):
        validated_urls.append(url)
        return original_validate(url, pub_id, raw_html, scraped_at)
        
    mock_relevance = RelevanceClassification(classification="RELEVANT")
    with patch(
        "knowledge_map.core.validation.get_metadata_embedding",
        return_value=[0.0] * 768,
    ) as mock_embedding, patch(
        "knowledge_map.core.validation.classify_article_with_llm",
        return_value=mock_relevance,
    ) as mock_llm, patch.object(
        validator, "validate_article", side_effect=mock_validate
    ):
        await validator.validate_pending_articles()

    assert mock_embedding.call_count == 2
    assert mock_llm.await_count == 2
        
    # Verify that failed-art (VALIDATION_FAILED) was validated first, followed by pending-art (PENDING)
    assert len(validated_urls) == 2
    assert validated_urls[0] == "https://testpub.com/failed-art"
    assert validated_urls[1] == "https://testpub.com/pending-art"
