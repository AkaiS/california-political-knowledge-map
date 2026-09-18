"""Local chat behavior observed through its ASGI application."""

from pathlib import Path

import httpx
import pytest
from starlette.testclient import TestClient

from knowledge_map.web import create_app


@pytest.mark.parametrize("path", ["/", "/api/configure", "/api/chat"])
def test_chat_rejects_a_nonlocal_host(path: str):
    with TestClient(create_app(), base_url="http://attacker.example") as client:
        response = client.request("POST" if path == "/api/chat" else "GET", path)

    assert response.status_code == 421


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "[::1]"])
def test_chat_accepts_local_hosts(host: str):
    with TestClient(create_app(), base_url="http://127.0.0.1:7932") as client:
        response = client.get("/api/configure", headers={"Host": f"{host}:7932"})

    assert response.status_code == 200
    assert response.json() == {"models": [], "builtinTools": []}


def test_root_serves_the_default_cdn_frontend_and_reuses_the_local_cache(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    downloads: list[httpx.URL] = []
    frontend = b"<!doctype html><title>CDN response fixture</title>"

    def cdn(request: httpx.Request) -> httpx.Response:
        downloads.append(request.url)
        return httpx.Response(200, content=frontend)

    http_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda: http_client(transport=httpx.MockTransport(cdn))
    )
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    # A fresh application must reuse the filesystem cache, without a second download.
    for _ in range(2):
        with TestClient(create_app(), base_url="http://127.0.0.1:7932") as client:
            response = client.get("/")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")
        assert response.content == frontend

    assert len(downloads) == 1
    assert downloads[0].scheme == "https"
    assert downloads[0].host == "cdn.jsdelivr.net"
    assert downloads[0].path.startswith("/npm/@pydantic/ai-chat-ui@")
    assert downloads[0].path.endswith("/dist/index.html")
