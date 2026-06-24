import os
import pytest
from db import init_db, save_story, get_all_stories

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
