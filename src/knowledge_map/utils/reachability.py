"""Confirm the local model endpoints a command needs before it starts work.

A command whose agents cannot reach their llama.cpp server fails partway
through: articles are scraped and then left unvalidated, or a Story changes
status and then stalls on its first model request. Answering "is the endpoint
there" up front turns that into one refusal before any state changes.

This is a transport question only. The endpoint answering says nothing about
which GGUF it has loaded or whether generation succeeds; the first real request
remains the authority on both.
"""

import os
from dataclasses import dataclass
from enum import StrEnum

import httpx

from .models import resolve_chat_base_url, resolve_embedding_base_url

# Short by design. A reachable llama.cpp server answers immediately, so a wait
# long enough to matter is itself the unreachable answer the caller wants.
REACHABILITY_TIMEOUT_SECONDS = 5.0
SKIP_MODEL_CHECK_ENV = "SKIP_MODEL_REACHABILITY_CHECK"


class ModelEndpoint(StrEnum):
    """A local llama.cpp server that some commands' agents depend on."""

    CHAT = "chat"
    EMBEDDING = "embedding"


def resolve_endpoint_url(endpoint: ModelEndpoint) -> str:
    """The configured base URL for one endpoint, normalised to ``/v1``."""

    if endpoint is ModelEndpoint.CHAT:
        return resolve_chat_base_url()
    return resolve_embedding_base_url()


@dataclass(frozen=True)
class EndpointReachability:
    """Whether one endpoint answered, and what went wrong when it did not."""

    endpoint: ModelEndpoint
    base_url: str
    reachable: bool
    detail: str = ""


def model_reachability_check_skipped() -> bool:
    """Whether the operator disabled the shared local-endpoint preflight."""

    return bool(os.environ.get(SKIP_MODEL_CHECK_ENV, "").strip())


async def request_model_listing(
    base_url: str,
    *,
    timeout: float = REACHABILITY_TIMEOUT_SECONDS,
    client: httpx.AsyncClient | None = None,
) -> None:
    """Ask a local model endpoint to respond without interpreting its status.

    Any HTTP response proves that a server accepted the request. Transport
    failures propagate so the caller can name the dependency that is down.
    """

    url = f"{base_url.rstrip('/')}/models"
    if client is None:
        async with httpx.AsyncClient(timeout=timeout) as owned_client:
            await owned_client.get(url)
    else:
        await client.get(url)


def check_endpoint(
    endpoint: ModelEndpoint,
    *,
    timeout: float = REACHABILITY_TIMEOUT_SECONDS,
    client: httpx.Client | None = None,
) -> EndpointReachability:
    """Ask one endpoint for its model listing and report whether it answered.

    Any HTTP status counts as reachable: a served error still proves a server
    is accepting requests at that address, and interpreting the response would
    make this a claim about the model rather than the transport.
    """

    base_url = resolve_endpoint_url(endpoint)
    url = f"{base_url}/models"
    try:
        if client is None:
            with httpx.Client(timeout=timeout) as owned_client:
                owned_client.get(url)
        else:
            client.get(url)
    except httpx.HTTPError as error:
        # The exception type is the actionable part -- ConnectError means
        # nothing is listening, ConnectTimeout means something is wrong on the
        # way there -- and httpx's own message is often empty.
        detail = str(error).strip() or type(error).__name__
        return EndpointReachability(
            endpoint=endpoint,
            base_url=base_url,
            reachable=False,
            detail=detail,
        )
    return EndpointReachability(endpoint=endpoint, base_url=base_url, reachable=True)


def check_endpoints(
    endpoints: frozenset[ModelEndpoint],
    *,
    timeout: float = REACHABILITY_TIMEOUT_SECONDS,
    client: httpx.Client | None = None,
) -> tuple[EndpointReachability, ...]:
    """Check every required endpoint, in a stable order, without stopping early.

    An operator restarting servers wants both failures in one message rather
    than one per run.
    """

    return tuple(
        check_endpoint(endpoint, timeout=timeout, client=client)
        for endpoint in sorted(endpoints, key=lambda value: value.value)
    )
