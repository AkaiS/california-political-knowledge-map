import os

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

# Normalise the `content: null` pydantic-ai emits for a text-free tool call:
# some OpenAI-compatible servers 400 on it, and only on a retry turn.  Patched
# at import so every `get_chat_model` caller is covered.
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

    base_url = os.environ.get("LLAMA_CPP_BASE_URL", "http://localhost:8080")
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
            supports_json_schema_output=True,
            supports_json_object_output=True,
        ),
    )


_models: dict[tuple[str, str], OpenAIChatModel] = {}


def _build_model(
    model_name: str,
    base_url: str,
    transport_settings: TransportSettings | None,
    transport: httpx.AsyncBaseTransport | None,
) -> OpenAIChatModel:
    # Retries belong to the transport, so the SDK makes exactly one attempt
    # rather than multiplying the configured count.
    openai_client = AsyncOpenAI(
        base_url=base_url,
        api_key=os.environ.get("LLAMA_CPP_API_KEY") or "api-key-not-set",
        http_client=build_retrying_client(transport_settings, transport),
        max_retries=0,
    )
    provider = OpenAIProvider(openai_client=openai_client)
    return OpenAIChatModel(
        model_name,
        provider=provider,
        profile=llama_cpp_model_profile(model_name),
        settings=OpenAIChatModelSettings(
            temperature=resolve_temperature(),
            # Read by the chat template, not by the sampler, so it has to travel
            # in the request body rather than as a sampling parameter.
            extra_body={"chat_template_kwargs": {"enable_thinking": resolve_thinking()}},
        ),
    )


def get_chat_model(
    default_model: str,
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

    Memoized by resolved model name and base URL, so agents share one client
    and connection pool.  Passing a transport or settings block bypasses the
    cache in both directions.
    """

    load_dotenv()

    base_url = resolve_chat_base_url()
    model_name = _resolve_model_name(default_model, env_var_name, allow_env_override)

    if transport is not None or transport_settings is not None:
        return _build_model(model_name, base_url, transport_settings, transport)

    key = (model_name, base_url)
    model = _models.get(key)
    if model is None:
        model = _build_model(model_name, base_url, None, None)
        _models[key] = model
    return model
