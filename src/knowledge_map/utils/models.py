import os
from dataclasses import dataclass

import httpx
from dotenv import load_dotenv
from openai import AsyncOpenAI
from pydantic_ai import ModelProfile
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIChatModelSettings
from pydantic_ai.profiles import InlineDefsJsonSchemaTransformer, merge_profile
from pydantic_ai.profiles.google import google_model_profile
from pydantic_ai.profiles.openai import OpenAIModelProfile
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.retries import AsyncTenacityTransport, RetryConfig, wait_retry_after
from tenacity import retry_if_exception_type, stop_after_attempt

from knowledge_map.config import TransportSettings, settings
from knowledge_map.schemas import DeploymentKind, ModelDeployment, ModelRequestSettings


class _LocalOpenAIChatModel(OpenAIChatModel):
    """OpenAI-compatible model with llama.cpp's empty-content workaround."""

    @dataclass
    class _MapModelResponseContext(OpenAIChatModel._MapModelResponseContext):
        def _into_message_param(self):
            # Normalize the ``content: null`` pydantic-ai emits for a text-free
            # tool call: llama.cpp rejects it on the retry request.
            result = super()._into_message_param()
            if result is not None and result.get("content") is None:
                result["content"] = ""
            return result


def build_retrying_client(
    transport_settings: TransportSettings | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> httpx.AsyncClient:
    """Build the HTTP client that retries a failed request where it failed.

    Every model in this module runs on one of these, so callers never see a
    rate limit or a dropped connection as a response.
    """

    transport_settings = transport_settings or settings.transport
    retrying_transport = AsyncTenacityTransport(
        RetryConfig(
            retry=retry_if_exception_type(
                (httpx.HTTPStatusError, httpx.TransportError)
            ),
            wait=wait_retry_after(max_wait=transport_settings.rate_limit_wait_cap),
            stop=stop_after_attempt(transport_settings.max_attempts),
            reraise=True,
        ),
        wrapped=transport,
        validate_response=lambda response: response.raise_for_status(),
    )
    return httpx.AsyncClient(
        transport=retrying_transport,
        timeout=transport_settings.request_timeout,
    )


def resolve_chat_base_url() -> str:
    """The llama.cpp base URL, normalised to the OpenAI-compatible ``/v1`` path.

    Read from ``LLAMA_CPP_BASE_URL``, default ``http://localhost:8080``.
    """

    return _normalise_chat_base_url(
        os.environ.get("LLAMA_CPP_BASE_URL", "http://localhost:8080")
    )


def _normalise_chat_base_url(base_url: str) -> str:
    base_url = base_url.rstrip("/")
    if base_url.endswith("/v1"):
        return base_url
    return f"{base_url}/v1"


def resolve_embedding_base_url() -> str:
    """The embedding server's base URL, normalised to the ``/v1`` path.

    A second ``llama-server`` process on its own port, started with
    ``scripts/llama-embed.sh``.
    """

    base_url = os.environ.get(
        "LLAMA_CPP_EMBEDDING_BASE_URL", "http://localhost:8081"
    )
    if base_url.endswith("/v1"):
        return base_url
    return f"{base_url}/v1"


def resolve_temperature() -> float:
    """The sampling temperature every agent runs at.

    Read from ``LLM_TEMPERATURE``, default 0.  Set here as well as on the
    server, so a run is deterministic however the server was started.
    """

    return float(os.environ.get("LLM_TEMPERATURE") or 0.0)


def resolve_thinking() -> bool:
    """Whether the model reasons before answering.  It does not, by default.

    Read from ``LLM_THINKING``.  Turning it on lets a call reason unbounded,
    since pydantic-ai sends no ``max_tokens``.
    """

    return (os.environ.get("LLM_THINKING") or "off").strip().lower() in {
        "1", "on", "true", "yes",
    }


def _resolve_model_name(
    default_model: str,
    env_var_name: str | None,
    allow_env_override: bool = True,
) -> str:
    if not allow_env_override:
        return default_model
    if env_var_name:
        model_name = os.environ.get(env_var_name)
        if model_name:
            return model_name
    return os.environ.get("OLLAMA_MODEL") or default_model


def llama_cpp_model_profile(model_name: str) -> ModelProfile | None:
    """The capabilities of a model served by ``llama-server``.

    Layered over the underlying model's own profile.  Tool schemas must be
    inlined: ``llama-server`` silently drops the grammar constraint for a
    schema containing a ``$ref``, and the model then generates unbounded.
    """

    # Local builds are named for their context window or purpose as often as
    # their family -- `32k-gemma-e4b-extraction` is still a gemma.
    upstream = None
    if "gemma" in model_name.lower():
        upstream = google_model_profile(model_name)

    return merge_profile(
        upstream,
        OpenAIModelProfile(
            # Last position deliberately: `merge_profile` is last-wins, and the
            # upstream google profile carries a transformer that keeps `$ref`.
            json_schema_transformer=InlineDefsJsonSchemaTransformer,
            # Structured output goes through `response_format: json_schema`,
            # not a tool call: llama-server's `peg-gemma4` parser does not
            # match Gemma 4's tool-call syntax, and the model then decodes
            # until the context runs out.
            default_structured_output_mode="native",
            openai_chat_thinking_field="reasoning_content",
            openai_supports_strict_tool_definition=False,
            openai_chat_supports_max_completion_tokens=False,
            supports_json_schema_output=True,
            supports_json_object_output=True,
        ),
    )


_models: dict[
    tuple[ModelDeployment, httpx.AsyncBaseTransport | None], OpenAIChatModel
] = {}


def _deployment_transport_settings(
    request_settings: ModelRequestSettings,
    transport_settings: TransportSettings | None,
) -> TransportSettings:
    """Resolve retry and client timeout settings for one local deployment."""

    configured = transport_settings or settings.transport
    return TransportSettings(
        max_attempts=(
            transport_settings.max_attempts
            if transport_settings is not None
            else request_settings.max_attempts
        ),
        rate_limit_wait_cap=(
            transport_settings.rate_limit_wait_cap
            if transport_settings is not None
            else request_settings.rate_limit_wait_cap
        ),
        request_timeout=(
            request_settings.timeout
            if request_settings.timeout is not None
            else configured.request_timeout
        ),
    )


def _build_model(
    model_name: str,
    base_url: str,
    request_settings: ModelRequestSettings | None,
    transport_settings: TransportSettings | None,
    transport: httpx.AsyncBaseTransport | None,
) -> OpenAIChatModel:
    # Retries belong to the transport, so the SDK makes exactly one attempt
    # rather than multiplying the configured count.
    request_settings = request_settings or ModelRequestSettings(
        temperature=resolve_temperature(),
        thinking=resolve_thinking(),
        max_attempts=(
            transport_settings.max_attempts
            if transport_settings is not None
            else settings.transport.max_attempts
        ),
        rate_limit_wait_cap=(
            transport_settings.rate_limit_wait_cap
            if transport_settings is not None
            else settings.transport.rate_limit_wait_cap
        ),
        timeout=(
            transport_settings.request_timeout
            if transport_settings is not None
            else None
        ),
    )
    effective_transport_settings = _deployment_transport_settings(
        request_settings, transport_settings
    )
    openai_client = AsyncOpenAI(
        base_url=base_url,
        api_key=os.environ.get("LLAMA_CPP_API_KEY") or "api-key-not-set",
        http_client=build_retrying_client(effective_transport_settings, transport),
        max_retries=0,
    )
    provider = OpenAIProvider(openai_client=openai_client)
    extra_body = {
        "chat_template_kwargs": {
            "enable_thinking": (
                request_settings.thinking
                if request_settings.thinking is not None
                else resolve_thinking()
            )
        }
    }
    if request_settings.top_k is not None:
        extra_body["top_k"] = request_settings.top_k
    return _LocalOpenAIChatModel(
        model_name,
        provider=provider,
        profile=llama_cpp_model_profile(model_name),
        settings=OpenAIChatModelSettings(
            temperature=request_settings.temperature,
            top_p=request_settings.top_p,
            max_tokens=request_settings.max_tokens,
            timeout=effective_transport_settings.request_timeout,
            # Read by the chat template, not by the sampler, so it has to travel
            # in the request body rather than as a sampling parameter.
            extra_body=extra_body,
        ),
    )


def get_chat_model(
    default_model: str | ModelDeployment,
    env_var_name: str | None = None,
    *,
    allow_env_override: bool = True,
    transport_settings: TransportSettings | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> OpenAIChatModel:
    """Get a chat model served by llama.cpp, on the retrying HTTP client.

    The model name resolves from ``env_var_name`` (e.g.
    ``OLLAMA_MODEL_HEALING``), then ``OLLAMA_MODEL``, then ``default_model``.
    It names what ``llama-server --alias`` was given; the server serves
    whichever GGUF it was started with regardless.

    Pass ``allow_env_override=False`` to use ``default_model`` verbatim, as an
    evaluation run naming the model it is comparing must.

    Typed local deployments are memoized by their effective identity and an
    injected transport, so equivalent agents share one client and connection
    pool without allowing distinct mock transports to leak into one another.
    Legacy string calls retain their existing environment lookup behavior.
    """

    load_dotenv()

    if isinstance(default_model, ModelDeployment):
        if default_model.kind is not DeploymentKind.LOCAL:
            raise ValueError(
                "the local chat model factory only accepts local deployments"
            )
        if env_var_name is not None:
            raise ValueError(
                "a Model Deployment cannot be combined with model environment overrides"
            )
        base_url = _normalise_chat_base_url(
            default_model.endpoint or resolve_chat_base_url()
        )
        request_settings = default_model.request_settings
        if request_settings.thinking is None:
            request_settings = request_settings.model_copy(
                update={"thinking": resolve_thinking()}
            )
        effective_deployment = default_model.model_copy(
            update={"endpoint": base_url, "request_settings": request_settings}
        )
        if transport_settings is not None:
            return _build_model(
                effective_deployment.model,
                base_url,
                request_settings,
                transport_settings,
                transport,
            )
        key = (effective_deployment, transport)
        model = _models.get(key)
        if model is None:
            model = _build_model(
                effective_deployment.model,
                base_url,
                request_settings,
                None,
                transport,
            )
            _models[key] = model
        return model

    base_url = resolve_chat_base_url()
    model_name = _resolve_model_name(default_model, env_var_name, allow_env_override)

    if transport is not None or transport_settings is not None:
        return _build_model(model_name, base_url, None, transport_settings, transport)

    deployment = ModelDeployment(
        kind=DeploymentKind.LOCAL,
        model=model_name,
        endpoint=base_url,
        request_settings=ModelRequestSettings(
            temperature=resolve_temperature(),
            thinking=resolve_thinking(),
            max_attempts=settings.transport.max_attempts,
            rate_limit_wait_cap=settings.transport.rate_limit_wait_cap,
        ),
    )
    key = (deployment, None)
    model = _models.get(key)
    if model is None:
        model = _build_model(
            deployment.model, base_url, deployment.request_settings, None, None
        )
        _models[key] = model
    return model
