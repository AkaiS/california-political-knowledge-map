import os
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


