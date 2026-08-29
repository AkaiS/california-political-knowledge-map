from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError
from pydantic_ai import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from knowledge_map.adapters.sqlite_db import (
    cache_scraped_html,
    init_db,
    register_publication,
)
from knowledge_map.core.relevance_agent import (
    RelevanceClassification,
    classify_article_with_llm,
    get_relevance_agent_prompt,
)
from knowledge_map.schemas import DeploymentKind, ModelDeployment, ModelRequestSettings


def _local_deployment() -> ModelDeployment:
    return ModelDeployment(
        kind=DeploymentKind.LOCAL,
        model="explicit-relevance-model",
        endpoint="http://explicit-relevance.test:9999",
        request_settings=ModelRequestSettings(thinking=False),
    )


def _relevance_response(messages, info) -> ModelResponse:
    return ModelResponse(
        parts=[
            ToolCallPart(
                tool_name=info.output_tools[0].name,
                args={"classification": "RELEVANT"},
                tool_call_id="call-1",
            )
        ]
    )

def test_relevance_classification_schema():
    """Verify that RelevanceClassification enforces schema fields and validation."""
    # Valid positive
    obj = RelevanceClassification(classification="RELEVANT")
    assert obj.classification == "RELEVANT"

    # Valid negative
    obj2 = RelevanceClassification(classification="IRRELEVANT")
    assert obj2.classification == "IRRELEVANT"

    # Invalid classification
    with pytest.raises(ValidationError):
        RelevanceClassification(classification="INCONCLUSIVE")


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


def test_prompt_rendering_no_examples():
    """Verify get_relevance_agent_prompt rendering when examples are empty."""
    prompt = get_relevance_agent_prompt(
        title="Test Article Title",
        body="Test Article Body Content",
        positive_examples=[],
        negative_examples=[]
    )
    
    assert "Test Article Title" in prompt
    assert "Test Article Body Content" in prompt
    assert "Examples of RELEVANT" not in prompt
    assert "Examples of IRRELEVANT" not in prompt
    assert "based on the examples provided" not in prompt


@pytest.mark.anyio
async def test_production_relevance_classification_uses_explicit_deployment(
    tmp_path, monkeypatch
):
    deployment = _local_deployment()
    seen: list[object] = []

    def model_factory(requested):
        seen.append(requested)
        assert isinstance(requested, ModelDeployment)
        return FunctionModel(_relevance_response)

    monkeypatch.setenv("OLLAMA_MODEL_RELEVANCE", "ambient-stage-model")
    monkeypatch.setattr(
        "knowledge_map.core.relevance_agent.get_chat_model", model_factory
    )

    result = await classify_article_with_llm(
        title="California election results",
        body="The county reported its election results.",
        db_path=str(tmp_path / "missing.db"),
        deployment=deployment,
    )

    assert result == RelevanceClassification(classification="RELEVANT")
    assert seen == [deployment]


@pytest.mark.anyio
async def test_classify_article_no_examples(tmp_path):
    """Verify that the agent runs without examples when DB examples are missing."""
    db_file = tmp_path / "test_empty.db"
    init_db(str(db_file))
    
    mock_result = AsyncMock()
    mock_result.output = RelevanceClassification(classification="RELEVANT")
    
    with patch("knowledge_map.core.relevance_agent.Agent.run") as mock_run, \
         patch("knowledge_map.core.relevance_agent.logger.warning") as mock_warn:
        mock_run.return_value = mock_result
        
        res = await classify_article_with_llm(
            title="Sutter County Election",
            body="Local election results for supervisor seat.",
            db_path=str(db_file)
        )
        
        # Verify run was called
        mock_run.assert_called_once()
        # Verify logger.warning was called
        mock_warn.assert_called_once_with(
            "Running relevance classifier agent without examples: No human-labeled examples available in the database."
        )
        assert res.classification == "RELEVANT"


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
    
    # Populate the cache with gold-standard examples and no Story rows.
    cache_scraped_html(
        url="https://test.com/pos1",
        publication_id="testpub",
        raw_html="<html>html</html>",
        validation="VALIDATED",
        headline="Db Pos Title",
        description="Db Pos Body",
        relevance_status="RELEVANT",
        relevance_label_source="HUMAN",
        db_path=db_path
    )
    cache_scraped_html(
        url="https://test.com/neg1",
        publication_id="testpub",
        raw_html="<html>html</html>",
        validation=None,
        headline="Db Neg Title",
        description="Db Neg Body",
        relevance_status="IRRELEVANT",
        relevance_label_source="HUMAN",
        db_path=db_path
    )
    mock_result = AsyncMock()
    mock_result.output = RelevanceClassification(classification="IRRELEVANT")

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
        
        # No static examples exist anymore, so we only need to verify DB examples are present
