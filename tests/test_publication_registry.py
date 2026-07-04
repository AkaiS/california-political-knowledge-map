import sqlite3
import pytest
from unittest.mock import patch
from knowledge_map.adapters.sqlite_db import init_db

def test_publications_table_schema(tmp_path):
    db_file = tmp_path / "test_publications.db"
    db_path = str(db_file)
    init_db(db_path)
    
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        # Verify the table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='publications'")
        table_exists = cursor.fetchone()
        assert table_exists is not None
        
        # Verify column names and default values/types
        cursor.execute("PRAGMA table_info(publications)")
        columns = {col[1]: {"type": col[2], "notnull": col[3], "dflt_value": col[4], "pk": col[5]} for col in cursor.fetchall()}
        
        # Check primary key
        assert columns["id"]["pk"] == 1
        assert columns["id"]["type"].upper() == "TEXT"
        
        # Check other fields
        assert columns["name"]["notnull"] == 1
        assert columns["name"]["type"].upper() == "TEXT"
        
        assert columns["base_url"]["notnull"] == 1
        assert columns["base_url"]["type"].upper() == "TEXT"
        
        assert columns["crawl_delay"]["type"].upper() == "REAL"
        assert float(columns["crawl_delay"]["dflt_value"]) == 2.0
        
        assert columns["max_concurrency"]["type"].upper() == "INTEGER"
        assert int(columns["max_concurrency"]["dflt_value"]) == 2
        
        assert columns["use_robots_txt"]["type"].upper() == "BOOLEAN"
        assert int(columns["use_robots_txt"]["dflt_value"]) == 1
        
        assert columns["discovery_config_json"]["type"].upper() == "TEXT"
        assert columns["discovery_config_json"]["dflt_value"] is None
        
        assert columns["archive_cutoff_years"]["type"].upper() == "INTEGER"
        assert int(columns["archive_cutoff_years"]["dflt_value"]) == 5
        
        assert columns["validation_paused"]["type"].upper() == "BOOLEAN"
        assert int(columns["validation_paused"]["dflt_value"]) == 0
        
        assert columns["failure_points"]["type"].upper() == "INTEGER"
        assert int(columns["failure_points"]["dflt_value"]) == 0
        
        assert columns["healing_in_progress"]["type"].upper() == "BOOLEAN"
        assert int(columns["healing_in_progress"]["dflt_value"]) == 0
        
        assert columns["created_at"]["type"].upper() == "DATETIME"
        assert columns["created_at"]["dflt_value"] == "CURRENT_TIMESTAMP"
    finally:
        conn.close()

def test_register_and_get_publication(tmp_path):
    from knowledge_map.adapters.sqlite_db import register_publication, get_publication, get_all_publications
    
    db_file = tmp_path / "test_publications.db"
    db_path = str(db_file)
    init_db(db_path)
    
    # Test registration with custom and default values
    register_publication(
        pub_id="calmatters",
        name="CalMatters",
        base_url="https://calmatters.org",
        crawl_delay=1.5,
        max_concurrency=3,
        use_robots_txt=False,
        discovery_config_json='{"listing_urls": ["https://calmatters.org/news/"]}',
        archive_cutoff_years=3,
        db_path=db_path
    )
    
    # Verify retrieval via get_publication
    pub = get_publication("calmatters", db_path=db_path)
    assert pub is not None
    assert pub["id"] == "calmatters"
    assert pub["name"] == "CalMatters"
    assert pub["base_url"] == "https://calmatters.org"
    assert pub["crawl_delay"] == 1.5
    assert pub["max_concurrency"] == 3
    assert pub["use_robots_txt"] is False  # should be parsed/returned as boolean
    assert pub["discovery_config_json"] == '{"listing_urls": ["https://calmatters.org/news/"]}'
    assert pub["archive_cutoff_years"] == 3
    # Check circuit-breaker defaults
    assert pub["validation_paused"] is False
    assert pub["failure_points"] == 0
    assert pub["healing_in_progress"] is False
    assert pub["created_at"] is not None
    
    # Verify retrieval of a non-existent publication returns None
    assert get_publication("nonexistent", db_path=db_path) is None
    
    # Register another publication with default values
    register_publication(
        pub_id="la-times",
        name="LA Times",
        base_url="https://latimes.com",
        db_path=db_path
    )
    
    pub_la = get_publication("la-times", db_path=db_path)
    assert pub_la is not None
    assert pub_la["id"] == "la-times"
    assert pub_la["crawl_delay"] == 2.0
    assert pub_la["max_concurrency"] == 2
    assert pub_la["use_robots_txt"] is True
    assert pub_la["discovery_config_json"] is None
    assert pub_la["archive_cutoff_years"] == 5
    
    # Verify get_all_publications
    all_pubs = get_all_publications(db_path=db_path)
    assert len(all_pubs) == 2
    assert {p["id"] for p in all_pubs} == {"calmatters", "la-times"}

def test_register_duplicate_publication_fails(tmp_path):
    from knowledge_map.adapters.sqlite_db import register_publication
    
    db_file = tmp_path / "test_publications.db"
    db_path = str(db_file)
    init_db(db_path)
    
    register_publication(
        pub_id="calmatters",
        name="CalMatters",
        base_url="https://calmatters.org",
        db_path=db_path
    )
    
    # Registering again with duplicate ID should raise ValueError
    with pytest.raises(ValueError) as excinfo:
        register_publication(
            pub_id="calmatters",
            name="CalMatters Duplicate",
            base_url="https://calmatters.org",
            db_path=db_path
        )
    assert "already registered" in str(excinfo.value)

def test_cli_register_publication_success(tmp_path, monkeypatch):
    from knowledge_map.cli.main import main
    from knowledge_map.adapters.sqlite_db import get_publication
    
    db_file = tmp_path / "test_cli_pub.db"
    db_path = str(db_file)
    init_db(db_path)
    
    monkeypatch.setenv("SQLITE_DB_PATH", db_path)
    
    # We mock the bootstrapper to verify it's called
    with patch("knowledge_map.cli.main.bootstrap_publication_stub") as mock_bootstrap:
        try:
            main([
                "register-publication",
                "--id", "sfchronicle",
                "--name", "SF Chronicle",
                "--base-url", "https://sfchronicle.com",
                "--crawl-delay", "3.0",
                "--max-concurrency", "4",
                "--no-robots-txt",
                "--discovery-config-json", '{"sitemap_urls": ["https://sfchronicle.com/sitemap.xml"]}',
                "--archive-cutoff-years", "2"
            ])
        except SystemExit as e:
            assert e.code == 0
            
        # Verify it was inserted in the DB
        pub = get_publication("sfchronicle", db_path=db_path)
        assert pub is not None
        assert pub["name"] == "SF Chronicle"
        assert pub["base_url"] == "https://sfchronicle.com"
        assert pub["crawl_delay"] == 3.0
        assert pub["max_concurrency"] == 4
        assert pub["use_robots_txt"] is False
        assert pub["discovery_config_json"] == '{"sitemap_urls": ["https://sfchronicle.com/sitemap.xml"]}'
        assert pub["archive_cutoff_years"] == 2
        
        # Verify the bootstrapper stub was invoked (Behavior 6)
        mock_bootstrap.assert_called_once_with("sfchronicle")

def test_cli_register_publication_duplicate_fails(tmp_path, monkeypatch, capsys):
    from knowledge_map.cli.main import main
    from knowledge_map.adapters.sqlite_db import register_publication
    
    db_file = tmp_path / "test_cli_pub_dup.db"
    db_path = str(db_file)
    init_db(db_path)
    
    register_publication(
        pub_id="calmatters",
        name="CalMatters",
        base_url="https://calmatters.org",
        db_path=db_path
    )
    
    monkeypatch.setenv("SQLITE_DB_PATH", db_path)
    
    # Registering again via CLI should fail cleanly with non-zero exit code
    with pytest.raises(SystemExit) as exc_info:
        main([
            "register-publication",
            "--id", "calmatters",
            "--name", "CalMatters Duplicate",
            "--base-url", "https://calmatters.org"
        ])
    assert exc_info.value.code == 1
    
    # Check that a clean message is printed
    captured = capsys.readouterr()
    assert "already registered" in captured.err or "already registered" in captured.out or "already registered" in captured.err.lower() or "already registered" in captured.out.lower()


def test_register_publication_with_categories_tracer(tmp_path):
    from knowledge_map.adapters.sqlite_db import register_publication, get_publication
    import json
    
    db_file = tmp_path / "test_publications.db"
    db_path = str(db_file)
    init_db(db_path)
    
    # Register with categories
    register_publication(
        pub_id="calmatters",
        name="CalMatters",
        base_url="https://calmatters.org",
        categories=["housing", "politics"],
        db_path=db_path
    )
    
    pub = get_publication("calmatters", db_path=db_path)
    assert pub is not None
    assert pub["discovery_config_json"] is not None
    config = json.loads(pub["discovery_config_json"])
    assert config == {"valid_categories": ["housing", "politics"]}


def test_register_publication_merges_categories(tmp_path):
    from knowledge_map.adapters.sqlite_db import register_publication, get_publication
    import json
    
    db_file = tmp_path / "test_publications.db"
    db_path = str(db_file)
    init_db(db_path)
    
    # Register with categories and existing discovery_config_json
    register_publication(
        pub_id="calmatters",
        name="CalMatters",
        base_url="https://calmatters.org",
        discovery_config_json='{"listing_urls": ["https://calmatters.org/news/"]}',
        categories=["housing", "politics"],
        db_path=db_path
    )
    
    pub = get_publication("calmatters", db_path=db_path)
    assert pub is not None
    assert pub["discovery_config_json"] is not None
    config = json.loads(pub["discovery_config_json"])
    assert config == {
        "listing_urls": ["https://calmatters.org/news/"],
        "valid_categories": ["housing", "politics"]
    }


def test_register_publication_preserves_config_when_categories_none(tmp_path):
    from knowledge_map.adapters.sqlite_db import register_publication, get_publication
    import json
    
    db_file = tmp_path / "test_publications.db"
    db_path = str(db_file)
    init_db(db_path)
    
    # Register with categories=None and existing discovery_config_json (containing valid_categories)
    register_publication(
        pub_id="calmatters",
        name="CalMatters",
        base_url="https://calmatters.org",
        discovery_config_json='{"listing_urls": ["https://calmatters.org/news/"], "valid_categories": ["housing"]}',
        categories=None,
        db_path=db_path
    )
    
    pub = get_publication("calmatters", db_path=db_path)
    assert pub is not None
    assert pub["discovery_config_json"] is not None
    config = json.loads(pub["discovery_config_json"])
    assert config == {
        "listing_urls": ["https://calmatters.org/news/"],
        "valid_categories": ["housing"]
    }


def test_cli_register_publication_with_categories(tmp_path, monkeypatch):
    from knowledge_map.cli.main import main
    from knowledge_map.adapters.sqlite_db import get_publication
    import json
    
    db_file = tmp_path / "test_cli_pub.db"
    db_path = str(db_file)
    init_db(db_path)
    
    monkeypatch.setenv("SQLITE_DB_PATH", db_path)
    
    with patch("knowledge_map.cli.main.bootstrap_publication_stub") as mock_bootstrap:
        try:
            main([
                "register-publication",
                "--id", "calmatters",
                "--name", "CalMatters",
                "--base-url", "https://calmatters.org",
                "--categories", "housing", "politics"
            ])
        except SystemExit as e:
            assert e.code == 0
            
        pub = get_publication("calmatters", db_path=db_path)
        assert pub is not None
        assert pub["discovery_config_json"] is not None
        config = json.loads(pub["discovery_config_json"])
        assert config == {"valid_categories": ["housing", "politics"]}
        
        mock_bootstrap.assert_called_once_with("calmatters")


def test_update_publication_success(tmp_path):
    from knowledge_map.adapters.sqlite_db import register_publication, get_publication, update_publication
    import json
    
    db_file = tmp_path / "test_publications_update.db"
    db_path = str(db_file)
    init_db(db_path)
    
    # 1. Register base publication
    register_publication(
        pub_id="calmatters",
        name="CalMatters",
        base_url="https://calmatters.org",
        crawl_delay=2.0,
        max_concurrency=2,
        use_robots_txt=True,
        discovery_config_json='{"listing_urls": ["https://calmatters.org/news/"]}',
        archive_cutoff_years=5,
        categories=["housing", "politics"],
        db_path=db_path
    )
    
    # 2. Perform partial update of fields
    update_publication(
        pub_id="calmatters",
        name="CalMatters Updated",
        crawl_delay=3.5,
        use_robots_txt=False,
        db_path=db_path
    )
    
    pub = get_publication("calmatters", db_path=db_path)
    assert pub is not None
    assert pub["name"] == "CalMatters Updated"
    assert pub["crawl_delay"] == 3.5
    assert pub["use_robots_txt"] is False
    # Verify categories and other fields are preserved
    assert pub["max_concurrency"] == 2
    config = json.loads(pub["discovery_config_json"])
    assert config["listing_urls"] == ["https://calmatters.org/news/"]
    assert config["valid_categories"] == ["housing", "politics"]
    
    # 3. Update categories only
    update_publication(
        pub_id="calmatters",
        categories=["education"],
        db_path=db_path
    )
    pub = get_publication("calmatters", db_path=db_path)
    config = json.loads(pub["discovery_config_json"])
    assert config["valid_categories"] == ["education"]
    assert config["listing_urls"] == ["https://calmatters.org/news/"]
    
    # 4. Clear categories
    update_publication(
        pub_id="calmatters",
        categories=[],
        db_path=db_path
    )
    pub = get_publication("calmatters", db_path=db_path)
    config = json.loads(pub["discovery_config_json"])
    assert "valid_categories" not in config
    assert config["listing_urls"] == ["https://calmatters.org/news/"]

    # 5. Overwrite config JSON string, ensuring valid_categories is not there (since it was cleared)
    update_publication(
        pub_id="calmatters",
        discovery_config_json='{"sitemap_urls": ["https://calmatters.org/sitemap.xml"]}',
        db_path=db_path
    )
    pub = get_publication("calmatters", db_path=db_path)
    config = json.loads(pub["discovery_config_json"])
    assert config == {"sitemap_urls": ["https://calmatters.org/sitemap.xml"]}
    assert "valid_categories" not in config
    assert "listing_urls" not in config

    # 6. Re-add categories
    update_publication(
        pub_id="calmatters",
        categories=["environment"],
        db_path=db_path
    )
    
    # 7. Overwrite config JSON string, ensuring valid_categories (which is now environment) is preserved
    update_publication(
        pub_id="calmatters",
        discovery_config_json='{"sitemap_urls": ["https://calmatters.org/new-sitemap.xml"]}',
        db_path=db_path
    )
    pub = get_publication("calmatters", db_path=db_path)
    config = json.loads(pub["discovery_config_json"])
    assert config["sitemap_urls"] == ["https://calmatters.org/new-sitemap.xml"]
    assert config["valid_categories"] == ["environment"]


def test_update_publication_nonexistent_fails(tmp_path):
    from knowledge_map.adapters.sqlite_db import update_publication
    import pytest
    
    db_file = tmp_path / "test_publications_update_err.db"
    db_path = str(db_file)
    init_db(db_path)
    
    with pytest.raises(ValueError) as excinfo:
        update_publication(pub_id="nonexistent", name="Fails", db_path=db_path)
    assert "is not registered" in str(excinfo.value)


def test_cli_update_publication_success(tmp_path, monkeypatch):
    from knowledge_map.cli.main import main
    from knowledge_map.adapters.sqlite_db import register_publication, get_publication
    import json
    
    db_file = tmp_path / "test_cli_update.db"
    db_path = str(db_file)
    init_db(db_path)
    
    register_publication(
        pub_id="calmatters",
        name="CalMatters",
        base_url="https://calmatters.org",
        db_path=db_path
    )
    
    monkeypatch.setenv("SQLITE_DB_PATH", db_path)
    
    try:
        main([
            "update-publication",
            "--id", "calmatters",
            "--name", "CalMatters Updated",
            "--categories", "politics", "environment",
            "--crawl-delay", "4.5"
        ])
    except SystemExit as e:
        assert e.code == 0
        
    pub = get_publication("calmatters", db_path=db_path)
    assert pub is not None
    assert pub["name"] == "CalMatters Updated"
    assert pub["crawl_delay"] == 4.5
    config = json.loads(pub["discovery_config_json"])
    assert config["valid_categories"] == ["politics", "environment"]


def test_cli_update_publication_nonexistent_fails(tmp_path, monkeypatch, capsys):
    from knowledge_map.cli.main import main
    
    db_file = tmp_path / "test_cli_update_fail.db"
    db_path = str(db_file)
    init_db(db_path)
    
    monkeypatch.setenv("SQLITE_DB_PATH", db_path)
    
    with pytest.raises(SystemExit) as exc_info:
        main([
            "update-publication",
            "--id", "nonexistent",
            "--name", "Does Not Exist"
        ])
    assert exc_info.value.code == 1
    
    captured = capsys.readouterr()
    assert "is not registered" in captured.err or "is not registered" in captured.out or "is not registered" in captured.err.lower() or "is not registered" in captured.out.lower()





