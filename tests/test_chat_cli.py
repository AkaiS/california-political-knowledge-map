"""The chat launcher uses the existing command dispatcher."""

from contextlib import asynccontextmanager
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from knowledge_map.cli.main import main
from knowledge_map.web import create_app


@asynccontextmanager
async def no_dependencies():
    yield None


def recorded_runner():
    calls = []

    def run(app, **kwargs):
        calls.append((app, kwargs))
        with TestClient(app, base_url="http://localhost"):
            pass

    return Mock(side_effect=run), calls


def local_app(*, browser_url):
    return create_app(startup=no_dependencies, browser_url=browser_url)


def test_chat_launches_on_loopback_and_prints_its_url_without_opening_a_browser(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    runner, calls = recorded_runner()
    browser = Mock()
    monkeypatch.setattr("uvicorn.run", runner)
    monkeypatch.setattr("knowledge_map.web.create_app", local_app)
    monkeypatch.setattr("webbrowser.open", browser)
    monkeypatch.setattr("webbrowser.open_new", browser)
    monkeypatch.setattr("webbrowser.open_new_tab", browser)

    main(["chat"])

    assert len(calls) == 1
    assert isinstance(calls[0][0], FastAPI)
    assert calls[0][1] == {"host": "127.0.0.1", "port": 7932}
    assert "http://127.0.0.1:7932" in capsys.readouterr().out
    browser.assert_not_called()


def test_chat_port_override_keeps_the_loopback_address(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    runner, calls = recorded_runner()
    monkeypatch.setattr("uvicorn.run", runner)
    monkeypatch.setattr("knowledge_map.web.create_app", local_app)

    main(["chat", "--port", "8123"])

    assert len(calls) == 1
    assert calls[0][1] == {"host": "127.0.0.1", "port": 8123}
    assert "http://127.0.0.1:8123" in capsys.readouterr().out


def test_chat_does_not_print_the_url_when_application_startup_fails(
    capsys: pytest.CaptureFixture[str],
):
    @asynccontextmanager
    async def failed_startup():
        raise RuntimeError("dependency unavailable")
        yield None

    app = create_app(startup=failed_startup, browser_url="http://127.0.0.1:7932")
    with (
        pytest.raises(RuntimeError, match="dependency unavailable"),
        TestClient(app, base_url="http://localhost"),
    ):
        pass

    assert "http://127.0.0.1:7932" not in capsys.readouterr().out


def test_chat_rejects_a_host_override(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    runner = Mock()
    monkeypatch.setattr("uvicorn.run", runner)

    with pytest.raises(SystemExit) as error:
        main(["chat", "--host", "0.0.0.0"])

    assert error.value.code == 2
    assert "unrecognized arguments: --host" in capsys.readouterr().err
    runner.assert_not_called()
