import os

import httpx
from dotenv import load_dotenv
from openai import AsyncOpenAI
from pydantic_ai.models.ollama import OllamaModel
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.ollama import OllamaProvider
from pydantic_ai.retries import AsyncTenacityTransport, RetryConfig, wait_retry_after
from tenacity import retry_if_exception_type, stop_after_attempt

from knowledge_map.config import TransportSettings, settings

# Ollama's OpenAI-compatible endpoint rejects an assistant message carrying
# `content: null`, which pydantic-ai emits for a tool call with no text. That
# shape only appears on a retry turn, so it surfaces as a sporadic 400
# ("invalid message content type: <nil>") part-way through a run.
#
# This lives here rather than beside any one agent so that every caller of
# `get_ollama_model` is covered by construction, instead of depending on
# which modules happened to be imported first.
_original_into_message_param = OpenAIChatModel._MapModelResponseContext._into_message_param


def _into_message_param_with_empty_content(self):
    result = _original_into_message_param(self)
    if result is not None and result.get("content") is None:
        result["content"] = ""
    return result


OpenAIChatModel._MapModelResponseContext._into_message_param = (
    _into_message_param_with_empty_content
)


def build_retrying_client(
    transport_settings: TransportSettings | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> httpx.AsyncClient:
    """Build the HTTP client that retries a failed request where it failed.

    A rate limit or a dropped connection is retried inside the model call that
    hit it, so an interrupted Coreference Critic round resumes rather than the
    Source Article restarting.  ``raise_for_status`` turns a 429 into a
    retryable exception instead of a response the caller has to interpret, and
    the wait comes from the ``Retry-After`` header httpx already parsed.
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


def resolve_base_url() -> str:
    """The Ollama base URL, normalised to the OpenAI-compatible ``/v1`` path."""

    ollama_base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
    if ollama_base_url.endswith("/v1"):
        return ollama_base_url
    return f"{ollama_base_url}/v1"


def _resolve_model_name(default_model: str, env_var_name: str | None) -> str:
    if env_var_name:
        model_name = os.environ.get(env_var_name)
        if model_name:
            return model_name
    return os.environ.get("OLLAMA_MODEL") or default_model


_models: dict[tuple[str, str], OllamaModel] = {}


def _build_model(
    model_name: str,
    base_url: str,
    transport_settings: TransportSettings | None,
    transport: httpx.AsyncBaseTransport | None,
) -> OllamaModel:
    # The OpenAI SDK retries on its own by default, which would multiply the
    # configured attempt count rather than replace it.  Retries belong to the
    # transport, so the SDK is told to make exactly one attempt.
    openai_client = AsyncOpenAI(
        base_url=base_url,
        api_key=os.environ.get("OLLAMA_API_KEY") or "api-key-not-set",
        http_client=build_retrying_client(transport_settings, transport),
        max_retries=0,
    )
    provider = OllamaProvider(openai_client=openai_client)
    return OllamaModel(model_name=model_name, provider=provider)


def get_ollama_model(
    default_model: str,
    env_var_name: str | None = None,
    *,
    transport_settings: TransportSettings | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> OllamaModel:
    """Get a configured `OllamaModel` backed by the retrying HTTP client.

    Loads configuration from environment variables:
    1. Base URL is read from `OLLAMA_BASE_URL` (default: "http://localhost:11434").
       Automatically ensures the URL ends with "/v1".
    2. Model name is read from:
       - The custom `env_var_name` if specified (e.g., OLLAMA_MODEL_HEALING).
       - Fallback to the general `OLLAMA_MODEL` environment variable.
       - Fallback to the provided `default_model`.

    The result is memoized by resolved model name and base URL, so repeated
    agent construction shares one provider, one client, and one connection
    pool.  An injected transport or an explicit settings block is a caller
    supplying its own wiring, so it is neither served from nor written to that
    cache.
    """

    load_dotenv()

    base_url = resolve_base_url()
    model_name = _resolve_model_name(default_model, env_var_name)

    if transport is not None or transport_settings is not None:
        return _build_model(model_name, base_url, transport_settings, transport)

    key = (model_name, base_url)
    model = _models.get(key)
    if model is None:
        model = _build_model(model_name, base_url, None, None)
        _models[key] = model
    return model
