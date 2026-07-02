import sqlite3
import pytest
from knowledge_map.adapters.sqlite_db import init_db

def test_publication_selectors_table_schema(tmp_path):
    db_file = tmp_path / "test_selectors.db"
    db_path = str(db_file)
    init_db(db_path)
    
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        # Verify the table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='publication_selectors'")
        table_exists = cursor.fetchone()
        assert table_exists is not None
        
        # Verify column names, types, and constraints
        cursor.execute("PRAGMA table_info(publication_selectors)")
        columns = {col[1]: {"type": col[2], "notnull": col[3], "dflt_value": col[4], "pk": col[5]} for col in cursor.fetchall()}
        
        # Check primary key
        assert columns["id"]["pk"] == 1
        assert columns["id"]["type"].upper() == "INTEGER"
        
        # Check other fields
        assert columns["publication_id"]["notnull"] == 1
        assert columns["publication_id"]["type"].upper() == "TEXT"
        
        assert columns["selectors_json"]["notnull"] == 1
        assert columns["selectors_json"]["type"].upper() == "TEXT"
        
        assert columns["earliest_success_date"]["type"].upper() == "DATETIME"
        assert columns["latest_success_date"]["type"].upper() == "DATETIME"
        
        assert columns["created_at"]["type"].upper() == "DATETIME"
        assert columns["created_at"]["dflt_value"] == "CURRENT_TIMESTAMP"
    finally:
        conn.close()

def test_insert_and_retrieve_selector_version(tmp_path):
    from knowledge_map.adapters.sqlite_db import register_publication, insert_selector_version, get_selector_versions, update_selector_window
    
    db_file = tmp_path / "test_selectors.db"
    db_path = str(db_file)
    init_db(db_path)
    
    # Register publication first since FK constraints require it
    register_publication(
        pub_id="calmatters",
        name="CalMatters",
        base_url="https://calmatters.org",
        db_path=db_path
    )
    
    selectors_json = '{"title": "h1.title", "author": "a.author", "date": "time", "body": "div.content"}'
    earliest = "2026-07-01T00:00:00Z"
    latest = "2026-07-02T00:00:00Z"
    
    version_id = insert_selector_version(
        publication_id="calmatters",
        selectors_json=selectors_json,
        earliest_success_date=earliest,
        latest_success_date=latest,
        db_path=db_path
    )
    assert version_id > 0
    
    versions = get_selector_versions("calmatters", db_path=db_path)
    assert len(versions) == 1
    assert versions[0]["id"] == version_id
    assert versions[0]["publication_id"] == "calmatters"
    assert versions[0]["selectors_json"] == selectors_json
    assert versions[0]["earliest_success_date"] == earliest
    assert versions[0]["latest_success_date"] == latest
    
    # Test updating window
    new_earliest = "2026-06-30T00:00:00Z"
    new_latest = "2026-07-03T00:00:00Z"
    update_selector_window(
        selector_version_id=version_id,
        earliest_success_date=new_earliest,
        latest_success_date=new_latest,
        db_path=db_path
    )
    
    versions_updated = get_selector_versions("calmatters", db_path=db_path)
    assert versions_updated[0]["earliest_success_date"] == new_earliest
    assert versions_updated[0]["latest_success_date"] == new_latest

def test_selector_pydantic_schemas():
    from knowledge_map.schemas.selectors import ArticleSelectors, SelectorVersion
    from datetime import datetime, timezone
    
    selectors = ArticleSelectors(
        title="h1.title",
        author="a.author",
        date="time.date",
        body="div.body"
    )
    
    assert selectors.title == "h1.title"
    
    now = datetime.now(timezone.utc)
    version = SelectorVersion(
        id=1,
        publication_id="calmatters",
        selectors=selectors,
        earliest_success_date=now,
        latest_success_date=now,
        created_at=now
    )
    
    assert version.publication_id == "calmatters"
    assert version.selectors.title == "h1.title"
    assert version.earliest_success_date == now

def test_proximity_ordering_and_widening(tmp_path):
    from datetime import datetime, timezone, timedelta
    from knowledge_map.adapters.sqlite_db import register_publication
    from knowledge_map.schemas.selectors import ArticleSelectors
    from knowledge_map.core.selectors import (
        add_selector_version,
        get_selector_versions_by_proximity,
        widen_selector_version_window
    )
    
    db_file = tmp_path / "test_selectors.db"
    db_path = str(db_file)
    init_db(db_path)
    
    # Register publication
    register_publication("calmatters", "CalMatters", "https://calmatters.org", db_path=db_path)
    
    # Selectors definitions
    selectors1 = ArticleSelectors(title="t1", author="a1", date="d1", body="b1")
    selectors2 = ArticleSelectors(title="t2", author="a2", date="d2", body="b2")
    selectors3 = ArticleSelectors(title="t3", author="a3", date="d3", body="b3")
    
    base_time = datetime(2026, 7, 2, 12, 0, 0, tzinfo=timezone.utc)
    
    # Version 1: window [base_time - 2 hours, base_time - 1 hour]
    v1_id = add_selector_version(
        publication_id="calmatters",
        selectors=selectors1,
        earliest_success_date=base_time - timedelta(hours=2),
        latest_success_date=base_time - timedelta(hours=1),
        db_path=db_path
    )
    
    # Version 2: window [base_time + 1 hour, base_time + 2 hours]
    v2_id = add_selector_version(
        publication_id="calmatters",
        selectors=selectors2,
        earliest_success_date=base_time + timedelta(hours=1),
        latest_success_date=base_time + timedelta(hours=2),
        db_path=db_path
    )
    
    # Version 3: window [base_time - 30 mins, base_time + 30 mins]
    v3_id = add_selector_version(
        publication_id="calmatters",
        selectors=selectors3,
        earliest_success_date=base_time - timedelta(minutes=30),
        latest_success_date=base_time + timedelta(minutes=30),
        db_path=db_path
    )
    
    # Test case 1: fetch date D is exactly at base_time.
    # D is inside v3's window, so distance to v3 is 0 (first).
    # v1 latest is 1 hour before base_time. Distance to v1 is 1 hour.
    # v2 earliest is 1 hour after base_time. Distance to v2 is 1 hour.
    # v1 and v2 are tied for distance (1 hour). Under our tie-breaking rules,
    # the newer version (higher ID) comes first, which is v2.
    # Thus, expected order: v3, v2, v1.
    versions = get_selector_versions_by_proximity("calmatters", fetch_date=base_time, db_path=db_path)
    assert [v.id for v in versions] == [v3_id, v2_id, v1_id]
    
    # Test case 2: fetch date D is before-window (e.g., base_time - 3 hours).
    # Distance to v1: from base_time - 3 hours to base_time - 2 hours = 1 hour.
    # Distance to v3: from base_time - 3 hours to base_time - 30 mins = 2.5 hours.
    # Distance to v2: from base_time - 3 hours to base_time + 1 hour = 4 hours.
    # Expected order: v1, v3, v2.
    before_time = base_time - timedelta(hours=3)
    versions_before = get_selector_versions_by_proximity("calmatters", fetch_date=before_time, db_path=db_path)
    assert [v.id for v in versions_before] == [v1_id, v3_id, v2_id]
    
    # Test case 3: fetch date D is after-window (e.g., base_time + 3 hours).
    # Distance to v2: from base_time + 3 hours to base_time + 2 hours = 1 hour.
    # Distance to v3: from base_time + 3 hours to base_time + 30 mins = 2.5 hours.
    # Distance to v1: from base_time + 3 hours to base_time - 1 hour = 4 hours.
    # Expected order: v2, v3, v1.
    after_time = base_time + timedelta(hours=3)
    versions_after = get_selector_versions_by_proximity("calmatters", fetch_date=after_time, db_path=db_path)
    assert [v.id for v in versions_after] == [v2_id, v3_id, v1_id]
    
    # Test case 4: Widen success window.
    # Let's say v3 (winning version) succeeds on extraction at `base_time + 1 hour`.
    # Widening v3 window to include `base_time + 1 hour`.
    widen_time = base_time + timedelta(hours=1)
    widen_selector_version_window(v3_id, fetch_date=widen_time, db_path=db_path)
    
    # Verify the window for v3 has been updated
    versions_post_widen = get_selector_versions_by_proximity("calmatters", fetch_date=base_time, db_path=db_path)
    v3_updated = next(v for v in versions_post_widen if v.id == v3_id)
    assert v3_updated.earliest_success_date == base_time - timedelta(minutes=30)
    assert v3_updated.latest_success_date == widen_time
    
    # Now, try-order fallback simulation:
    # A component wants to run validation. It tries versions in order:
    # If first two fail, we fall back to the third. If that fails, it's exhausted.
    tried = []
    success_on_v1 = False
    for v in versions:
        tried.append(v.id)
        if v.id == v1_id:
            # Simulate success on v1 (e.g. last fallback)
            success_on_v1 = True
            widen_selector_version_window(v.id, fetch_date=base_time, db_path=db_path)
            break
            
    assert tried == [v3_id, v2_id, v1_id]
    assert success_on_v1 is True
    
    # Verify v1 window is widened
    versions_final = get_selector_versions_by_proximity("calmatters", fetch_date=base_time, db_path=db_path)
    v1_updated = next(v for v in versions_final if v.id == v1_id)
    # v1's old window: [base_time - 2 hours, base_time - 1 hour]
    # base_time is after latest, so new latest should be base_time
    assert v1_updated.earliest_success_date == base_time - timedelta(hours=2)
    assert v1_updated.latest_success_date == base_time



