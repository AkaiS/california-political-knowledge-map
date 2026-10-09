"""Suite-wide defaults.

The test suite is deterministic and offline, so no test may depend on a local
llama.cpp server being up. The Model Reachability Check is bypassed here rather
than on every gated command line; the tests that cover the check itself opt
back in by removing this.
"""

import pytest


@pytest.fixture(autouse=True)
def isolate_source_guide_store(monkeypatch, tmp_path):
    from knowledge_map.adapters import sqlite_db

    monkeypatch.setattr(
        sqlite_db, "DEFAULT_DB_PATH", str(tmp_path / "document_store.db")
    )
    monkeypatch.setenv("SQLITE_DB_PATH", str(tmp_path / "document_store.db"))


@pytest.fixture(autouse=True)
def skip_model_reachability_check(monkeypatch):
    # Imported lazily: the CLI module pulls in the whole adapter stack, and
    # collection should not pay for that in every test session.
    from knowledge_map.utils.reachability import SKIP_MODEL_CHECK_ENV

    monkeypatch.setenv(SKIP_MODEL_CHECK_ENV, "1")
