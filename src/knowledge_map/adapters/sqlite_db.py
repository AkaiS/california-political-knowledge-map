import sqlite3
import os
import json
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
                tripping_article_url TEXT,
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
        # Create scraped_html_cache table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS scraped_html_cache (
                url TEXT PRIMARY KEY,
                publication_id TEXT NOT NULL,
                raw_html TEXT,
                validation TEXT CHECK(validation IN ('PENDING', 'VALIDATED', 'VALIDATION_FAILED', 'UNVALIDATABLE')) DEFAULT 'PENDING',
                validation_date DATETIME,
                scraped_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(publication_id) REFERENCES publications(id) ON DELETE CASCADE
            )
        """)
        # Create rejected_articles table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS rejected_articles (
                url TEXT PRIMARY KEY,
                publication_id TEXT NOT NULL,
                relevance_status TEXT CHECK(relevance_status IN ('IRRELEVANT', 'INCONCLUSIVE')) NOT NULL,
                metadata_json TEXT,
                checked_at DATETIME DEFAULT CURRENT_TIMESTAMP,
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
            
        # Safe migration: add column 'tripping_article_url' if it's missing in publications table
        try:
            cursor.execute("ALTER TABLE publications ADD COLUMN tripping_article_url TEXT")
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
        # Create publication_discovery_state table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS publication_discovery_state (
                publication_id TEXT PRIMARY KEY,
                state_json TEXT NOT NULL,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(publication_id) REFERENCES publications(id) ON DELETE CASCADE
            )
        """)
        # Create selector_proposals table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS selector_proposals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                publication_id TEXT NOT NULL,
                selectors_json TEXT NOT NULL,       -- Candidate article selectors (title, author, date, body)
                trigger_article_url TEXT NOT NULL,  -- The VALIDATION_FAILED article that tripped the breaker (Recovery Check target)
                status TEXT CHECK(status IN ('PENDING_REVIEW', 'APPROVED', 'REJECTED', 'HEALING_FAILED')) DEFAULT 'PENDING_REVIEW',
                critic_iterations INTEGER,          -- Number of Generator/Critic iterations consumed
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                resolved_at DATETIME,
                FOREIGN KEY(publication_id) REFERENCES publications(id) ON DELETE CASCADE
            )
        """)
        # Reset all healing_in_progress flags to 0 on startup
        cursor.execute("UPDATE publications SET healing_in_progress = 0")
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
                   validation_paused, failure_points, healing_in_progress, tripping_article_url, created_at
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
                   validation_paused, failure_points, healing_in_progress, tripping_article_url, created_at
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


def cache_scraped_html(
    url: str,
    publication_id: str,
    raw_html: str,
    validation: str = "PENDING",
    db_path: str = DEFAULT_DB_PATH
) -> None:
    """
    Caches scraped raw HTML in scraped_html_cache table.
    """
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO scraped_html_cache (url, publication_id, raw_html, validation, validation_date)
            VALUES (?, ?, ?, ?, NULL)
        """, (url, publication_id, raw_html, validation))
        conn.commit()
    finally:
        conn.close()


def get_cached_html(url: str, db_path: str = DEFAULT_DB_PATH) -> Optional[Dict[str, Any]]:
    """
    Retrieves a cached raw HTML record by URL.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT url, publication_id, raw_html, validation, validation_date, scraped_at
            FROM scraped_html_cache
            WHERE url = ?
        """, (url,))
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def update_cached_html_status(url: str, validation: str, db_path: str = DEFAULT_DB_PATH) -> None:
    """
    Updates the validation status and sets validation_date to CURRENT_TIMESTAMP.
    """
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE scraped_html_cache
            SET validation = ?, validation_date = CURRENT_TIMESTAMP
            WHERE url = ?
        """, (validation, url))
        conn.commit()
    finally:
        conn.close()


def is_url_known(url: str, db_path: str = DEFAULT_DB_PATH) -> bool:
    """
    Checks if a URL is already present in stories, scraped_html_cache, or rejected_articles.
    """
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        # Check stories
        cursor.execute("SELECT 1 FROM stories WHERE url = ?", (url,))
        if cursor.fetchone() is not None:
            return True
        # Check scraped_html_cache
        cursor.execute("SELECT 1 FROM scraped_html_cache WHERE url = ?", (url,))
        if cursor.fetchone() is not None:
            return True
        # Check rejected_articles
        cursor.execute("SELECT 1 FROM rejected_articles WHERE url = ?", (url,))
        if cursor.fetchone() is not None:
            return True
        return False
    finally:
        conn.close()


def save_rejected_article(
    url: str,
    publication_id: str,
    relevance_status: str,
    metadata_json: Optional[Dict[str, Any]] = None,
    db_path: str = DEFAULT_DB_PATH
) -> None:
    """
    Saves a rejected or inconclusive article to the rejected_articles table.
    """
    import json
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        meta_str = json.dumps(metadata_json) if metadata_json is not None else None
        cursor.execute("""
            INSERT OR REPLACE INTO rejected_articles (url, publication_id, relevance_status, metadata_json)
            VALUES (?, ?, ?, ?)
        """, (url, publication_id, relevance_status, meta_str))
        conn.commit()
    finally:
        conn.close()


def get_rejected_article(url: str, db_path: str = DEFAULT_DB_PATH) -> Optional[Dict[str, Any]]:
    """
    Retrieves a rejected article record by URL.
    """
    import json
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT url, publication_id, relevance_status, metadata_json, checked_at
            FROM rejected_articles
            WHERE url = ?
        """, (url,))
        row = cursor.fetchone()
        if row is None:
            return None
        d = dict(row)
        if d["metadata_json"]:
            try:
                d["metadata_json"] = json.loads(d["metadata_json"])
            except Exception:
                pass
        return d
    finally:
        conn.close()


def get_discovery_state(pub_id: str, db_path: str = DEFAULT_DB_PATH) -> Optional[Dict[str, Any]]:
    """
    Retrieves the discovery state for a publication. Returns None if not found.
    """
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT state_json FROM publication_discovery_state WHERE publication_id = ?
        """, (pub_id,))
        row = cursor.fetchone()
        if row is None:
            return None
        return json.loads(row[0])
    finally:
        conn.close()


def save_discovery_state(pub_id: str, state: Dict[str, Any], db_path: str = DEFAULT_DB_PATH) -> None:
    """
    Saves or updates the discovery state for a publication.
    """
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        state_str = json.dumps(state)
        cursor.execute("""
            INSERT OR REPLACE INTO publication_discovery_state (publication_id, state_json, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
        """, (pub_id, state_str))
        conn.commit()
    finally:
        conn.close()


def increment_publication_failure_points(
    pub_id: str,
    points_to_add: int,
    db_path: str = DEFAULT_DB_PATH
) -> int:
    """
    Increments the failure points for a publication and returns the updated count.
    """
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE publications
            SET failure_points = failure_points + ?
            WHERE id = ?
        """, (points_to_add, pub_id))
        conn.commit()
        
        cursor.execute("SELECT failure_points FROM publications WHERE id = ?", (pub_id,))
        row = cursor.fetchone()
        return row[0] if row else 0
    finally:
        conn.close()


def reset_publication_failure_points(
    pub_id: str,
    db_path: str = DEFAULT_DB_PATH
) -> None:
    """
    Resets failure points to 0 for a publication.
    """
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE publications
            SET failure_points = 0
            WHERE id = ?
        """, (pub_id,))
        conn.commit()
    finally:
        conn.close()


def pause_publication_validation(
    pub_id: str,
    tripping_article_url: str,
    db_path: str = DEFAULT_DB_PATH
) -> None:
    """
    Pauses validation for a publication and records the tripping article URL.
    """
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE publications
            SET validation_paused = 1,
                tripping_article_url = ?
            WHERE id = ?
        """, (tripping_article_url, pub_id))
        conn.commit()
    finally:
        conn.close()


def unpause_publication_validation(
    pub_id: str,
    db_path: str = DEFAULT_DB_PATH
) -> None:
    """
    Unpauses validation for a publication and resets the tripping article URL to NULL.
    """
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE publications
            SET validation_paused = 0,
                tripping_article_url = NULL
            WHERE id = ?
        """, (pub_id,))
        conn.commit()
    finally:
        conn.close()


def insert_selector_proposal(
    publication_id: str,
    selectors_json: str,
    trigger_article_url: str,
    status: str,
    critic_iterations: int,
    db_path: str = DEFAULT_DB_PATH
) -> int:
    """
    Inserts a new Selector Proposal into the database and returns its ID.
    """
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO selector_proposals (
                publication_id, selectors_json, trigger_article_url, status, critic_iterations
            ) VALUES (?, ?, ?, ?, ?)
        """, (publication_id, selectors_json, trigger_article_url, status, critic_iterations))
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def has_unresolved_selector_proposal(
    pub_id: str,
    db_path: str = DEFAULT_DB_PATH
) -> bool:
    """
    Returns True if an unresolved selector proposal (PENDING_REVIEW or HEALING_FAILED) exists for a publication.
    """
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT 1 FROM selector_proposals
            WHERE publication_id = ? AND status IN ('PENDING_REVIEW', 'HEALING_FAILED')
            LIMIT 1
        """, (pub_id,))
        return cursor.fetchone() is not None
    finally:
        conn.close()


def set_publication_healing_in_progress(
    pub_id: str,
    in_progress: bool,
    db_path: str = DEFAULT_DB_PATH
) -> None:
    """
    Sets the healing_in_progress flag (0 or 1) for a publication.
    """
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE publications
            SET healing_in_progress = ?
            WHERE id = ?
        """, (1 if in_progress else 0, pub_id))
        conn.commit()
    finally:
        conn.close()


def get_unresolved_proposals(
    db_path: str = DEFAULT_DB_PATH
) -> List[Dict[str, Any]]:
    """
    Retrieves all unresolved selector proposals from the database.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, publication_id, selectors_json, trigger_article_url, status, critic_iterations, created_at
            FROM selector_proposals
            WHERE resolved_at IS NULL AND status IN ('PENDING_REVIEW', 'HEALING_FAILED')
            ORDER BY id ASC
        """)
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def resolve_selector_proposal(
    proposal_id: int,
    status: str,
    db_path: str = DEFAULT_DB_PATH
) -> None:
    """
    Resolves a Selector Proposal by updating its status and setting resolved_at to the current timestamp.
    """
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE selector_proposals
            SET status = ?,
                resolved_at = datetime('now')
            WHERE id = ?
        """, (status, proposal_id))
        conn.commit()
    finally:
        conn.close()


def get_latest_selector_proposal(
    pub_id: str,
    db_path: str = DEFAULT_DB_PATH
) -> Optional[Dict[str, Any]]:
    """
    Retrieves the most recent selector proposal for a given publication.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, publication_id, selectors_json, trigger_article_url, status, critic_iterations, created_at, resolved_at
            FROM selector_proposals
            WHERE publication_id = ?
            ORDER BY id DESC
            LIMIT 1
        """, (pub_id,))
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()










