import pytest
import sys
import os
import json
import sqlite3
from unittest.mock import patch, MagicMock
from knowledge_map.cli.main import main
from knowledge_map.adapters.sqlite_db import (
    init_db,
    register_publication,
    cache_scraped_html,
    get_publication,
    insert_selector_proposal,
    set_publication_healing_in_progress,
    get_latest_selector_proposal
)
from knowledge_map.core.healing import get_generator_agent, get_critic_agent
from pydantic_ai import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel

def test_cli_heal_selectors_missing_publication():
    # Calling heal-selectors without --publication should trigger a parser error (SystemExit with code 2)
    with pytest.raises(SystemExit) as exc_info:
        main(["heal-selectors"])
    assert exc_info.value.code == 2

def test_cli_heal_selectors_nonexistent_publication(tmp_path, monkeypatch, capsys):
    db_file = tmp_path / "test_cli_heal.db"
    db_path = str(db_file)
    init_db(db_path)
    monkeypatch.setenv("SQLITE_DB_PATH", db_path)

    with pytest.raises(SystemExit) as exc_info:
        main(["heal-selectors", "--publication", "nonexistent"])
    
    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "Error: Publication 'nonexistent' not found." in captured.err

def test_cli_heal_selectors_no_tripping_url(tmp_path, monkeypatch, capsys):
    db_file = tmp_path / "test_cli_heal_no_trip.db"
    db_path = str(db_file)
    init_db(db_path)
    monkeypatch.setenv("SQLITE_DB_PATH", db_path)

    # Register publication with NO tripping URL
    register_publication("testpub", "Test Pub", "https://testpub.com", db_path=db_path)

    with pytest.raises(SystemExit) as exc_info:
        main(["heal-selectors", "--publication", "testpub"])
    
    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "Error: Publication 'testpub' does not have a tripping article URL." in captured.err

def test_cli_heal_selectors_context_propagation(tmp_path, monkeypatch):
    db_file = tmp_path / "test_cli_context.db"
    db_path = str(db_file)
    init_db(db_path)
    monkeypatch.setenv("SQLITE_DB_PATH", db_path)

    # Register publication with tripping URL
    register_publication("testpub", "Test Pub", "https://testpub.com", db_path=db_path)
    
    # Update tripping URL directly in database
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE publications SET tripping_article_url = 'https://testpub.com/tripped' WHERE id = 'testpub'")
    conn.commit()
    conn.close()

    # Cache raw HTML for the tripping URL
    html = "<html><body><h1>Headline</h1><span class='author'>Author</span><div class='content'>Body</div></body></html>"
    cache_scraped_html("https://testpub.com/tripped", "testpub", html, validation="VALIDATION_FAILED", db_path=db_path)

    # Mock Generator/Critic models
    prompt_captured = []
    def mock_generator_model(messages, info):
        nonlocal prompt_captured
        prompt_captured.append(str(messages))
        tool_name = info.output_tools[0].name
        return ModelResponse(parts=[
            ToolCallPart(
                tool_name=tool_name,
                args={
                    "title": "h1",
                    "author": "span",
                    "date": "",
                    "body": "div"
                },
                tool_call_id="call_gen"
            )
        ])

    def mock_critic_model(messages, info):
        tool_name = info.output_tools[0].name
        return ModelResponse(parts=[
            ToolCallPart(
                tool_name=tool_name,
                args={
                    "is_valid": True,
                    "issues": []
                },
                tool_call_id="call_crit"
            )
        ])

    generator_agent = get_generator_agent(defer_check=True)
    critic_agent = get_critic_agent(defer_check=True)

    with generator_agent.override(model=FunctionModel(mock_generator_model)), \
         critic_agent.override(model=FunctionModel(mock_critic_model)), \
         patch("knowledge_map.core.healing.get_generator_agent", return_value=generator_agent), \
         patch("knowledge_map.core.healing.get_critic_agent", return_value=critic_agent):
        
        try:
            main(["heal-selectors", "--publication", "testpub", "--context", "Target exact body tag"])
        except SystemExit as e:
            assert e.code == 0

    # Verify context guidance was propagated
    assert any("Target exact body tag" in prompt for prompt in prompt_captured)

def test_cli_heal_selectors_retry(tmp_path, monkeypatch):
    db_file = tmp_path / "test_cli_retry.db"
    db_path = str(db_file)
    init_db(db_path)
    monkeypatch.setenv("SQLITE_DB_PATH", db_path)

    # Register publication with tripping URL
    register_publication("testpub", "Test Pub", "https://testpub.com", db_path=db_path)
    
    # Cache raw HTML
    html = "<html><body><h1>Headline</h1><span class='author'>Author</span><div class='content'>Body</div></body></html>"
    cache_scraped_html("https://testpub.com/tripped", "testpub", html, validation="VALIDATION_FAILED", db_path=db_path)

    # Insert a failed proposal in the database
    old_selectors = {"title": "wrong-title", "author": "wrong-author", "date": "", "body": "wrong-body"}
    proposal_id = insert_selector_proposal(
        publication_id="testpub",
        selectors_json=json.dumps(old_selectors),
        trigger_article_url="https://testpub.com/tripped",
        status="HEALING_FAILED",
        critic_iterations=3,
        db_path=db_path
    )

    # Mock Generator/Critic models
    prompt_captured = []
    def mock_generator_model(messages, info):
        nonlocal prompt_captured
        prompt_captured.append(str(messages))
        tool_name = info.output_tools[0].name
        return ModelResponse(parts=[
            ToolCallPart(
                tool_name=tool_name,
                args={
                    "title": "h1",
                    "author": "span",
                    "date": "",
                    "body": "div"
                },
                tool_call_id="call_gen"
            )
        ])

    def mock_critic_model(messages, info):
        tool_name = info.output_tools[0].name
        return ModelResponse(parts=[
            ToolCallPart(
                tool_name=tool_name,
                args={
                    "is_valid": True,
                    "issues": []
                },
                tool_call_id="call_crit"
            )
        ])

    generator_agent = get_generator_agent(defer_check=True)
    critic_agent = get_critic_agent(defer_check=True)

    with generator_agent.override(model=FunctionModel(mock_generator_model)), \
         critic_agent.override(model=FunctionModel(mock_critic_model)), \
         patch("knowledge_map.core.healing.get_generator_agent", return_value=generator_agent), \
         patch("knowledge_map.core.healing.get_critic_agent", return_value=critic_agent):
        
        try:
            main(["heal-selectors", "--publication", "testpub", "--retry"])
        except SystemExit as e:
            assert e.code == 0

    # Verify old proposal was marked REJECTED
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT status, resolved_at FROM selector_proposals WHERE id = ?", (proposal_id,))
    row = cursor.fetchone()
    conn.close()

    assert row["status"] == "REJECTED"
    assert row["resolved_at"] is not None

    # Verify negative selectors were propagated into the generator prompt
    assert any("Avoid using these previously failing selectors:" in prompt for prompt in prompt_captured)
    assert any("wrong-title" in prompt for prompt in prompt_captured)

def test_cli_heal_selectors_guard_bypass(tmp_path, monkeypatch):
    db_file = tmp_path / "test_cli_bypass.db"
    db_path = str(db_file)
    init_db(db_path)
    monkeypatch.setenv("SQLITE_DB_PATH", db_path)

    # Register publication and set healing_in_progress=True and an unresolved proposal
    register_publication("testpub", "Test Pub", "https://testpub.com", db_path=db_path)
    set_publication_healing_in_progress("testpub", True, db_path=db_path)

    # Tripping URL
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE publications SET tripping_article_url = 'https://testpub.com/tripped' WHERE id = 'testpub'")
    conn.commit()
    conn.close()

    # Cache raw HTML
    html = "<html><body><h1>Headline</h1><span class='author'>Author</span><div class='content'>Body</div></body></html>"
    cache_scraped_html("https://testpub.com/tripped", "testpub", html, validation="VALIDATION_FAILED", db_path=db_path)

    # Insert an unresolved proposal
    insert_selector_proposal(
        publication_id="testpub",
        selectors_json="{}",
        trigger_article_url="https://testpub.com/tripped",
        status="PENDING_REVIEW",
        critic_iterations=1,
        db_path=db_path
    )

    # Mock Generator/Critic models
    generator_calls = 0
    def mock_generator_model(messages, info):
        nonlocal generator_calls
        generator_calls += 1
        tool_name = info.output_tools[0].name
        return ModelResponse(parts=[
            ToolCallPart(
                tool_name=tool_name,
                args={
                    "title": "h1",
                    "author": "span",
                    "date": "",
                    "body": "div"
                },
                tool_call_id="call_gen"
            )
        ])

    def mock_critic_model(messages, info):
        tool_name = info.output_tools[0].name
        return ModelResponse(parts=[
            ToolCallPart(
                tool_name=tool_name,
                args={
                    "is_valid": True,
                    "issues": []
                },
                tool_call_id="call_crit"
            )
        ])

    generator_agent = get_generator_agent(defer_check=True)
    critic_agent = get_critic_agent(defer_check=True)

    with generator_agent.override(model=FunctionModel(mock_generator_model)), \
         critic_agent.override(model=FunctionModel(mock_critic_model)), \
         patch("knowledge_map.core.healing.get_generator_agent", return_value=generator_agent), \
         patch("knowledge_map.core.healing.get_critic_agent", return_value=critic_agent):
        
        try:
            # This manual invocation should bypass guards (which would otherwise reject/skip) and complete
            main(["heal-selectors", "--publication", "testpub"])
        except SystemExit as e:
            assert e.code == 0

    assert generator_calls > 0
