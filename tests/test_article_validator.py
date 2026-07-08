import pytest
from knowledge_map.core.validation import (
    damerau_levenshtein_distance,
    edit_distance_ratio,
    normalize_author_string,
    parse_date_string,
    extract_json_ld_ground_truth,
    validate_extraction,
    ArticleValidatorService,
    clean_and_normalize_text,
    count_words
)

def test_edit_distance_ratio():
    # Identical strings
    assert edit_distance_ratio("hello", "hello") == 1.0
    # Completely different
    assert edit_distance_ratio("hello", "world") == pytest.approx(0.2)
    # Empty strings
    assert edit_distance_ratio("", "") == 1.0
    assert edit_distance_ratio("hello", "") == 0.0
    # Case sensitive distance check
    assert edit_distance_ratio("hello", "Hello") == pytest.approx(0.8)

def test_clean_and_normalize_text():
    # HTML decoding
    assert clean_and_normalize_text("Hello &amp; World") == "Hello & World"
    assert clean_and_normalize_text("John&#39;s Project") == "John's Project"
    
    # Unicode whitespace normalization
    assert clean_and_normalize_text("Hello\xa0World") == "Hello World"
    assert clean_and_normalize_text("Hello\u2002World") == "Hello World"
    
    # Multiple whitespace collapse and stripping
    assert clean_and_normalize_text("  Hello   World  ") == "Hello World"
    assert clean_and_normalize_text("Hello\n\tWorld") == "Hello World"
    
    # Combined HTML + Unicode + whitespace
    assert clean_and_normalize_text(" &amp;  Hello\xa0\xa0World&#39;s   ") == "& Hello World's"

def test_author_normalization():
    # Stripping filler words and normalization
    assert normalize_author_string("By Ana B. Ibarra") == ["ana b. ibarra"]
    assert normalize_author_string("Ana B. Ibarra Staff") == ["ana b. ibarra"]
    assert normalize_author_string("By John Doe and Jane Smith") == ["john doe", "jane smith"]
    # Comma separation
    assert normalize_author_string("John Doe, Jane Smith, and Bob Jones") == ["john doe", "jane smith", "bob jones"]
    # Empty author
    assert normalize_author_string("") == []
    
    # HTML entities and Unicode whitespace in authors
    assert normalize_author_string("By Ana&amp;nbsp;B.&nbsp;Ibarra") == ["ana b. ibarra"]
    assert normalize_author_string("John&#39;s Doe\xa0Staff") == ["john's doe"]

def test_date_parsing_and_comparison():
    import datetime
    # ISO formats
    dt1 = parse_date_string("2026-07-02T23:50:00-07:00") # UTC: 2026-07-03T06:50:00+00:00
    dt2 = parse_date_string("2026-07-03T06:50:00Z")
    assert dt1 is not None
    assert dt2 is not None
    assert dt1.astimezone(datetime.timezone.utc).date() == dt2.astimezone(datetime.timezone.utc).date()

    # Plain text format
    dt3 = parse_date_string("June 18, 2026")
    assert dt3 is not None
    assert dt3.year == 2026
    assert dt3.month == 6
    assert dt3.day == 18

    # Format with weekday
    dt4 = parse_date_string("Thursday, June 18, 2026")
    assert dt4 is not None
    assert dt4.year == 2026
    assert dt4.month == 6
    assert dt4.day == 18

    # Invalid date
    assert parse_date_string("not-a-date") is None


def test_extract_json_ld_ground_truth():
    # 1. Standard NewsArticle JSON-LD
    html1 = """
    <html>
    <head>
        <script type="application/ld+json">
        {
            "@context": "https://schema.org",
            "@type": "NewsArticle",
            "headline": "Test Headline",
            "datePublished": "2026-07-02T18:11:34-07:00",
            "author": {
                "@type": "Person",
                "name": "Jane Smith"
            },
            "wordCount": 350
        }
        </script>
    </head>
    <body></body>
    </html>
    """
    gt1 = extract_json_ld_ground_truth(html1)
    assert gt1 is not None
    assert gt1["headline"] == "Test Headline"
    assert gt1["datePublished"] == "2026-07-02T18:11:34-07:00"
    assert gt1["authors"] == ["Jane Smith"]
    assert gt1["wordCount"] == 350

    # 2. Multi-author / list structure
    html2 = """
    <html>
    <head>
        <script type="application/ld+json">
        {
            "@type": "BlogPosting",
            "headline": "Another Post",
            "datePublished": "2026-07-03Z",
            "author": [
                {"name": "John Doe"},
                "Bob Jones"
            ]
        }
        </script>
    </head>
    </html>
    """
    gt2 = extract_json_ld_ground_truth(html2)
    assert gt2 is not None
    assert gt2["headline"] == "Another Post"
    assert gt2["authors"] == ["John Doe", "Bob Jones"]
    assert gt2["wordCount"] is None

    # 3. Missing JSON-LD entirely
    html3 = "<html><body>No JSON-LD here</body></html>"
    assert extract_json_ld_ground_truth(html3) is None


def test_validate_extraction():
    from bs4 import BeautifulSoup

    # 1. Success with wordCount
    ground_truth = {
        "headline": "Governor Newsom Signs Major Climate Bill",
        "datePublished": "2026-07-02T18:11:34-07:00",
        "authors": ["Ana B. Ibarra", "John Doe"],
        "wordCount": 100
    }
    extracted_good = {
        "title": "Governor Newsom Signs Major Climate Bill",
        "date": "2026-07-02T18:11:34-07:00",
        "author": "By Ana B. Ibarra and John Doe",
        "body": " ".join(["word"] * 100),
        "body_elements": [BeautifulSoup("<div>" + " ".join(["word"] * 100) + "</div>", "html.parser")]
    }
    valid, errors, points = validate_extraction(extracted_good, ground_truth)
    assert valid is True
    assert len(errors) == 0
    assert points == 0

    # 1b. Success with HTML entities and Unicode non-breaking spaces in title & author
    ground_truth_dirty = {
        "headline": "Governor Newsom Signs Major&nbsp;Climate Bill",
        "datePublished": "2026-07-02T18:11:34-07:00",
        "authors": ["Ana&nbsp;B.&nbsp;Ibarra", "John&#39;s Doe"],
        "wordCount": 100
    }
    extracted_dirty = {
        "title": "Governor Newsom Signs Major Climate Bill",
        "date": "2026-07-02T18:11:34-07:00",
        "author": "By Ana B. Ibarra and John's Doe",
        "body": " ".join(["word"] * 100),
        "body_elements": [BeautifulSoup("<div>" + " ".join(["word"] * 100) + "</div>", "html.parser")]
    }
    valid, errors, points = validate_extraction(extracted_dirty, ground_truth_dirty)
    assert valid is True
    assert len(errors) == 0
    assert points == 0

    # 2. Title mismatch failure (3 points)
    extracted_bad_title = extracted_good.copy()
    extracted_bad_title["title"] = "Sports Game Result"
    valid, errors, points = validate_extraction(extracted_bad_title, ground_truth)
    assert valid is False
    assert "title" in errors
    assert points == 3

    # 3. Author mismatch failure (3 points)
    extracted_bad_author = extracted_good.copy()
    extracted_bad_author["author"] = "By Jane Smith"
    valid, errors, points = validate_extraction(extracted_bad_author, ground_truth)
    assert valid is False
    assert "author" in errors
    assert points == 3

    # 4. Date mismatch failure (3 points)
    extracted_bad_date = extracted_good.copy()
    extracted_bad_date["date"] = "2026-07-04"
    valid, errors, points = validate_extraction(extracted_bad_date, ground_truth)
    assert valid is False
    assert "date" in errors
    assert points == 3

    # 5. Word count ratio failure (3 points)
    extracted_bad_wc = extracted_good.copy()
    extracted_bad_wc["body"] = " ".join(["word"] * 50)  # 50 words instead of 100 (ratio 0.5)
    valid, errors, points = validate_extraction(extracted_bad_wc, ground_truth)
    assert valid is False
    assert "body" in errors
    assert points == 3

    # 6. Fallback sanity check success (no wordCount in JSON-LD)
    ground_truth_no_wc = ground_truth.copy()
    ground_truth_no_wc["wordCount"] = None

    # Body has low link density and high stopwords
    body_html_good = "<div>The governor signed a bill today. It was a very good day for the environment and we are happy.</div>"
    extracted_fallback_good = {
        "title": "Governor Newsom Signs Major Climate Bill",
        "date": "2026-07-02T18:11:34-07:00",
        "author": "By Ana B. Ibarra and John Doe",
        "body": "The governor signed a bill today. It was a very good day for the environment and we are happy.",
        "body_elements": [BeautifulSoup(body_html_good, "html.parser")]
    }
    valid, errors, points = validate_extraction(extracted_fallback_good, ground_truth_no_wc)
    assert valid is True
    assert points == 0

    # 7. Fallback failure: Link Density too high (1 point)
    body_html_bad_links = "<div>" + "".join(f"<a href='/url'>{w}</a> " for w in ["the", "governor", "signed", "a", "bill"]) + "</div>"
    extracted_fallback_bad_links = extracted_fallback_good.copy()
    extracted_fallback_bad_links["body_elements"] = [BeautifulSoup(body_html_bad_links, "html.parser")]
    valid, errors, points = validate_extraction(extracted_fallback_bad_links, ground_truth_no_wc)
    assert valid is False
    assert "body" in errors
    assert points == 1

    # 8. Fallback failure: Stopwords too low (1 point)
    body_html_bad_stopwords = "<div>Newsom legislature Sacramento environment environment environment environment</div>"
    extracted_fallback_bad_stopwords = extracted_fallback_good.copy()
    extracted_fallback_bad_stopwords["body_elements"] = [BeautifulSoup(body_html_bad_stopwords, "html.parser")]
    valid, errors, points = validate_extraction(extracted_fallback_bad_stopwords, ground_truth_no_wc)
    assert valid is False
    assert "body" in errors
    assert points == 1


def test_article_validator_service(tmp_path):
    from datetime import datetime, timezone, timedelta
    from knowledge_map.adapters.sqlite_db import (
        init_db,
        register_publication,
        cache_scraped_html,
        get_cached_html,
        get_all_stories
    )
    from knowledge_map.schemas.selectors import ArticleSelectors
    from knowledge_map.core.selectors import add_selector_version, get_selector_versions_by_proximity
    
    db_file = tmp_path / "test_validator_service.db"
    db_path = str(db_file)
    init_db(db_path)
    
    # 1. Register publication
    register_publication("calmatters", "CalMatters", "https://calmatters.org", db_path=db_path)
    
    # 2. Add selector version
    selectors = ArticleSelectors(
        title="h1.entry-title",
        author="span.author",
        date="time",
        body="div.entry-content"
    )
    # Success window base: today
    now = datetime.now(timezone.utc)
    version_id = add_selector_version(
        publication_id="calmatters",
        selectors=selectors,
        earliest_success_date=now - timedelta(days=1),
        latest_success_date=now + timedelta(days=1),
        db_path=db_path
    )
    
    # 3. Cache PENDING HTML blocks
    # Good article:
    html_good = """
    <html>
    <head>
        <script type="application/ld+json">
        {
            "@type": "NewsArticle",
            "headline": "A Beautiful Climate Bill",
            "datePublished": "2026-07-02T18:11:34-07:00",
            "author": {"name": "Ana B. Ibarra"}
        }
        </script>
    </head>
    <body>
        <h1 class="entry-title">A Beautiful Climate Bill</h1>
        <span class="author">By Ana B. Ibarra</span>
        <time datetime="2026-07-02T18:11:34-07:00"></time>
        <div class="entry-content">
            This is a very good article. The weather in California is beautiful and Newsom signed a bill.
        </div>
    </body>
    </html>
    """
    
    # Bad article (fails validation):
    html_bad = """
    <html>
    <head>
        <script type="application/ld+json">
        {
            "@type": "NewsArticle",
            "headline": "A Beautiful Climate Bill",
            "datePublished": "2026-07-02T18:11:34-07:00",
            "author": {"name": "Ana B. Ibarra"}
        }
        </script>
    </head>
    <body>
        <h1 class="entry-title">Completely Different Title</h1>
        <span class="author">By Jane Smith</span>
        <time datetime="2026-07-05T00:00:00Z"></time>
        <div class="entry-content">
            Short body text.
        </div>
    </body>
    </html>
    """
    
    # Unvalidatable article (missing JSON-LD):
    html_unval = """
    <html>
    <body>
        <h1 class="entry-title">A Beautiful Climate Bill</h1>
        <span class="author">By Ana B. Ibarra</span>
        <time datetime="2026-07-02T18:11:34-07:00"></time>
        <div class="entry-content">
            No JSON-LD exists on this page.
        </div>
    </body>
    </html>
    """
    
    url_good = "https://calmatters.org/politics/good"
    url_bad = "https://calmatters.org/politics/bad"
    url_unval = "https://calmatters.org/politics/unval"
    
    cache_scraped_html(url_good, "calmatters", html_good, validation="PENDING", db_path=db_path)
    cache_scraped_html(url_bad, "calmatters", html_bad, validation="PENDING", db_path=db_path)
    cache_scraped_html(url_unval, "calmatters", html_unval, validation="PENDING", db_path=db_path)
    
    # 4. Run validator service
    service = ArticleValidatorService(db_path=db_path)
    results = service.validate_pending_articles()
    
    # 5. Assert outcomes
    # Validate cache statuses
    cached_good = get_cached_html(url_good, db_path=db_path)
    assert cached_good["validation"] == "VALIDATED"
    assert cached_good["validation_date"] is not None
    
    cached_bad = get_cached_html(url_bad, db_path=db_path)
    assert cached_bad["validation"] == "VALIDATION_FAILED"
    
    cached_unval = get_cached_html(url_unval, db_path=db_path)
    assert cached_unval["validation"] == "UNVALIDATABLE"
    
    # Validate story insertion
    stories = get_all_stories(db_path=db_path)
    assert len(stories) == 1
    assert stories[0]["url"] == url_good
    assert stories[0]["title"] == "A Beautiful Climate Bill"
    assert stories[0]["author"] == "ana b. ibarra" # normalized author string
    
    # Validate selector success window widening
    versions = get_selector_versions_by_proximity("calmatters", now, db_path=db_path)
    v = next(x for x in versions if x.id == version_id)
    assert v.earliest_success_date <= now


def test_circuit_breaker_points_accumulation(tmp_path):
    from datetime import datetime, timezone, timedelta
    from knowledge_map.adapters.sqlite_db import (
        init_db,
        register_publication,
        cache_scraped_html,
        get_publication
    )
    from knowledge_map.schemas.selectors import ArticleSelectors
    from knowledge_map.core.selectors import add_selector_version
    
    db_file = tmp_path / "test_cb_accumulation.db"
    db_path = str(db_file)
    init_db(db_path)
    
    register_publication("testpub", "Test Pub", "https://testpub.com", db_path=db_path)
    
    # 2. Add selector version
    selectors = ArticleSelectors(
        title="h1.entry-title",
        author="span.author",
        date="time",
        body="div.entry-content"
    )
    now = datetime.now(timezone.utc)
    add_selector_version(
        publication_id="testpub",
        selectors=selectors,
        earliest_success_date=now - timedelta(days=1),
        latest_success_date=now + timedelta(days=1),
        db_path=db_path
    )
    
    # Validation failed article (Ground truth mismatch: title mismatch) -> should add 3 points
    html_gt_mismatch = """
    <html>
    <head>
        <script type="application/ld+json">
        {
            "@type": "NewsArticle",
            "headline": "Expected Title",
            "datePublished": "2026-07-02T18:11:34-07:00",
            "author": {"name": "Ana B. Ibarra"}
        }
        </script>
    </head>
    <body>
        <h1 class="entry-title">Mismatched Title</h1>
        <span class="author">By Ana B. Ibarra</span>
        <time datetime="2026-07-02T18:11:34-07:00"></time>
        <div class="entry-content">
            This is a very good article. The weather in California is beautiful and Newsom signed a bill.
        </div>
    </body>
    </html>
    """
    
    # Validation failed article (Fallback failure: wordCount is absent and link density fails) -> should add 1 point
    html_fallback_fail = """
    <html>
    <head>
        <script type="application/ld+json">
        {
            "@type": "NewsArticle",
            "headline": "Expected Title",
            "datePublished": "2026-07-02T18:11:34-07:00",
            "author": {"name": "Ana B. Ibarra"}
        }
        </script>
    </head>
    <body>
        <h1 class="entry-title">Expected Title</h1>
        <span class="author">By Ana B. Ibarra</span>
        <time datetime="2026-07-02T18:11:34-07:00"></time>
        <div class="entry-content">
            <a href="/1">link1</a> <a href="/2">link2</a> <a href="/3">link3</a> <a href="/4">link4</a>
        </div>
    </body>
    </html>
    """
    
    # Unvalidatable article -> should add 0 points
    html_unval = """
    <html>
    <body>
        <h1 class="entry-title">Expected Title</h1>
    </body>
    </html>
    """
    
    service = ArticleValidatorService(db_path=db_path)
    
    # First, validate the GT mismatch article
    cache_scraped_html("https://testpub.com/gt-mismatch", "testpub", html_gt_mismatch, validation="PENDING", db_path=db_path)
    service.validate_pending_articles()
    pub = get_publication("testpub", db_path=db_path)
    assert pub["failure_points"] == 3
    
    # Next, validate the fallback fail article (should add 1 point -> total 4)
    cache_scraped_html("https://testpub.com/fallback-fail", "testpub", html_fallback_fail, validation="PENDING", db_path=db_path)
    service.validate_pending_articles()
    pub = get_publication("testpub", db_path=db_path)
    assert pub["failure_points"] == 4
    
    # Next, validate the unvalidatable article (should add 0 points -> total 4)
    cache_scraped_html("https://testpub.com/unval", "testpub", html_unval, validation="PENDING", db_path=db_path)
    service.validate_pending_articles()
    pub = get_publication("testpub", db_path=db_path)
    assert pub["failure_points"] == 4


def test_circuit_breaker_reset_on_success(tmp_path):
    from datetime import datetime, timezone, timedelta
    from knowledge_map.adapters.sqlite_db import (
        init_db,
        register_publication,
        cache_scraped_html,
        get_publication
    )
    from knowledge_map.schemas.selectors import ArticleSelectors
    from knowledge_map.core.selectors import add_selector_version
    
    db_file = tmp_path / "test_cb_reset.db"
    db_path = str(db_file)
    init_db(db_path)
    
    register_publication("testpub", "Test Pub", "https://testpub.com", db_path=db_path)
    
    selectors = ArticleSelectors(
        title="h1.entry-title",
        author="span.author",
        date="time",
        body="div.entry-content"
    )
    now = datetime.now(timezone.utc)
    add_selector_version(
        publication_id="testpub",
        selectors=selectors,
        earliest_success_date=now - timedelta(days=1),
        latest_success_date=now + timedelta(days=1),
        db_path=db_path
    )
    
    # 1. Failed article (adds 3 points)
    html_fail = """
    <html>
    <head>
        <script type="application/ld+json">
        {
            "@type": "NewsArticle",
            "headline": "Expected Title",
            "datePublished": "2026-07-02T18:11:34-07:00",
            "author": {"name": "Ana B. Ibarra"}
        }
        </script>
    </head>
    <body>
        <h1 class="entry-title">Mismatched Title</h1>
        <span class="author">By Ana B. Ibarra</span>
        <time datetime="2026-07-02T18:11:34-07:00"></time>
        <div class="entry-content">This is a body text.</div>
    </body>
    </html>
    """
    
    # 2. Successful article
    html_success = """
    <html>
    <head>
        <script type="application/ld+json">
        {
            "@type": "NewsArticle",
            "headline": "Expected Title",
            "datePublished": "2026-07-02T18:11:34-07:00",
            "author": {"name": "Ana B. Ibarra"}
        }
        </script>
    </head>
    <body>
        <h1 class="entry-title">Expected Title</h1>
        <span class="author">By Ana B. Ibarra</span>
        <time datetime="2026-07-02T18:11:34-07:00"></time>
        <div class="entry-content">This is a body text. Stopword stopword stopword stopword stopword.</div>
    </body>
    </html>
    """
    
    service = ArticleValidatorService(db_path=db_path)
    
    # Fail first
    cache_scraped_html("https://testpub.com/fail", "testpub", html_fail, validation="PENDING", db_path=db_path)
    service.validate_pending_articles()
    pub = get_publication("testpub", db_path=db_path)
    assert pub["failure_points"] == 3
    
    # Succeed next -> should reset points to 0
    cache_scraped_html("https://testpub.com/success", "testpub", html_success, validation="PENDING", db_path=db_path)
    service.validate_pending_articles()
    pub = get_publication("testpub", db_path=db_path)
    assert pub["failure_points"] == 0


def test_circuit_breaker_trips(tmp_path):
    from unittest.mock import patch
    from datetime import datetime, timezone, timedelta
    from knowledge_map.adapters.sqlite_db import (
        init_db,
        register_publication,
        cache_scraped_html,
        get_publication
    )
    from knowledge_map.schemas.selectors import ArticleSelectors
    from knowledge_map.core.selectors import add_selector_version
    
    db_file = tmp_path / "test_cb_trip.db"
    db_path = str(db_file)
    init_db(db_path)
    
    register_publication("testpub", "Test Pub", "https://testpub.com", db_path=db_path)
    
    selectors = ArticleSelectors(
        title="h1.entry-title",
        author="span.author",
        date="time",
        body="div.entry-content"
    )
    now = datetime.now(timezone.utc)
    add_selector_version(
        publication_id="testpub",
        selectors=selectors,
        earliest_success_date=now - timedelta(days=1),
        latest_success_date=now + timedelta(days=1),
        db_path=db_path
    )
    
    # 4 articles that will fail ground-truth validation (each adds 3 points)
    html_fail = """
    <html>
    <head>
        <script type="application/ld+json">
        {
            "@type": "NewsArticle",
            "headline": "Expected Title",
            "datePublished": "2026-07-02T18:11:34-07:00",
            "author": {"name": "Ana B. Ibarra"}
        }
        </script>
    </head>
    <body>
        <h1 class="entry-title">Mismatched Title</h1>
        <span class="author">By Ana B. Ibarra</span>
        <time datetime="2026-07-02T18:11:34-07:00"></time>
        <div class="entry-content">This is a body text.</div>
    </body>
    </html>
    """
    
    urls = [
        "https://testpub.com/fail1",
        "https://testpub.com/fail2",
        "https://testpub.com/fail3",
        "https://testpub.com/fail4"
    ]
    
    service = ArticleValidatorService(db_path=db_path)
    
    # Cache all 4 articles
    for url in urls:
        cache_scraped_html(url, "testpub", html_fail, validation="PENDING", db_path=db_path)
        
    with patch("knowledge_map.core.healing.trigger_selector_healing_stub") as mock_healing:
        service.validate_pending_articles()
        
        # Verify that the circuit breaker tripped
        pub = get_publication("testpub", db_path=db_path)
        assert pub["validation_paused"] is True
        # The 4th article is the one that tripped it (the last one validated)
        # Because ORDER BY scraped_at ASC, and we cached them sequentially.
        assert pub["tripping_article_url"] == "https://testpub.com/fail4"
        assert pub["failure_points"] == 12
        
        # Verify healing seam was triggered exactly once with correct arguments
        mock_healing.assert_called_once_with("testpub", "https://testpub.com/fail4", db_path=db_path)


def test_circuit_breaker_skips_paused_publications(tmp_path):
    from datetime import datetime, timezone, timedelta
    from knowledge_map.adapters.sqlite_db import (
        init_db,
        register_publication,
        cache_scraped_html,
        get_cached_html,
        pause_publication_validation
    )
    from knowledge_map.schemas.selectors import ArticleSelectors
    from knowledge_map.core.selectors import add_selector_version
    
    db_file = tmp_path / "test_cb_skip.db"
    db_path = str(db_file)
    init_db(db_path)
    
    # Register testpub1 (active) and testpub2 (paused)
    register_publication("testpub1", "Test Pub 1", "https://testpub1.com", db_path=db_path)
    register_publication("testpub2", "Test Pub 2", "https://testpub2.com", db_path=db_path)
    
    pause_publication_validation("testpub2", "https://testpub2.com/tripped", db_path=db_path)
    
    selectors = ArticleSelectors(
        title="h1.entry-title",
        author="span.author",
        date="time",
        body="div.entry-content"
    )
    now = datetime.now(timezone.utc)
    for pub_id in ["testpub1", "testpub2"]:
        add_selector_version(
            publication_id=pub_id,
            selectors=selectors,
            earliest_success_date=now - timedelta(days=1),
            latest_success_date=now + timedelta(days=1),
            db_path=db_path
        )
        
    html_good = """
    <html>
    <head>
        <script type="application/ld+json">
        {
            "@type": "NewsArticle",
            "headline": "Expected Title",
            "datePublished": "2026-07-02T18:11:34-07:00",
            "author": {"name": "Ana B. Ibarra"}
        }
        </script>
    </head>
    <body>
        <h1 class="entry-title">Expected Title</h1>
        <span class="author">By Ana B. Ibarra</span>
        <time datetime="2026-07-02T18:11:34-07:00"></time>
        <div class="entry-content">This is a body text. Stopword stopword stopword stopword stopword.</div>
    </body>
    </html>
    """
    
    url_active = "https://testpub1.com/good"
    url_paused = "https://testpub2.com/good"
    
    cache_scraped_html(url_active, "testpub1", html_good, validation="PENDING", db_path=db_path)
    cache_scraped_html(url_paused, "testpub2", html_good, validation="PENDING", db_path=db_path)
    
    service = ArticleValidatorService(db_path=db_path)
    service.validate_pending_articles()
    
    # Active publication's article should be validated
    cached_active = get_cached_html(url_active, db_path=db_path)
    assert cached_active["validation"] == "VALIDATED"
    
    # Paused publication's article should still be PENDING
    cached_paused = get_cached_html(url_paused, db_path=db_path)
    assert cached_paused["validation"] == "PENDING"


def test_circuit_breaker_success_while_paused_does_not_reset_or_unpause(tmp_path):
    from datetime import datetime, timezone, timedelta
    from unittest.mock import patch
    from knowledge_map.adapters.sqlite_db import (
        init_db,
        register_publication,
        cache_scraped_html,
        get_publication
    )
    from knowledge_map.schemas.selectors import ArticleSelectors
    from knowledge_map.core.selectors import add_selector_version
    
    db_file = tmp_path / "test_cb_paused_success.db"
    db_path = str(db_file)
    init_db(db_path)
    
    register_publication("testpub", "Test Pub", "https://testpub.com", db_path=db_path)
    
    selectors = ArticleSelectors(
        title="h1.entry-title",
        author="span.author",
        date="time",
        body="div.entry-content"
    )
    now = datetime.now(timezone.utc)
    add_selector_version(
        publication_id="testpub",
        selectors=selectors,
        earliest_success_date=now - timedelta(days=1),
        latest_success_date=now + timedelta(days=1),
        db_path=db_path
    )
    
    # 4 articles that will fail ground-truth validation (each adds 3 points to trip it)
    html_fail = """
    <html>
    <head>
        <script type="application/ld+json">
        {
            "@type": "NewsArticle",
            "headline": "Expected Title",
            "datePublished": "2026-07-02T18:11:34-07:00",
            "author": {"name": "Ana B. Ibarra"}
        }
        </script>
    </head>
    <body>
        <h1 class="entry-title">Mismatched Title</h1>
        <span class="author">By Ana B. Ibarra</span>
        <time datetime="2026-07-02T18:11:34-07:00"></time>
        <div class="entry-content">This is a body text.</div>
    </body>
    </html>
    """
    
    # Successful article
    html_success = """
    <html>
    <head>
        <script type="application/ld+json">
        {
            "@type": "NewsArticle",
            "headline": "Expected Title",
            "datePublished": "2026-07-02T18:11:34-07:00",
            "author": {"name": "Ana B. Ibarra"}
        }
        </script>
    </head>
    <body>
        <h1 class="entry-title">Expected Title</h1>
        <span class="author">By Ana B. Ibarra</span>
        <time datetime="2026-07-02T18:11:34-07:00"></time>
        <div class="entry-content">This is a body text. Stopword stopword stopword stopword stopword.</div>
    </body>
    </html>
    """
    
    service = ArticleValidatorService(db_path=db_path)
    
    # Trip it first
    for i in range(4):
        cache_scraped_html(f"https://testpub.com/fail{i}", "testpub", html_fail, validation="PENDING", db_path=db_path)
    with patch("knowledge_map.core.healing.trigger_selector_healing_stub") as mock_healing:
        service.validate_pending_articles()
    
    pub = get_publication("testpub", db_path=db_path)
    assert pub["validation_paused"] is True
    assert pub["failure_points"] == 12
    
    # Now execute a successful validation manually
    res = service.validate_article("https://testpub.com/success", "testpub", html_success, now)
    assert res["status"] == "VALIDATED"
    
    # Verify that the publication remains paused and points are not reset
    pub = get_publication("testpub", db_path=db_path)
    assert pub["validation_paused"] is True
    assert pub["failure_points"] == 12


def test_extract_json_ld_author_resolution():
    # Test JSON-LD with @graph containing referenced authors
    html = """
    <html>
    <head>
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@graph": [
            {
              "@type": "NewsArticle",
              "headline": "Private prison company sells two of California’s immigrant detention centers",
              "datePublished": "2026-07-06T19:43:19+00:00",
              "author": [
                {"@id": "https://calmatters.org/#/schema/person/e0c38bba12c1c115fd22ef4e5db7124d"},
                {"@id": "https://calmatters.org/#/schema/person/1d0455c44130b374153aa2e8312e9c44"}
              ]
            },
            {
              "@type": "Person",
              "@id": "https://calmatters.org/#/schema/person/e0c38bba12c1c115fd22ef4e5db7124d",
              "name": "Wendy Fry"
            },
            {
              "@type": "Person",
              "@id": "https://calmatters.org/#/schema/person/1d0455c44130b374153aa2e8312e9c44",
              "name": "Nigel Duara"
            }
          ]
        }
        </script>
    </head>
    </html>
    """
    gt = extract_json_ld_ground_truth(html)
    assert gt is not None
    assert gt["headline"] == "Private prison company sells two of California’s immigrant detention centers"
    assert gt["authors"] == ["Wendy Fry", "Nigel Duara"]

    # Test cross-script resolution
    html_cross_script = """
    <html>
    <head>
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "NewsArticle",
          "headline": "Cross Script Test",
          "datePublished": "2026-07-06T19:43:19+00:00",
          "author": {
            "@id": "https://calmatters.org/#/schema/person/resolved-later"
          }
        }
        </script>
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Person",
          "@id": "https://calmatters.org/#/schema/person/resolved-later",
          "name": "Jane Doe"
        }
        </script>
    </head>
    </html>
    """
    gt_cross = extract_json_ld_ground_truth(html_cross_script)
    assert gt_cross is not None
    assert gt_cross["headline"] == "Cross Script Test"
    assert gt_cross["authors"] == ["Jane Doe"]


def test_extract_json_ld_author_resolution_priority():
    # Test that a smaller node with type "Person" and "name" overrides a larger node without them
    html = """
    <html>
    <head>
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@graph": [
            {
              "@type": "NewsArticle",
              "headline": "Test Priority Resolution",
              "datePublished": "2026-07-06T19:43:19+00:00",
              "author": {
                "@id": "https://calmatters.org/#/schema/person/priority-test"
              }
            },
            {
              "@id": "https://calmatters.org/#/schema/person/priority-test",
              "description": "A very long description that is indeed very long and makes this node have many keys, but lacks name.",
              "url": "https://calmatters.org/author/priority-test/",
              "jobTitle": "Investigative Reporter",
              "sameAs": ["https://x.com/priority-test", "https://facebook.com/priority-test"]
            },
            {
              "@type": "Person",
              "@id": "https://calmatters.org/#/schema/person/priority-test",
              "name": "Wendy Fry"
            }
          ]
        }
        </script>
    </head>
    </html>
    """
    gt = extract_json_ld_ground_truth(html)
    assert gt is not None
    assert gt["authors"] == ["Wendy Fry"]


def test_count_words():
    assert count_words("") == 0
    assert count_words(None) == 0
    assert count_words("Hello world") == 2
    assert count_words("  Hello   world \n test  ") == 3


def test_fallback_individual_elements():
    from bs4 import BeautifulSoup
    from knowledge_map.core.validation import validate_extraction
    
    # Base ground truth without wordCount to trigger fallback validation
    ground_truth_no_wc = {
        "headline": "Test Individual Elements",
        "datePublished": "2026-07-02T18:11:34-07:00",
        "authors": ["John Doe"],
        "wordCount": None
    }
    
    # 1. Test case where one element is good and another element has high link density (bad)
    # The good element: 20 words, no links.
    # The bad element: 10 words, all inside links (1.0 link density).
    good_html = "<div>The legislative assembly met today in Sacramento to discuss new rules. It was a very productive session for all.</div>"
    bad_link_html = "<div>" + "".join(f"<a href='/url'>{w}</a> " for w in ["visit", "us", "now", "click", "here", "read", "more", "online", "source", "link"]) + "</div>"
    
    extracted_diluted_links = {
        "title": "Test Individual Elements",
        "date": "2026-07-02T18:11:34-07:00",
        "author": "John Doe",
        "body": "The legislative assembly met today in Sacramento to discuss new rules. It was a very productive session for all. visit us now click here read more online source link",
        "body_elements": [
            BeautifulSoup(good_html, "html.parser"),
            BeautifulSoup(bad_link_html, "html.parser")
        ]
    }
    
    # Under individual validation, this MUST fail because the second element has link density >= 0.15
    valid, errors, points = validate_extraction(extracted_diluted_links, ground_truth_no_wc)
    assert valid is False
    assert "body" in errors
    assert "Fallback link density failure" in errors["body"]
    assert points == 1
    
    # 2. Test case where one element is good and another element has low stopword ratio (bad)
    # The good element: 20 words, lots of stopwords (e.g. "the", "in", "to", "it", "was", "for").
    # The bad element: 10 words, zero stopwords (only keywords).
    bad_stopword_html = "<div>Newsom legislature Sacramento environment environment environment environment bills laws budget</div>"
    
    extracted_diluted_stopwords = {
        "title": "Test Individual Elements",
        "date": "2026-07-02T18:11:34-07:00",
        "author": "John Doe",
        "body": "The legislative assembly met today in Sacramento to discuss new rules. Newsom legislature Sacramento environment environment environment environment bills laws budget",
        "body_elements": [
            BeautifulSoup(good_html, "html.parser"),
            BeautifulSoup(bad_stopword_html, "html.parser")
        ]
    }
    
    # Under individual validation, this MUST fail because the second element has stopword ratio <= 0.25
    valid, errors, points = validate_extraction(extracted_diluted_stopwords, ground_truth_no_wc)
    assert valid is False
    assert "body" in errors
    assert "Fallback stopword ratio failure" in errors["body"]
    assert points == 1

    # 3. Test case with empty elements (which should be skipped without causing failure)
    empty_html = "<div>   </div>"
    extracted_with_empty = {
        "title": "Test Individual Elements",
        "date": "2026-07-02T18:11:34-07:00",
        "author": "John Doe",
        "body": "The legislative assembly met today in Sacramento to discuss new rules. It was a very productive session for all.",
        "body_elements": [
            BeautifulSoup(good_html, "html.parser"),
            BeautifulSoup(empty_html, "html.parser")
        ]
    }
    valid, errors, points = validate_extraction(extracted_with_empty, ground_truth_no_wc)
    assert valid is True
    assert points == 0


def test_extract_fields_multiple_authors():
    from knowledge_map.schemas.selectors import ArticleSelectors
    from knowledge_map.core.validation import extract_fields

    html = """
    <html>
    <body>
        <div class="authors">
            <span class="author-name">Jane Doe</span>
            <span class="author-name">John Smith</span>
        </div>
    </body>
    </html>
    """
    selectors = ArticleSelectors(
        title="",
        author="span.author-name",
        date="",
        body=""
    )
    extracted = extract_fields(html, selectors)
    assert extracted["author"] == "Jane Doe, John Smith"


def test_extract_json_ld_multiple_authors_edge_cases():
    from knowledge_map.core.validation import extract_json_ld_ground_truth

    # Test nested lists, lists of names inside object, and typical array of person objects
    html = """
    <html>
    <head>
        <script type="application/ld+json">
        {
            "@context": "https://schema.org",
            "@type": "NewsArticle",
            "headline": "Multiple Authors Test",
            "datePublished": "2026-07-02T18:11:34-07:00",
            "author": [
                {
                    "@type": "Person",
                    "name": ["Ana B. Ibarra", "John Doe"]
                },
                {
                    "@type": "Person",
                    "name": "Jane Smith"
                }
            ]
        }
        </script>
    </head>
    </html>
    """
    gt = extract_json_ld_ground_truth(html)
    assert gt is not None
    assert gt["authors"] == ["Ana B. Ibarra", "John Doe", "Jane Smith"]


def test_extract_fields_illegitimate_parent_filtering():
    from knowledge_map.core.validation import extract_fields
    from knowledge_map.schemas.selectors import ArticleSelectors

    html = """
    <html>
    <body>
        <div class="main-content">
            <h1 class="entry-title">Actual Headline</h1>
            <span class="author">Real Author</span>
            <time class="pubdate" datetime="2026-07-07">July 7, 2026</time>
            <div class="entry-content">
                <p>Real paragraph 1.</p>
                <p>Real paragraph 2.</p>
            </div>
        </div>
        <aside class="sidebar">
            <h1 class="entry-title">Sidebar Title</h1>
            <span class="author">Sidebar Author</span>
            <div class="entry-content">
                <p>Sidebar paragraph.</p>
            </div>
        </aside>
        <footer class="footer">
            <span class="author">Footer Author</span>
            <p>Footer paragraph.</p>
        </footer>
    </body>
    </html>
    """

    selectors = ArticleSelectors(
        title="h1.entry-title",
        author="span.author",
        date="time.pubdate",
        body="p"
    )

    extracted = extract_fields(html, selectors)

    # 1. Title: should ignore the one in <aside>
    assert extracted["title"] == "Actual Headline"

    # 2. Author: should ignore the ones in <aside> and <footer>
    assert extracted["author"] == "Real Author"

    # 3. Body: should only get the two paragraphs from the main-content
    assert "Real paragraph 1." in extracted["body"]
    assert "Real paragraph 2." in extracted["body"]
    assert "Sidebar paragraph." not in extracted["body"]
    assert "Footer paragraph." not in extracted["body"]


def test_extract_fields_promotional_filtering():
    from knowledge_map.core.validation import extract_fields
    from knowledge_map.schemas.selectors import ArticleSelectors

    html = """
    <html>
    <body>
        <div class="main-content">
            <h1 class="entry-title">Actual Headline</h1>
            <div class="entry-content">
                <p>Real paragraph 1.</p>
                <p>READ NEXT: Governor signs new education bill</p>
                <p>Real paragraph 2.</p>
                <p>[Read Next] Some other title</p>
                <p>*More News* from the legislature</p>
                <p>Most Popular: The primary debates</p>
                <p>Learn More about the campaign</p>
            </div>
        </div>
    </body>
    </html>
    """

    selectors = ArticleSelectors(
        title="h1.entry-title",
        author="",
        date="",
        body="p"
    )

    extracted = extract_fields(html, selectors)

    # Check that actual body paragraphs are present
    assert "Real paragraph 1." in extracted["body"]
    assert "Real paragraph 2." in extracted["body"]

    # Check that promotional/recommendation links are filtered out
    assert "READ NEXT" not in extracted["body"]
    assert "Some other title" not in extracted["body"]
    assert "More News" not in extracted["body"]
    assert "Most Popular" not in extracted["body"]
    assert "Learn More" not in extracted["body"]

    # Check number of elements in body_elements matches expected (which is 2)
    assert len(extracted["body_elements"]) == 2
