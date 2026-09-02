"""Command and assembly boundaries for Story Pipeline deployments."""

import json
from unittest.mock import MagicMock, patch

import httpx
import pytest
from pydantic_ai import Agent

from knowledge_map.cli.main import (
    build_story_pipeline,
    select_story_deployment,
)
from knowledge_map.schemas import (
    DeploymentKind,
    ModelDeployment,
    OpenRouterProviderPolicy,
)


def test_story_pipeline_deployment_defaults_to_local(monkeypatch) -> None:
    monkeypatch.setenv("LLAMA_CPP_MODEL", "local/story-model")
    monkeypatch.setenv("LLAMA_CPP_BASE_URL", "http://story-local.test:8080")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_MODEL", raising=False)
    monkeypatch.delenv("OPENROUTER_PROVIDERS", raising=False)

    deployment = select_story_deployment()

    assert deployment.kind is DeploymentKind.LOCAL
    assert deployment.model == "local/story-model"
    assert deployment.endpoint == "http://story-local.test:8080/v1"
    assert deployment.provider_policy is None


def test_story_pipeline_local_selection_uses_default_when_model_is_unset(
    monkeypatch,
) -> None:
    monkeypatch.delenv("LLAMA_CPP_MODEL", raising=False)
    monkeypatch.setenv("LLAMA_CPP_BASE_URL", "http://story-local.test:8080")

    deployment = select_story_deployment()

    assert deployment.model == "gemma4:26b"


def test_story_pipeline_deployment_selects_one_openrouter_configuration(
    monkeypatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-story-test")
    monkeypatch.setenv("OPENROUTER_MODEL", "remote/story-model")
    monkeypatch.setenv("OPENROUTER_PROVIDERS", "google-ai-studio, openai")

    deployment = select_story_deployment("openrouter")

    assert deployment.kind is DeploymentKind.OPENROUTER
    assert deployment.model == "remote/story-model"
    assert deployment.endpoint is None
    assert deployment.provider_policy == OpenRouterProviderPolicy(
        providers=("google-ai-studio", "openai")
    )


def test_incomplete_story_openrouter_configuration_fails_before_assembly(
    monkeypatch,
) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("OPENROUTER_MODEL", "")
    monkeypatch.setenv("OPENROUTER_PROVIDERS", "")

    with pytest.raises(ValueError, match="OPENROUTER_API_KEY") as error:
        select_story_deployment("openrouter")

    assert "OPENROUTER_MODEL" in str(error.value)
    assert "OPENROUTER_PROVIDERS" in str(error.value)


@pytest.mark.parametrize(
    "provider_text",
    ("google-ai-studio,", ",google-ai-studio", "google-ai-studio, ,openai"),
)
def test_blank_story_openrouter_provider_entry_fails_before_assembly(
    monkeypatch, provider_text: str
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-story-test")
    monkeypatch.setenv("OPENROUTER_MODEL", "remote/story-model")
    monkeypatch.setenv("OPENROUTER_PROVIDERS", provider_text)

    with pytest.raises(ValueError, match="OPENROUTER_PROVIDERS"):
        select_story_deployment("openrouter")


def test_story_pipeline_assembly_passes_one_deployment_to_chat_stages_only() -> None:
    deployment = ModelDeployment(
        kind=DeploymentKind.OPENROUTER,
        model="remote/story-model",
        provider_policy={"providers": ("google-ai-studio",)},
    )
    db_adapter = MagicMock()
    embedding_adapter = MagicMock()
    status_tracker = MagicMock()
    dlq_adapter = MagicMock()

    with patch("knowledge_map.cli.main.PydanticAICoreferenceAdapter") as coref, \
         patch("knowledge_map.cli.main.PydanticAIEntityExtractionAdapter") as extraction, \
         patch("knowledge_map.cli.main.PydanticAIPolicyAreaAdapter"):
        pipeline = build_story_pipeline(
            deployment,
            db_adapter=db_adapter,
            embedding_adapter=embedding_adapter,
            status_tracker=status_tracker,
            dlq_adapter=dlq_adapter,
        )

    coref.assert_called_once_with(deployment=deployment)
    extraction.assert_called_once_with(deployment=deployment)
    assert pipeline.embedding_adapter is embedding_adapter
    assert pipeline.db_adapter is db_adapter
    assert pipeline.status_tracker is status_tracker
    assert pipeline.dlq_adapter is dlq_adapter


def test_story_ingest_command_forwards_selected_deployment_to_both_chat_stages():
    from knowledge_map.cli.main import main

    deployment = ModelDeployment(
        kind=DeploymentKind.OPENROUTER,
        model="remote/story-model",
        provider_policy={"providers": ("google-ai-studio",)},
    )

    with (
        patch("knowledge_map.cli.main.select_story_deployment", return_value=deployment) as select,
        patch("knowledge_map.cli.main.Neo4jAdapter"),
        patch("knowledge_map.cli.main.PydanticAIEmbeddingAdapter") as embedding,
        patch("knowledge_map.cli.main.PydanticAICoreferenceAdapter") as coref,
        patch("knowledge_map.cli.main.PydanticAIEntityExtractionAdapter") as extraction,
        patch("knowledge_map.cli.main.PydanticAIPolicyAreaAdapter") as policy_areas,
        patch("knowledge_map.cli.main.LocalFileDLQAdapter"),
        patch("knowledge_map.cli.main.SQLiteStatusTracker"),
        patch("knowledge_map.cli.main.BatchIngestionService") as service,
        pytest.raises(SystemExit) as error,
    ):
        main(["ingest", "--deployment", "openrouter"])

    assert error.value.code == 0
    select.assert_called_once_with("openrouter")
    embedding.assert_called_once_with()
    coref.assert_called_once_with(deployment=deployment)
    extraction.assert_called_once_with(deployment=deployment)
    policy_areas.assert_called_once_with(deployment=deployment)
    service.return_value.run.assert_called_once_with()


def test_incomplete_story_openrouter_command_stops_before_pipeline_setup():
    from knowledge_map.cli.main import main

    with (
        patch(
            "knowledge_map.cli.main.select_story_deployment",
            side_effect=ValueError("missing OpenRouter configuration"),
        ),
        patch("knowledge_map.cli.main.Neo4jAdapter") as neo4j,
        patch("knowledge_map.cli.main.BatchIngestionService") as service,
        patch("knowledge_map.cli.main.PydanticAIEmbeddingAdapter") as embedding,
        patch("knowledge_map.cli.main.PydanticAICoreferenceAdapter") as coref,
        patch("knowledge_map.cli.main.PydanticAIEntityExtractionAdapter") as extraction,
        pytest.raises(SystemExit) as error,
    ):
        main(["ingest", "--deployment", "openrouter"])

    assert error.value.code == 1
    neo4j.assert_not_called()
    service.assert_not_called()
    embedding.assert_not_called()
    coref.assert_not_called()
    extraction.assert_not_called()


def test_selected_openrouter_deployment_reaches_both_chat_stage_requests(
    monkeypatch,
) -> None:
    from knowledge_map.utils.models import get_chat_model

    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-story-test")
    deployment = ModelDeployment(
        kind=DeploymentKind.OPENROUTER,
        model="remote/story-model",
        provider_policy={"providers": ("google-ai-studio",)},
    )
    requests: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append(body)
        return httpx.Response(
            200,
            json={
                "id": f"story-{len(requests)}",
                "object": "chat.completion",
                "created": 0,
                "model": deployment.model,
                "provider": "google-ai-studio/test",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": "ok",
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 1,
                    "completion_tokens": 1,
                    "total_tokens": 2,
                },
            },
        )

    transport = httpx.MockTransport(handler)
    Agent(
        get_chat_model(deployment, transport=transport),
        name="story_coreference_stage",
        output_type=str,
        defer_model_check=True,
    ).run_sync("coreference stage")
    Agent(
        get_chat_model(deployment, transport=transport),
        name="story_extraction_stage",
        output_type=str,
        defer_model_check=True,
    ).run_sync("extraction stage")

    assert len(requests) == 2
    assert [body["model"] for body in requests] == [deployment.model] * len(requests)
    assert [body["provider"] for body in requests] == [
        {
            "order": ["google-ai-studio"],
            "only": ["google-ai-studio"],
            "allow_fallbacks": True,
            "require_parameters": True,
        }
    ] * len(requests)
    assert all("tools" not in body for body in requests)


def test_selected_openrouter_deployment_reaches_concrete_chat_stage_agents(
    monkeypatch,
) -> None:
    """Exercise the actual Coreference Annotator, Critic, and Extraction factories."""

    import knowledge_map.adapters.coreference as coreference_module
    import knowledge_map.adapters.extraction as extraction_module
    from knowledge_map.adapters.coreference import (
        CoreferenceDeps,
        get_annotator_agent,
        get_critic_agent,
    )
    from knowledge_map.adapters.extraction import get_extraction_agent
    from knowledge_map.utils.models import get_chat_model

    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-story-test")
    deployment = ModelDeployment(
        kind=DeploymentKind.OPENROUTER,
        model="remote/story-model",
        provider_policy={"providers": ("google-ai-studio",)},
    )
    requests: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append(body)
        parameters = body["tools"][0]["function"]["parameters"]
        schema_text = json.dumps(parameters)
        if '"nodes"' in schema_text:
            arguments = {"nodes": [], "relationships": []}
        elif '"accepted"' in schema_text:
            arguments = {
                "response": [
                    {
                        "sentence_label": "1",
                        "mention_text": "Alice",
                        "accepted": True,
                    }
                ]
            }
        else:
            arguments = {
                "response": [
                    {
                        "sentence_label": "1",
                        "mention_text": "Alice",
                        "canonical_entity_name": "Alice",
                    }
                ]
            }
        return httpx.Response(
            200,
            json={
                "id": f"story-concrete-{len(requests)}",
                "object": "chat.completion",
                "created": 0,
                "model": deployment.model,
                "provider": "google-ai-studio/test",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": f"call-{len(requests)}",
                                    "type": "function",
                                    "function": {
                                        "name": "final_result",
                                        "arguments": json.dumps(arguments),
                                    },
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ],
            },
        )

    transport = httpx.MockTransport(handler)

    def model_for_selected_deployment(selected: ModelDeployment):
        return get_chat_model(selected, transport=transport)

    monkeypatch.setattr(
        coreference_module, "get_chat_model", model_for_selected_deployment
    )
    monkeypatch.setattr(
        extraction_module, "get_chat_model", model_for_selected_deployment
    )

    annotator = get_annotator_agent(deployment, retries=0)
    annotator_result = annotator.run_sync(
        "Resolve references.",
        deps=CoreferenceDeps.for_content("Alice spoke."),
    )
    extractor = get_extraction_agent(deployment, retries=0)
    extraction_result = extractor.run_sync("Extract entities.")
    critic = get_critic_agent(deployment, retries=0)
    critic_result = critic.run_sync(
        "Judge the references.",
        deps=CoreferenceDeps.for_content("Alice spoke."),
    )

    assert annotator_result.output[0].canonical_entity_name == "Alice"
    assert extraction_result.output.nodes == []
    assert critic_result.output[0].accepted is True
    assert len(requests) == 3
    assert all(body["model"] == deployment.model for body in requests)
    assert all(
        body["provider"]
        == {
            "order": ["google-ai-studio"],
            "only": ["google-ai-studio"],
            "allow_fallbacks": True,
            "require_parameters": True,
        }
        for body in requests
    )


def test_story_pipeline_assembly_builds_the_policy_area_stage_from_the_deployment() -> None:
    deployment = ModelDeployment(
        kind=DeploymentKind.OPENROUTER,
        model="remote/story-model",
        provider_policy={"providers": ("google-ai-studio",)},
    )

    with patch("knowledge_map.cli.main.PydanticAICoreferenceAdapter"), \
         patch("knowledge_map.cli.main.PydanticAIEntityExtractionAdapter"), \
         patch("knowledge_map.cli.main.PydanticAIPolicyAreaAdapter") as policy_areas:
        pipeline = build_story_pipeline(
            deployment,
            db_adapter=MagicMock(),
            embedding_adapter=MagicMock(),
            status_tracker=MagicMock(),
        )

    policy_areas.assert_called_once_with(deployment=deployment)
    assert pipeline.policy_area_adapter is policy_areas.return_value


def test_story_pipeline_assembly_preserves_the_policy_area_injection_seam() -> None:
    deployment = ModelDeployment(
        kind=DeploymentKind.LOCAL,
        model="local/story-model",
        endpoint="http://story-local.test:8080/v1",
    )
    injected = MagicMock()

    with patch("knowledge_map.cli.main.PydanticAICoreferenceAdapter"), \
         patch("knowledge_map.cli.main.PydanticAIEntityExtractionAdapter"):
        pipeline = build_story_pipeline(
            deployment,
            db_adapter=MagicMock(),
            embedding_adapter=MagicMock(),
            status_tracker=MagicMock(),
            policy_area_adapter=injected,
        )

    assert pipeline.policy_area_adapter is injected
