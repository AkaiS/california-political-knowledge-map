"""Resolve command-selected Model Deployments from process configuration."""

import os

from knowledge_map.schemas import (
    DeploymentKind,
    ModelDeployment,
    OpenRouterProviderPolicy,
)

from .models import resolve_chat_base_url, resolve_local_chat_model


def deployment_from_environment(
    kind: str | DeploymentKind,
    *,
    default_local_model: str,
    model_override: str | None = None,
    command_name: str,
) -> ModelDeployment:
    """Build and validate one command-selected chat deployment."""

    deployment_kind = DeploymentKind(kind)
    if deployment_kind is DeploymentKind.LOCAL:
        configured_model = resolve_local_chat_model(default_local_model)
        model = configured_model if model_override is None else model_override
        return ModelDeployment(
            kind=deployment_kind,
            model=model,
            endpoint=resolve_chat_base_url(),
        )

    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    configured_model = os.environ.get("OPENROUTER_MODEL", "").strip()
    provider_text = os.environ.get("OPENROUTER_PROVIDERS", "")
    providers = tuple(provider.strip() for provider in provider_text.split(","))
    missing: list[str] = []
    if not api_key:
        missing.append("OPENROUTER_API_KEY")
    if model_override is None:
        model = configured_model
        model_setting = "OPENROUTER_MODEL"
    else:
        model = model_override
        model_setting = "--model"
    if not model or not model.strip():
        missing.append(model_setting)
    if not provider_text.strip() or any(not provider for provider in providers):
        missing.append("OPENROUTER_PROVIDERS")
    if missing:
        raise ValueError(
            f"OpenRouter {command_name} deployment is incomplete; set "
            + ", ".join(missing)
        )

    return ModelDeployment(
        kind=deployment_kind,
        model=model,
        provider_policy=OpenRouterProviderPolicy(providers=providers),
    )
