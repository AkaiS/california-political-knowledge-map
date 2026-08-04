import os
import sqlite3
import pytest
from knowledge_map.adapters.sqlite_db import init_db, save_story, get_all_stories

def test_get_all_stories(tmp_path):
    db_file = tmp_path / "test_stories.db"
    db_path = str(db_file)
    
    # Initialize test DB
    init_db(db_path)
    
    # Setup test stories
    story_with_content = {
        "title": "Story with content",
        "url": "http://example.com/1",
        "category": "Politics",
        "author": "Author A",
        "published_date": "2026-06-24",
        "summary": "Summary A",
        "content": "This is actual news content."
    }
    
    story_without_content = {
        "title": "Story without content",
        "url": "http://example.com/2",
        "category": "Politics",
        "author": "Author B",
        "published_date": "2026-06-24",
        "summary": "Summary B",
        "content": ""  # empty content
    }
    
    story_none_content = {
        "title": "Story with None content",
        "url": "http://example.com/3",
        "category": "Politics",
        "author": "Author C",
        "published_date": "2026-06-24",
        "summary": "Summary C",
        "content": None  # None content
    }
    
    save_story(story_with_content, db_path=db_path)
    save_story(story_without_content, db_path=db_path)
    save_story(story_none_content, db_path=db_path)
    
    # Retrieve stories and assert
    stories = get_all_stories(db_path=db_path)
    
    assert len(stories) == 1
    assert stories[0]["url"] == "http://example.com/1"
    assert stories[0]["content"] == "This is actual news content."


def test_story_links_table_schema(tmp_path):
    db_file = tmp_path / "test_stories.db"
    db_path = str(db_file)
    init_db(db_path)
    
    # Query sqlite_master to verify the table exists
    import sqlite3
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='story_links'")
        table_exists = cursor.fetchone()
        assert table_exists is not None
        
        # Verify columns
        cursor.execute("PRAGMA table_info(story_links)")
        columns = {col[1]: col[2] for col in cursor.fetchall()}
        assert "id" in columns
        assert "story_id" in columns
        assert "text" in columns
        assert "url" in columns
        assert "scraped" in columns
        assert "created_at" in columns
    finally:
        conn.close()


def test_save_story_with_links(tmp_path):
    from knowledge_map.adapters.sqlite_db import get_story_links
    db_file = tmp_path / "test_stories.db"
    db_path = str(db_file)
    init_db(db_path)
    
    story = {
        "title": "Story with links",
        "url": "http://example.com/story-1",
        "category": "Politics",
        "author": "Author A",
        "published_date": "2026-06-24",
        "summary": "Summary",
        "content": "Content here.",
        "links": [
            {"text": "Link Text 1", "url": "http://example.com/target-1"},
            {"text": "Link Text 2", "url": "http://example.com/target-2"}
        ]
    }
    
    assert save_story(story, db_path=db_path) is True
    
    # Fetch the saved story
    stories = get_all_stories(db_path=db_path)
    assert len(stories) == 1
    story_id = stories[0]["id"]
    
    # Fetch links
    links = get_story_links(story_id, db_path=db_path)
    assert len(links) == 2
    assert links[0]["story_id"] == story_id
    assert links[0]["text"] == "Link Text 1"
    assert links[0]["url"] == "http://example.com/target-1"
    assert links[0]["scraped"] == 0
    
    assert links[1]["text"] == "Link Text 2"
    assert links[1]["url"] == "http://example.com/target-2"


def test_save_story_links_uniqueness(tmp_path):
    from knowledge_map.adapters.sqlite_db import get_story_links
    db_file = tmp_path / "test_stories.db"
    db_path = str(db_file)
    init_db(db_path)
    
    story = {
        "title": "Story with duplicate links",
        "url": "http://example.com/story-1",
        "category": "Politics",
        "content": "Content here.",
        "links": [
            {"text": "Link Text 1", "url": "http://example.com/target-1"},
            {"text": "Duplicate Link Text 1", "url": "http://example.com/target-1"},  # same URL
            {"text": "Link Text 2", "url": "http://example.com/target-2"}
        ]
    }
    
    save_story(story, db_path=db_path)
    stories = get_all_stories(db_path=db_path)
    story_id = stories[0]["id"]
    
    links = get_story_links(story_id, db_path=db_path)
    # The duplicate link with the same url for the same story should be ignored
    assert len(links) == 2
    assert {link["url"] for link in links} == {"http://example.com/target-1", "http://example.com/target-2"}


def test_sqlite_status_column(tmp_path):
    from knowledge_map.adapters.sqlite_db import SQLiteStatusTracker
    db_file = tmp_path / "test_stories.db"
    db_path = str(db_file)
    init_db(db_path)
    
    # Save a story
    story = {
        "title": "Test Status Default",
        "url": "http://example.com/status-test",
        "category": "Politics",
        "content": "Some content."
    }
    save_story(story, db_path=db_path)
    
    # Check default status is 'UNPROCESSED'
    import sqlite3
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT status FROM stories WHERE url = ?", (story["url"],))
        row = cursor.fetchone()
        assert row is not None
        assert row[0] == "UNPROCESSED"
    finally:
        conn.close()


def test_story_status_rejects_irrelevant(tmp_path):
    db_path = str(tmp_path / "test_story_status_constraint.db")
    init_db(db_path)

    conn = sqlite3.connect(db_path)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO stories (title, url, content, status) VALUES (?, ?, ?, ?)",
                ("Irrelevant Story", "http://example.com/irrelevant-story", "Content", "IRRELEVANT"),
            )
    finally:
        conn.close()


def test_sqlite_status_migration(tmp_path):
    # 1. Create a DB with the old schema (no status column)
    db_file = tmp_path / "test_migration.db"
    db_path = str(db_file)
    
    import sqlite3
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE stories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                url TEXT NOT NULL UNIQUE,
                category TEXT,
                author TEXT,
                published_date TEXT,
                summary TEXT,
                content TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Insert a story before migration
        cursor.execute("""
            INSERT INTO stories (title, url, content)
            VALUES (?, ?, ?)
        """, ("Pre-migration Story", "http://example.com/pre", "Content"))
        conn.commit()
    finally:
        conn.close()
        
    # 2. Run init_db which should migrate it
    init_db(db_path)
    
    # 3. Check if status column exists and default values are set for existing rows
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT status FROM stories WHERE url = ?", ("http://example.com/pre",))
        row = cursor.fetchone()
        assert row is not None
        assert row[0] == "UNPROCESSED"
    finally:
        conn.close()


def test_update_story_status(tmp_path):
    from knowledge_map.adapters.sqlite_db import update_story_status
    db_file = tmp_path / "test_update_status.db"
    db_path = str(db_file)
    init_db(db_path)
    
    story = {
        "title": "Test Story Status",
        "url": "http://example.com/update-test",
        "content": "Content"
    }
    save_story(story, db_path=db_path)
    
    # Update status to PROCESSING
    update_story_status(story["url"], "PROCESSING", db_path=db_path)
    
    import sqlite3
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT status FROM stories WHERE url = ?", (story["url"],))
        assert cursor.fetchone()[0] == "PROCESSING"
        
        # Update to COMPLETED
        update_story_status(story["url"], "COMPLETED", db_path=db_path)
        cursor.execute("SELECT status FROM stories WHERE url = ?", (story["url"],))
        assert cursor.fetchone()[0] == "COMPLETED"
    finally:
        conn.close()


def test_sqlite_status_tracker(tmp_path):
    from knowledge_map.adapters.sqlite_db import SQLiteStatusTracker
    db_file = tmp_path / "test_tracker.db"
    db_path = str(db_file)
    init_db(db_path)
    
    story = {
        "title": "Test Tracker Story",
        "url": "http://example.com/tracker-test",
        "content": "Content"
    }
    save_story(story, db_path=db_path)
    
    tracker = SQLiteStatusTracker(db_path=db_path)
    tracker.update_status(story["url"], "PROCESSING")
    
    import sqlite3
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT status FROM stories WHERE url = ?", (story["url"],))
        assert cursor.fetchone()[0] == "PROCESSING"
    finally:
        conn.close()


def test_sqlite_relevance_schema_migration(tmp_path):
    db_file = tmp_path / "test_relevance_migration.db"
    db_path = str(db_file)
    init_db(db_path)

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("DROP TABLE scraped_html_cache")
        cursor.execute("""
            CREATE TABLE scraped_html_cache (
                url TEXT PRIMARY KEY,
                publication_id TEXT NOT NULL,
                raw_html TEXT,
                validation TEXT CHECK(validation IN ('PENDING', 'VALIDATED', 'VALIDATION_FAILED', 'UNVALIDATABLE', 'PENDING_RELEVANCE')),
                validation_date DATETIME,
                scraped_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                headline TEXT,
                description TEXT,
                embedding BLOB,
                relevance_status TEXT CHECK(relevance_status IN ('RELEVANT', 'IRRELEVANT', 'INCONCLUSIVE', 'PENDING')) DEFAULT 'RELEVANT',
                relevance_label_source TEXT CHECK(relevance_label_source IN ('KEYWORD', 'LLM', 'HUMAN', 'MODEL')) DEFAULT 'KEYWORD',
                raw_metadata_json TEXT,
                FOREIGN KEY(publication_id) REFERENCES publications(id) ON DELETE CASCADE
            )
        """)
        cursor.execute("INSERT OR IGNORE INTO publications (id, name, base_url) VALUES ('pub1', 'Pub 1', 'http://example.com')")
        for index in range(22):
            cursor.execute("""
                INSERT INTO scraped_html_cache (url, publication_id, raw_html, headline)
                VALUES (?, 'pub1', ?, ?)
            """, (
                f"http://example.com/unassessed-{index}",
                "<html>cached</html>" if index == 0 else None,
                "Previously extracted headline" if index == 1 else None,
            ))
        classified_rows = [
            ("keyword", "RELEVANT", "KEYWORD", '{"headline": "California Legislature"}'),
            ("model", "IRRELEVANT", "MODEL", None),
            ("llm", "INCONCLUSIVE", "LLM", None),
            ("human", "RELEVANT", "HUMAN", None),
        ]
        cursor.executemany("""
            INSERT INTO scraped_html_cache (
                url, publication_id, validation, relevance_status,
                relevance_label_source, raw_metadata_json
            ) VALUES (?, 'pub1', 'PENDING_RELEVANCE', ?, ?, ?)
        """, [
            (f"http://example.com/{name}", status, source, metadata)
            for name, status, source, metadata in classified_rows
        ])
        conn.commit()
    finally:
        conn.close()

    init_db(db_path)

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(scraped_html_cache)")
        columns = {col[1]: col for col in cursor.fetchall()}
        assert columns["fetch_status"][2].upper() == "INTEGER"
        assert columns["relevance_status"][4] == "'PENDING'"

        cursor.execute("""
            SELECT COUNT(*) FROM scraped_html_cache
            WHERE url LIKE 'http://example.com/unassessed-%'
              AND relevance_status = 'PENDING'
        """)
        assert cursor.fetchone()[0] == 22

        cursor.execute("""
            SELECT relevance_status, relevance_label_source, validation
            FROM scraped_html_cache
            WHERE url IN (
                'http://example.com/keyword', 'http://example.com/model',
                'http://example.com/llm', 'http://example.com/human'
            )
            ORDER BY url
        """)
        assert cursor.fetchall() == [
            ("RELEVANT", "HUMAN", None),
            ("RELEVANT", "KEYWORD", None),
            ("INCONCLUSIVE", "LLM", None),
            ("IRRELEVANT", "MODEL", None),
        ]

        cursor.execute("""
            SELECT fetch_status FROM scraped_html_cache
            WHERE url = 'http://example.com/unassessed-0'
        """)
        assert cursor.fetchone()[0] == 200
        cursor.execute("""
            SELECT fetch_status FROM scraped_html_cache
            WHERE url = 'http://example.com/unassessed-1'
        """)
        assert cursor.fetchone()[0] is None

        cursor.execute("""
            INSERT INTO scraped_html_cache (url, publication_id)
            VALUES ('http://example.com/new', 'pub1')
        """)
        conn.commit()
        cursor.execute("SELECT relevance_status FROM scraped_html_cache WHERE url = 'http://example.com/new'")
        assert cursor.fetchone()[0] == "PENDING"

        with pytest.raises(sqlite3.IntegrityError):
            cursor.execute("""
                INSERT INTO scraped_html_cache (url, publication_id, validation)
                VALUES ('http://example.com/invalid-validation', 'pub1', 'PENDING_RELEVANCE')
            """)
    finally:
        conn.close()

    assert os.path.exists(db_path + ".backup")


def test_get_gold_standard_examples(tmp_path):
    from knowledge_map.adapters.sqlite_db import get_gold_standard_examples
    db_file = tmp_path / "test_examples.db"
    db_path = str(db_file)
    init_db(db_path)
    
    # Let's insert some publications, stories, and cache entries
    import sqlite3
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO publications (id, name, base_url) VALUES ('pub1', 'Pub 1', 'http://example.com')")
        
        # 1. Insert 4 RELEVANT human-labeled examples (should limit to 3)
        for i in range(1, 5):
            url = f"http://example.com/rel{i}"
            cursor.execute("""
                INSERT INTO stories (title, url, content, status)
                VALUES (?, ?, ?, 'UNPROCESSED')
            """, (f"Relevant Title {i}", url, f"Relevant Content {i}"))
            cursor.execute("""
                INSERT INTO scraped_html_cache (url, publication_id, relevance_status, relevance_label_source)
                VALUES (?, 'pub1', 'RELEVANT', 'HUMAN')
            """, (url,))
            
        for i in range(1, 5):
            url = f"http://example.com/irrel{i}"
            cursor.execute("""
                INSERT INTO scraped_html_cache (url, publication_id, relevance_status, relevance_label_source)
                VALUES (?, 'pub1', 'IRRELEVANT', 'HUMAN')
            """, (url,))
            
        # 3. Insert some non-HUMAN labeled examples (should be ignored)
        cursor.execute("""
            INSERT INTO stories (title, url, content, status)
            VALUES ('Model Title', 'http://example.com/model1', 'Model Content', 'UNPROCESSED')
        """)
        cursor.execute("""
            INSERT INTO scraped_html_cache (url, publication_id, relevance_status, relevance_label_source)
            VALUES ('http://example.com/model1', 'pub1', 'RELEVANT', 'MODEL')
        """)
        
        conn.commit()
    finally:
        conn.close()
        
    # Retrieve gold standard examples
    examples = get_gold_standard_examples(db_path)
    
    assert len(examples) == 3
    
    relevant = [ex for ex in examples if ex["relevance_status"] == "RELEVANT"]
    irrelevant = [ex for ex in examples if ex["relevance_status"] == "IRRELEVANT"]
    
    assert len(relevant) == 3
    assert irrelevant == []
    
    # Check shape/keys of returned dictionaries
    for ex in examples:
        assert "title" in ex
        assert "content" in ex
        assert "relevance_status" in ex


def test_relevance_label_source_updates(tmp_path):
    from knowledge_map.adapters.sqlite_db import update_relevance_status, cache_scraped_html, get_cached_html
    db_file = tmp_path / "test_updates.db"
    db_path = str(db_file)
    init_db(db_path)
    
    # 1. Test cache_scraped_html with relevance_label_source
    cache_scraped_html(
        url="http://example.com/art1",
        publication_id="pub1",
        raw_html="<html></html>",
        validation="VALIDATED",
        relevance_status="RELEVANT",
        relevance_label_source="LLM",
        db_path=db_path
    )
    
    cached = get_cached_html("http://example.com/art1", db_path=db_path)
    assert cached is not None
    assert cached["relevance_status"] == "RELEVANT"
    assert cached.get("relevance_label_source") == "LLM"
    
    # 2. Test update_relevance_status updates relevance_label_source
    update_relevance_status(
        url="http://example.com/art1",
        status="IRRELEVANT",
        relevance_label_source="HUMAN",
        db_path=db_path
    )
    cached = get_cached_html("http://example.com/art1", db_path=db_path)
    assert cached is not None
    assert cached["relevance_status"] == "IRRELEVANT"
    assert cached["validation"] == "VALIDATED"
    assert cached.get("relevance_label_source") == "HUMAN"
    
    # 3. Test cache_scraped_html with a different relevance_label_source
    cache_scraped_html(
        url="http://example.com/art2",
        publication_id="pub1",
        raw_html=None,
        relevance_status="INCONCLUSIVE",
        relevance_label_source="MODEL",
        db_path=db_path
    )
    cached = get_cached_html("http://example.com/art2", db_path=db_path)
    assert cached is not None
    assert cached["relevance_status"] == "INCONCLUSIVE"
    assert cached.get("relevance_label_source") == "MODEL"


def test_update_relevance_status_protects_human_labels(tmp_path):
    from knowledge_map.adapters.sqlite_db import (
        cache_scraped_html,
        get_cached_html,
        init_db,
        update_relevance_status,
    )

    db_path = str(tmp_path / "human-label-guard.db")
    url = "https://example.com/human-reviewed"
    init_db(db_path)
    cache_scraped_html(
        url,
        "pub1",
        "<html></html>",
        validation="PENDING",
        headline="Automated headline",
        relevance_status="INCONCLUSIVE",
        relevance_label_source="MODEL",
        db_path=db_path,
    )

    human_label = update_relevance_status(
        url,
        "RELEVANT",
        "HUMAN",
        db_path=db_path,
    )

    assert human_label.applied is True

    rejected = update_relevance_status(
        url,
        "IRRELEVANT",
        "MODEL",
        db_path=db_path,
    )

    assert rejected.status == "RELEVANT"
    assert rejected.label_source == "HUMAN"
    assert rejected.applied is False
    cached = get_cached_html(url, db_path=db_path)
    assert cached["relevance_status"] == "RELEVANT"
    assert cached["relevance_label_source"] == "HUMAN"
    assert cached["validation"] == "PENDING"
    assert cached["headline"] == "Automated headline"

    applied = update_relevance_status(
        url,
        "IRRELEVANT",
        "HUMAN",
        db_path=db_path,
    )

    assert applied.status == "IRRELEVANT"
    assert applied.label_source == "HUMAN"
    assert applied.applied is True
    cached = get_cached_html(url, db_path=db_path)
    assert cached["relevance_status"] == "IRRELEVANT"
    assert cached["relevance_label_source"] == "HUMAN"


def test_populate_article_metadata_is_idempotent_for_human_labeled_article(tmp_path):
    from unittest.mock import patch

    from knowledge_map.adapters.sqlite_db import cache_scraped_html, get_cached_html, init_db
    from knowledge_map.core.relevance_classification import populate_article_metadata

    db_path = str(tmp_path / "article-metadata.db")
    url = "https://example.com/human-metadata"
    embedding = [0.25] * 768
    init_db(db_path)
    cache_scraped_html(
        url,
        "pub1",
        """
        <html><head>
          <meta property="og:title" content="Human reviewed headline">
          <meta name="description" content="Human reviewed description">
        </head></html>
        """,
        relevance_status="RELEVANT",
        relevance_label_source="HUMAN",
        db_path=db_path,
    )

    with patch(
        "knowledge_map.adapters.embedding.PydanticAIEmbeddingAdapter.embed_text",
        return_value=embedding,
    ) as embed_text:
        first = populate_article_metadata(url, db_path=db_path)
        second = populate_article_metadata(url, db_path=db_path)

    assert first.applied is True
    assert second.applied is False
    assert embed_text.call_count == 1
    cached = get_cached_html(url, db_path=db_path)
    assert cached["headline"] == "Human reviewed headline"
    assert cached["description"] == "Human reviewed description"
    assert cached["embedding"] == pytest.approx(embedding, rel=1e-5)
    assert cached["relevance_status"] == "RELEVANT"
    assert cached["relevance_label_source"] == "HUMAN"


def test_populate_article_metadata_uses_stored_metadata_without_html(tmp_path):
    from unittest.mock import patch

    from knowledge_map.adapters.sqlite_db import cache_scraped_html, get_cached_html, init_db
    from knowledge_map.core.relevance_classification import populate_article_metadata

    db_path = str(tmp_path / "stored-article-metadata.db")
    url = "https://example.com/stored-metadata"
    embedding = [0.5] * 768
    init_db(db_path)
    cache_scraped_html(
        url,
        "pub1",
        None,
        raw_metadata_json={
            "article": {
                "title": "Stored headline",
                "summary": "Stored description",
            }
        },
        db_path=db_path,
    )

    with patch(
        "knowledge_map.adapters.embedding.PydanticAIEmbeddingAdapter.embed_text",
        return_value=embedding,
    ):
        result = populate_article_metadata(url, db_path=db_path)

    assert result.applied is True
    cached = get_cached_html(url, db_path=db_path)
    assert cached["headline"] == "Stored headline"
    assert cached["description"] == "Stored description"
    assert cached["embedding"] == pytest.approx(embedding, rel=1e-5)


def test_record_failed_fetch_preserves_an_existing_row(tmp_path):
    """
    Recording a failed fetch must not reuse the discovery cache writer's
    whole-row replacement, which would discard the labels already on the row.
    """
    from knowledge_map.adapters.sqlite_db import (
        cache_scraped_html,
        get_cached_html,
        is_url_known,
        record_failed_fetch,
    )
    db_file = tmp_path / "test_failed_fetch.db"
    db_path = str(db_file)
    init_db(db_path)

    url = "http://example.com/labelled"
    cache_scraped_html(
        url=url,
        publication_id="pub1",
        raw_html="<html></html>",
        validation="VALIDATED",
        relevance_status="RELEVANT",
        relevance_label_source="HUMAN",
        headline="Human headline",
        db_path=db_path
    )

    record_failed_fetch(url, "pub1", 503, db_path=db_path)

    cached = get_cached_html(url, db_path=db_path)
    assert cached["fetch_status"] == 503
    assert cached["relevance_status"] == "RELEVANT"
    assert cached["relevance_label_source"] == "HUMAN"
    assert cached["headline"] == "Human headline"
    assert cached["validation"] == "VALIDATED"
    assert cached["raw_html"] == "<html></html>"
    # A row that still holds content stays known regardless of the failure
    assert is_url_known(url, db_path=db_path)


def test_record_failed_fetch_creates_a_contentless_row(tmp_path):
    from knowledge_map.adapters.sqlite_db import (
        get_cached_html,
        is_url_known,
        record_failed_fetch,
    )
    db_file = tmp_path / "test_failed_fetch_new.db"
    db_path = str(db_file)
    init_db(db_path)

    url = "http://example.com/never-fetched"
    record_failed_fetch(url, "pub1", 500, db_path=db_path)

    cached = get_cached_html(url, db_path=db_path)
    assert cached["raw_html"] is None
    assert cached["fetch_status"] == 500
    # Null validation keeps the row out of the validation loop's selection
    assert cached["validation"] is None
    assert cached["relevance_status"] == "PENDING"
    # Retryable, so discovery offers it again
    assert not is_url_known(url, db_path=db_path)

    # A later terminal status settles it
    record_failed_fetch(url, "pub1", 410, db_path=db_path)
    assert is_url_known(url, db_path=db_path)


def _seed_labeled_articles(db_path):
    """Seeds one article per label source, including one with no source at all."""
    from knowledge_map.adapters.sqlite_db import cache_scraped_html

    for slug, status, source in (
        ("human", "INCONCLUSIVE", "HUMAN"),
        ("machine", "INCONCLUSIVE", "MODEL"),
        ("irrelevant", "IRRELEVANT", "KEYWORD"),
        ("relevant", "RELEVANT", "LLM"),
    ):
        cache_scraped_html(
            url=f"http://example.com/{slug}",
            publication_id="pub1",
            raw_html="<html></html>",
            validation="PENDING",
            relevance_status=status,
            relevance_label_source=source,
            db_path=db_path,
        )

    # A row predating the label-source column, so its source is NULL
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("""
            INSERT INTO scraped_html_cache
                (url, publication_id, raw_html, validation, relevance_status,
                 relevance_label_source)
            VALUES (?, 'pub1', '<html></html>', 'PENDING', 'INCONCLUSIVE', NULL)
        """, ("http://example.com/unsourced",))
        conn.commit()
    finally:
        conn.close()


def test_get_articles_for_human_labeling_skips_human_labeled_articles(tmp_path):
    from knowledge_map.adapters.sqlite_db import get_articles_for_human_labeling

    db_path = str(tmp_path / "test_labeling.db")
    init_db(db_path)
    _seed_labeled_articles(db_path)

    urls = {row[0] for row in get_articles_for_human_labeling(db_path=db_path)}
    # An unset source is not a human one, so those articles stay labelable
    assert urls == {"http://example.com/machine", "http://example.com/unsourced"}

    all_urls = {
        row[0]
        for row in get_articles_for_human_labeling(include_all=True, db_path=db_path)
    }
    assert all_urls == {
        "http://example.com/machine",
        "http://example.com/unsourced",
        "http://example.com/irrelevant",
        "http://example.com/relevant",
    }


def test_get_machine_labeled_for_reevaluation_skips_human_and_relevant(tmp_path):
    from knowledge_map.adapters.sqlite_db import get_machine_labeled_for_reevaluation

    db_path = str(tmp_path / "test_reevaluation.db")
    init_db(db_path)
    _seed_labeled_articles(db_path)

    rows = get_machine_labeled_for_reevaluation(db_path=db_path)
    assert {row[0] for row in rows} == {
        "http://example.com/machine",
        "http://example.com/irrelevant",
        "http://example.com/unsourced",
    }
    # Callers read the prior status off the last column
    assert {row[0]: row[4] for row in rows}["http://example.com/irrelevant"] == "IRRELEVANT"
