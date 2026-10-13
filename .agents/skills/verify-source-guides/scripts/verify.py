#!/usr/bin/env -S uv run --frozen python
"""Drive production Source Guides HTTP routes with an owned app instance."""

import argparse
import json
import os
import shutil
import signal
import socket
import sqlite3
import subprocess
import tempfile
import time
from contextlib import closing
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[4]


def save(directory, name, value):
    (directory / name).write_text(json.dumps(value, indent=2) + "\n")


def command(*args):
    return subprocess.check_output(args, text=True).strip()


def doctor(process, port, state, evidence, client):
    assert process.poll() is None, "Owned launcher exited; inspect server.log"
    pids = sorted(
        {
            int(value)
            for value in command(
                "lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"
            ).splitlines()
        }
    )
    assert pids, "No listener on the owned port"
    identities = []
    for pid in pids:
        assert os.getpgid(pid) == process.pid, "Listener belongs to another run"
        identity = command("ps", "-p", str(pid), "-o", "command=")
        assert f"ca-map chat --port {port}" in identity, identity
        cwd = command("lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn").split("\nn")[-1]
        assert Path(cwd) == state, "Listener uses a different working directory"
        identities.append({"pid": pid, "command": identity})
    shell = client.get("/")
    shell.raise_for_status()
    assert "<title>California Source Guides</title>" in shell.text
    coverage = client.get("/api/coverage")
    coverage.raise_for_status()
    assert coverage.json()["entries"], "Coverage initialization is incomplete"
    guides = client.get("/api/guides")
    guides.raise_for_status()
    with closing(
        sqlite3.connect(f"file:{state / 'document_store.db'}?mode=ro", uri=True)
    ) as db:
        tables = {
            row[0]
            for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert {
            "source_guides",
            "source_guide_attempts",
            "stories",
            "publications",
        } <= tables
    save(
        evidence,
        "doctor.json",
        {
            "url": str(client.base_url),
            "cwd": str(state),
            "sqlite": str(state / "document_store.db"),
            "process_group": process.pid,
            "listeners": identities,
            "revision": command("git", "-C", str(ROOT), "rev-parse", "HEAD"),
            "dirty": bool(command("git", "-C", str(ROOT), "status", "--porcelain")),
            "coverage": coverage.json(),
            "guide_count": len(guides.json()["guides"]),
            "authentication": "No application login; production startup accepted dependency configuration",
            "limits": "Model listing checks reachability. Doctor does not prove Jev or embedding inference.",
        },
    )
    (evidence / "root.html").write_text(shell.text)
    return guides.json()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8132)
    parser.add_argument("--question", default="Who supported that bill?")
    parser.add_argument(
        "--expect",
        default="needs_edit",
        choices=("needs_edit", "declined", "completed", "empty"),
    )
    parser.add_argument("--timeout", type=float, default=240)
    parser.add_argument(
        "--pause-after-doctor",
        action="store_true",
        help="Hold an owned instance for additional mapped drives; press Enter to finish the default journey",
    )
    parser.add_argument(
        "--interrupt-after-submit",
        action="store_true",
        help="Stop a running submitted attempt, restart, verify interruption, then retry explicitly",
    )
    parser.add_argument("--evidence-dir", type=Path, required=True)
    args = parser.parse_args()
    evidence = args.evidence_dir.resolve()
    scratch = ROOT / ".scratch"
    assert not evidence.is_relative_to(scratch), (
        "Keep proof outside disposable .scratch state"
    )
    evidence.mkdir(parents=True, exist_ok=False)
    scratch.mkdir(exist_ok=True)
    state = Path(
        tempfile.mkdtemp(prefix="verify-source-guides-", dir=scratch)
    ).resolve()
    process = None
    log = None
    succeeded = False
    events = []

    def stop(owned):
        if owned.poll() is None:
            os.killpg(owned.pid, signal.SIGINT)
            try:
                owned.wait(timeout=20)
            except subprocess.TimeoutExpired:
                os.killpg(owned.pid, signal.SIGTERM)
                owned.wait(timeout=10)
        events.append(
            {"event": "stop", "process_group": owned.pid, "exit_code": owned.returncode}
        )

    try:
        load_dotenv(ROOT / ".env")
        source = Path(os.environ.get("SQLITE_DB_PATH", "document_store.db"))
        if not source.is_absolute():
            source = ROOT / source
        assert source.is_file(), (
            "Existing document store required for production-data copy"
        )
        with (
            closing(
                sqlite3.connect(f"file:{source.resolve()}?mode=ro", uri=True)
            ) as original,
            closing(sqlite3.connect(state / "document_store.db")) as clone,
            clone,
        ):
            original.backup(clone)
            for table in ("source_guide_attempts", "source_guides"):
                if clone.execute(
                    "SELECT 1 FROM sqlite_master WHERE name=?", (table,)
                ).fetchone():
                    clone.execute(f"DELETE FROM {table}")
        from knowledge_map.adapters.sqlite_db import init_db
        from knowledge_map.utils.telemetry import resolve_credential

        init_db(str(state / "document_store.db"))
        env = dict(os.environ)
        env["SQLITE_DB_PATH"] = str(state / "document_store.db")
        env["PYTHONUNBUFFERED"] = "1"
        credential = resolve_credential()
        if credential:
            env["LOGFIRE_TOKEN"] = credential.token
            if credential.project_url:
                env["LOGFIRE_PROJECT_URL"] = credential.project_url
        assert credential or env.get("KNOWLEDGE_MAP_ALLOW_UNTRACED"), (
            "Configure Logfire per docs/agents/secrets.md"
        )
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", args.port))
        launch = [
            "uv",
            "run",
            "--frozen",
            "--no-sync",
            "--project",
            str(ROOT),
            "ca-map",
            "chat",
            "--port",
            str(args.port),
        ]
        save(
            evidence,
            "manifest.json",
            {
                "feature": "attempt-interrupt"
                if args.interrupt_after_submit
                else "question-assessment",
                "entry_point": "HTTP POST /api/questions",
                "question": args.question,
                "expected": args.expect,
                "state": str(state),
                "source_sqlite": str(source.resolve()),
                "command": launch,
                "deployment": env.get("CHAT_DEPLOYMENT", "local"),
                "untraced": bool(env.get("KNOWLEDGE_MAP_ALLOW_UNTRACED")),
                "shared_dependencies": "Existing Neo4j and model services; never stopped or migrated by this run",
                "unverified": [
                    "Browser rendering, focus, navigation and screenshots",
                    "Other feature-map journeys",
                ],
            },
        )
        log = (evidence / "server.log").open("w")
        with httpx.Client(
            base_url=f"http://127.0.0.1:{args.port}", timeout=10, trust_env=False
        ) as client:

            def start():
                nonlocal process
                process = subprocess.Popen(
                    launch,
                    cwd=state,
                    env=env,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
                events.append(
                    {"event": "start", "process_group": process.pid, "command": launch}
                )
                deadline = time.monotonic() + 60
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        raise RuntimeError("App startup failed; inspect server.log")
                    try:
                        response = client.get("/api/coverage")
                        if response.status_code == 200 and response.json().get(
                            "entries"
                        ):
                            return
                    except httpx.HTTPError:
                        pass
                    time.sleep(0.5)
                raise TimeoutError("App initialization exceeded 60 seconds")

            def request(method, route, name, body=None):
                response = client.request(
                    method, route, **({"json": body} if body is not None else {})
                )
                events.append(
                    {
                        "method": method,
                        "route": route,
                        "body": body,
                        "status": response.status_code,
                        "response": response.json(),
                    }
                )
                save(evidence, "actions.json", events)
                response.raise_for_status()
                result = response.json()
                save(evidence, name, result)
                return response.status_code, result

            start()
            baseline = doctor(process, args.port, state, evidence, client)
            assert baseline == {"guides": []}, "Clone must start without saved guides"
            save(evidence, "baseline.json", baseline)
            if args.pause_after_doctor:
                input(
                    f"Owned app ready at {client.base_url}. Capture extra actions in {evidence}. Press Enter to run the default journey and clean up: "
                )
            status, submitted = request(
                "POST", "/api/questions", "submitted.json", {"question": args.question}
            )
            assert status == 202 and submitted["question"] == args.question
            guide_id = submitted["guide_id"]
            route = f"/api/guides/{guide_id}"
            if args.interrupt_after_submit:
                stop(process)
                start()
                doctor(process, args.port, state, evidence, client)
                _, interrupted = request("GET", route, "interrupted.json")
                assert interrupted["latest_attempt"]["status"] == "interrupted", (
                    "Attempt finished before interruption; this run does not prove the interruption path"
                )
                status, retried = request("POST", f"{route}/update", "retried.json", {})
                assert status == 202 and retried["question"] == args.question
                assert (
                    retried["latest_attempt"]["attempt_id"]
                    != submitted["latest_attempt"]["attempt_id"]
                )
            deadline = time.monotonic() + args.timeout
            while True:
                _, terminal = request("GET", route, "terminal.json")
                if terminal["latest_attempt"]["status"] != "running":
                    break
                assert time.monotonic() < deadline, (
                    "Search exceeded verification deadline"
                )
                time.sleep(1)
            assert terminal["status"] == args.expect, (
                f"Expected {args.expect}, observed {terminal['status']}"
            )
            assert terminal["question"] == args.question
            if args.expect in {"needs_edit", "declined"}:
                assert terminal["articles"] == []
                assert terminal["search_details"]["completion"] == "not_searched"
                assert terminal["latest_attempt"]["assessment"]["explanation"]
            _, listing = request("GET", "/api/guides", "saved-list.json")
            assert listing["guides"][0]["guide_id"] == guide_id
            _, reopened = request("GET", route, "reopened.json")
            assert reopened == terminal
            with closing(
                sqlite3.connect(f"file:{state / 'document_store.db'}?mode=ro", uri=True)
            ) as db:
                rows = db.execute(
                    "SELECT question, latest_attempt_id FROM source_guides WHERE guide_id=?",
                    (guide_id,),
                ).fetchall()
                count = db.execute(
                    "SELECT count(*) FROM source_guide_attempts WHERE guide_id=?",
                    (guide_id,),
                ).fetchone()[0]
            assert rows == [
                (args.question, terminal["latest_attempt"]["attempt_id"])
            ] and count == (2 if args.interrupt_after_submit else 1)
            save(
                evidence,
                "sqlite-proof.json",
                {"guide_id": guide_id, "rows": rows, "attempt_count": count},
            )
            stop(process)
            start()
            doctor(process, args.port, state, evidence, client)
            _, persisted = request("GET", route, "persisted.json")
            assert persisted == terminal, (
                "Restart changed saved content or attempt identity"
            )
            succeeded = True
    finally:
        if process is not None and process.poll() is None:
            stop(process)
        if log is not None:
            log.close()
        for path in (state / ".scratch").glob("pipeline.log*"):
            shutil.copy2(path, evidence / path.name)
        shutil.rmtree(state)
        save(evidence, "actions.json", events)
        save(
            evidence,
            "cleanup.json",
            {
                "passed": succeeded,
                "state_removed": not state.exists(),
                "owned_process_stopped": process is None or process.poll() is not None,
                "shared_services": "Left running",
            },
        )
        artifacts = sorted(path.name for path in evidence.iterdir() if path.is_file())
        assert all((evidence / name).is_file() for name in artifacts)
        save(evidence, "artifacts.json", artifacts)
        print(f"{'PASS' if succeeded else 'FAIL'}: proof retained at {evidence}")


if __name__ == "__main__":
    main()
