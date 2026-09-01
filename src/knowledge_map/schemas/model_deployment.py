"""Typed value objects describing the chat Model Deployment contract."""

from enum import StrEnum
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class DeploymentKind(StrEnum):
    """The chat deployment kinds supported by the model factory."""

    LOCAL = "local"
    OPENROUTER = "openrouter"


class ModelRequestSettings(BaseModel):
    """Effective request settings shared by chat Model Deployments."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        hide_input_in_errors=True,
    )

    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    top_p: float | None = Field(default=None, gt=0.0, le=1.0)
    top_k: int | None = Field(default=None, ge=1)
    thinking: bool | None = False
    reasoning_effort: str | None = Field(default=None, min_length=1)
    max_tokens: int | None = Field(default=None, ge=1)
    timeout: float = Field(default=3600.0, gt=0.0)
    max_attempts: int = Field(default=3, ge=1)
    rate_limit_wait_cap: float = Field(default=120.0, ge=0.0)

    @field_validator("reasoning_effort")
    @classmethod
    def reasoning_effort_is_not_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("reasoning effort must be non-empty when provided")
        return value


class OpenRouterProviderPolicy(BaseModel):
    """The ordered provider policy for one OpenRouter Model Deployment."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        hide_input_in_errors=True,
    )

    providers: tuple[str, ...] = Field(min_length=1)
    allow_fallback: bool = True
    require_parameters: bool = True
    exclusive: bool = True

    @field_validator("providers")
    @classmethod
    def providers_are_non_empty_and_unique(
        cls, value: tuple[str, ...]
    ) -> tuple[str, ...]:
        if not value:
            raise ValueError(
                "an OpenRouter provider policy needs at least one provider"
            )
        if any(not provider.strip() for provider in value):
            raise ValueError("OpenRouter providers must be non-empty")
        if len(set(value)) != len(value):
            raise ValueError("OpenRouter providers must not be repeated")
        return value

    @model_validator(mode="after")
    def require_routing_guards(self) -> "OpenRouterProviderPolicy":
        if not self.exclusive:
            raise ValueError("OpenRouter provider policy must be exclusive")
        if not self.allow_fallback:
            raise ValueError("OpenRouter provider fallback must remain enabled")
        if not self.require_parameters:
            raise ValueError(
                "OpenRouter provider policy must require parameter support"
            )
        return self


class ModelDeployment(BaseModel):
    """A concrete chat deployment, safe to retain as run provenance."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        hide_input_in_errors=True,
    )

    kind: DeploymentKind
    model: str = Field(min_length=1)
    request_settings: ModelRequestSettings = Field(
        default_factory=ModelRequestSettings
    )
    endpoint: str | None = None
    provider_policy: OpenRouterProviderPolicy | None = None

    @field_validator("model")
    @classmethod
    def model_name_is_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("the requested model must be non-empty")
        return value

    @field_validator("endpoint")
    @classmethod
    def endpoint_is_public_url_without_credentials(
        cls, value: str | None
    ) -> str | None:
        if value is None:
            return None
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("endpoint must be an absolute HTTP or HTTPS URL")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("endpoint must not carry credentials or query data")
        return value

    @model_validator(mode="after")
    def route_matches_kind(self) -> "ModelDeployment":
        if self.kind is DeploymentKind.OPENROUTER and self.provider_policy is None:
            raise ValueError("an OpenRouter Model Deployment needs a provider policy")
        if self.kind is DeploymentKind.OPENROUTER and self.endpoint is not None:
            raise ValueError(
                "an OpenRouter Model Deployment cannot carry a local endpoint"
            )
        if self.kind is DeploymentKind.LOCAL and self.provider_policy is not None:
            raise ValueError(
                "a local Model Deployment cannot carry an OpenRouter policy"
            )
        return self
