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

# An OpenAI-compatible endpoint may reject an assistant message carrying
# `content: null`, which pydantic-ai emits for a tool call with no text.  Ollama
# does, with a 400 ("invalid message content type: <nil>"), and because that
# shape only appears on a retry turn it surfaces part-way through a run rather
# than on the first request.  Normalising null to "" costs nothing on a server
# that would have accepted it.
#
# This lives here rather than beside any one agent so that every caller of
# `get_chat_model` is covered by construction, instead of depending on which
# modules happened to be imported first.
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


def resolve_chat_base_url() -> str:
    """The llama.cpp base URL, normalised to the OpenAI-compatible ``/v1`` path.

    Chat runs on llama.cpp rather than Ollama because Ollama accepts
    ``tool_choice: "required"`` and then ignores it, leaving pydantic-ai's
    structured output tool as a suggestion the model may answer in prose.
    ``llama-server`` compiles the tool schema to a GBNF grammar and constrains
    decoding, so the tool call is the only output the sampler can reach.
    """

    base_url = os.environ.get("LLAMA_CPP_BASE_URL", "http://localhost:8080")
    if base_url.endswith("/v1"):
        return base_url
    return f"{base_url}/v1"


def resolve_embedding_base_url() -> str:
    """The embedding server's base URL, normalised to the ``/v1`` path.

    Embedding runs on its own ``llama-server`` process, on its own port, because
    ``llama-server`` serves one model per process and chat already holds 8080.
    Nothing about an embedding call needs a grammar; the second process exists so
    that the pipeline depends on Ollama for nothing.  Start it with
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

    Extraction and coreference are transcription tasks against a fixed Source
    Article, so sampling breadth is not wanted: the default is 0.  It is set on
    the client as well as by ``scripts/llama-server.sh --temp 0`` so that a run
    is deterministic regardless of how the server was started.
    """

    return float(os.environ.get("LLM_TEMPERATURE") or 0.0)


def resolve_thinking() -> bool:
    """Whether the model reasons before answering.  It does not, by default.

    Gemma 4's own template defaults `enable_thinking` to false; llama.cpp's
    `--reasoning auto` sees that the template *supports* thinking and turns it
    on. Nothing then bounds it, because pydantic-ai sends no `max_tokens`: one
    annotator call was measured emitting 6,181 characters of reasoning and no
    tool call at all, and another was still going at 7,480 tokens. With thinking
    off the same call returns a complete tool call in 724 tokens.

    Coreference and extraction transcribe a fixed Source Article rather than
    reason toward a conclusion, so the reasoning was not buying anything.
    """

    return (os.environ.get("LLM_THINKING") or "off").strip().lower() in {
        "1", "on", "true", "yes",
    }


def _resolve_model_name(default_model: str, env_var_name: str | None) -> str:
    if env_var_name:
        model_name = os.environ.get(env_var_name)
        if model_name:
            return model_name
    return os.environ.get("OLLAMA_MODEL") or default_model


def llama_cpp_model_profile(model_name: str) -> ModelProfile | None:
    """The capabilities of a model served by ``llama-server``.

    ``llama-server`` has no strict-tool-definition mode, and its ``json_schema``
    response format is a GBNF grammar rather than OpenAI's ``strict`` schema
    validator, so both are declared explicitly.  The underlying model's own
    profile still applies underneath — the weights are the same ones Ollama was
    serving.

    Tool schemas are inlined rather than passed as ``$ref``/``$defs``.  A schema
    containing a ``$ref`` does not produce a grammar in ``llama-server``: instead
    of failing, it drops the constraint and lets the model generate freely, which
    it does until it runs out of context, because pydantic-ai sends no
    ``max_tokens``.  Measured on one 25-sentence article, the same annotator
    request took 66s and produced 4000 unconstrained tokens and no tool call with
    ``$ref``, against 18s and a valid 30-span tool call once inlined.
    """

    # Local builds are named for their context window or their purpose as often
    # as for their family -- `32k-gemma-e4b-extraction` is still a gemma -- so
    # the family is matched anywhere in the name rather than as a prefix.
    upstream = None
    if "gemma" in model_name.lower():
        upstream = google_model_profile(model_name)

    return merge_profile(
        upstream,
        OpenAIModelProfile(
            # Last position deliberately: `merge_profile` is last-wins, and the
            # upstream google profile carries a transformer that keeps `$ref`.
            json_schema_transformer=InlineDefsJsonSchemaTransformer,
            # Structured output goes through `response_format: json_schema`
            # rather than a tool call.  Gemma 4's tool-call syntax does not match
            # the `peg-gemma4` parser in llama-server: the model answers
            # correctly, closes with a literal `<tool_call|>` -- which is not a
            # real special token, so it does not stop decoding -- and then
            # repeats the whole answer until the context runs out.  The parser
            # finds no tool call, pydantic-ai sees no result, and retries.  The
            # `json_schema` path compiles a GBNF grammar instead and terminates:
            # the same critic request went from 1500+ tokens and no result to
            # 123 tokens and a valid answer in 3s.
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
    # The OpenAI SDK retries on its own by default, which would multiply the
    # configured attempt count rather than replace it.  Retries belong to the
    # transport, so the SDK is told to make exactly one attempt.
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
    transport_settings: TransportSettings | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> OpenAIChatModel:
    """Get a chat model served by llama.cpp, on the retrying HTTP client.

    Loads configuration from environment variables:
    1. Base URL is read from `LLAMA_CPP_BASE_URL` (default: "http://localhost:8080").
       Automatically ensures the URL ends with "/v1".
    2. Model name is read from:
       - The custom `env_var_name` if specified (e.g., OLLAMA_MODEL_HEALING).
       - Fallback to the general `OLLAMA_MODEL` environment variable.
       - Fallback to the provided `default_model`.

    The model name is what `llama-server --alias` was given; the server serves
    whichever GGUF it was started with either way, so the name identifies the
    intended model rather than selecting one.

    The result is memoized by resolved model name and base URL, so repeated
    agent construction shares one provider, one client, and one connection
    pool.  An injected transport or an explicit settings block is a caller
    supplying its own wiring, so it is neither served from nor written to that
    cache.
    """

    load_dotenv()

    base_url = resolve_chat_base_url()
    model_name = _resolve_model_name(default_model, env_var_name)

    if transport is not None or transport_settings is not None:
        return _build_model(model_name, base_url, transport_settings, transport)

    key = (model_name, base_url)
    model = _models.get(key)
    if model is None:
        model = _build_model(model_name, base_url, None, None)
        _models[key] = model
    return model
