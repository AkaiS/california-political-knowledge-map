import os
import json
import sqlite3
import pytest
from unittest.mock import patch, MagicMock
from knowledge_map.adapters.sqlite_db import (
    init_db,
    cache_scraped_html,
    get_cached_html,
    update_relevance_status,
    clear_cached_html,
    is_url_known
)
from knowledge_map.core.relevance_classification import backfill_article_metadata
from knowledge_map.core.relevance import (
    serialize_embedding,
    deserialize_embedding,
    classify_article,
    WEIGHTS_PATH
)
from classifier.trainer import get_training_rows, train_classifier

def test_blob_conversions():
    """Verify that binary BLOB conversions preserve float array precision."""
    emb = [0.123456, -0.987654, 0.0, 1.2345e-5, 999.99]
    blob = serialize_embedding(emb)
    assert blob is not None
    emb_back = deserialize_embedding(blob)
    assert emb_back is not None
    assert len(emb_back) == len(emb)
    # Check close precision for 32-bit floats
    for orig, back in zip(emb, emb_back):
        assert pytest.approx(orig, rel=1e-5) == back

    assert serialize_embedding(None) is None
    assert deserialize_embedding(None) is None
    assert deserialize_embedding(b"") == []


def test_schema_migration(tmp_path):
    """Verify database migration functions and consolidated table operations."""
    db_file = tmp_path / "test_migration.db"
    db_path = str(db_file)

    # 1. Manually set up the database using the OLD schema
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE scraped_html_cache (
            url TEXT PRIMARY KEY,
            publication_id TEXT NOT NULL,
            raw_html TEXT,
            validation TEXT CHECK(validation IN ('PENDING', 'VALIDATED', 'VALIDATION_FAILED', 'UNVALIDATABLE')) DEFAULT 'PENDING',
            validation_date DATETIME,
            scraped_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE rejected_articles (
            url TEXT PRIMARY KEY,
            publication_id TEXT NOT NULL,
            relevance_status TEXT CHECK(relevance_status IN ('IRRELEVANT', 'INCONCLUSIVE')) NOT NULL,
            metadata_json TEXT,
            checked_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Insert some old data
    cursor.execute(
        "INSERT INTO scraped_html_cache (url, publication_id, raw_html) VALUES (?, ?, ?)",
        ("https://example.com/relevant", "pub1", "<html>relevant article</html>")
    )
    cursor.execute(
        "INSERT INTO rejected_articles (url, publication_id, relevance_status, metadata_json) VALUES (?, ?, ?, ?)",
        ("https://example.com/irrelevant", "pub1", "IRRELEVANT", json.dumps({"headline": "No politics", "description": "some text"}))
    )
    cursor.execute(
        "INSERT INTO rejected_articles (url, publication_id, relevance_status, metadata_json) VALUES (?, ?, ?, ?)",
        ("https://example.com/inconclusive", "pub1", "INCONCLUSIVE", json.dumps({"headline": "Local politics maybe", "description": "local council"}))
    )
    conn.commit()
    conn.close()

    # 2. Run init_db which should execute the migration
    init_db(db_path)

    # 3. Verify the migrated schema and records
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Verify rejected_articles table is dropped
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='rejected_articles'")
    assert cursor.fetchone() is None

    # Verify the contents of scraped_html_cache
    cursor.execute("SELECT url, raw_html, validation, relevance_status, raw_metadata_json FROM scraped_html_cache")
    rows = {r[0]: r for r in cursor.fetchall()}
    assert len(rows) == 3

    # Check relevant article
    assert rows["https://example.com/relevant"][1] == "<html>relevant article</html>"
    assert rows["https://example.com/relevant"][2] == "PENDING"
    assert rows["https://example.com/relevant"][3] == "PENDING"

    # Check irrelevant article
    assert rows["https://example.com/irrelevant"][1] is None
    assert rows["https://example.com/irrelevant"][2] is None
    assert rows["https://example.com/irrelevant"][3] == "IRRELEVANT"
    meta_irrelevant = json.loads(rows["https://example.com/irrelevant"][4])
    assert meta_irrelevant["headline"] == "No politics"

    # Check inconclusive article
    assert rows["https://example.com/inconclusive"][1] is None
    assert rows["https://example.com/inconclusive"][2] is None
    assert rows["https://example.com/inconclusive"][3] == "INCONCLUSIVE"
    meta_inconclusive = json.loads(rows["https://example.com/inconclusive"][4])
    assert meta_inconclusive["headline"] == "Local politics maybe"

    conn.close()


def test_model_inference_boundaries(tmp_path):
    """Test model inference using dummy weights to verify probability boundaries (p >= 0.7, 0.3 <= p < 0.7, p < 0.3)."""
    # Create mock weights: dimension is 3
    # dot_product = coef * embedding + intercept
    # p = 1 / (1 + exp(-dot_product))
    dummy_weights = {
        "coefficients": [1.0, 2.0, -1.0],
        "intercept": 0.0
    }

    # Write dummy weights temporarily
    os.makedirs(os.path.dirname(WEIGHTS_PATH), exist_ok=True)
    with open(WEIGHTS_PATH, "w") as f:
        json.dump(dummy_weights, f)

    try:
        from knowledge_map.core.relevance import load_classifier_weights
        # Clear cache to force reload
        import knowledge_map.core.relevance
        knowledge_map.core.relevance._cached_weights = None

        # 1. High probability (dot product = 2.0 + 2.0 - 0.0 = 4.0 -> p ~ 0.98 >= 0.7)
        # Should be RELEVANT
        status_high = classify_article("H", "D", [2.0, 1.0, 0.0])
        assert status_high == "RELEVANT"

        # 2. Medium probability (dot product = 0.1 * 1 + 0 * 2 - 0.1 * -1 = 0.2 -> p ~ 0.55 between 0.3 and 0.7)
        # Should be INCONCLUSIVE
        status_med = classify_article("H", "D", [0.1, 0.0, -0.1])
        assert status_med == "INCONCLUSIVE"

        # 3. Low probability (dot product = -3.0 * 1 + 0 * 2 - 1.0 * -1 = -2.0 -> p ~ 0.12 < 0.3)
        # Should be IRRELEVANT
        status_low = classify_article("H", "D", [-3.0, 0.0, 1.0])
        assert status_low == "IRRELEVANT"

    finally:
        # Clean up weights file
        if os.path.exists(WEIGHTS_PATH):
            os.remove(WEIGHTS_PATH)
        import knowledge_map.core.relevance
        knowledge_map.core.relevance._cached_weights = None


def test_sqlite_cache_helpers(tmp_path):
    """Verify cache metadata, relevance fields, and URL recognition."""
    db_file = tmp_path / "test_helpers.db"
    db_path = str(db_file)
    init_db(db_path)

    cache_scraped_html(
        "https://example.com/1", "pub1", None,
        relevance_status="IRRELEVANT", raw_metadata_json={"headline": "H1"},
        db_path=db_path
    )
    cache_scraped_html(
        "https://example.com/2", "pub1", None,
        relevance_status="INCONCLUSIVE", raw_metadata_json={"headline": "H2"},
        db_path=db_path
    )

    # Verify is_url_known
    assert is_url_known("https://example.com/1", db_path=db_path) is True
    assert is_url_known("https://example.com/2", db_path=db_path) is True
    assert is_url_known("https://example.com/nonexistent", db_path=db_path) is False

    cached_1 = get_cached_html("https://example.com/1", db_path=db_path)
    assert cached_1 is not None
    assert cached_1["relevance_status"] == "IRRELEVANT"
    assert cached_1["raw_metadata_json"] == {"headline": "H1"}

    cached_2 = get_cached_html("https://example.com/2", db_path=db_path)
    assert cached_2 is not None
    assert cached_2["relevance_status"] == "INCONCLUSIVE"
    assert cached_2["raw_metadata_json"] == {"headline": "H2"}

    # Verify cache_scraped_html with new columns
    embedding = [0.1] * 768
    cache_scraped_html(
        "https://example.com/3", "pub1", "<html>relevant content</html>",
        validation="PENDING", headline="H3", description="D3",
        embedding=embedding, relevance_status="RELEVANT",
        raw_metadata_json={"headline": "H3", "description": "D3"},
        db_path=db_path
    )

    c3 = get_cached_html("https://example.com/3", db_path=db_path)
    assert c3 is not None
    assert c3["headline"] == "H3"
    assert c3["description"] == "D3"
    assert c3["relevance_status"] == "RELEVANT"
    assert c3["raw_metadata_json"] == {"headline": "H3", "description": "D3"}
    assert c3["embedding"] is not None
    assert len(c3["embedding"]) == 768
    assert c3["embedding"][0] == pytest.approx(0.1, rel=1e-5)

    # Verify clear_cached_html
    clear_cached_html("https://example.com/3", db_path=db_path)
    c3_cleared = get_cached_html("https://example.com/3", db_path=db_path)
    assert c3_cleared is not None
    assert c3_cleared["raw_html"] is None
    assert c3_cleared["headline"] == "H3" # kept metadata
    assert len(c3_cleared["embedding"]) == 768 # kept embedding

    # Verify update_relevance_status
    update_relevance_status("https://example.com/3", "IRRELEVANT", "MODEL", db_path=db_path)
    c3_updated = get_cached_html("https://example.com/3", db_path=db_path)
    assert c3_updated["relevance_status"] == "IRRELEVANT"
    assert c3_updated["validation"] == "PENDING"


def test_model_training(tmp_path):
    """Test model training pipeline end-to-end with mock data."""
    db_file = tmp_path / "test_training.db"
    db_path = str(db_file)
    init_db(db_path)

    # Insert some training data (3 relevant, 3 irrelevant)
    for i in range(3):
        cache_scraped_html(
            f"https://example.com/rel/{i}", "pub1", None,
            validation="PENDING", headline="R", description="D",
            embedding=[1.0, 1.0, 0.0], relevance_status="RELEVANT",
            relevance_label_source="LLM",
            db_path=db_path
        )
        cache_scraped_html(
            f"https://example.com/irrel/{i}", "pub1", None,
            validation=None, headline="I", description="D",
            embedding=[-1.0, -1.0, 0.0], relevance_status="IRRELEVANT",
            relevance_label_source="LLM",
            db_path=db_path
        )

    # Run the trainer with the mock weights path patched
    weights_test_path = str(tmp_path / "classifier_weights_test.json")
    with patch("classifier.trainer.WEIGHTS_PATH", weights_test_path):
        train_classifier(db_path=db_path)
        assert os.path.exists(weights_test_path)
        with open(weights_test_path, "r") as f:
            weights = json.load(f)
        assert "coefficients" in weights
        assert "intercept" in weights
        assert weights["n_samples"] == 6


def test_model_training_filters_source(tmp_path):
    """Verify that only LLM labels train the model and HUMAN labels are held out."""
    db_file = tmp_path / "test_filtering.db"
    db_path = str(db_file)
    init_db(db_path)

    # Insert 3 LLM relevant and irrelevant examples.
    for i in range(3):
        cache_scraped_html(
            f"https://example.com/llm-rel/{i}", "pub1", None,
            validation="PENDING", headline="R", description="D",
            embedding=[1.0, 1.0, 0.0], relevance_status="RELEVANT",
            relevance_label_source="LLM", db_path=db_path
        )
        cache_scraped_html(
            f"https://example.com/llm-irrel/{i}", "pub1", None,
            validation=None, headline="I", description="D",
            embedding=[-1.0, -1.0, 0.0], relevance_status="IRRELEVANT",
            relevance_label_source="LLM", db_path=db_path
        )

    # Insert HUMAN, KEYWORD, and MODEL examples that must be ignored.
    for i in range(3):
        cache_scraped_html(
            f"https://example.com/human-rel/{i}", "pub1", None,
            validation="PENDING", headline="R", description="D",
            embedding=[1.0, 1.0, 0.0], relevance_status="RELEVANT",
            relevance_label_source="HUMAN", db_path=db_path
        )
        cache_scraped_html(
            f"https://example.com/kw-rel/{i}", "pub1", None,
            validation="PENDING", headline="R", description="D",
            embedding=[1.0, 1.0, 0.0], relevance_status="RELEVANT",
            relevance_label_source="KEYWORD", db_path=db_path
        )
        cache_scraped_html(
            f"https://example.com/model-irrel/{i}", "pub1", None,
            validation=None, headline="I", description="D",
            embedding=[-1.0, -1.0, 0.0], relevance_status="IRRELEVANT",
            relevance_label_source="MODEL", db_path=db_path
        )

    # Run the trainer with the mock weights path patched
    weights_test_path = str(tmp_path / "classifier_weights_test.json")
    with patch("classifier.trainer.WEIGHTS_PATH", weights_test_path):
        train_classifier(db_path=db_path)
        assert os.path.exists(weights_test_path)
        with open(weights_test_path, "r") as f:
            weights = json.load(f)
        # Only the six LLM examples are training input.
        assert weights["n_samples"] == 6


def test_backfill_populates_training_data_offline_and_is_idempotent(tmp_path):
    db_path = str(tmp_path / "backfill.db")
    init_db(db_path)
    cache_scraped_html(
        "https://example.com/irrelevant",
        "pub1",
        "<html><title>HTML headline</title><meta name='description' content='HTML description'></html>",
        relevance_status="IRRELEVANT",
        relevance_label_source="LLM",
        raw_metadata_json={
            "article": {
                "title": "Stored headline",
                "summary": "Stored description",
            }
        },
        db_path=db_path,
    )
    cache_scraped_html(
        "https://example.com/inconclusive",
        "pub1",
        "<html><title>HTML fallback</title><meta name='description' content='Fallback description'></html>",
        relevance_status="INCONCLUSIVE",
        relevance_label_source="LLM",
        db_path=db_path,
    )
    cache_scraped_html(
        "https://example.com/relevant",
        "pub1",
        None,
        headline="Relevant headline",
        description="Relevant description",
        embedding=[1.0, 0.0],
        relevance_status="RELEVANT",
        relevance_label_source="LLM",
        db_path=db_path,
    )
    cache_scraped_html(
        "https://example.com/human",
        "pub1",
        None,
        headline="Human headline",
        description="Human description",
        embedding=[0.5, 0.5],
        relevance_status="RELEVANT",
        relevance_label_source="HUMAN",
        db_path=db_path,
    )

    with patch(
        "knowledge_map.adapters.embedding.PydanticAIEmbeddingAdapter.embed_text",
        side_effect=[[0.25, 0.75], [0.0, 1.0]],
    ) as embed_text, patch("httpx.get") as network_get:
        first = backfill_article_metadata(db_path=db_path)
        second = backfill_article_metadata(db_path=db_path)

    assert first.candidates == 2
    assert first.updated == 2
    assert second.candidates == 0
    assert second.updated == 0
    assert embed_text.call_count == 2
    network_get.assert_not_called()

    irrelevant = get_cached_html("https://example.com/irrelevant", db_path=db_path)
    assert irrelevant["headline"] == "Stored headline"
    assert irrelevant["description"] == "Stored description"
    assert irrelevant["embedding"] == pytest.approx([0.0, 1.0])

    inconclusive = get_cached_html("https://example.com/inconclusive", db_path=db_path)
    assert inconclusive["headline"] == "HTML fallback"
    assert inconclusive["description"] == "Fallback description"
    assert inconclusive["embedding"] == pytest.approx([0.25, 0.75])

    training_rows = get_training_rows(db_path)
    training_statuses = {status for _, status in training_rows}
    assert len(training_rows) == 2
    assert training_statuses == {"RELEVANT", "IRRELEVANT"}
