"""The launcher reuses only the requested reviewer and owns its child cleanup."""

import importlib.util
import json
import os
import socket
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/start_rag_reviewer.py"
SPEC = importlib.util.spec_from_file_location("start_rag_reviewer", SCRIPT)
assert SPEC and SPEC.loader
launcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(launcher)

STUB_SERVER = """
import argparse, json, os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
parser = argparse.ArgumentParser()
parser.add_argument("--mode")
parser.add_argument("--port", type=int)
parser.add_argument("--reports-dir")
parser.add_argument("--samples-dir")
args = parser.parse_args()
identity = {
    "service": "ca-map-evaluation-reviewer-v1", "mode": args.mode,
    "checkout": str(Path(__file__).resolve().parents[1]),
    "reports_dir": args.reports_dir, "samples_dir": args.samples_dir,
    "pid": os.getpid(),
}
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(json.dumps(identity).encode())
    def log_message(self, *args): pass
server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
print(f"Browse rag evals at http://127.0.0.1:{server.server_port}/", flush=True)
server.serve_forever()
"""


@pytest.fixture
def checkout(tmp_path, monkeypatch):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "review_chat_eval.py").write_text(STUB_SERVER)
    monkeypatch.setattr(launcher, "REPOSITORY", tmp_path)
    children = []
    popen = subprocess.Popen

    def start(command, **kwargs):
        assert command[:5] == ["uv", "run", "--no-sync", "python", "-u"]
        process = popen([sys.executable, "-u", *command[5:]], **kwargs)
        children.append(process)
        return process

    monkeypatch.setattr(launcher.subprocess, "Popen", start)
    yield tmp_path, children
    for process in children:
        if process.poll() is None:
            launcher.stop_child(process)


@contextmanager
def owned_listener(response):
    """Serve test-owned connections without touching an existing reviewer."""
    stopped = threading.Event()
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        listener.settimeout(0.05)
        port = listener.getsockname()[1]

        def serve():
            while not stopped.is_set():
                try:
                    client, _address = listener.accept()
                except TimeoutError:
                    continue
                with client:
                    client.settimeout(1)
                    try:
                        client.recv(4096)
                        response(client, stopped)
                    except OSError:
                        pass

        thread = threading.Thread(target=serve)
        thread.start()
        try:
            yield port, thread
        finally:
            stopped.set()
            thread.join(timeout=2)
            assert not thread.is_alive()


def map_default_probe(monkeypatch, port):
    probe = launcher.matching_server
    monkeypatch.setattr(
        launcher,
        "matching_server",
        lambda candidate, *args: probe(port if candidate == 8765 else candidate, *args),
    )


@pytest.mark.parametrize("phase", ["headers", "body"])
def test_probe_total_deadline_includes_streaming_headers_and_body(phase):
    def stream(client, stopped):
        if phase == "headers":
            client.sendall(b"HTTP/1.0 200 OK\r\nX-Slow: ")
        else:
            client.sendall(b"HTTP/1.0 200 OK\r\n\r\n")
        until = time.monotonic() + 0.8
        while time.monotonic() < until and not stopped.wait(0.02):
            client.sendall(b" ")

    with owned_listener(stream) as (port, thread):
        started = time.monotonic()
        assert not launcher.matching_server(port, {"mode": "rag"}, 0.15)
        assert time.monotonic() - started < 0.45
        assert thread.is_alive()


@pytest.mark.parametrize("recorded", [False, True])
def test_expired_reuse_probe_does_not_start_a_child(checkout, monkeypatch, recorded):
    root, children = checkout
    reports, samples = root / "reports", root / "samples"

    def stream(client, stopped):
        client.sendall(b"HTTP/1.0 200 OK\r\n\r\n")
        until = time.monotonic() + 0.8
        while time.monotonic() < until and not stopped.wait(0.02):
            client.sendall(b" ")

    with owned_listener(stream) as (port, thread):
        map_default_probe(monkeypatch, port)
        if recorded:
            scratch = root / ".scratch/rag-reviewer"
            scratch.mkdir(parents=True)
            identity = launcher.reviewer_identity(reports, samples)
            key = launcher.hashlib.sha256(
                json.dumps(identity, sort_keys=True).encode()
            ).hexdigest()[:16]
            (scratch / f"{key}.json").write_text(json.dumps({"port": port}))
        started = time.monotonic()
        with pytest.raises(RuntimeError, match="not ready"):
            launcher.launch(reports, samples, 0.15)
        assert time.monotonic() - started < 0.45
        assert not children
        assert thread.is_alive()


def test_manual_default_reuse_reports_unavailable_log(checkout, monkeypatch, capsys):
    root, children = checkout
    reports, samples = root / "reports", root / "samples"
    identity = launcher.reviewer_identity(reports, samples)

    def respond(client, _stopped):
        client.sendall(b"HTTP/1.0 200 OK\r\n\r\n" + json.dumps(identity).encode())

    with owned_listener(respond) as (port, thread):
        map_default_probe(monkeypatch, port)
        assert launcher.launch(reports, samples, 5) == (8765, None)
        monkeypatch.setattr(
            sys,
            "argv",
            [str(SCRIPT), "--reports-dir", str(reports), "--samples-dir", str(samples)],
        )
        launcher.main()
        output = capsys.readouterr().out
        assert "Ready: http://127.0.0.1:8765/" in output
        assert "Log: unavailable" in output
        assert ".scratch/rag-reviewer" not in output
        assert not children
        assert thread.is_alive()


@pytest.mark.parametrize("stored_log", [None, 42, {}, "", "missing.log", ".scratch"])
def test_recorded_reuse_with_invalid_log_reports_unavailable(checkout, stored_log):
    root, children = checkout
    reports, samples = root / "reports", root / "samples"
    port, _log = launcher.launch(reports, samples, 5)
    state_path = next((root / ".scratch/rag-reviewer").glob("*.json"))
    state = json.loads(state_path.read_text())
    if stored_log is None:
        del state["log"]
    elif isinstance(stored_log, str):
        state["log"] = str(root / stored_log)
    else:
        state["log"] = stored_log
    state_path.write_text(json.dumps(state))

    assert launcher.launch(reports, samples, 5) == (port, None)
    assert len(children) == 1


def test_start_detaches_and_reuses_ready_server(checkout):
    root, children = checkout
    reports, samples = root / "reports", root / "samples"
    port, log = launcher.launch(reports, samples, 5)

    assert log.is_relative_to(root / ".scratch")
    assert launcher.matching_server(port, launcher.reviewer_identity(reports, samples))
    assert os.getpgid(children[0].pid) == children[0].pid
    assert launcher.launch(reports, samples, 5) == (port, log)
    assert len(children) == 1


@pytest.mark.parametrize("field", ["mode", "checkout", "reports_dir", "samples_dir"])
def test_server_with_different_identity_is_not_reused(checkout, field):
    root, _children = checkout
    reports, samples = root / "reports", root / "samples"
    port, _log = launcher.launch(reports, samples, 5)
    identity = launcher.reviewer_identity(reports, samples)
    identity[field] = "other"
    assert not launcher.matching_server(port, identity)


def test_conflicting_port_is_left_running(checkout):
    root, children = checkout
    reports, samples = root / "reports", root / "samples"
    original_port, _log = launcher.launch(reports, samples, 5)
    # Point a second configuration at an unrelated listener, as with stale state.
    samples = root / "other-samples"
    identity = launcher.reviewer_identity(reports, samples)
    key = launcher.hashlib.sha256(
        json.dumps(identity, sort_keys=True).encode()
    ).hexdigest()[:16]
    state_path = root / ".scratch/rag-reviewer" / f"{key}.json"
    state_path.write_text(json.dumps({"port": original_port}))

    port, _log = launcher.launch(reports, samples, 5)

    assert port != original_port
    assert len(children) == 2
    assert children[0].poll() is None
    assert launcher.matching_server(
        original_port, launcher.reviewer_identity(reports, root / "samples")
    )


def test_concurrent_launches_share_one_server(checkout):
    root, children = checkout
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda _: launcher.launch(root / "reports", root / "samples", 5),
                range(2),
            )
        )
    assert results[0] == results[1]
    assert len(children) == 1


def test_non_http_listener_is_left_running_when_reviewer_starts(checkout, monkeypatch):
    root, children = checkout
    greeting = b"SSH-2.0-OpenSSH_9.9\r\n"
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        listener.settimeout(0.1)
        unrelated_port = listener.getsockname()[1]
        stopped = threading.Event()

        def serve():
            while not stopped.is_set():
                try:
                    client, _address = listener.accept()
                except TimeoutError:
                    continue
                with client:
                    client.sendall(greeting)

        thread = threading.Thread(target=serve)
        thread.start()
        map_default_probe(monkeypatch, unrelated_port)
        try:
            port, _log = launcher.launch(root / "reports", root / "samples", 5)

            assert port != unrelated_port
            assert len(children) == 1
            assert launcher.matching_server(
                port, launcher.reviewer_identity(root / "reports", root / "samples")
            )
            with (
                socket.create_connection(
                    ("127.0.0.1", unrelated_port), timeout=1
                ) as client,
                client.makefile("rb") as response,
            ):
                assert response.readline() == greeting
        finally:
            stopped.set()
            thread.join(timeout=2)
            assert not thread.is_alive()


def test_startup_failure_reports_log_without_ready_state(checkout):
    root, children = checkout
    (root / "scripts/review_chat_eval.py").write_text(
        'print("missing dependency", flush=True)\nraise SystemExit(7)\n'
    )

    with pytest.raises(RuntimeError, match="status 7.*Log:"):
        launcher.launch(root / "reports", root / "samples", 5)

    assert children[0].poll() == 7
    assert not list((root / ".scratch/rag-reviewer").glob("*.json"))
    assert (
        "missing dependency"
        in next((root / ".scratch/rag-reviewer").glob("*.log")).read_text()
    )


def test_readiness_timeout_stops_only_launched_child(checkout):
    root, children = checkout
    (root / "scripts/review_chat_eval.py").write_text("import time\ntime.sleep(60)\n")
    with pytest.raises(RuntimeError, match="not ready.*Log:"):
        launcher.launch(root / "reports", root / "samples", 0.5)
    assert children[0].poll() is not None


def test_streaming_readiness_timeout_stops_only_launched_child(checkout, monkeypatch):
    root, children = checkout

    def stream(client, stopped):
        client.sendall(b"HTTP/1.0 200 OK\r\n\r\n")
        until = time.monotonic() + 0.8
        while time.monotonic() < until and not stopped.wait(0.02):
            client.sendall(b" ")

    with owned_listener(stream) as (port, thread):
        probe = launcher.matching_server
        monkeypatch.setattr(
            launcher,
            "matching_server",
            lambda candidate, *args: (
                False if candidate == 8765 else probe(candidate, *args)
            ),
        )
        (root / "scripts/review_chat_eval.py").write_text(
            f'import time\nprint("Browse rag evals at http://127.0.0.1:{port}/", flush=True)\n'
            "time.sleep(60)\n"
        )
        started = time.monotonic()
        with pytest.raises(RuntimeError, match="not ready.*Log:"):
            launcher.launch(root / "reports", root / "samples", 0.35)
        assert time.monotonic() - started < 0.65
        assert len(children) == 1
        assert children[0].poll() is not None
        assert thread.is_alive()
        assert not list((root / ".scratch/rag-reviewer").glob("*.json"))


def test_identity_probe_stops_at_body_limit():
    def respond(client, stopped):
        client.sendall(
            b'HTTP/1.0 200 OK\r\nContent-Length: 20000\r\n\r\n{"mode":"rag"}'
            + b" " * 10000
        )
        stopped.wait(0.8)

    with owned_listener(respond) as (port, thread):
        assert launcher.matching_server(port, {"mode": "rag"}, 0.15)
        assert thread.is_alive()
