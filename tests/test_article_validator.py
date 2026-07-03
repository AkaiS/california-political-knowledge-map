import pytest
from knowledge_map.core.validation import (
    damerau_levenshtein_distance,
    edit_distance_ratio,
    normalize_author_string,
    parse_date_string,
    extract_json_ld_ground_truth,
    validate_extraction,
    ArticleValidatorService
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

def test_author_normalization():
    # Stripping filler words and normalization
    assert normalize_author_string("By Ana B. Ibarra") == ["ana b. ibarra"]
    assert normalize_author_string("Ana B. Ibarra Staff") == ["ana b. ibarra"]
    assert normalize_author_string("By John Doe and Jane Smith") == ["john doe", "jane smith"]
    # Comma separation
    assert normalize_author_string("John Doe, Jane Smith, and Bob Jones") == ["john doe", "jane smith", "bob jones"]
    # Empty author
    assert normalize_author_string("") == []

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
        "body_element": BeautifulSoup("<div>" + " ".join(["word"] * 100) + "</div>", "html.parser")
    }
    valid, errors, points = validate_extraction(extracted_good, ground_truth)
    assert valid is True
    assert len(errors) == 0
    assert points == 0

    # 2. Title mismatch failure (3 points)
    extracted_bad_title = extracted_good.copy()
    extracted_bad_title["title"] = "Sports Game Result"
    valid, errors, points = validate_extraction(extracted_bad_title, ground_truth)
    assert valid is False
    assert any("Title mismatch" in e for e in errors)
    assert points == 3

    # 3. Author mismatch failure (3 points)
    extracted_bad_author = extracted_good.copy()
    extracted_bad_author["author"] = "By Jane Smith"
    valid, errors, points = validate_extraction(extracted_bad_author, ground_truth)
    assert valid is False
    assert any("Author mismatch" in e for e in errors)
    assert points == 3

    # 4. Date mismatch failure (3 points)
    extracted_bad_date = extracted_good.copy()
    extracted_bad_date["date"] = "2026-07-04"
    valid, errors, points = validate_extraction(extracted_bad_date, ground_truth)
    assert valid is False
    assert any("Date mismatch" in e for e in errors)
    assert points == 3

    # 5. Word count ratio failure (3 points)
    extracted_bad_wc = extracted_good.copy()
    extracted_bad_wc["body"] = " ".join(["word"] * 50)  # 50 words instead of 100 (ratio 0.5)
    valid, errors, points = validate_extraction(extracted_bad_wc, ground_truth)
    assert valid is False
    assert any("word count ratio" in e for e in errors)
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
        "body_element": BeautifulSoup(body_html_good, "html.parser")
    }
    valid, errors, points = validate_extraction(extracted_fallback_good, ground_truth_no_wc)
    assert valid is True
    assert points == 0

    # 7. Fallback failure: Link Density too high (1 point)
    body_html_bad_links = "<div>" + "".join(f"<a href='/url'>{w}</a> " for w in ["the", "governor", "signed", "a", "bill"]) + "</div>"
    extracted_fallback_bad_links = extracted_fallback_good.copy()
    extracted_fallback_bad_links["body_element"] = BeautifulSoup(body_html_bad_links, "html.parser")
    valid, errors, points = validate_extraction(extracted_fallback_bad_links, ground_truth_no_wc)
    assert valid is False
    assert any("link density" in e for e in errors)
    assert points == 1

    # 8. Fallback failure: Stopwords too low (1 point)
    body_html_bad_stopwords = "<div>Newsom legislature Sacramento environment environment environment environment</div>"
    extracted_fallback_bad_stopwords = extracted_fallback_good.copy()
    extracted_fallback_bad_stopwords["body_element"] = BeautifulSoup(body_html_bad_stopwords, "html.parser")
    valid, errors, points = validate_extraction(extracted_fallback_bad_stopwords, ground_truth_no_wc)
    assert valid is False
    assert any("stopword ratio" in e for e in errors)
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
