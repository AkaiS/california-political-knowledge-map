"""The Model Reachability Check, and the commands it gates."""

import argparse

import httpx
import pytest

from knowledge_map.cli.main import (
    SKIP_MODEL_CHECK_ENV,
    enforce_model_reachability,
    main,
    required_model_endpoints,
)
from knowledge_map.utils.reachability import (
    EndpointReachability,
    ModelEndpoint,
    check_endpoint,
    check_endpoints,
)

CHAT_AND_EMBEDDING = frozenset({ModelEndpoint.CHAT, ModelEndpoint.EMBEDDING})


@pytest.fixture(autouse=True)
def local_endpoints(monkeypatch):
    monkeypatch.setenv("LLAMA_CPP_BASE_URL", "http://localhost:8080")
    monkeypatch.setenv("LLAMA_CPP_EMBEDDING_BASE_URL", "http://localhost:8081")


def _namespace(**kwargs) -> argparse.Namespace:
    return argparse.Namespace(**kwargs)


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


# --- the check itself -------------------------------------------------------


def test_answering_endpoint_is_reachable():
    with _client(lambda request: httpx.Response(200, json={"data": []})) as client:
        result = check_endpoint(ModelEndpoint.CHAT, client=client)

    assert result.reachable
    assert result.base_url == "http://localhost:8080/v1"


def test_error_status_still_counts_as_reachable():
    """A served error proves a server is accepting requests at that address."""

    with _client(lambda request: httpx.Response(503)) as client:
        result = check_endpoint(ModelEndpoint.EMBEDDING, client=client)

    assert result.reachable


def test_refused_connection_is_unreachable_and_keeps_the_reason():
    def refuse(request):
        raise httpx.ConnectError("[Errno 61] Connection refused")

    with _client(refuse) as client:
        result = check_endpoint(ModelEndpoint.CHAT, client=client)

    assert not result.reachable
    assert "Connection refused" in result.detail
    assert result.base_url == "http://localhost:8080/v1"


def test_a_timeout_names_its_exception_type_when_the_message_is_empty():
    def stall(request):
        raise httpx.ConnectTimeout("")

    with _client(stall) as client:
        result = check_endpoint(ModelEndpoint.CHAT, client=client)

    assert not result.reachable
    assert result.detail == "ConnectTimeout"


def test_every_required_endpoint_is_checked_even_after_one_fails():
    """One run should report every server an operator has to restart."""

    def refuse(request):
        raise httpx.ConnectError("down")

    with _client(refuse) as client:
        results = check_endpoints(CHAT_AND_EMBEDDING, client=client)

    assert [result.endpoint for result in results] == [
        ModelEndpoint.CHAT,
        ModelEndpoint.EMBEDDING,
    ]
    assert not any(result.reachable for result in results)


def test_the_check_reads_the_configured_endpoints(monkeypatch):
    monkeypatch.setenv("LLAMA_CPP_EMBEDDING_BASE_URL", "http://elsewhere:9999")
    seen = []

    def record(request):
        seen.append(str(request.url))
        return httpx.Response(200)

    with _client(record) as client:
        check_endpoint(ModelEndpoint.EMBEDDING, client=client)

    assert seen == ["http://elsewhere:9999/v1/models"]


# --- which commands are gated ----------------------------------------------


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("update-sources", CHAT_AND_EMBEDDING),
        ("scrape-archive", CHAT_AND_EMBEDDING),
        ("validate-articles", CHAT_AND_EMBEDDING),
        ("heal-selectors", frozenset({ModelEndpoint.CHAT})),
    ],
)
def test_agent_running_commands_require_their_endpoints(command, expected):
    assert required_model_endpoints(_namespace(action=command)) == expected


@pytest.mark.parametrize(
    "command",
    [
        "clear",
        "analyze",
        "janitor",
        "register-publication",
        "update-publication",
        "review-selectors",
        "refetch-html",
        "purge-cache",
    ],
)
def test_commands_that_run_no_agent_are_not_gated(command):
    assert required_model_endpoints(_namespace(action=command)) == frozenset()


def test_classifier_requirements_are_per_subcommand():
    embedding = frozenset({ModelEndpoint.EMBEDDING})
    for subcommand in ("backfill", "label"):
        namespace = _namespace(action="classifier", classifier_action=subcommand)
        assert required_model_endpoints(namespace) == embedding

    for subcommand in ("train", "reevaluate"):
        namespace = _namespace(action="classifier", classifier_action=subcommand)
        assert required_model_endpoints(namespace) == frozenset()


def test_selecting_openrouter_drops_only_the_chat_endpoint():
    """Embedding stays local llama.cpp whichever chat deployment is selected."""

    local = _namespace(action="ingest", deployment="local")
    openrouter = _namespace(action="ingest", deployment="openrouter")

    assert required_model_endpoints(local) == CHAT_AND_EMBEDDING
    assert required_model_endpoints(openrouter) == frozenset(
        {ModelEndpoint.EMBEDDING}
    )


# --- the gate ---------------------------------------------------------------


def _unreachable(*args, **kwargs):
    return (
        EndpointReachability(
            endpoint=ModelEndpoint.CHAT,
            base_url="http://localhost:8080/v1",
            reachable=False,
            detail="[Errno 61] Connection refused",
        ),
    )


def _reachable(*args, **kwargs):
    return (
        EndpointReachability(
            endpoint=ModelEndpoint.CHAT,
            base_url="http://localhost:8080/v1",
            reachable=True,
        ),
    )


@pytest.fixture
def enforcing(monkeypatch):
    monkeypatch.delenv(SKIP_MODEL_CHECK_ENV, raising=False)


def test_an_unreachable_endpoint_stops_the_command(enforcing, monkeypatch, caplog):
    monkeypatch.setattr("knowledge_map.cli.main.check_endpoints", _unreachable)

    with pytest.raises(SystemExit) as exit_info:
        enforce_model_reachability(_namespace(action="update-sources"))

    assert exit_info.value.code == 1
    # The banner only reaches a TTY, so the log is where the reason always
    # lands -- including under cron, which is where this will usually fire.
    logged = caplog.text
    assert "update-sources" in logged
    assert "http://localhost:8080/v1" in logged
    assert "Connection refused" in logged
    assert "--skip-model-check" in logged


def test_a_reachable_endpoint_lets_the_command_run(enforcing, monkeypatch):
    monkeypatch.setattr("knowledge_map.cli.main.check_endpoints", _reachable)

    enforce_model_reachability(_namespace(action="update-sources"))


def test_the_flag_forces_a_run_past_an_unreachable_endpoint(enforcing, monkeypatch):
    monkeypatch.setattr("knowledge_map.cli.main.check_endpoints", _unreachable)

    enforce_model_reachability(
        _namespace(action="update-sources", skip_model_check=True)
    )


def test_the_environment_variable_forces_a_run(monkeypatch):
    monkeypatch.setenv(SKIP_MODEL_CHECK_ENV, "1")
    monkeypatch.setattr("knowledge_map.cli.main.check_endpoints", _unreachable)

    enforce_model_reachability(_namespace(action="update-sources"))


def test_an_ungated_command_never_reaches_an_endpoint(enforcing, monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("an ungated command must not check an endpoint")

    monkeypatch.setattr("knowledge_map.cli.main.check_endpoints", fail)

    enforce_model_reachability(_namespace(action="purge-cache"))


def test_update_sources_stops_before_touching_the_database(
    enforcing, monkeypatch, tmp_path
):
    """The whole point: no scraping starts that cannot then be validated."""

    monkeypatch.setenv("SQLITE_DB_PATH", str(tmp_path / "unused.db"))
    monkeypatch.setattr("knowledge_map.cli.main.check_endpoints", _unreachable)

    def fail(*args, **kwargs):
        raise AssertionError("discovery must not start")

    monkeypatch.setattr(
        "knowledge_map.cli.main.ListingPageDiscoveryService", fail
    )

    with pytest.raises(SystemExit) as exit_info:
        main(["update-sources"])

    assert exit_info.value.code == 1
    assert not (tmp_path / "unused.db").exists()


def test_the_flag_is_accepted_on_a_gated_command(monkeypatch, tmp_path):
    """The documented override has to actually parse."""

    monkeypatch.setenv("SQLITE_DB_PATH", str(tmp_path / "heal.db"))

    with pytest.raises(SystemExit) as exit_info:
        main(["heal-selectors", "--publication", "nonexistent", "--skip-model-check"])

    # Past the gate, and stopped by the missing publication instead.
    assert exit_info.value.code == 1
