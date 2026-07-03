import os
import sqlite3
import datetime
import pytest
from knowledge_map.adapters.sqlite_db import init_db, get_cached_html, purge_html_cache

def test_purge_unvalidatable_older_than_30_days(tmp_path):
    db_file = tmp_path / "test_purge.db"
    db_path = str(db_file)
    init_db(db_path)

    # Insert a dummy publication first
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO publications (id, name, base_url) VALUES (?, ?, ?)",
            ("testpub", "Test Publication", "https://testpub.com")
        )
        
        # Insert UNVALIDATABLE row older than 30 days (e.g. 35 days ago)
        validation_date = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=35)).strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute("""
            INSERT INTO scraped_html_cache (url, publication_id, raw_html, validation, validation_date)
            VALUES (?, ?, ?, ?, ?)
        """, (
            "https://testpub.com/unval-old",
            "testpub",
            "<html><body>Older unvalidatable article</body></html>",
            "UNVALIDATABLE",
            validation_date
        ))
        conn.commit()
    finally:
        conn.close()

    # Verify initial state
    cached = get_cached_html("https://testpub.com/unval-old", db_path=db_path)
    assert cached is not None
    assert cached["raw_html"] == "<html><body>Older unvalidatable article</body></html>"
    assert cached["validation"] == "UNVALIDATABLE"

    # Run purge
    res = purge_html_cache(db_path=db_path)

    # Verify return counts
    assert res == {"validated": 0, "unvalidatable": 1, "total": 1}

    # Verify raw_html was nulled out but row remains
    cached = get_cached_html("https://testpub.com/unval-old", db_path=db_path)
    assert cached is not None
    assert cached["raw_html"] is None
    assert cached["validation"] == "UNVALIDATABLE"


def test_purge_validated_older_than_30_days(tmp_path):
    db_file = tmp_path / "test_purge_validated.db"
    db_path = str(db_file)
    init_db(db_path)

    # Insert a dummy publication first
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO publications (id, name, base_url) VALUES (?, ?, ?)",
            ("testpub", "Test Publication", "https://testpub.com")
        )
        
        # Insert VALIDATED row older than 30 days
        validation_date = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=35)).strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute("""
            INSERT INTO scraped_html_cache (url, publication_id, raw_html, validation, validation_date)
            VALUES (?, ?, ?, ?, ?)
        """, (
            "https://testpub.com/validated-old",
            "testpub",
            "<html><body>Older validated article</body></html>",
            "VALIDATED",
            validation_date
        ))
        
        # Insert corresponding story marked COMPLETED 35 days ago
        completed_at = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=35)).strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute("""
            INSERT INTO stories (title, url, status, completed_at)
            VALUES (?, ?, ?, ?)
        """, (
            "Older Validated Story",
            "https://testpub.com/validated-old",
            "COMPLETED",
            completed_at
        ))
        conn.commit()
    finally:
        conn.close()

    # Verify initial state
    cached = get_cached_html("https://testpub.com/validated-old", db_path=db_path)
    assert cached is not None
    assert cached["raw_html"] == "<html><body>Older validated article</body></html>"

    # Run purge
    res = purge_html_cache(db_path=db_path)

    # Verify counts
    assert res == {"validated": 1, "unvalidatable": 0, "total": 1}

    # Verify raw_html was nulled out
    cached = get_cached_html("https://testpub.com/validated-old", db_path=db_path)
    assert cached is not None
    assert cached["raw_html"] is None


def test_purge_policy_boundaries_and_exclusions(tmp_path):
    db_file = tmp_path / "test_purge_boundaries.db"
    db_path = str(db_file)
    init_db(db_path)

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO publications (id, name, base_url) VALUES (?, ?, ?)",
            ("testpub", "Test Publication", "https://testpub.com")
        )
        
        now = datetime.datetime.now(datetime.timezone.utc)
        old_time = (now - datetime.timedelta(days=35)).strftime("%Y-%m-%d %H:%M:%S")
        recent_time = (now - datetime.timedelta(days=25)).strftime("%Y-%m-%d %H:%M:%S")

        # 1. Eligible VALIDATED row (story completed 35 days ago) -> should purge
        cursor.execute("""
            INSERT INTO scraped_html_cache (url, publication_id, raw_html, validation, validation_date)
            VALUES (?, ?, ?, ?, ?)
        """, ("https://testpub.com/validated-eligible", "testpub", "html-eligible", "VALIDATED", old_time))
        cursor.execute("""
            INSERT INTO stories (title, url, status, completed_at)
            VALUES (?, ?, ?, ?)
        """, ("Story Eligible", "https://testpub.com/validated-eligible", "COMPLETED", old_time))

        # 2. Ineligible VALIDATED row (story completed 25 days ago) -> should NOT purge
        cursor.execute("""
            INSERT INTO scraped_html_cache (url, publication_id, raw_html, validation, validation_date)
            VALUES (?, ?, ?, ?, ?)
        """, ("https://testpub.com/validated-ineligible", "testpub", "html-ineligible-recent", "VALIDATED", recent_time))
        cursor.execute("""
            INSERT INTO stories (title, url, status, completed_at)
            VALUES (?, ?, ?, ?)
        """, ("Story Recent", "https://testpub.com/validated-ineligible", "COMPLETED", recent_time))

        # 3. Ineligible VALIDATED row (story UNPROCESSED) -> should NOT purge
        cursor.execute("""
            INSERT INTO scraped_html_cache (url, publication_id, raw_html, validation, validation_date)
            VALUES (?, ?, ?, ?, ?)
        """, ("https://testpub.com/validated-unprocessed", "testpub", "html-ineligible-unprocessed", "VALIDATED", old_time))
        cursor.execute("""
            INSERT INTO stories (title, url, status, completed_at)
            VALUES (?, ?, ?, ?)
        """, ("Story Unprocessed", "https://testpub.com/validated-unprocessed", "UNPROCESSED", None))

        # 4. Eligible UNVALIDATABLE row (validated 35 days ago) -> should purge
        cursor.execute("""
            INSERT INTO scraped_html_cache (url, publication_id, raw_html, validation, validation_date)
            VALUES (?, ?, ?, ?, ?)
        """, ("https://testpub.com/unval-eligible", "testpub", "html-unval-eligible", "UNVALIDATABLE", old_time))

        # 5. Ineligible UNVALIDATABLE row (validated 25 days ago) -> should NOT purge
        cursor.execute("""
            INSERT INTO scraped_html_cache (url, publication_id, raw_html, validation, validation_date)
            VALUES (?, ?, ?, ?, ?)
        """, ("https://testpub.com/unval-ineligible", "testpub", "html-unval-ineligible", "UNVALIDATABLE", recent_time))

        # 6. Ineligible VALIDATION_FAILED row (35 days old) -> should NOT purge
        cursor.execute("""
            INSERT INTO scraped_html_cache (url, publication_id, raw_html, validation, validation_date)
            VALUES (?, ?, ?, ?, ?)
        """, ("https://testpub.com/failed-old", "testpub", "html-failed", "VALIDATION_FAILED", old_time))

        # 7. Ineligible PENDING row (35 days old) -> should NOT purge
        cursor.execute("""
            INSERT INTO scraped_html_cache (url, publication_id, raw_html, validation, validation_date)
            VALUES (?, ?, ?, ?, ?)
        """, ("https://testpub.com/pending-old", "testpub", "html-pending", "PENDING", old_time))

        conn.commit()
    finally:
        conn.close()

    # Run purge
    res = purge_html_cache(db_path=db_path)

    # Verify counts
    assert res == {"validated": 1, "unvalidatable": 1, "total": 2}

    # Verify states
    # 1. Eligible VALIDATED row should be purged
    c = get_cached_html("https://testpub.com/validated-eligible", db_path=db_path)
    assert c["raw_html"] is None

    # 2. Ineligible VALIDATED row (recent) should NOT be purged
    c = get_cached_html("https://testpub.com/validated-ineligible", db_path=db_path)
    assert c["raw_html"] == "html-ineligible-recent"

    # 3. Ineligible VALIDATED row (unprocessed) should NOT be purged
    c = get_cached_html("https://testpub.com/validated-unprocessed", db_path=db_path)
    assert c["raw_html"] == "html-ineligible-unprocessed"

    # 4. Eligible UNVALIDATABLE row should be purged
    c = get_cached_html("https://testpub.com/unval-eligible", db_path=db_path)
    assert c["raw_html"] is None

    # 5. Ineligible UNVALIDATABLE row should NOT be purged
    c = get_cached_html("https://testpub.com/unval-ineligible", db_path=db_path)
    assert c["raw_html"] == "html-unval-ineligible"

    # 6. Ineligible VALIDATION_FAILED row should NOT be purged
    c = get_cached_html("https://testpub.com/failed-old", db_path=db_path)
    assert c["raw_html"] == "html-failed"

    # 7. Ineligible PENDING row should NOT be purged
    c = get_cached_html("https://testpub.com/pending-old", db_path=db_path)
    assert c["raw_html"] == "html-pending"


def test_purge_idempotency(tmp_path):
    db_file = tmp_path / "test_purge_idempotency.db"
    db_path = str(db_file)
    init_db(db_path)

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO publications (id, name, base_url) VALUES (?, ?, ?)",
            ("testpub", "Test Publication", "https://testpub.com")
        )
        
        # Eligible UNVALIDATABLE row (validated 35 days ago)
        validation_date = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=35)).strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute("""
            INSERT INTO scraped_html_cache (url, publication_id, raw_html, validation, validation_date)
            VALUES (?, ?, ?, ?, ?)
        """, (
            "https://testpub.com/unval-old",
            "testpub",
            "<html><body>Older unvalidatable article</body></html>",
            "UNVALIDATABLE",
            validation_date
        ))
        conn.commit()
    finally:
        conn.close()

    # First run should purge
    res = purge_html_cache(db_path=db_path)
    assert res == {"validated": 0, "unvalidatable": 1, "total": 1}

    # Second run should do nothing and return 0 counts
    res2 = purge_html_cache(db_path=db_path)
    assert res2 == {"validated": 0, "unvalidatable": 0, "total": 0}


def test_cli_purge_cache(tmp_path, capsys, monkeypatch):
    db_file = tmp_path / "test_cli_purge.db"
    db_path = str(db_file)
    init_db(db_path)
    
    # Set the environment variable SQLITE_DB_PATH so main uses it
    monkeypatch.setenv("SQLITE_DB_PATH", db_path)
    
    # Seed the DB with some eligible rows
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO publications (id, name, base_url) VALUES (?, ?, ?)",
            ("testpub", "Test Publication", "https://testpub.com")
        )
        
        # Eligible UNVALIDATABLE row (validated 35 days ago)
        validation_date = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=35)).strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute("""
            INSERT INTO scraped_html_cache (url, publication_id, raw_html, validation, validation_date)
            VALUES (?, ?, ?, ?, ?)
        """, (
            "https://testpub.com/unval-old-cli",
            "testpub",
            "<html><body>Older unvalidatable article CLI</body></html>",
            "UNVALIDATABLE",
            validation_date
        ))
        conn.commit()
    finally:
        conn.close()
        
    from knowledge_map.cli.main import main
    
    # Run the purge-cache command through CLI
    try:
        main(["purge-cache"])
    except SystemExit as e:
        assert e.code == 0
        
    captured = capsys.readouterr()
    assert "Purged 0 validated rows." in captured.out
    assert "Purged 1 unvalidatable rows." in captured.out
    assert "Total rows purged: 1." in captured.out

