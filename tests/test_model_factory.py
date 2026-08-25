"""The model factory's retrying HTTP client, observed through a real agent call.

Every assertion here runs a real ``Agent`` against a model the factory built,
with an ``httpx.MockTransport`` standing in for the llama.cpp host.  That is the
highest point at which transport retry is observable, and it exercises the real
provider wiring rather than a client in isolation.
"""

import asyncio
import json

import httpx
import pytest
from pydantic import BaseModel
from pydantic_ai import Agent

from knowledge_map.config import TransportSettings, settings
from knowledge_map.utils.models import (
    get_chat_model,
    llama_cpp_model_profile,
    resolve_chat_base_url,
    resolve_embedding_base_url,
    resolve_thinking,
)


def chat_completion(content: str) -> dict:
    """A minimal OpenAI-compatible chat completion body."""

    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 0,
        "model": "test-model",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


@pytest.fixture
def recorded_waits(monkeypatch):
    """Record every retry wait and take none of them."""

    waits: list[float] = []
    real_sleep = asyncio.sleep

    async def recording_sleep(delay, *args, **kwargs):
        waits.append(delay)
        return await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", recording_sleep)
    return waits


def agent_for(transport: httpx.MockTransport, **kwargs) -> Agent:
    model = get_chat_model("test-model", transport=transport, **kwargs)
    return Agent(model, output_type=str, defer_model_check=True)


def test_rate_limited_request_is_retried_after_the_header_delay(recorded_waits):
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(
                429,
                headers={"Retry-After": "7"},
                json={"error": {"message": "rate limited"}},
            )
        return httpx.Response(200, json=chat_completion("resolved"))

    agent = agent_for(httpx.MockTransport(handler))
    result = agent.run_sync("Resolve the references.")

    assert result.output == "resolved"
    assert len(requests) == 2
    assert 7.0 in recorded_waits


def test_transport_errors_are_retried_until_the_attempt_count_is_exhausted(
    recorded_waits,
):
    attempts: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(request)
        raise httpx.ConnectError("connection reset by peer")

    transport_settings = TransportSettings(max_attempts=2)
    agent = agent_for(
        httpx.MockTransport(handler), transport_settings=transport_settings
    )

    with pytest.raises(Exception) as exc_info:
        agent.run_sync("Resolve the references.")

    assert len(attempts) == transport_settings.max_attempts
    assert any(
        isinstance(cause, httpx.ConnectError)
        for cause in _causes(exc_info.value)
    )


def _causes(error: BaseException) -> list[BaseException]:
    """Every exception in the chain, so a re-raise can be found under a wrapper."""

    chain: list[BaseException] = []
    current: BaseException | None = error
    while current is not None and current not in chain:
        chain.append(current)
        current = current.__cause__ or current.__context__
    return chain


def test_rate_limit_wait_is_capped_by_the_configured_maximum(recorded_waits):
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(
                429,
                headers={"Retry-After": "600"},
                json={"error": {"message": "rate limited"}},
            )
        return httpx.Response(200, json=chat_completion("resolved"))

    agent = agent_for(
        httpx.MockTransport(handler),
        transport_settings=TransportSettings(rate_limit_wait_cap=30),
    )
    result = agent.run_sync("Resolve the references.")

    assert result.output == "resolved"
    assert max(recorded_waits) == 30


def test_transport_settings_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("LLM_TRANSPORT_MAX_ATTEMPTS", "7")
    monkeypatch.setenv("LLM_TRANSPORT_RATE_LIMIT_WAIT_CAP", "45")
    monkeypatch.setenv("LLM_TRANSPORT_REQUEST_TIMEOUT", "90.5")

    transport_settings = TransportSettings()

    assert transport_settings.max_attempts == 7
    assert transport_settings.rate_limit_wait_cap == 45
    assert transport_settings.request_timeout == 90.5


def test_transport_settings_have_defaults():
    assert settings.transport.max_attempts == 3
    assert settings.transport.rate_limit_wait_cap == 120
    assert settings.transport.request_timeout == 600.0


def test_repeated_construction_shares_one_model_and_connection_pool():
    first = get_chat_model("test-model", "OLLAMA_MODEL_COREFERENCE")
    second = get_chat_model("test-model", "OLLAMA_MODEL_COREFERENCE")

    assert first is second


def test_a_different_model_name_gets_its_own_client(monkeypatch):
    # `default_model` is the lowest precedence, so a developer's `.env` setting
    # `OLLAMA_MODEL` would answer both calls with the same name and collapse the
    # two into one cache entry.  Deleting it is not enough: the factory calls
    # `load_dotenv`, which puts an absent key straight back.  An empty value is
    # present enough for dotenv to leave alone and falsy enough to fall through.
    monkeypatch.setenv("OLLAMA_MODEL", "")

    first = get_chat_model("test-model-a")
    second = get_chat_model("test-model-b")

    assert first is not second


def test_the_null_content_patch_applies_to_every_model():
    from pydantic_ai.models.openai import OpenAIChatModel

    get_chat_model("test-model")

    assert (
        OpenAIChatModel._MapModelResponseContext._into_message_param.__name__
        == "_into_message_param_with_empty_content"
    )


def test_every_model_is_built_for_the_llama_cpp_host(monkeypatch):
    """Chat goes to llama.cpp, not Ollama, and the ``/v1`` path is added once."""

    monkeypatch.setenv("LLAMA_CPP_BASE_URL", "http://localhost:9999")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434")

    model = get_chat_model("test-model", transport=httpx.MockTransport(lambda r: None))

    assert model.base_url.rstrip("/") == "http://localhost:9999/v1"


def test_a_base_url_that_already_names_v1_is_left_alone(monkeypatch):
    monkeypatch.setenv("LLAMA_CPP_BASE_URL", "http://localhost:9999/v1")

    assert resolve_chat_base_url() == "http://localhost:9999/v1"


def test_embedding_gets_its_own_llama_cpp_port(monkeypatch):
    """llama-server serves one model per process, so embedding runs beside chat."""

    monkeypatch.setenv("LLAMA_CPP_BASE_URL", "http://localhost:9999")
    monkeypatch.delenv("LLAMA_CPP_EMBEDDING_BASE_URL", raising=False)

    assert resolve_embedding_base_url() == "http://localhost:8081/v1"


def test_the_embedding_host_is_no_longer_read_from_ollama(monkeypatch):
    """A leftover `OLLAMA_BASE_URL` must not pull embedding back onto Ollama."""

    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434")
    monkeypatch.delenv("LLAMA_CPP_EMBEDDING_BASE_URL", raising=False)

    assert resolve_embedding_base_url() == "http://localhost:8081/v1"


def test_the_embedding_base_url_can_be_moved_and_keeps_a_named_v1(monkeypatch):
    monkeypatch.setenv("LLAMA_CPP_EMBEDDING_BASE_URL", "http://localhost:9001/v1")

    assert resolve_embedding_base_url() == "http://localhost:9001/v1"


def test_agents_sample_deterministically_by_default(monkeypatch):
    monkeypatch.delenv("LLM_TEMPERATURE", raising=False)

    model = get_chat_model("test-model", transport=httpx.MockTransport(lambda r: None))

    assert model.settings["temperature"] == 0.0


def test_the_temperature_can_be_raised_from_the_environment(monkeypatch):
    monkeypatch.setenv("LLM_TEMPERATURE", "0.7")

    model = get_chat_model("test-model", transport=httpx.MockTransport(lambda r: None))

    assert model.settings["temperature"] == 0.7


def test_the_profile_declares_what_llama_cpp_can_and_cannot_do():
    """The two capabilities that decide whether a tool call is enforceable.

    ``llama-server`` constrains decoding with a GBNF grammar built from the tool
    schema, which is what makes ``tool_choice: "required"`` binding rather than
    advisory.  It has no OpenAI-style strict mode, so asking for one would be
    rejected.
    """

    profile = llama_cpp_model_profile("gemma4:26b")

    assert profile["supports_tools"] is True
    assert profile["supports_json_schema_output"] is True
    assert profile["openai_supports_strict_tool_definition"] is False


def test_a_locally_named_gemma_build_still_gets_the_gemma_profile():
    """`32k-gemma-e4b-extraction` is a gemma, whatever the build is called."""

    renamed = llama_cpp_model_profile("32k-gemma-e4b-extraction")
    canonical = llama_cpp_model_profile("gemma4:26b")

    assert renamed == canonical


def test_agents_do_not_reason_before_answering_by_default(monkeypatch):
    """Thinking is off unless asked for, and it is off in the request body.

    Gemma 4's template defaults `enable_thinking` to false, but llama.cpp's
    `--reasoning auto` turns it on because the template supports it, and nothing
    bounds it because pydantic-ai sends no `max_tokens`.  Saying so per request
    keeps the answer with the code rather than with the launch flags.
    """

    monkeypatch.delenv("LLM_THINKING", raising=False)

    model = get_chat_model("test-model", transport=httpx.MockTransport(lambda r: None))

    assert model.settings["extra_body"] == {
        "chat_template_kwargs": {"enable_thinking": False}
    }


def test_thinking_can_be_turned_back_on_from_the_environment(monkeypatch):
    monkeypatch.setenv("LLM_THINKING", "on")

    model = get_chat_model("test-model", transport=httpx.MockTransport(lambda r: None))

    assert model.settings["extra_body"]["chat_template_kwargs"]["enable_thinking"]


def test_the_thinking_switch_reads_the_usual_spellings(monkeypatch):
    for value in ("on", "ON", " true ", "1", "yes"):
        monkeypatch.setenv("LLM_THINKING", value)
        assert resolve_thinking() is True, value
    for value in ("off", "false", "0", "no", ""):
        monkeypatch.setenv("LLM_THINKING", value)
        assert resolve_thinking() is False, value


def test_enable_thinking_reaches_the_wire(monkeypatch):
    """The setting is only useful if it survives into the request body."""

    monkeypatch.delenv("LLM_THINKING", raising=False)
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json=chat_completion("resolved"))

    agent = agent_for(httpx.MockTransport(handler))
    agent.run_sync("Resolve the references.")

    assert bodies[0]["chat_template_kwargs"] == {"enable_thinking": False}
    assert bodies[0]["temperature"] == 0.0


class _Item(BaseModel):
    """A structured result whose schema pydantic references rather than inlines."""

    label: str
    accepted: bool


def _structured_request_body(monkeypatch) -> dict:
    monkeypatch.delenv("LLM_THINKING", raising=False)
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(
            200, json=chat_completion('{"response": [{"label": "1", "accepted": true}]}')
        )

    model = get_chat_model("test-model", transport=httpx.MockTransport(handler))
    Agent(model, output_type=list[_Item], defer_model_check=True).run_sync("Judge them.")
    return bodies[0]


def test_structured_output_goes_through_json_schema_not_a_tool_call(monkeypatch):
    """Gemma 4's tool-call syntax does not survive llama-server's parser.

    The model closes a correct answer with a literal ``<tool_call|>``, which is
    not a special token, so decoding never stops and the answer repeats until
    the context is exhausted.  The ``json_schema`` response format compiles a
    grammar instead, which terminates.
    """

    body = _structured_request_body(monkeypatch)

    assert body["response_format"]["type"] == "json_schema"
    assert "tools" not in body


def test_the_response_schema_carries_no_refs(monkeypatch):
    """A ``$ref`` in the schema costs the request its grammar entirely.

    ``llama-server`` does not fail on an unresolved reference -- it drops the
    constraint and lets the model generate freely, unbounded, because
    pydantic-ai sends no ``max_tokens``.
    """

    body = _structured_request_body(monkeypatch)
    schema = json.dumps(body["response_format"]["json_schema"]["schema"])

    assert "$ref" not in schema
    assert "$defs" not in schema
    assert "accepted" in schema
