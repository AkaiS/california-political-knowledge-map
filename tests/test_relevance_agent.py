import pytest
from unittest.mock import patch, AsyncMock
from pydantic import ValidationError

from knowledge_map.adapters.sqlite_db import init_db, cache_scraped_html, register_publication
from knowledge_map.core.relevance_agent import (
    RelevanceClassification,
    get_relevance_agent_prompt,
    classify_article_with_llm,
    STATIC_POSITIVE_EXAMPLES,
    STATIC_NEGATIVE_EXAMPLES
)

def test_relevance_classification_schema():
    """Verify that RelevanceClassification enforces schema fields and validation."""
    # Valid positive
    obj = RelevanceClassification(classification="RELEVANT", rationale="Mentions CA Governor.")
    assert obj.classification == "RELEVANT"
    assert obj.rationale == "Mentions CA Governor."

    # Valid negative
    obj2 = RelevanceClassification(classification="IRRELEVANT", rationale="It is a cookie recipe.")
    assert obj2.classification == "IRRELEVANT"
    assert obj2.rationale == "It is a cookie recipe."

    # Invalid classification
    with pytest.raises(ValidationError):
        RelevanceClassification(classification="INCONCLUSIVE", rationale="Unsure")

    # Missing rationale
    with pytest.raises(ValidationError):
        RelevanceClassification(classification="RELEVANT")


def test_prompt_rendering():
    """Verify get_relevance_agent_prompt renders title, body, and examples correctly."""
    pos = [{"title": "Pos Title", "content": "Pos Body", "relevance_status": "RELEVANT"}]
    neg = [{"title": "Neg Title", "content": "Neg Body", "relevance_status": "IRRELEVANT"}]
    prompt = get_relevance_agent_prompt(
        title="Test Article Title",
        body="Test Article Body Content",
        positive_examples=pos,
        negative_examples=neg
    )
    
    assert "Test Article Title" in prompt
    assert "Test Article Body Content" in prompt
    assert "Pos Title" in prompt
    assert "Pos Body" in prompt
    assert "Neg Title" in prompt
    assert "Neg Body" in prompt
    assert "RELEVANT" in prompt
    assert "IRRELEVANT" in prompt


@pytest.mark.anyio
async def test_classify_article_fallback_examples(tmp_path):
    """Verify that the agent falls back to static examples when DB examples are missing."""
    db_file = tmp_path / "test_empty.db"
    init_db(str(db_file))
    
    # We will mock the agent run to see what prompt/content was passed.
    mock_result = AsyncMock()
    mock_result.output = RelevanceClassification(classification="RELEVANT", rationale="Mocked response")
    
    with patch("knowledge_map.core.relevance_agent.Agent.run") as mock_run:
        mock_run.return_value = mock_result
        
        await classify_article_with_llm(
            title="Sutter County Election",
            body="Local election results for supervisor seat.",
            db_path=str(db_file)
        )
        
        # Verify run was called
        mock_run.assert_called_once()
        # Verify prompt contained static examples since database was empty
        called_prompt = mock_run.call_args[0][0]
        assert STATIC_POSITIVE_EXAMPLES[0]["title"] in called_prompt
        assert STATIC_NEGATIVE_EXAMPLES[0]["title"] in called_prompt


@pytest.mark.anyio
async def test_classify_article_dynamic_examples(tmp_path):
    """Verify that the agent uses DB gold-standard examples when they exist."""
    db_file = tmp_path / "test_dynamic.db"
    db_path = str(db_file)
    init_db(db_path)
    
    # Register a publication
    register_publication(
        pub_id="testpub",
        name="Test Pub",
        base_url="https://test.com",
        db_path=db_path
    )
    
    # Populate the database with gold-standard stories
    # Insert 1 positive HUMAN story
    cache_scraped_html(
        url="https://test.com/pos1",
        publication_id="testpub",
        raw_html="<html>html</html>",
        validation="VALIDATED",
        relevance_status="RELEVANT",
        relevance_label_source="HUMAN",
        db_path=db_path
    )
    # Insert story record to satisfy JOIN on url
    with sqlite3_connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO stories (title, url, content) VALUES (?, ?, ?)",
            ("Db Pos Title", "https://test.com/pos1", "Db Pos Body")
        )
        conn.commit()
    
    # Insert 1 negative HUMAN story
    cache_scraped_html(
        url="https://test.com/neg1",
        publication_id="testpub",
        raw_html="<html>html</html>",
        validation=None,
        relevance_status="IRRELEVANT",
        relevance_label_source="HUMAN",
        db_path=db_path
    )
    with sqlite3_connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO stories (title, url, content) VALUES (?, ?, ?)",
            ("Db Neg Title", "https://test.com/neg1", "Db Neg Body")
        )
        conn.commit()

    mock_result = AsyncMock()
    mock_result.output = RelevanceClassification(classification="IRRELEVANT", rationale="Mocked response")

    with patch("knowledge_map.core.relevance_agent.Agent.run") as mock_run:
        mock_run.return_value = mock_result
        
        await classify_article_with_llm(
            title="Candidate Speech",
            body="A candidate gave a speech.",
            db_path=db_path
        )
        
        # Verify run was called
        mock_run.assert_called_once()
        called_prompt = mock_run.call_args[0][0]
        
        # Verify prompt contained DB examples
        assert "Db Pos Title" in called_prompt
        assert "Db Pos Body" in called_prompt
        assert "Db Neg Title" in called_prompt
        assert "Db Neg Body" in called_prompt
        
        # Verify static examples are NOT in the prompt (as dynamic ones took precedence)
        assert STATIC_POSITIVE_EXAMPLES[0]["title"] not in called_prompt
        assert STATIC_NEGATIVE_EXAMPLES[0]["title"] not in called_prompt


def sqlite3_connect(db_path):
    import sqlite3
    return sqlite3.connect(db_path)
