"""Behavioral tests for the public Model Deployment value contract."""

import json

import pytest
from pydantic import ValidationError

import knowledge_map.schemas as exported_schemas
from knowledge_map.schemas import (
    DeploymentKind,
    ModelDeployment,
    ModelRequestSettings,
    OpenRouterProviderPolicy,
)


def test_local_deployment_is_a_hashable_serializable_value():
    settings = ModelRequestSettings(
        temperature=0.0,
        top_p=0.9,
        top_k=40,
        thinking=False,
        max_tokens=512,
        timeout=30.0,
        max_attempts=3,
        rate_limit_wait_cap=120.0,
    )
    deployment = ModelDeployment(
        kind=DeploymentKind.LOCAL,
        model="google/gemma-4-26b-a4b-it",
        request_settings=settings,
        endpoint="http://localhost:8080/v1",
    )

    assert deployment.model_dump(mode="json") == {
        "kind": "local",
        "model": "google/gemma-4-26b-a4b-it",
        "request_settings": {
            "temperature": 0.0,
            "top_p": 0.9,
            "top_k": 40,
            "thinking": False,
            "reasoning_effort": None,
            "max_tokens": 512,
            "timeout": 30.0,
            "max_attempts": 3,
            "rate_limit_wait_cap": 120.0,
        },
        "endpoint": "http://localhost:8080/v1",
        "provider_policy": None,
    }
    assert json.loads(deployment.model_dump_json()) == deployment.model_dump(
        mode="json"
    )
    assert deployment == ModelDeployment.model_validate(
        deployment.model_dump(mode="json")
    )
    assert hash(deployment) == hash(
        ModelDeployment.model_validate(deployment.model_dump())
    )


def test_deployment_kind_controls_route_requirements_and_identity():
    settings = ModelRequestSettings()
    upstream_model = "google/gemma-4-26b-a4b-it"

    with pytest.raises(ValidationError):
        ModelDeployment(
            kind=DeploymentKind.OPENROUTER,
            model=upstream_model,
            request_settings=settings,
        )
    with pytest.raises(ValidationError):
        ModelDeployment(
            kind=DeploymentKind.LOCAL,
            model=upstream_model,
            request_settings=settings,
            provider_policy={"providers": ("llama.cpp",)},
        )

    local = ModelDeployment(
        kind=DeploymentKind.LOCAL,
        model=upstream_model,
        request_settings=settings,
        endpoint="http://localhost:8080/v1",
    )
    openrouter = ModelDeployment(
        kind=DeploymentKind.OPENROUTER,
        model=upstream_model,
        request_settings=settings,
        provider_policy={
            "providers": ("google-ai-studio", "openrouter/free"),
        },
    )

    assert local != openrouter
    assert len({local, openrouter}) == 2
    assert openrouter.model_dump(mode="json")["provider_policy"] == {
        "providers": ["google-ai-studio", "openrouter/free"],
        "allow_fallback": True,
        "require_parameters": True,
        "exclusive": True,
    }


def test_deployment_contract_is_exported_with_the_other_domain_schemas():
    assert exported_schemas.DeploymentKind is DeploymentKind
    assert exported_schemas.ModelDeployment is ModelDeployment
    assert exported_schemas.ModelRequestSettings is ModelRequestSettings
    assert exported_schemas.OpenRouterProviderPolicy is OpenRouterProviderPolicy


def test_request_settings_reject_impossible_sampling_and_limit_values():
    invalid_values = (
        {"temperature": -0.1},
        {"temperature": 2.1},
        {"top_p": 0.0},
        {"top_p": 1.1},
        {"top_k": 0},
        {"max_tokens": 0},
        {"timeout": 0.0},
        {"timeout": None},
        {"max_attempts": 0},
        {"rate_limit_wait_cap": -1.0},
        {"reasoning_effort": " "},
    )

    for values in invalid_values:
        with pytest.raises(ValidationError):
            ModelRequestSettings(**values)


def test_contract_rejects_invalid_or_secret_values():
    with pytest.raises(ValidationError):
        ModelDeployment(kind="remote", model="some-model")
    with pytest.raises(ValidationError):
        ModelDeployment(kind=DeploymentKind.LOCAL, model=" ")
    with pytest.raises(ValidationError):
        OpenRouterProviderPolicy(providers=("provider-a", "provider-a"))
    with pytest.raises(ValidationError):
        OpenRouterProviderPolicy()
    secret = "must-not-be-carried"
    with pytest.raises(ValidationError) as error:
        ModelDeployment(
            kind=DeploymentKind.LOCAL,
            model="some-model",
            api_key=secret,
        )
    assert secret not in str(error.value)


def test_route_values_cannot_carry_credentials_or_disable_openrouter_guards():
    with pytest.raises(ValidationError):
        ModelDeployment(
            kind=DeploymentKind.LOCAL,
            model="some-model",
            endpoint="localhost:8080",
        )
    with pytest.raises(ValidationError):
        ModelDeployment(
            kind=DeploymentKind.LOCAL,
            model="some-model",
            endpoint="https://user:secret@example.test/v1",
        )
    with pytest.raises(ValidationError):
        ModelDeployment(
            kind=DeploymentKind.LOCAL,
            model="some-model",
            endpoint="https://example.test/v1?api_key=secret",
        )
    with pytest.raises(ValidationError):
        ModelDeployment(
            kind=DeploymentKind.OPENROUTER,
            model="some-model",
            endpoint="https://openrouter.ai/api/v1",
            provider_policy={"providers": ("google-ai-studio",)},
        )
    with pytest.raises(ValidationError):
        OpenRouterProviderPolicy(
            providers=("google-ai-studio",),
            exclusive=False,
        )
    with pytest.raises(ValidationError):
        OpenRouterProviderPolicy(
            providers=("google-ai-studio",),
            allow_fallback=False,
        )
    with pytest.raises(ValidationError):
        OpenRouterProviderPolicy(
            providers=("google-ai-studio",),
            require_parameters=False,
        )
