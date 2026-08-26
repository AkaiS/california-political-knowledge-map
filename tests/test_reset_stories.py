import sqlite3
import sys
from pathlib import Path

import pytest

from knowledge_map.adapters.sqlite_db import (
    RESETTABLE_STORY_STATUSES,
    count_stories_by_status,
    init_db,
    reset_stories_to_unprocessed,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import reset_stories


def _seed(db_path: str, rows: list[tuple[str, str]]) -> None:
    """Insert one Story per (status, completed_at) pair."""

    with sqlite3.connect(db_path) as conn:
        for index, (status, completed_at) in enumerate(rows):
            conn.execute(
                "INSERT INTO stories (title, url, status, completed_at) "
                "VALUES (?, ?, ?, ?)",
                (f"Story {index}", f"https://example.com/{index}", status, completed_at),
            )


@pytest.fixture
def db(tmp_path) -> str:
    db_path = str(tmp_path / "document_store.db")
    init_db(db_path)
    return db_path


def _statuses(db_path: str) -> list[str]:
    with sqlite3.connect(db_path) as conn:
        return [row[0] for row in conn.execute("SELECT status FROM stories ORDER BY id")]


def test_the_default_statuses_are_the_two_a_run_gets_stuck_at():
    assert RESETTABLE_STORY_STATUSES == ("PROCESSING", "FAILED_DLQ")


def test_a_status_with_no_stories_is_counted_as_zero_not_omitted(db):
    _seed(db, [("FAILED_DLQ", None)])

    assert count_stories_by_status(("PROCESSING", "FAILED_DLQ"), db_path=db) == {
        "PROCESSING": 0,
        "FAILED_DLQ": 1,
    }


def test_the_reset_moves_only_the_named_statuses(db):
    _seed(
        db,
        [
            ("UNPROCESSED", None),
            ("FAILED_DLQ", None),
            ("COMPLETED", "2026-08-24 00:00:00"),
            ("PROCESSING", None),
            ("SYSTEM_ERROR", None),
        ],
    )

    reset_stories_to_unprocessed(("PROCESSING", "FAILED_DLQ"), db_path=db)

    assert _statuses(db) == [
        "UNPROCESSED",
        "UNPROCESSED",
        "COMPLETED",
        "UNPROCESSED",
        "SYSTEM_ERROR",
    ]


def test_the_reset_clears_a_stale_completion_time(db):
    _seed(db, [("FAILED_DLQ", "2026-08-24 00:00:00")])

    reset_stories_to_unprocessed(("FAILED_DLQ",), db_path=db)

    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT completed_at FROM stories").fetchone()[0] is None


def test_the_counts_returned_describe_the_rows_before_the_update(db):
    _seed(db, [("PROCESSING", None), ("FAILED_DLQ", None), ("FAILED_DLQ", None)])

    assert reset_stories_to_unprocessed(("PROCESSING", "FAILED_DLQ"), db_path=db) == {
        "PROCESSING": 1,
        "FAILED_DLQ": 2,
    }


def test_a_bare_return_at_the_prompt_changes_nothing(db, monkeypatch, capsys):
    """The prompt defaults to no, so Return must cancel rather than proceed."""

    _seed(db, [("FAILED_DLQ", None)])
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _prompt: "")

    assert reset_stories.main(["--db", db]) == 0
    assert _statuses(db) == ["FAILED_DLQ"]
    assert "Cancelled" in capsys.readouterr().out


@pytest.mark.parametrize("answer", ["n", "N", "no", "yeah", "sure", " "])
def test_only_an_explicit_yes_proceeds(db, monkeypatch, answer):
    _seed(db, [("FAILED_DLQ", None)])
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _prompt: answer)

    reset_stories.main(["--db", db])

    assert _statuses(db) == ["FAILED_DLQ"]


@pytest.mark.parametrize("answer", ["y", "Y", "yes", "  YES  "])
def test_an_explicit_yes_resets(db, monkeypatch, answer):
    _seed(db, [("FAILED_DLQ", None)])
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _prompt: answer)

    reset_stories.main(["--db", db])

    assert _statuses(db) == ["UNPROCESSED"]


def test_a_closed_stdin_is_not_consent(db, monkeypatch):
    _seed(db, [("FAILED_DLQ", None)])
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)

    def raise_eof(_prompt):
        raise EOFError

    monkeypatch.setattr("builtins.input", raise_eof)

    assert reset_stories.main(["--db", db]) == 0
    assert _statuses(db) == ["FAILED_DLQ"]


def test_a_non_interactive_run_refuses_rather_than_assuming_yes(db, monkeypatch, capsys):
    _seed(db, [("FAILED_DLQ", None)])
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)

    assert reset_stories.main(["--db", db]) == 1
    assert _statuses(db) == ["FAILED_DLQ"]
    assert "--yes" in capsys.readouterr().err


def test_yes_skips_the_prompt_entirely(db, monkeypatch):
    _seed(db, [("FAILED_DLQ", None)])
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)

    def fail_if_asked(_prompt):
        raise AssertionError("--yes must not prompt")

    monkeypatch.setattr("builtins.input", fail_if_asked)

    assert reset_stories.main(["--db", db, "--yes"]) == 0
    assert _statuses(db) == ["UNPROCESSED"]


def test_a_dry_run_never_prompts_and_never_writes(db, monkeypatch, capsys):
    _seed(db, [("FAILED_DLQ", None)])

    def fail_if_asked(_prompt):
        raise AssertionError("--dry-run must not prompt")

    monkeypatch.setattr("builtins.input", fail_if_asked)

    assert reset_stories.main(["--db", db, "--dry-run"]) == 0
    assert _statuses(db) == ["FAILED_DLQ"]
    assert "Would reset 1 Story" in capsys.readouterr().out


def test_an_already_unprocessed_story_is_left_alone_by_default(db, monkeypatch):
    """UNPROCESSED is no longer in the default set; the run has not touched it."""

    _seed(db, [("UNPROCESSED", None)])

    def fail_if_asked(_prompt):
        raise AssertionError("an empty reset must not prompt")

    monkeypatch.setattr("builtins.input", fail_if_asked)

    assert reset_stories.main(["--db", db]) == 0
    assert _statuses(db) == ["UNPROCESSED"]


def test_nothing_to_reset_exits_cleanly_without_prompting(db, monkeypatch, capsys):
    _seed(db, [("COMPLETED", "2026-08-24 00:00:00")])

    def fail_if_asked(_prompt):
        raise AssertionError("an empty reset must not prompt")

    monkeypatch.setattr("builtins.input", fail_if_asked)

    assert reset_stories.main(["--db", db]) == 0
    assert "Nothing to reset" in capsys.readouterr().out


def test_repeated_status_flags_do_not_double_count(db, monkeypatch, capsys):
    _seed(db, [("FAILED_DLQ", None)])
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)

    reset_stories.main(["--db", db, "--yes", "--status", "FAILED_DLQ", "--status", "FAILED_DLQ"])

    assert "Reset 1 Story" in capsys.readouterr().out


def test_a_missing_database_is_reported_rather_than_traced(tmp_path, capsys):
    missing = str(tmp_path / "nope.db")

    assert reset_stories.main(["--db", missing]) == 1
    assert "Could not read" in capsys.readouterr().err
