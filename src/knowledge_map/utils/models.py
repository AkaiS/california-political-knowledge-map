import asyncio
import math
import os
import random
import threading
import time
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC
from decimal import Decimal, InvalidOperation
from email.utils import parsedate_to_datetime
from types import TracebackType
from typing import Any, Self

import httpx
import logfire
from dotenv import load_dotenv
from openai import AsyncOpenAI
from pydantic_ai import ModelProfile, ModelResponse
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIChatModelSettings
from pydantic_ai.models.openrouter import OpenRouterModel, OpenRouterModelSettings
from pydantic_ai.profiles import InlineDefsJsonSchemaTransformer, merge_profile
from pydantic_ai.profiles.google import google_model_profile
from pydantic_ai.profiles.openai import OpenAIModelProfile
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.providers.openrouter import OpenRouterProvider
from pydantic_ai.retries import AsyncTenacityTransport, RetryConfig, wait_retry_after
from tenacity import retry_if_exception_type, stop_after_attempt

from knowledge_map.config import (
    TransportSettings,
    configured_temperature,
    configured_thinking,
    settings,
)
from knowledge_map.schemas import (
    DeploymentKind,
    ModelDeployment,
    ModelRequestProvenance,
    ModelRequestSettings,
)
from knowledge_map.utils.telemetry import setup_telemetry

DEFAULT_LOCAL_CHAT_MODEL = "gemma4:26b"


@dataclass
class _RequestRetryState:
    """Track one HTTP request across its bounded transport attempts."""

    request_sequence: int | None = None
    attempts: int = 0


@dataclass
class _RequestProvenanceCapture:
    case_id: str
    records: list[ModelRequestProvenance]
    _next_request_sequence: int = field(default=1, init=False, repr=False)
    _lock: threading.Lock = field(
        default_factory=threading.Lock, init=False, repr=False
    )

    @classmethod
    def for_case(cls, case_id: str) -> "_RequestProvenanceCapture":
        return cls(case_id=case_id, records=[])

    def start_request(self) -> int:
        """Reserve the next case-local sequence at request initiation."""

        with self._lock:
            sequence = self._next_request_sequence
            self._next_request_sequence += 1
            return sequence

    def _request_sequence(self, retry_state: _RequestRetryState) -> int:
        """Return the sequence reserved when this request started."""

        sequence = retry_state.request_sequence
        if sequence is None:
            raise RuntimeError(
                "request provenance lost the sequence reserved at initiation"
            )
        return sequence

    def _append_in_sequence_order(self, record: ModelRequestProvenance) -> None:
        with self._lock:
            self.records.append(record)
            self.records.sort(key=lambda item: item.request_sequence)

    def record(
        self,
        deployment: str,
        requested_model: str,
        response: ModelResponse,
        raw_response: Any,
        retry_state: _RequestRetryState,
    ) -> None:
        details = response.provider_details
        downstream_provider = None
        is_byok = None
        if deployment == "openrouter" and isinstance(details, dict):
            provider = details.get("downstream_provider")
            if (
                isinstance(provider, str)
                and provider.strip()
                and provider.casefold() not in {"unknown", "unavailable"}
            ):
                downstream_provider = provider
            byok = details.get("is_byok")
            if isinstance(byok, bool):
                is_byok = byok

        returned_model = response.model_name if response.model_name else None
        generation_id = (
            response.provider_response_id
            if deployment == "openrouter" and response.provider_response_id
            else None
        )
        usage_facts = _request_usage_facts(
            response, raw_response, deployment=deployment
        )
        attempts = retry_state.attempts or 1
        request_sequence = self._request_sequence(retry_state)
        self._append_in_sequence_order(
            ModelRequestProvenance(
                case_id=self.case_id,
                request_sequence=request_sequence,
                deployment=deployment,
                requested_model=requested_model,
                returned_model=returned_model,
                downstream_provider=downstream_provider,
                generation_id=generation_id,
                is_byok=is_byok,
                **usage_facts,
                route_attempts=(
                    _raw_response_route_attempts(raw_response)
                    if deployment == "openrouter"
                    else None
                ),
                attempts=attempts,
                retry_count=max(attempts - 1, 0),
            )
        )

    def record_failure(
        self,
        deployment: str,
        requested_model: str,
        retry_state: _RequestRetryState,
    ) -> None:
        attempts = retry_state.attempts or 1
        request_sequence = self._request_sequence(retry_state)
        self._append_in_sequence_order(
            ModelRequestProvenance(
                case_id=self.case_id,
                request_sequence=request_sequence,
                deployment=deployment,
                requested_model=requested_model,
                returned_model=None,
                downstream_provider=None,
                generation_id=None,
                is_byok=None,
                input_tokens=None,
                output_tokens=None,
                reasoning_tokens=None,
                cache_write_tokens=None,
                cache_read_tokens=None,
                total_tokens=None,
                charged_cost=None,
                upstream_cost=None,
                route_attempts=None,
                attempts=attempts,
                retry_count=max(attempts - 1, 0),
            )
        )


def _raw_response_data(raw_response: Any) -> dict[str, Any] | None:
    if isinstance(raw_response, dict):
        response_data = raw_response
    else:
        model_dump = getattr(raw_response, "model_dump", None)
        if not callable(model_dump):
            return None
        response_data = model_dump(exclude_none=True)
    return response_data if isinstance(response_data, dict) else None


def _raw_response_usage(raw_response: Any) -> dict[str, Any] | None:
    """Keep provider-reported usage before SDK normalization drops raw totals."""

    response_data = _raw_response_data(raw_response)
    if response_data is None:
        return None
    nested_provider = response_data.get("provider")
    if isinstance(nested_provider, dict) and isinstance(
        nested_provider.get("choices"), list
    ):
        nested_usage = nested_provider.get("usage")
        if isinstance(nested_usage, dict):
            return nested_usage
    raw_usage = response_data.get("usage")
    if isinstance(raw_usage, dict):
        return raw_usage
    return None


def _raw_response_route_attempts(raw_response: Any) -> int | None:
    """Read router-attempt metadata without inferring it from app retries."""

    response_data = _raw_response_data(raw_response)
    if response_data is None:
        return None
    candidates = [response_data]
    nested_provider = response_data.get("provider")
    if isinstance(nested_provider, dict) and isinstance(
        nested_provider.get("choices"), list
    ):
        candidates.insert(0, nested_provider)

    for candidate in candidates:
        metadata = candidate.get("openrouter_metadata")
        if not isinstance(metadata, dict):
            continue
        route_attempts = metadata.get("attempts")
        if isinstance(route_attempts, list):
            return len(route_attempts)
        route_attempt = metadata.get("attempt")
        if type(route_attempt) is int:
            return route_attempt
        provider_responses = candidate.get("provider_responses")
        if isinstance(provider_responses, list):
            return len(provider_responses)
    return None


def _raw_mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _usage_int(mapping: dict[str, Any], *keys: str) -> int | None:
    for key in keys:
        if key in mapping:
            value = mapping[key]
            return value if type(value) is int else None
    return None


def _usage_cost(mapping: dict[str, Any], *keys: str) -> Decimal | None:
    for key in keys:
        if key in mapping:
            value = mapping[key]
            if isinstance(value, bool) or value is None:
                return None
            try:
                cost = Decimal(str(value))
            except (InvalidOperation, TypeError, ValueError):
                return None
            return cost if cost.is_finite() else None
    return None


def _usage_for_validation(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    usage_data = dict(value)
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        if usage_data.get(key) is None:
            usage_data[key] = 0
    return usage_data


def _request_usage_facts(
    response: ModelResponse,
    raw_response: Any,
    *,
    deployment: str,
) -> dict[str, int | Decimal | None]:
    """Normalize only usage values explicitly returned by the model.

    ``RequestUsage`` intentionally exposes a computed total and zero defaults;
    neither is evidence that a provider returned that value. Read the raw
    response so missing categories stay unavailable and a reported total is not
    reconstructed from input and output counts.
    """

    raw_usage = _raw_response_usage(raw_response)
    if raw_usage is None:
        return {
            "input_tokens": None,
            "output_tokens": None,
            "reasoning_tokens": None,
            "cache_write_tokens": None,
            "cache_read_tokens": None,
            "total_tokens": None,
            "charged_cost": None,
            "upstream_cost": None,
        }

    prompt_details = _raw_mapping(raw_usage.get("prompt_tokens_details"))
    completion_details = _raw_mapping(raw_usage.get("completion_tokens_details"))
    usage_details = _raw_mapping(raw_usage.get("usage_details"))
    input_tokens = _usage_int(raw_usage, "prompt_tokens", "input_tokens")
    output_tokens = _usage_int(raw_usage, "completion_tokens", "output_tokens")
    reasoning_tokens = _usage_int(completion_details, "reasoning_tokens")
    if reasoning_tokens is None:
        reasoning_tokens = _usage_int(usage_details, "reasoning_tokens")
    cache_write_tokens = _usage_int(prompt_details, "cache_write_tokens")
    if cache_write_tokens is None:
        cache_write_tokens = _usage_int(usage_details, "cache_write_tokens")
    cache_read_tokens = _usage_int(prompt_details, "cached_tokens", "cache_read_tokens")
    if cache_read_tokens is None:
        cache_read_tokens = _usage_int(usage_details, "cache_read_tokens")
    total_tokens = _usage_int(raw_usage, "total_tokens")

    charged_cost = None
    upstream_cost = None
    if deployment == "openrouter":
        charged_cost = _usage_cost(raw_usage, "cost", "charged_cost")
        if charged_cost is None and "cost" not in raw_usage and "charged_cost" not in raw_usage:
            charged_cost = _usage_cost(response.provider_details or {}, "cost")
        cost_details = _raw_mapping(raw_usage.get("cost_details"))
        upstream_cost = _usage_cost(
            raw_usage, "upstream_inference_cost", "upstream_cost"
        )
        if upstream_cost is None:
            upstream_cost = _usage_cost(
                cost_details, "upstream_inference_cost", "upstream_cost"
            )
        if upstream_cost is None and "cost_details" not in raw_usage:
            upstream_cost = _usage_cost(
                response.provider_details or {}, "upstream_inference_cost"
            )

    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "reasoning_tokens": reasoning_tokens,
        "cache_write_tokens": cache_write_tokens,
        "cache_read_tokens": cache_read_tokens,
        "total_tokens": total_tokens,
        "charged_cost": charged_cost,
        "upstream_cost": upstream_cost,
    }


_CURRENT_REQUEST_PROVENANCE: ContextVar[_RequestProvenanceCapture | None] = ContextVar(
    "current_request_provenance", default=None
)
_CURRENT_REQUEST_RETRY: ContextVar[_RequestRetryState | None] = ContextVar(
    "current_request_retry", default=None
)


def _start_request_retry_state() -> _RequestRetryState:
    """Reserve case order before a model request can await or complete."""

    capture = _CURRENT_REQUEST_PROVENANCE.get()
    request_sequence = capture.start_request() if capture is not None else None
    retry_state = _RequestRetryState(request_sequence=request_sequence)
    _CURRENT_REQUEST_RETRY.set(retry_state)
    return retry_state


@contextmanager
def request_provenance_scope(
    case_id: str,
) -> Iterator[list[ModelRequestProvenance]]:
    """Capture safe model-response route facts for one authored case."""

    capture = _RequestProvenanceCapture.for_case(case_id)
    token = _CURRENT_REQUEST_PROVENANCE.set(capture)
    try:
        yield capture.records
    finally:
        _CURRENT_REQUEST_PROVENANCE.reset(token)


def _record_request_provenance(
    deployment: str,
    requested_model: str,
    response: ModelResponse,
    raw_response: Any,
    retry_state: _RequestRetryState | None,
) -> None:
    capture = _CURRENT_REQUEST_PROVENANCE.get()
    if capture is not None:
        if retry_state is None:
            raise RuntimeError(
                "request provenance has no state reserved at request initiation"
            )
        capture.record(
            deployment,
            requested_model,
            response,
            raw_response,
            retry_state,
        )


def _record_failed_request_provenance(
    deployment: str,
    requested_model: str,
    retry_state: _RequestRetryState,
) -> None:
    if retry_state.attempts == 0:
        return
    capture = _CURRENT_REQUEST_PROVENANCE.get()
    if capture is not None:
        capture.record_failure(deployment, requested_model, retry_state)


class _RequestAttemptTrackingTransport(httpx.AsyncBaseTransport):
    """Count each underlying transport call within one logical request."""

    def __init__(self, wrapped: httpx.AsyncBaseTransport | None) -> None:
        self._wrapped = wrapped or httpx.AsyncHTTPTransport()

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
        retry_state = _CURRENT_REQUEST_RETRY.get()
        if retry_state is not None:
            retry_state.attempts += 1
        return await self._wrapped.handle_async_request(request)

    async def aclose(self) -> None:
        await self._wrapped.aclose()


class _RequestTrackingAsyncTenacityTransport(AsyncTenacityTransport):
    """Expose SDK transport retry state at the model response boundary."""

    def __init__(
        self,
        config: RetryConfig,
        *,
        wrapped: httpx.AsyncBaseTransport,
        validate_response: Callable[[httpx.Response], Any] | None,
        deployment: str,
        requested_model: str,
    ) -> None:
        super().__init__(config, wrapped=wrapped, validate_response=validate_response)
        self._provenance_deployment = deployment
        self._provenance_model = requested_model

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        retry_state = _start_request_retry_state()
        try:
            return await super().handle_async_request(request)
        except BaseException:
            _record_failed_request_provenance(
                self._provenance_deployment,
                self._provenance_model,
                retry_state,
            )
            _CURRENT_REQUEST_RETRY.set(None)
            raise


class _RequestProvenanceModelMixin:
    _provenance_deployment: str

    def _process_response(self, response: Any) -> ModelResponse:
        retry_state = _CURRENT_REQUEST_RETRY.get()
        _CURRENT_REQUEST_RETRY.set(None)
        model_response = super()._process_response(response)  # type: ignore[misc]
        if self._provenance_deployment == "openrouter":
            _log_openrouter_route(
                self,
                model_response,
                response,
                retry_state,
            )
        _record_request_provenance(
            self._provenance_deployment,
            self.model_name,
            model_response,
            response,
            retry_state,
        )
        return model_response


def _log_openrouter_route(
    model: Any,
    response: ModelResponse,
    raw_response: Any,
    retry_state: _RequestRetryState | None,
) -> None:
    """Attach OpenRouter's safe routing result to the active model trace."""

    details = response.provider_details or {}
    downstream_provider = details.get("downstream_provider")
    is_byok = details.get("is_byok")
    provider_policy = (getattr(model, "settings", None) or {}).get(
        "openrouter_provider", {}
    )
    usage = _request_usage_facts(response, raw_response, deployment="openrouter")
    logfire.info(
        "OpenRouter model request completed",
        deployment="openrouter",
        requested_model=model.model_name,
        returned_model=response.model_name or None,
        downstream_provider=(
            downstream_provider
            if isinstance(downstream_provider, str) and downstream_provider.strip()
            else None
        ),
        is_byok=is_byok if isinstance(is_byok, bool) else None,
        generation_id=response.provider_response_id or None,
        route_attempts=_raw_response_route_attempts(raw_response),
        application_attempts=(retry_state.attempts if retry_state else 1),
        provider_order=provider_policy.get("order"),
        allow_fallbacks=provider_policy.get("allow_fallbacks"),
        charged_cost=(
            str(usage["charged_cost"])
            if usage["charged_cost"] is not None
            else None
        ),
        upstream_cost=(
            str(usage["upstream_cost"])
            if usage["upstream_cost"] is not None
            else None
        ),
    )


class _LocalOpenAIChatModel(_RequestProvenanceModelMixin, OpenAIChatModel):
    """OpenAI-compatible model with llama.cpp's empty-content workaround."""

    _provenance_deployment = "llama.cpp"

    @dataclass
    class _MapModelResponseContext(OpenAIChatModel._MapModelResponseContext):
        def _into_message_param(self):
            # Normalize the ``content: null`` pydantic-ai emits for a text-free
            # tool call: llama.cpp rejects it on the retry request.
            result = super()._into_message_param()
            if result is not None and result.get("content") is None:
                result["content"] = ""
            return result


class _OpenRouterModel(_RequestProvenanceModelMixin, OpenRouterModel):
    """Native OpenRouter model that exposes safe response route facts."""

    _provenance_deployment = "openrouter"

    def _validate_completion(self, response: Any) -> Any:
        """Keep a response usable when OpenRouter omits its provider field."""

        response_data = response.model_dump()
        updates: dict[str, Any] = {}
        if not response_data.get("provider"):
            # The provider is optional in OpenRouter's response in practice;
            # retain the successful completion while provenance marks it unknown.
            updates["provider"] = "unknown"

        usage_data = _usage_for_validation(response_data.get("usage"))
        if usage_data is not None:
            # OpenAI's typed usage model requires these fields even when an
            # OpenRouter response omits one; zero is validation-only, while
            # provenance reads the original response and records None.
            usage_type = type(response.usage)
            usage_validate = getattr(usage_type, "model_validate", None)
            if callable(usage_validate):
                updates["usage"] = usage_validate(usage_data)
            else:
                updates["usage"] = usage_data

        provider_data = response_data.get("provider")
        if isinstance(provider_data, dict) and isinstance(
            provider_data.get("choices"), list
        ):
            nested_usage_data = _usage_for_validation(provider_data.get("usage"))
            if nested_usage_data is not None:
                provider_data = dict(provider_data)
                provider_data["usage"] = nested_usage_data
                updates["provider"] = provider_data

        if updates:
            response = response.model_copy(update=updates)
        return super()._validate_completion(response)


def build_retrying_client(
    transport_settings: TransportSettings | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    *,
    provenance_deployment: str | None = None,
    requested_model: str | None = None,
) -> httpx.AsyncClient:
    """Build the HTTP client used to retry failed local model requests.

    A rate limit or dropped connection is retried before the local model sees
    it as a response.
    """

    transport_settings = transport_settings or settings.transport
    retry_config = RetryConfig(
        retry=retry_if_exception_type(
            (httpx.HTTPStatusError, httpx.TransportError)
        ),
        wait=wait_retry_after(max_wait=transport_settings.rate_limit_wait_cap),
        stop=stop_after_attempt(transport_settings.max_attempts),
        reraise=True,
    )
    if provenance_deployment is not None and requested_model is not None:
        retrying_transport = _RequestTrackingAsyncTenacityTransport(
            retry_config,
            wrapped=_RequestAttemptTrackingTransport(transport),
            validate_response=lambda response: response.raise_for_status(),
            deployment=provenance_deployment,
            requested_model=requested_model,
        )
    else:
        retrying_transport = AsyncTenacityTransport(
            retry_config,
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

    return configured_temperature()


def resolve_thinking() -> bool:
    """Whether the model reasons before answering.  It does not, by default.

    Read from ``LLM_THINKING``.  Turning it on lets a call reason unbounded,
    since pydantic-ai sends no ``max_tokens``.
    """

    return configured_thinking()


def resolve_local_chat_model(default_model: str) -> str:
    """Resolve the one configured llama.cpp chat model for a legacy caller."""

    load_dotenv()
    return os.environ.get("LLAMA_CPP_MODEL", "").strip() or default_model


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
    """Coordinate adaptive admission for new OpenRouter requests."""

    def __init__(self, max_concurrency: int | None = None) -> None:
        if max_concurrency is not None and max_concurrency < 1:
            raise ValueError("OpenRouter admission ceiling must be greater than 0")
        self._deadline = 0.0
        self._paused = False
        self._probe_in_flight = False
        self._base_ceiling = max_concurrency
        self._ceiling = max_concurrency
        self._working_limit = max_concurrency
        self._ceiling_leases: dict[int, int] = {}
        self._next_ceiling_lease = 0
        self._in_flight = 0
        self._lock = threading.Lock()
        self._waiters: dict[asyncio.AbstractEventLoop, set[asyncio.Event]] = {}

    @contextmanager
    def configured_ceiling(self, max_concurrency: int) -> Iterator[None]:
        """Temporarily bound this shared gate to one evaluation's ceiling.

        Multiple evaluations can overlap, so active ceilings combine by the
        strictest bound. Releasing the last run-scoped ceiling restores the
        gate's unbounded default rather than leaking a prior run's limit into
        later model calls.
        """

        if max_concurrency < 1:
            raise ValueError("OpenRouter admission ceiling must be greater than 0")
        with self._lock:
            lease = self._next_ceiling_lease
            self._next_ceiling_lease += 1
            self._ceiling_leases[lease] = max_concurrency
            self._ceiling = self._effective_ceiling_locked()
            self._working_limit = self._bounded_working_limit_locked()
        self._wake_waiters()
        try:
            yield
        finally:
            with self._lock:
                self._ceiling_leases.pop(lease, None)
                self._ceiling = self._effective_ceiling_locked()
                if self._ceiling is None:
                    self._working_limit = None
                else:
                    self._working_limit = self._bounded_working_limit_locked()
            self._wake_waiters()

    def _effective_ceiling_locked(self) -> int | None:
        ceilings = list(self._ceiling_leases.values())
        if self._base_ceiling is not None:
            ceilings.append(self._base_ceiling)
        return min(ceilings) if ceilings else None

    def _bounded_working_limit_locked(self) -> int | None:
        if self._ceiling is None:
            return self._working_limit
        if self._working_limit is None:
            return self._ceiling
        return min(self._working_limit, self._ceiling)

    def pause_until(self, deadline: float) -> None:
        with self._lock:
            self._deadline = max(self._deadline, deadline)
            self._paused = True
        self._wake_waiters()

    def _try_admit(self, now: float) -> tuple[float | None, bool, bool]:
        with self._lock:
            if self._paused:
                remaining = self._deadline - now
                if remaining > 0:
                    return remaining, False, False
                if (
                    self._working_limit is not None
                    and self._in_flight >= self._working_limit
                ):
                    return None, False, False
                if self._probe_in_flight:
                    return None, False, True
                # This check is the admission point. A pause racing after it
                # affects later requests, not this already-admitted request.
                self._probe_in_flight = True
                self._in_flight += 1
                return None, True, True
            if (
                self._working_limit is not None
                and self._in_flight >= self._working_limit
            ):
                return None, False, False
            self._in_flight += 1
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

    def _release_slot_locked(self) -> None:
        if self._in_flight:
            self._in_flight -= 1

    def _complete_request(
        self,
        *,
        is_probe: bool,
        now: float,
        successful: bool,
        release_slot: bool,
    ) -> None:
        with self._lock:
            if release_slot:
                self._release_slot_locked()
            if successful and self._working_limit is not None:
                self._working_limit = min(
                    self._ceiling, self._working_limit + 1
                )
            if is_probe:
                self._probe_in_flight = False
                if successful and self._deadline <= now:
                    self._paused = False
                elif not successful:
                    # A failed probe must leave the pause in place so another
                    # caller can probe later instead of releasing a burst.
                    self._paused = True
        self._wake_waiters()

    def _record_rate_limit_locked(self) -> None:
        if self._working_limit is not None:
            self._working_limit = max(1, self._working_limit - 1)
        self._paused = True

    def record_rate_limit(self) -> None:
        """Lower the working limit in response to one observed ``429``."""

        with self._lock:
            self._record_rate_limit_locked()
        self._wake_waiters()

    def request_completed(
        self, *, is_probe: bool, now: float, successful: bool = True
    ) -> None:
        self._complete_request(
            is_probe=is_probe,
            now=now,
            successful=successful,
            release_slot=True,
        )

    def request_failed(self, *, is_probe: bool) -> None:
        with self._lock:
            self._release_slot_locked()
            if is_probe:
                self._probe_in_flight = False
                # A transport failure is not evidence that the route is
                # healthy, so leave the pause for a later probe.
                self._paused = True
        self._wake_waiters()

    def request_rate_limited(self, *, is_probe: bool) -> None:
        with self._lock:
            self._record_rate_limit_locked()
            self._release_slot_locked()
            if is_probe:
                self._probe_in_flight = False
        self._wake_waiters()

    def probe_succeeded(self, now: float) -> None:
        self.request_completed(is_probe=True, now=now)

    def probe_rate_limited(self) -> None:
        self.request_rate_limited(is_probe=True)

    def probe_failed(self) -> None:
        self.request_failed(is_probe=True)

    async def wait_until_open(self, hooks: "OpenRouterRetryHooks") -> bool:
        while True:
            wait, admitted, is_probe = self._try_admit(hooks.now())
            if admitted:
                return is_probe
            if wait is not None:
                await hooks.sleep(wait)
                continue
            event = self._register_waiter()
            try:
                wait, admitted, is_probe = self._try_admit(hooks.now())
                if admitted:
                    return is_probe
                if wait is None:
                    await event.wait()
            finally:
                self._unregister_waiter(event)


_DEFAULT_OPENROUTER_ADMISSION_GATE = OpenRouterAdmissionGate()


@contextmanager
def openrouter_admission_ceiling(max_concurrency: int) -> Iterator[None]:
    """Apply one Evaluation Run's ceiling to the process-wide OpenRouter gate."""

    with _DEFAULT_OPENROUTER_ADMISSION_GATE.configured_ceiling(max_concurrency):
        yield


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

    try:
        retry_at = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=UTC)
    retry_at = retry_at.astimezone(UTC)
    if value not in {
        retry_at.strftime("%a, %d %b %Y %H:%M:%S GMT"),
        retry_at.strftime("%A, %d-%b-%y %H:%M:%S GMT"),
        retry_at.strftime("%a %b %d %H:%M:%S %Y"),
    }:
        return None
    wait = retry_at.timestamp() - now
    return wait if wait >= 0 else None


class _OpenRouterRetryTransport(httpx.AsyncBaseTransport):
    """Retry request-local OpenRouter failures that are safe to repeat."""

    def __init__(
        self,
        wrapped: httpx.AsyncBaseTransport | None,
        max_attempts: int,
        rate_limit_wait_cap: float,
        retry_hooks: OpenRouterRetryHooks | None = None,
        requested_model: str = "",
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
        self._requested_model = requested_model

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
        retry_state = _start_request_retry_state()
        admitted = False
        try:
            is_probe = await self._admission_gate.wait_until_open(
                self._retry_hooks
            )
            admitted = True
        except BaseException:
            _CURRENT_REQUEST_RETRY.set(None)
            raise
        try:
            for attempt in range(self._max_attempts):
                retry_state.attempts += 1
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
                    self._admission_gate.request_rate_limited(is_probe=is_probe)
                    admitted = False
                    if attempt + 1 < self._max_attempts:
                        # Release the failed response before waiting so its
                        # connection is available while this request backs off.
                        await response.aclose()
                        # A rate-limited retry competes with every other waiting
                        # request for the one probe admitted after the pause.
                        is_probe = await self._admission_gate.wait_until_open(
                            self._retry_hooks
                        )
                        admitted = True
                        continue
                    _record_failed_request_provenance(
                        "openrouter", self._requested_model, retry_state
                    )
                    _CURRENT_REQUEST_RETRY.set(None)
                    return response

                if (
                    response.status_code in _RETRYABLE_OPENROUTER_STATUS_CODES
                    and attempt + 1 < self._max_attempts
                ):
                    # Return the final response so OpenAI can preserve its typed
                    # HTTP error; raising here would turn it into a connection error.
                    await response.aclose()
                    continue
                self._admission_gate.request_completed(
                    is_probe=is_probe,
                    now=self._retry_hooks.now(),
                    successful=200 <= response.status_code < 300,
                )
                admitted = False
                if not 200 <= response.status_code < 300:
                    _record_failed_request_provenance(
                        "openrouter", self._requested_model, retry_state
                    )
                    _CURRENT_REQUEST_RETRY.set(None)
                return response
        except BaseException:
            _record_failed_request_provenance(
                "openrouter", self._requested_model, retry_state
            )
            _CURRENT_REQUEST_RETRY.set(None)
            if admitted:
                self._admission_gate.request_failed(is_probe=is_probe)
            raise

        raise AssertionError("OpenRouter retry transport made no attempt")

    async def aclose(self) -> None:
        await self._wrapped.aclose()


def _openrouter_retry_transport(
    transport_settings: TransportSettings,
    transport: httpx.AsyncBaseTransport | None,
    requested_model: str,
    retry_hooks: OpenRouterRetryHooks | None = None,
) -> httpx.AsyncBaseTransport:
    """Apply bounded OpenRouter retries at the HTTP boundary."""

    return _OpenRouterRetryTransport(
        transport,
        transport_settings.max_attempts,
        transport_settings.rate_limit_wait_cap,
        retry_hooks,
        requested_model,
    )


def _deployment_transport_settings(
    request_settings: ModelRequestSettings,
    transport_settings: TransportSettings | None,
) -> TransportSettings:
    """Resolve retry and client timeout settings for one local deployment."""

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
        request_timeout=request_settings.timeout,
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
            else settings.transport.request_timeout
        ),
    )
    effective_transport_settings = _deployment_transport_settings(
        request_settings, transport_settings
    )
    openai_client = AsyncOpenAI(
        base_url=base_url,
        api_key=os.environ.get("LLAMA_CPP_API_KEY") or "api-key-not-set",
        http_client=build_retrying_client(
            effective_transport_settings,
            transport,
            provenance_deployment="llama.cpp",
            requested_model=model_name,
        ),
        max_retries=0,
    )
    provider = OpenAIProvider(openai_client=openai_client)
    extra_body = {
        "chat_template_kwargs": {
            "enable_thinking": request_settings.thinking
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
    request_timeout = request_settings.timeout

    http_client = httpx.AsyncClient(
        transport=_openrouter_retry_transport(
            effective_transport_settings, transport, deployment.model, retry_hooks
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

    return _OpenRouterModel(
        deployment.model,
        provider=provider,
        settings=OpenRouterModelSettings(**model_settings),  # type: ignore[arg-type]
    )


def get_chat_model(
    default_model: str | ModelDeployment,
    *,
    transport_settings: TransportSettings | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    openrouter_retry_hooks: OpenRouterRetryHooks | None = None,
) -> OpenAIChatModel:
    """Get a chat model from a typed deployment or a configured local path.

    Typed deployments are authoritative and cannot be replaced by ambient
    configuration. Legacy string callers resolve only ``LLAMA_CPP_MODEL`` and
    otherwise use their explicit default.

    Typed local deployments are memoized by their effective identity and an
    injected transport, so equivalent agents share one client and connection
    pool without allowing distinct mock transports to leak into one another.
    """

    # Instrument Pydantic AI and HTTPX before constructing either provider's
    # client. This also covers callers that build their own Agent around a
    # model returned by this factory.
    setup_telemetry()
    load_dotenv()

    if isinstance(default_model, ModelDeployment):
        if transport_settings is not None:
            raise ValueError(
                "transport settings for a typed Model Deployment must be part of "
                "its request_settings"
            )
        if default_model.kind is DeploymentKind.OPENROUTER:
            if openrouter_retry_hooks is not None:
                return _build_openrouter_model(
                    default_model,
                    None,
                    transport,
                    openrouter_retry_hooks,
                )
            key = (default_model, transport)
            model = _models.get(key)
            if model is None:
                model = _build_openrouter_model(
                    default_model, None, transport
                )
                _models[key] = model
            return model
        if default_model.kind is not DeploymentKind.LOCAL:
            raise ValueError(f"unsupported chat deployment kind: {default_model.kind}")
        base_url = _normalise_chat_base_url(
            default_model.endpoint or resolve_chat_base_url()
        )
        request_settings = default_model.request_settings
        key = (default_model, transport)
        model = _models.get(key)
        if model is None:
            model = _build_model(
                default_model.model,
                base_url,
                request_settings,
                None,
                transport,
            )
            _models[key] = model
        return model

    base_url = resolve_chat_base_url()
    model_name = resolve_local_chat_model(default_model)

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
            timeout=settings.transport.request_timeout,
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
