import sqlite3
import os
import json
from typing import List, Dict, Any, NamedTuple, Optional

DEFAULT_DB_PATH = "document_store.db"

# Fetch statuses meaning the URL is permanently gone, so it is never fetched
# again. Blocking statuses (403, 429, 503) are deliberately absent: they say we
# were refused, not that the article stopped existing.
TERMINAL_FETCH_STATUSES = (404, 410)


class RelevanceUpdateResult(NamedTuple):
    status: str
    label_source: Optional[str]
    applied: bool


class ArticleMetadataUpdateResult(NamedTuple):
    headline: Optional[str]
    description: Optional[str]
    embedding: Optional[list[float]]
    applied: bool

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
                completed_at DATETIME,
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
        # Migration: check if scraped_html_cache exists and needs update
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='scraped_html_cache'")
        table_exists = cursor.fetchone() is not None
        
        if table_exists:
            cursor.execute("PRAGMA table_info(scraped_html_cache)")
            columns = [row[1] for row in cursor.fetchall()]
            
            cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='scraped_html_cache'")
            table_sql = cursor.fetchone()[0]
            
            cursor.execute("PRAGMA table_info(scraped_html_cache)")
            column_info = {row[1]: row for row in cursor.fetchall()}
            relevance_default = column_info.get("relevance_status", (None,) * 5)[4]

            # Check if we need the new migration
            needs_new_migration = (
                "relevance_label_source" not in columns
                or "fetch_status" not in columns
                or relevance_default != "'PENDING'"
                or "PENDING_RELEVANCE" in table_sql
            )
            has_headline = "headline" in columns

            if not has_headline or needs_new_migration:
                if os.path.exists(db_path):
                    import shutil
                    shutil.copy2(db_path, db_path + ".backup")
                    
                cursor.execute("ALTER TABLE scraped_html_cache RENAME TO scraped_html_cache_old")
                
                cursor.execute("""
                    CREATE TABLE scraped_html_cache (
                        url TEXT PRIMARY KEY,
                        publication_id TEXT NOT NULL,
                        raw_html TEXT,
                        validation TEXT CHECK(validation IN ('PENDING', 'VALIDATED', 'VALIDATION_FAILED', 'UNVALIDATABLE')) DEFAULT 'PENDING',
                        validation_date DATETIME,
                        scraped_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        headline TEXT,
                        description TEXT,
                        embedding BLOB,
                        relevance_status TEXT CHECK(relevance_status IN ('RELEVANT', 'IRRELEVANT', 'INCONCLUSIVE', 'PENDING')) DEFAULT 'PENDING',
                        relevance_label_source TEXT CHECK(relevance_label_source IN ('KEYWORD', 'LLM', 'HUMAN', 'MODEL')) DEFAULT 'KEYWORD',
                        fetch_status INTEGER,
                        raw_metadata_json TEXT,
                        FOREIGN KEY(publication_id) REFERENCES publications(id) ON DELETE CASCADE
                    )
                """)

                def legacy_value(name: str, fallback: str = "NULL") -> str:
                    """
                    SQL for reading `name` out of the pre-migration table, or the
                    literal `fallback` when that table predates the column.
                    """
                    return name if name in columns else fallback

                relevance_source = legacy_value("relevance_label_source", "'KEYWORD'")
                raw_metadata = legacy_value("raw_metadata_json")
                relevance_status = legacy_value("relevance_status", "'PENDING'")
                migrated_relevance_status = f"""
                    CASE
                        WHEN {relevance_status} = 'RELEVANT'
                         AND COALESCE({relevance_source}, 'KEYWORD') = 'KEYWORD'
                         AND {raw_metadata} IS NULL
                        THEN 'PENDING'
                        ELSE {relevance_status}
                    END
                """
                validation = legacy_value("validation")
                migrated_validation = f"CASE WHEN {validation} = 'PENDING_RELEVANCE' THEN NULL ELSE {validation} END"
                raw_html = legacy_value("raw_html")
                fetch_status = (
                    f"COALESCE(fetch_status, CASE WHEN {raw_html} IS NOT NULL THEN 200 ELSE NULL END)"
                    if "fetch_status" in columns
                    else f"CASE WHEN {raw_html} IS NOT NULL THEN 200 ELSE NULL END"
                )

                cursor.execute(f"""
                    INSERT INTO scraped_html_cache (
                        url, publication_id, raw_html, validation, validation_date,
                        scraped_at, headline, description, embedding, relevance_status,
                        relevance_label_source, fetch_status, raw_metadata_json
                    )
                    SELECT
                        {legacy_value('url')},
                        {legacy_value('publication_id')},
                        {legacy_value('raw_html')},
                        {migrated_validation},
                        {legacy_value('validation_date')},
                        {legacy_value('scraped_at', 'CURRENT_TIMESTAMP')},
                        {legacy_value('headline')},
                        {legacy_value('description')},
                        {legacy_value('embedding')},
                        {migrated_relevance_status},
                        {relevance_source},
                        {fetch_status},
                        {raw_metadata}
                    FROM scraped_html_cache_old
                """)
                
                cursor.execute("DROP TABLE scraped_html_cache_old")
                
                # Check and migrate rejected_articles
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='rejected_articles'")
                rejected_exists = cursor.fetchone() is not None
                if rejected_exists:
                    cursor.execute("SELECT url, publication_id, relevance_status, metadata_json, checked_at FROM rejected_articles")
                    rejected_rows = cursor.fetchall()
                    for r_url, r_pub_id, r_status, r_meta, r_checked in rejected_rows:
                        cursor.execute("""
                            INSERT OR REPLACE INTO scraped_html_cache (
                                url, publication_id, raw_html, validation, relevance_status, raw_metadata_json, scraped_at
                            ) VALUES (?, ?, NULL, ?, ?, ?, ?)
                        """, (r_url, r_pub_id, None, r_status, r_meta, r_checked))
                    cursor.execute("DROP TABLE rejected_articles")
        else:
            # Create scraped_html_cache table with new schema
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS scraped_html_cache (
                    url TEXT PRIMARY KEY,
                    publication_id TEXT NOT NULL,
                    raw_html TEXT,
                    validation TEXT CHECK(validation IN ('PENDING', 'VALIDATED', 'VALIDATION_FAILED', 'UNVALIDATABLE')) DEFAULT 'PENDING',
                    validation_date DATETIME,
                    scraped_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    headline TEXT,
                    description TEXT,
                    embedding BLOB,
                    relevance_status TEXT CHECK(relevance_status IN ('RELEVANT', 'IRRELEVANT', 'INCONCLUSIVE', 'PENDING')) DEFAULT 'PENDING',
                    relevance_label_source TEXT CHECK(relevance_label_source IN ('KEYWORD', 'LLM', 'HUMAN', 'MODEL')) DEFAULT 'KEYWORD',
                    fetch_status INTEGER,
                    raw_metadata_json TEXT,
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

        # Safe migration: add column 'completed_at' if it's missing in stories table
        try:
            cursor.execute("ALTER TABLE stories ADD COLUMN completed_at DATETIME")
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
            INSERT OR IGNORE INTO stories (title, url, category, author, published_date, summary, content, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            story.get("title"),
            story.get("url"),
            story.get("category"),
            story.get("author"),
            story.get("published_date"),
            story.get("summary"),
            story.get("content"),
            story.get("status", "UNPROCESSED")
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
            SELECT id, title, url, category, author, published_date, summary, content, created_at, status
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
    status_str = status.value if hasattr(status, "value") else str(status)
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        if status_str == "COMPLETED":
            cursor.execute(
                "UPDATE stories SET status = ?, completed_at = CURRENT_TIMESTAMP WHERE url = ?",
                (status_str, url)
            )
        else:
            cursor.execute(
                "UPDATE stories SET status = ?, completed_at = NULL WHERE url = ?",
                (status_str, url)
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
    discovery_config_json: Optional[str] = None,
    archive_cutoff_years: int = 5,
    db_path: str = DEFAULT_DB_PATH,
    categories: Optional[List[str]] = None
) -> None:
    """
    Registers a new Publication in the database.
    """
    if categories is not None:
        config = {}
        if discovery_config_json:
            try:
                config = json.loads(discovery_config_json)
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid JSON in discovery_config_json: {e}")
        config["valid_categories"] = categories
        discovery_config_json = json.dumps(config)

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


def update_publication(
    pub_id: str,
    name: Optional[str] = None,
    base_url: Optional[str] = None,
    crawl_delay: Optional[float] = None,
    max_concurrency: Optional[int] = None,
    use_robots_txt: Optional[bool] = None,
    discovery_config_json: Optional[str] = None,
    archive_cutoff_years: Optional[int] = None,
    categories: Optional[List[str]] = None,
    db_path: str = DEFAULT_DB_PATH,
) -> None:
    """
    Updates an existing publication in the database.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        
        # Check if the publication ID exists
        cursor.execute("""
            SELECT id, name, base_url, crawl_delay, max_concurrency, 
                   use_robots_txt, discovery_config_json, archive_cutoff_years
            FROM publications WHERE id = ?
        """, (pub_id,))
        row = cursor.fetchone()
        if row is None:
            raise ValueError(f"Publication with ID '{pub_id}' is not registered.")
            
        current_pub = dict(row)
        
        # Build update sets
        update_fields = []
        params = []
        
        if name is not None:
            update_fields.append("name = ?")
            params.append(name)
            
        if base_url is not None:
            update_fields.append("base_url = ?")
            params.append(base_url)
            
        if crawl_delay is not None:
            update_fields.append("crawl_delay = ?")
            params.append(crawl_delay)
            
        if max_concurrency is not None:
            update_fields.append("max_concurrency = ?")
            params.append(max_concurrency)
            
        if use_robots_txt is not None:
            update_fields.append("use_robots_txt = ?")
            params.append(1 if use_robots_txt else 0)
            
        if archive_cutoff_years is not None:
            update_fields.append("archive_cutoff_years = ?")
            params.append(archive_cutoff_years)
            
        current_config = {}
        if current_pub.get("discovery_config_json"):
            try:
                current_config = json.loads(current_pub["discovery_config_json"])
            except json.JSONDecodeError:
                pass
                
        new_config = None
        
        if discovery_config_json is not None:
            try:
                new_config = json.loads(discovery_config_json)
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid JSON in discovery_config_json: {e}")
        elif categories is not None or "valid_categories" in current_config:
            new_config = current_config.copy()
            
        if categories is not None:
            if new_config is None:
                new_config = {}
            if categories:
                new_config["valid_categories"] = categories
            else:
                new_config.pop("valid_categories", None)
        elif new_config is not None and "valid_categories" in current_config:
            new_config["valid_categories"] = current_config["valid_categories"]
            
        if new_config is not None or discovery_config_json is not None:
            val = json.dumps(new_config) if new_config else None
            update_fields.append("discovery_config_json = ?")
            params.append(val)
            
        if update_fields:
            params.append(pub_id)
            query = f"UPDATE publications SET {', '.join(update_fields)} WHERE id = ?"
            cursor.execute(query, tuple(params))
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
    raw_html: Optional[str],
    validation: Optional[str] = "PENDING",
    headline: Optional[str] = None,
    description: Optional[str] = None,
    embedding: Optional[list[float]] = None,
    relevance_status: str = "PENDING",
    raw_metadata_json: Optional[dict[str, Any]] = None,
    relevance_label_source: str = "KEYWORD",
    fetch_status: Optional[int] = None,
    db_path: str = DEFAULT_DB_PATH
) -> None:
    """
    Caches scraped raw HTML in scraped_html_cache table with optional metadata & embedding.
    """
    import json
    from knowledge_map.core.relevance import serialize_embedding
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        meta_str = json.dumps(raw_metadata_json) if raw_metadata_json is not None else None
        embedding_blob = serialize_embedding(embedding)
        recorded_fetch_status = 200 if raw_html is not None and fetch_status is None else fetch_status
        cursor.execute("""
            INSERT OR REPLACE INTO scraped_html_cache (
                url, publication_id, raw_html, validation, validation_date,
                headline, description, embedding, relevance_status, relevance_label_source,
                fetch_status, raw_metadata_json
            )
            VALUES (?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?)
        """, (
            url, publication_id, raw_html, validation, headline, description,
            embedding_blob, relevance_status, relevance_label_source,
            recorded_fetch_status, meta_str,
        ))
        conn.commit()
    finally:
        conn.close()


def get_cached_html(url: str, db_path: str = DEFAULT_DB_PATH) -> Optional[Dict[str, Any]]:
    """
    Retrieves a cached raw HTML record by URL.
    """
    import json
    from knowledge_map.core.relevance import deserialize_embedding
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT url, publication_id, raw_html, validation, validation_date, scraped_at,
                   headline, description, embedding, relevance_status, relevance_label_source,
                   fetch_status, raw_metadata_json
            FROM scraped_html_cache
            WHERE url = ?
        """, (url,))
        row = cursor.fetchone()
        if not row:
            return None
        d = dict(row)
        if d.get("raw_metadata_json"):
            try:
                d["raw_metadata_json"] = json.loads(d["raw_metadata_json"])
            except Exception:
                pass
        if d.get("embedding"):
            d["embedding"] = deserialize_embedding(d["embedding"])
        return d
    finally:
        conn.close()


def update_cached_html_status(url: str, validation: Optional[str], db_path: str = DEFAULT_DB_PATH) -> None:
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


def record_failed_fetch(
    url: str,
    publication_id: str,
    fetch_status: Optional[int],
    db_path: str = DEFAULT_DB_PATH
) -> None:
    """
    Records the outcome of a fetch that returned no article content.

    Writes the fetch status and nothing else. Validation is left null because no
    content is held, which also keeps the row out of the validation loop. An
    existing row keeps its raw HTML, relevance decision, and metadata; only the
    recorded status changes.
    """
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO scraped_html_cache (url, publication_id, raw_html, validation, fetch_status)
            VALUES (?, ?, NULL, NULL, ?)
            ON CONFLICT(url) DO UPDATE SET fetch_status = excluded.fetch_status
        """, (url, publication_id, fetch_status))
        conn.commit()
    finally:
        conn.close()


def is_url_known(url: str, db_path: str = DEFAULT_DB_PATH) -> bool:
    """
    Checks whether discovery has already dealt with a URL and should skip it.

    A cache row left by a fetch that returned no content does not make a URL
    known unless its recorded status is terminal. A URL that timed out or
    returned 5xx stays discoverable so the next crawl retries it, while one that
    is permanently gone is not fetched again. A row holding raw HTML or carrying
    a relevance decision is known either way.
    """
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        # Check stories
        cursor.execute("SELECT 1 FROM stories WHERE url = ?", (url,))
        if cursor.fetchone() is not None:
            return True
        # Check scraped_html_cache, ignoring rows that only record a retryable
        # fetch failure
        placeholders = ", ".join("?" for _ in TERMINAL_FETCH_STATUSES)
        cursor.execute(f"""
            SELECT 1 FROM scraped_html_cache
            WHERE url = ?
              AND NOT (
                raw_html IS NULL
                AND relevance_status = 'PENDING'
                AND (fetch_status IS NULL OR fetch_status NOT IN ({placeholders}))
              )
        """, (url, *TERMINAL_FETCH_STATUSES))
        if cursor.fetchone() is not None:
            return True
        return False
    finally:
        conn.close()


def get_gold_standard_examples(db_path: str = DEFAULT_DB_PATH) -> List[Dict[str, Any]]:
    """
    Retrieves balanced human-labeled examples (max 3 per class) by joining cache and stories.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        
        # Get up to 3 relevant human-labeled stories
        cursor.execute("""
            SELECT s.title, s.content, c.relevance_status
            FROM scraped_html_cache c
            JOIN stories s ON c.url = s.url
            WHERE c.relevance_label_source = 'HUMAN' AND c.relevance_status = 'RELEVANT'
            LIMIT 3
        """)
        relevant = [dict(row) for row in cursor.fetchall()]
        
        # Get up to 3 irrelevant human-labeled stories
        cursor.execute("""
            SELECT s.title, s.content, c.relevance_status
            FROM scraped_html_cache c
            JOIN stories s ON c.url = s.url
            WHERE c.relevance_label_source = 'HUMAN' AND c.relevance_status = 'IRRELEVANT'
            LIMIT 3
        """)
        irrelevant = [dict(row) for row in cursor.fetchall()]
        
        return relevant + irrelevant
    finally:
        conn.close()


def get_articles_for_human_labeling(
    include_all: bool = False,
    db_path: str = DEFAULT_DB_PATH,
) -> List[tuple]:
    """
    Retrieves cached articles a human may still label, as
    (url, headline, description, embedding) rows.

    By default only INCONCLUSIVE articles are offered, since those are the ones
    the classifier could not decide. `include_all` widens the set to every
    machine-labeled article, for reviewing decisions the classifier did make.
    """
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        if include_all:
            cursor.execute("""
                SELECT url, headline, description, embedding
                FROM scraped_html_cache
                WHERE relevance_label_source IS NOT 'HUMAN'
            """)
        else:
            cursor.execute("""
                SELECT url, headline, description, embedding
                FROM scraped_html_cache
                WHERE relevance_status = 'INCONCLUSIVE'
                  AND relevance_label_source IS NOT 'HUMAN'
            """)
        return cursor.fetchall()
    finally:
        conn.close()


def get_machine_labeled_for_reevaluation(db_path: str = DEFAULT_DB_PATH) -> List[tuple]:
    """
    Retrieves machine-labeled articles the classifier may reconsider, as
    (url, headline, description, embedding, relevance_status) rows.

    Only INCONCLUSIVE and IRRELEVANT articles are returned: reevaluation exists
    to promote articles a weaker classifier passed over, not to revisit ones
    already accepted as RELEVANT.
    """
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT url, headline, description, embedding, relevance_status
            FROM scraped_html_cache
            WHERE relevance_status IN ('INCONCLUSIVE', 'IRRELEVANT')
              AND relevance_label_source IS NOT 'HUMAN'
        """)
        return cursor.fetchall()
    finally:
        conn.close()


def update_relevance_status(
    url: str,
    status: str,
    relevance_label_source: str,
    db_path: str = DEFAULT_DB_PATH
) -> RelevanceUpdateResult:
    """
    Updates relevance data unless an automated write would replace a human label.

    Returns the effective persisted relevance status and source together with
    whether this write was applied.
    """
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()

        # `IS NOT` rather than `!=` so a row with no recorded source counts as
        # non-human instead of failing the comparison against NULL. Only another
        # human write may replace a human label.
        query = """
            UPDATE scraped_html_cache
            SET relevance_status = ?, relevance_label_source = ?
            WHERE url = ?
              AND (relevance_label_source IS NOT 'HUMAN' OR ? = 'HUMAN')
            RETURNING relevance_status, relevance_label_source
        """
        cursor.execute(query, (status, relevance_label_source, url, relevance_label_source))
        row = cursor.fetchone()
        applied = row is not None

        if row is None:
            cursor.execute("""
                SELECT relevance_status, relevance_label_source
                FROM scraped_html_cache
                WHERE url = ?
            """, (url,))
            row = cursor.fetchone()

        if row is None:
            raise ValueError(f"Cached article not found: {url}")

        conn.commit()
        return RelevanceUpdateResult(
            status=row[0],
            label_source=row[1],
            applied=applied,
        )
    finally:
        conn.close()


def update_article_metadata(
    url: str,
    headline: Optional[str],
    description: Optional[str],
    embedding: Optional[list[float]],
    db_path: str = DEFAULT_DB_PATH,
) -> ArticleMetadataUpdateResult:
    """Populate missing article metadata without replacing stored values."""
    from knowledge_map.core.relevance import deserialize_embedding, serialize_embedding

    normalized_headline = headline.strip() if headline and headline.strip() else None
    normalized_description = description.strip() if description and description.strip() else None
    serialized_embedding = serialize_embedding(embedding) if embedding is not None else None

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE scraped_html_cache
            SET headline = CASE
                    WHEN headline IS NULL OR TRIM(headline) = '' THEN ?
                    ELSE headline
                END,
                description = CASE
                    WHEN description IS NULL OR TRIM(description) = '' THEN ?
                    ELSE description
                END,
                embedding = CASE
                    WHEN embedding IS NULL THEN ?
                    ELSE embedding
                END
            WHERE url = ?
              AND (
                  ((headline IS NULL OR TRIM(headline) = '') AND ? IS NOT NULL)
                  OR ((description IS NULL OR TRIM(description) = '') AND ? IS NOT NULL)
                  OR (embedding IS NULL AND ? IS NOT NULL)
              )
            RETURNING headline, description, embedding
            """,
            (
                normalized_headline,
                normalized_description,
                serialized_embedding,
                url,
                normalized_headline,
                normalized_description,
                serialized_embedding,
            ),
        )
        row = cursor.fetchone()
        applied = row is not None

        if row is None:
            cursor.execute(
                """
                SELECT headline, description, embedding
                FROM scraped_html_cache
                WHERE url = ?
                """,
                (url,),
            )
            row = cursor.fetchone()

        if row is None:
            raise ValueError(f"Cached article not found: {url}")

        conn.commit()
        return ArticleMetadataUpdateResult(
            headline=row[0],
            description=row[1],
            embedding=deserialize_embedding(row[2]) if row[2] is not None else None,
            applied=applied,
        )
    finally:
        conn.close()


def clear_cached_html(url: str, db_path: str = DEFAULT_DB_PATH) -> None:
    """
    Clears the raw_html content of a cached article while keeping its metadata and embedding.
    """
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE scraped_html_cache
            SET raw_html = NULL
            WHERE url = ?
        """, (url,))
        conn.commit()
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


def purge_html_cache(db_path: str = DEFAULT_DB_PATH) -> Dict[str, int]:
    """
    Applies the Raw HTML Store retention policy to purge raw HTML from the cache.
    """
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        
        # 1. Purge VALIDATED rows older than 30 days based on their completed story status
        cursor.execute("""
            UPDATE scraped_html_cache
            SET raw_html = NULL
            WHERE validation = 'VALIDATED'
              AND url IN (
                  SELECT url FROM stories
                  WHERE status = 'COMPLETED'
                    AND completed_at < datetime('now', '-30 days')
              )
              AND raw_html IS NOT NULL
        """)
        validated_count = cursor.rowcount
        
        # 2. Purge UNVALIDATABLE rows older than 30 days
        cursor.execute("""
            UPDATE scraped_html_cache
            SET raw_html = NULL
            WHERE validation = 'UNVALIDATABLE'
              AND validation_date < datetime('now', '-30 days')
              AND raw_html IS NOT NULL
        """)
        unvalidatable_count = cursor.rowcount
        
        conn.commit()
        return {
            "validated": validated_count,
            "unvalidatable": unvalidatable_count,
            "total": validated_count + unvalidatable_count
        }
    finally:
        conn.close()


