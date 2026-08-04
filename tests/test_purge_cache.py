import datetime
import sqlite3

import pytest

from knowledge_map.adapters.sqlite_db import get_cached_html, init_db, purge_html_cache


def _timestamp_days_ago(days: int) -> str:
    return (
        datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)
    ).strftime("%Y-%m-%d %H:%M:%S")


def _seed_publication(db_path: str) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO publications (id, name, base_url) VALUES (?, ?, ?)",
            ("testpub", "Test Publication", "https://testpub.com"),
        )


@pytest.mark.parametrize(
    "validation",
    ["VALIDATION_FAILED", "UNVALIDATABLE", None],
)
def test_purge_removes_html_older_than_thirty_days_regardless_of_validation(
    tmp_path,
    validation,
):
    db_path = str(tmp_path / "test_purge.db")
    init_db(db_path)
    _seed_publication(db_path)
    url = f"https://testpub.com/{validation or 'null'}"
    validation_date = _timestamp_days_ago(2)

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO scraped_html_cache (
                url,
                publication_id,
                raw_html,
                validation,
                validation_date,
                scraped_at,
                headline,
                description,
                relevance_status,
                relevance_label_source,
                fetch_status,
                raw_metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                url,
                "testpub",
                "old html",
                validation,
                validation_date,
                _timestamp_days_ago(31),
                "Retained headline",
                "Retained description",
                "RELEVANT",
                "HUMAN",
                200,
                '{"source": "retained"}',
            ),
        )

    assert purge_html_cache(db_path=db_path) == {"total": 1}

    cached = get_cached_html(url, db_path=db_path)
    assert cached is not None
    assert cached["raw_html"] is None
    assert cached["validation"] == validation
    assert cached["validation_date"] == validation_date
    assert cached["publication_id"] == "testpub"
    assert cached["headline"] == "Retained headline"
    assert cached["description"] == "Retained description"
    assert cached["relevance_status"] == "RELEVANT"
    assert cached["relevance_label_source"] == "HUMAN"
    assert cached["fetch_status"] == 200
    assert cached["raw_metadata_json"] == {"source": "retained"}


def test_purge_keeps_failed_article_html_scraped_within_thirty_days(tmp_path):
    db_path = str(tmp_path / "test_recent_purge.db")
    init_db(db_path)
    _seed_publication(db_path)
    url = "https://testpub.com/recent-failure"

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO scraped_html_cache (
                url, publication_id, raw_html, validation, validation_date, scraped_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                url,
                "testpub",
                "recent failed html",
                "VALIDATION_FAILED",
                _timestamp_days_ago(29),
                _timestamp_days_ago(29),
            ),
        )

    assert purge_html_cache(db_path=db_path) == {"total": 0}
    assert get_cached_html(url, db_path=db_path)["raw_html"] == "recent failed html"


def test_purge_uses_scrape_time_not_validation_or_story_time(tmp_path):
    db_path = str(tmp_path / "test_scrape_time_purge.db")
    init_db(db_path)
    _seed_publication(db_path)

    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            """
            INSERT INTO scraped_html_cache (
                url, publication_id, raw_html, validation, validation_date, scraped_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "https://testpub.com/old-scrape",
                    "testpub",
                    "old scrape html",
                    "VALIDATION_FAILED",
                    _timestamp_days_ago(1),
                    _timestamp_days_ago(31),
                ),
                (
                    "https://testpub.com/recent-scrape",
                    "testpub",
                    "recent scrape html",
                    "UNVALIDATABLE",
                    _timestamp_days_ago(31),
                    _timestamp_days_ago(1),
                ),
            ],
        )
        conn.execute(
            """
            INSERT INTO stories (title, url, content, status, completed_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                "Recent story",
                "https://testpub.com/old-scrape",
                "Stored content",
                "COMPLETED",
                _timestamp_days_ago(1),
            ),
        )

    assert purge_html_cache(db_path=db_path) == {"total": 1}
    assert get_cached_html(
        "https://testpub.com/old-scrape",
        db_path=db_path,
    )["raw_html"] is None
    assert get_cached_html(
        "https://testpub.com/recent-scrape",
        db_path=db_path,
    )["raw_html"] == "recent scrape html"


def test_purge_is_idempotent(tmp_path):
    db_path = str(tmp_path / "test_purge_idempotency.db")
    init_db(db_path)
    _seed_publication(db_path)

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO scraped_html_cache (
                url, publication_id, raw_html, validation, scraped_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                "https://testpub.com/old",
                "testpub",
                "old html",
                "PENDING",
                _timestamp_days_ago(31),
            ),
        )

    assert purge_html_cache(db_path=db_path) == {"total": 1}
    assert purge_html_cache(db_path=db_path) == {"total": 0}


def test_cli_purge_cache(tmp_path, capsys, monkeypatch):
    db_path = str(tmp_path / "test_cli_purge.db")
    init_db(db_path)
    _seed_publication(db_path)
    monkeypatch.setenv("SQLITE_DB_PATH", db_path)

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO scraped_html_cache (
                url, publication_id, raw_html, validation, scraped_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                "https://testpub.com/old-cli",
                "testpub",
                "old html",
                None,
                _timestamp_days_ago(31),
            ),
        )

    from knowledge_map.cli.main import main

    with pytest.raises(SystemExit) as exc_info:
        main(["purge-cache"])

    assert exc_info.value.code == 0
    assert "Total rows purged: 1." in capsys.readouterr().out
