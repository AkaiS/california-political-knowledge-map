"""The chat launcher uses the existing command dispatcher."""

from unittest.mock import Mock

import pytest
from fastapi import FastAPI

from knowledge_map.cli.main import main


def test_chat_launches_on_loopback_and_prints_its_url_without_opening_a_browser(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    runner = Mock()
    browser = Mock()
    monkeypatch.setattr("uvicorn.run", runner)
    monkeypatch.setattr("webbrowser.open", browser)
    monkeypatch.setattr("webbrowser.open_new", browser)
    monkeypatch.setattr("webbrowser.open_new_tab", browser)

    main(["chat"])

    runner.assert_called_once()
    assert isinstance(runner.call_args.args[0], FastAPI)
    assert runner.call_args.kwargs == {"host": "127.0.0.1", "port": 7932}
    assert "http://127.0.0.1:7932" in capsys.readouterr().out
    browser.assert_not_called()


def test_chat_port_override_keeps_the_loopback_address(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    runner = Mock()
    monkeypatch.setattr("uvicorn.run", runner)

    main(["chat", "--port", "8123"])

    runner.assert_called_once()
    assert runner.call_args.kwargs == {"host": "127.0.0.1", "port": 8123}
    assert "http://127.0.0.1:8123" in capsys.readouterr().out


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
