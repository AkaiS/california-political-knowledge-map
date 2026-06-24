import sqlite3
import os
from typing import List, Dict, Any

DEFAULT_DB_PATH = "document_store.db"

def init_db(db_path: str = DEFAULT_DB_PATH) -> None:
    """
    Initializes the SQLite database and creates the stories table if it doesn't exist.
    """
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS stories (
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
        # Safe migration: add column 'content' if it's missing in an existing database
        try:
            cursor.execute("ALTER TABLE stories ADD COLUMN content TEXT")
        except sqlite3.OperationalError:
            # Column already exists
            pass
        conn.commit()
    finally:
        conn.close()

def save_story(story: Dict[str, Any], db_path: str = DEFAULT_DB_PATH) -> bool:
    """
    Saves a single story to the database.
    Uses INSERT OR IGNORE to handle the UNIQUE constraint on url.
    Returns True if the story was inserted, False if it was ignored (already exists).
    """
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR IGNORE INTO stories (title, url, category, author, published_date, summary, content)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            story.get("title"),
            story.get("url"),
            story.get("category"),
            story.get("author"),
            story.get("published_date"),
            story.get("summary"),
            story.get("content")
        ))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()

def get_last_n_stories(n: int = 5, db_path: str = DEFAULT_DB_PATH) -> List[Dict[str, Any]]:
    """
    Retrieves the last n inserted stories from the database.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, title, url, category, author, published_date, summary, content, created_at
            FROM stories
            ORDER BY id DESC
            LIMIT ?
        """, (n,))
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()

def get_all_stories(db_path: str = DEFAULT_DB_PATH) -> List[Dict[str, Any]]:
    """
    Retrieves all stories from the database that have non-empty content.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, title, url, category, author, published_date, summary, content, created_at
            FROM stories
            WHERE content IS NOT NULL AND content != ''
            ORDER BY id ASC
        """)
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()

