"""The launcher reuses only the requested reviewer and owns its child cleanup."""

import importlib.util
import json
import os
import socket
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
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
        original_http = launcher.HTTP

        class ProbeOwnedListener:
            def open(self, url, **kwargs):
                return original_http.open(
                    url.replace(":8765/", f":{unrelated_port}/"), **kwargs
                )

        monkeypatch.setattr(launcher, "HTTP", ProbeOwnedListener())
        try:
            port, _log = launcher.launch(root / "reports", root / "samples", 5)

            assert port != unrelated_port
            assert len(children) == 1
            assert launcher.matching_server(
                port, launcher.reviewer_identity(root / "reports", root / "samples")
            )
            with socket.create_connection(
                ("127.0.0.1", unrelated_port), timeout=1
            ) as client, client.makefile("rb") as response:
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
