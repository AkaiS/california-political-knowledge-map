import sqlite3
import os
from typing import List, Dict, Any, Optional

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
                status TEXT DEFAULT 'UNPROCESSED',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Create publications table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS publications (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                base_url TEXT NOT NULL,
                crawl_delay REAL DEFAULT 2.0,
                max_concurrency INTEGER DEFAULT 2,
                use_robots_txt BOOLEAN DEFAULT 1,
                discovery_config_json TEXT,
                archive_cutoff_years INTEGER DEFAULT 5,
                validation_paused BOOLEAN DEFAULT 0,
                failure_points INTEGER DEFAULT 0,
                healing_in_progress BOOLEAN DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Create publication_selectors table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS publication_selectors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                publication_id TEXT NOT NULL,
                selectors_json TEXT NOT NULL,
                earliest_success_date DATETIME,
                latest_success_date DATETIME,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(publication_id) REFERENCES publications(id) ON DELETE CASCADE
            )
        """)
        # Safe migration: add column 'content' if it's missing in an existing database
        try:
            cursor.execute("ALTER TABLE stories ADD COLUMN content TEXT")
        except sqlite3.OperationalError:
            # Column already exists
            pass
            
        # Safe migration: add column 'status' if it's missing in an existing database
        try:
            cursor.execute("ALTER TABLE stories ADD COLUMN status TEXT DEFAULT 'UNPROCESSED'")
        except sqlite3.OperationalError:
            # Column already exists
            pass
            
        # Create story_links table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS story_links (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                story_id INTEGER NOT NULL,
                text TEXT,
                url TEXT NOT NULL,
                scraped BOOLEAN DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(story_id) REFERENCES stories(id) ON DELETE CASCADE,
                UNIQUE(story_id, url)
            )
        """)
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
        inserted = cursor.rowcount > 0
        
        # Get the ID of the story to associate the links
        cursor.execute("SELECT id FROM stories WHERE url = ?", (story.get("url"),))
        row = cursor.fetchone()
        if row:
            story_id = row[0]
            if "links" in story:
                for link in story["links"]:
                    cursor.execute("""
                        INSERT OR IGNORE INTO story_links (story_id, text, url)
                        VALUES (?, ?, ?)
                    """, (story_id, link.get("text"), link.get("url")))
                    
        conn.commit()
        return inserted
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


def get_unprocessed_stories(db_path: str = DEFAULT_DB_PATH) -> List[Dict[str, Any]]:
    """
    Retrieves all stories from the database where status is 'UNPROCESSED' and content is non-empty.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, title, url, category, author, published_date, summary, content, created_at, status
            FROM stories
            WHERE status = 'UNPROCESSED' AND content IS NOT NULL AND content != ''
            ORDER BY id ASC
        """)
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()



def get_story_links(story_id: int, db_path: str = DEFAULT_DB_PATH) -> List[Dict[str, Any]]:
    """
    Retrieves all links associated with a specific story.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, story_id, text, url, scraped, created_at
            FROM story_links
            WHERE story_id = ?
            ORDER BY id ASC
        """, (story_id,))
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def update_story_status(url: str, status: str, db_path: str = DEFAULT_DB_PATH) -> None:
    """
    Updates the status of a story in the SQLite database by its URL.
    """
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE stories SET status = ? WHERE url = ?",
            (status, url)
        )
        conn.commit()
    finally:
        conn.close()


class SQLiteStatusTracker:
    def __init__(self, db_path: str = DEFAULT_DB_PATH) -> None:
        self.db_path = db_path

    def update_status(self, url: str, status: str) -> None:
        update_story_status(url, status, db_path=self.db_path)


def register_publication(
    pub_id: str,
    name: str,
    base_url: str,
    crawl_delay: float = 2.0,
    max_concurrency: int = 2,
    use_robots_txt: bool = True,
    discovery_config_json: str = None,
    archive_cutoff_years: int = 5,
    db_path: str = DEFAULT_DB_PATH
) -> None:
    """
    Registers a new Publication in the database.
    """
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        
        # Check if the publication ID already exists
        cursor.execute("SELECT id FROM publications WHERE id = ?", (pub_id,))
        if cursor.fetchone() is not None:
            raise ValueError(f"Publication with ID '{pub_id}' is already registered.")
            
        cursor.execute("""
            INSERT INTO publications (
                id, name, base_url, crawl_delay, max_concurrency, 
                use_robots_txt, discovery_config_json, archive_cutoff_years
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            pub_id, name, base_url, crawl_delay, max_concurrency,
            1 if use_robots_txt else 0, discovery_config_json, archive_cutoff_years
        ))
        conn.commit()
    finally:
        conn.close()


def _row_to_pub_dict(row: sqlite3.Row) -> Dict[str, Any]:
    """Helper to convert database Row to Dict with proper boolean types."""
    d = dict(row)
    # Convert booleans
    d["use_robots_txt"] = bool(d["use_robots_txt"])
    d["validation_paused"] = bool(d["validation_paused"])
    d["healing_in_progress"] = bool(d["healing_in_progress"])
    return d


def get_publication(pub_id: str, db_path: str = DEFAULT_DB_PATH) -> Optional[Dict[str, Any]]:
    """
    Retrieves a publication by its ID. Returns None if not found.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, name, base_url, crawl_delay, max_concurrency,
                   use_robots_txt, discovery_config_json, archive_cutoff_years,
                   validation_paused, failure_points, healing_in_progress, created_at
            FROM publications WHERE id = ?
        """, (pub_id,))
        row = cursor.fetchone()
        if row is None:
            return None
        return _row_to_pub_dict(row)
    finally:
        conn.close()


def get_all_publications(db_path: str = DEFAULT_DB_PATH) -> List[Dict[str, Any]]:
    """
    Retrieves all registered publications.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, name, base_url, crawl_delay, max_concurrency,
                   use_robots_txt, discovery_config_json, archive_cutoff_years,
                   validation_paused, failure_points, healing_in_progress, created_at
            FROM publications
            ORDER BY id ASC
        """)
        rows = cursor.fetchall()
        return [_row_to_pub_dict(row) for row in rows]
    finally:
        conn.close()


def insert_selector_version(
    publication_id: str,
    selectors_json: str,
    earliest_success_date: str,
    latest_success_date: str,
    db_path: str = DEFAULT_DB_PATH
) -> int:
    """
    Inserts a new Selector Version into the database.
    """
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO publication_selectors (
                publication_id, selectors_json, earliest_success_date, latest_success_date
            ) VALUES (?, ?, ?, ?)
        """, (publication_id, selectors_json, earliest_success_date, latest_success_date))
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def get_selector_versions(
    publication_id: str,
    db_path: str = DEFAULT_DB_PATH
) -> List[Dict[str, Any]]:
    """
    Retrieves all selector versions for a given publication.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, publication_id, selectors_json, earliest_success_date, latest_success_date, created_at
            FROM publication_selectors
            WHERE publication_id = ?
            ORDER BY id ASC
        """, (publication_id,))
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def update_selector_window(
    selector_version_id: int,
    earliest_success_date: str,
    latest_success_date: str,
    db_path: str = DEFAULT_DB_PATH
) -> None:
    """
    Updates the success window boundaries of a selector version.
    """
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE publication_selectors
            SET earliest_success_date = ?,
                latest_success_date = ?
            WHERE id = ?
        """, (earliest_success_date, latest_success_date, selector_version_id))
        conn.commit()
    finally:
        conn.close()


def get_selector_version_by_id(
    selector_version_id: int,
    db_path: str = DEFAULT_DB_PATH
) -> Optional[Dict[str, Any]]:
    """
    Retrieves a single selector version by its ID.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, publication_id, selectors_json, earliest_success_date, latest_success_date, created_at
            FROM publication_selectors
            WHERE id = ?
        """, (selector_version_id,))
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()





