import asyncio
import math
import os
import random
import threading
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from types import TracebackType
from typing import Self

import httpx
from dotenv import load_dotenv
from openai import AsyncOpenAI
from pydantic_ai import ModelProfile
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIChatModelSettings
from pydantic_ai.models.openrouter import OpenRouterModel, OpenRouterModelSettings
from pydantic_ai.profiles import InlineDefsJsonSchemaTransformer, merge_profile
from pydantic_ai.profiles.google import google_model_profile
from pydantic_ai.profiles.openai import OpenAIModelProfile
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.providers.openrouter import OpenRouterProvider
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
    """Build the HTTP client used to retry failed local model requests.

    A rate limit or dropped connection is retried before the local model sees
    it as a response.
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


_RETRYABLE_OPENROUTER_STATUS_CODES = frozenset({
    500,
    502,
    503,
    504,
    524,
    529,
})


class OpenRouterAdmissionGate:
    """Coordinate the pause for new OpenRouter requests."""

    def __init__(self) -> None:
        self._deadline = 0.0
        self._paused = False
        self._probe_in_flight = False
        self._lock = threading.Lock()
        self._waiters: dict[asyncio.AbstractEventLoop, set[asyncio.Event]] = {}

    def pause_until(self, deadline: float) -> None:
        with self._lock:
            self._deadline = max(self._deadline, deadline)
            self._paused = True
        self._wake_waiters()

    def _try_admit(self, now: float) -> tuple[float | None, bool, bool]:
        with self._lock:
            if not self._paused:
                return None, False, False
            remaining = self._deadline - now
            if remaining > 0:
                return remaining, False, False
            if self._probe_in_flight:
                return None, False, True
            # This check is the admission point. A pause racing after it
            # affects later requests, not this already-admitted request.
            self._probe_in_flight = True
            return None, True, False

    def _register_waiter(self) -> asyncio.Event:
        loop = asyncio.get_running_loop()
        event = asyncio.Event()
        with self._lock:
            self._waiters.setdefault(loop, set()).add(event)
        return event

    def _unregister_waiter(self, event: asyncio.Event) -> None:
        loop = asyncio.get_running_loop()
        with self._lock:
            events = self._waiters.get(loop)
            if events is None:
                return
            events.discard(event)
            if not events:
                self._waiters.pop(loop, None)

    def _wake_waiters(self) -> None:
        with self._lock:
            waiters = tuple(
                (loop, event)
                for loop, events in self._waiters.items()
                for event in events
            )
        for loop, event in waiters:
            if loop.is_closed():
                continue
            try:
                loop.call_soon_threadsafe(event.set)
            except RuntimeError:
                # The loop may close between ``is_closed`` and scheduling.
                continue

    def _probe_is_in_flight(self) -> bool:
        with self._lock:
            return self._probe_in_flight

    def probe_succeeded(self, now: float) -> None:
        with self._lock:
            if not self._probe_in_flight:
                return
            self._probe_in_flight = False
            if self._deadline <= now:
                self._paused = False
        self._wake_waiters()

    def probe_rate_limited(self) -> None:
        with self._lock:
            if not self._probe_in_flight:
                return
            self._probe_in_flight = False
            self._paused = True
        self._wake_waiters()

    def probe_failed(self) -> None:
        with self._lock:
            if not self._probe_in_flight:
                return
            # Release only this probe's permit. A failed probe is not evidence
            # that the route is healthy, so waiting callers must not bypass the
            # pause until another caller can probe it.
            self._probe_in_flight = False
            self._paused = True
        self._wake_waiters()

    async def wait_until_open(self, hooks: "OpenRouterRetryHooks") -> bool:
        while True:
            wait, is_probe, wait_for_probe = self._try_admit(hooks.now())
            if is_probe or (wait is None and not wait_for_probe):
                return is_probe
            if wait is not None:
                await hooks.sleep(wait)
                continue
            event = self._register_waiter()
            try:
                if self._probe_is_in_flight():
                    await event.wait()
            finally:
                self._unregister_waiter(event)


_DEFAULT_OPENROUTER_ADMISSION_GATE = OpenRouterAdmissionGate()


def _default_openrouter_jitter(max_delay: float) -> float:
    return random.uniform(0.0, max_delay)


@dataclass(frozen=True)
class OpenRouterRetryHooks:
    """Clock and wait hooks for deterministic OpenRouter retry behavior.

    ``now`` returns Unix epoch seconds, ``sleep`` receives the selected delay,
    and ``jitter`` receives the exponential-delay upper bound and returns the
    actual fallback delay.
    """

    now: Callable[[], float] = time.time
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep
    jitter: Callable[[float], float] = _default_openrouter_jitter
    admission_gate: OpenRouterAdmissionGate | None = None


def _parse_openrouter_reset_wait(
    value: str | None,
    now: float,
) -> float | None:
    """Parse OpenRouter's Unix reset timestamp in seconds or milliseconds."""

    if not value:
        return None
    try:
        reset = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(reset):
        return None
    if reset >= 10_000_000_000:
        reset /= 1_000
    wait = reset - now
    return wait if wait >= 0 else None


def _parse_retry_after_wait(
    value: str | None,
    now: float,
) -> float | None:
    """Parse RFC 9110 delay-seconds or HTTP-date Retry-After evidence."""

    if not value:
        return None
    value = value.strip()
    if value.isascii() and value.isdecimal():
        return float(value)

    for date_format in (
        "%a, %d %b %Y %H:%M:%S GMT",
        "%A, %d-%b-%y %H:%M:%S GMT",
        "%a %b %d %H:%M:%S %Y",
    ):
        try:
            retry_at = datetime.strptime(value, date_format).replace(tzinfo=UTC)
        except ValueError:
            continue
        wait = retry_at.timestamp() - now
        return wait if wait >= 0 else None
    return None


class _OpenRouterRetryTransport(httpx.AsyncBaseTransport):
    """Retry request-local OpenRouter failures that are safe to repeat."""

    def __init__(
        self,
        wrapped: httpx.AsyncBaseTransport | None,
        max_attempts: int,
        rate_limit_wait_cap: float,
        retry_hooks: OpenRouterRetryHooks | None = None,
    ) -> None:
        self._wrapped = (
            wrapped if wrapped is not None else httpx.AsyncHTTPTransport()
        )
        self._max_attempts = max_attempts
        self._rate_limit_wait_cap = rate_limit_wait_cap
        self._retry_hooks = retry_hooks or OpenRouterRetryHooks()
        self._admission_gate = (
            self._retry_hooks.admission_gate or _DEFAULT_OPENROUTER_ADMISSION_GATE
        )

    def _bounded_wait(self, wait: float) -> float:
        return min(max(wait, 0.0), self._rate_limit_wait_cap)

    def _rate_limit_wait(
        self,
        response: httpx.Response,
        retry_index: int,
        now: float | None = None,
    ) -> float:
        now = self._retry_hooks.now() if now is None else now
        reset_wait = _parse_openrouter_reset_wait(
            response.headers.get("X-RateLimit-Reset"), now
        )
        if reset_wait is not None:
            return self._bounded_wait(reset_wait)

        retry_after_wait = _parse_retry_after_wait(
            response.headers.get("Retry-After"), now
        )
        if retry_after_wait is not None:
            return self._bounded_wait(retry_after_wait)

        exponential_wait = min(self._rate_limit_wait_cap, 2.0**retry_index)
        return self._bounded_wait(self._retry_hooks.jitter(exponential_wait))

    async def __aenter__(self) -> Self:
        await self._wrapped.__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None = None,
        exc_value: BaseException | None = None,
        traceback: TracebackType | None = None,
    ) -> None:
        await self._wrapped.__aexit__(exc_type, exc_value, traceback)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        is_probe = await self._admission_gate.wait_until_open(self._retry_hooks)
        try:
            for attempt in range(self._max_attempts):
                try:
                    response = await self._wrapped.handle_async_request(request)
                except httpx.TransportError:
                    if attempt + 1 == self._max_attempts:
                        raise
                    continue

                if response.status_code == 429:
                    now = self._retry_hooks.now()
                    wait = self._rate_limit_wait(response, attempt, now)
                    self._admission_gate.pause_until(now + wait)
                    if attempt + 1 < self._max_attempts:
                        # Release the failed response before waiting so its
                        # connection is available while this request backs off.
                        await response.aclose()
                        # This request was admitted before the 429; let its
                        # request-local retry finish while new callers wait.
                        await self._retry_hooks.sleep(wait)
                        continue
                    if is_probe:
                        self._admission_gate.probe_rate_limited()
                    return response

                if (
                    response.status_code in _RETRYABLE_OPENROUTER_STATUS_CODES
                    and attempt + 1 < self._max_attempts
                ):
                    # Return the final response so OpenAI can preserve its typed
                    # HTTP error; raising here would turn it into a connection error.
                    await response.aclose()
                    continue
                if is_probe:
                    self._admission_gate.probe_succeeded(self._retry_hooks.now())
                return response
        except BaseException:
            if is_probe:
                self._admission_gate.probe_failed()
            raise

        raise AssertionError("OpenRouter retry transport made no attempt")

    async def aclose(self) -> None:
        await self._wrapped.aclose()


def _openrouter_retry_transport(
    transport_settings: TransportSettings,
    transport: httpx.AsyncBaseTransport | None,
    retry_hooks: OpenRouterRetryHooks | None = None,
) -> httpx.AsyncBaseTransport:
    """Apply bounded OpenRouter retries at the HTTP boundary."""

    return _OpenRouterRetryTransport(
        transport,
        transport_settings.max_attempts,
        transport_settings.rate_limit_wait_cap,
        retry_hooks,
    )


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


def _build_openrouter_model(
    deployment: ModelDeployment,
    transport_settings: TransportSettings | None,
    transport: httpx.AsyncBaseTransport | None,
    retry_hooks: OpenRouterRetryHooks | None = None,
) -> OpenRouterModel:
    """Build one native OpenRouter model with deployment request settings."""

    request_settings = deployment.request_settings
    effective_transport_settings = _deployment_transport_settings(
        request_settings, transport_settings
    )
    request_timeout = (
        request_settings.timeout
        if request_settings.timeout is not None
        else effective_transport_settings.request_timeout
    )

    http_client = httpx.AsyncClient(
        transport=_openrouter_retry_transport(
            effective_transport_settings, transport, retry_hooks
        ),
        timeout=request_timeout,
    )
    provider = OpenRouterProvider(
        api_key=os.environ.get("OPENROUTER_API_KEY"),
        http_client=http_client,
    )
    # OpenAI's default retries would make one failed request look like several
    # attempts to the surrounding request handling.
    provider.client.max_retries = 0

    extra_body: dict[str, object] = {}
    if request_settings.top_k is not None:
        extra_body["top_k"] = request_settings.top_k
    provider_policy = deployment.provider_policy
    if provider_policy is None:  # pragma: no cover - ModelDeployment validates this
        raise ValueError("an OpenRouter Model Deployment needs a provider policy")
    provider_names = list(provider_policy.providers)
    provider_settings = {
        "order": provider_names,
        "only": provider_names,
        "allow_fallbacks": provider_policy.allow_fallback,
        "require_parameters": provider_policy.require_parameters,
    }

    model_settings: dict[str, object] = {
        "temperature": request_settings.temperature,
        "max_tokens": request_settings.max_tokens,
        "timeout": request_timeout,
        "extra_body": extra_body,
        "extra_headers": {"X-OpenRouter-Metadata": "enabled"},
        "openrouter_provider": provider_settings,
    }
    if request_settings.top_p is not None:
        model_settings["top_p"] = request_settings.top_p
    if request_settings.thinking is not None:
        model_settings["thinking"] = request_settings.thinking
    if request_settings.reasoning_effort is not None:
        model_settings["openrouter_reasoning"] = {
            "effort": request_settings.reasoning_effort
        }

    return OpenRouterModel(
        deployment.model,
        provider=provider,
        settings=OpenRouterModelSettings(**model_settings),  # type: ignore[arg-type]
    )


def get_chat_model(
    default_model: str | ModelDeployment,
    env_var_name: str | None = None,
    *,
    allow_env_override: bool = True,
    transport_settings: TransportSettings | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    openrouter_retry_hooks: OpenRouterRetryHooks | None = None,
) -> OpenAIChatModel:
    """Get a chat model from a typed deployment or the legacy local path.

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
        if env_var_name is not None:
            raise ValueError(
                "a Model Deployment cannot be combined with model environment overrides"
            )
        if default_model.kind is DeploymentKind.OPENROUTER:
            request_settings = default_model.request_settings
            if request_settings.timeout is None:
                request_settings = request_settings.model_copy(
                    update={
                        "timeout": (
                            transport_settings or settings.transport
                        ).request_timeout
                    }
                )
            effective_deployment = default_model.model_copy(
                update={"request_settings": request_settings}
            )
            if transport_settings is not None or openrouter_retry_hooks is not None:
                return _build_openrouter_model(
                    effective_deployment,
                    transport_settings,
                    transport,
                    openrouter_retry_hooks,
                )
            key = (effective_deployment, transport)
            model = _models.get(key)
            if model is None:
                model = _build_openrouter_model(
                    effective_deployment, None, transport
                )
                _models[key] = model
            return model
        if default_model.kind is not DeploymentKind.LOCAL:
            raise ValueError(f"unsupported chat deployment kind: {default_model.kind}")
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
