"""Start or reuse this checkout's detached RAG reviewer."""

from __future__ import annotations

import argparse
import asyncio
import fcntl
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

REPOSITORY = Path(__file__).resolve().parents[1]
# Reuse the identity protocol from this checkout's source, even when another
# checkout supplied the editable installation used by uv.
sys.path.insert(0, str(REPOSITORY / "src"))

from knowledge_map.reviewer_identity import reviewer_identity as build_reviewer_identity

URL_PATTERN = re.compile(r"Browse rag evals at http://127\.0\.0\.1:(\d+)/")


def reviewer_identity(reports_dir: Path, samples_dir: Path) -> dict[str, str]:
    return build_reviewer_identity("rag", REPOSITORY, reports_dir, samples_dir)


def matching_server(port: int, identity: dict[str, str], timeout: float = 0.5) -> bool:
    if not 0 < port < 65536 or timeout <= 0:
        return False
    deadline = time.monotonic() + timeout

    async def probe() -> bool:
        # A socket timeout resets with each byte. Cancel the entire request so
        # streaming headers or bodies cannot hold the launch lock indefinitely.
        async with asyncio.timeout(max(0, deadline - time.monotonic())):
            async with (
                httpx.AsyncClient(trust_env=False, timeout=timeout) as client,
                client.stream(
                    "GET",
                    f"http://127.0.0.1:{port}/api/identity",
                    headers={"Accept-Encoding": "identity"},
                ) as response,
            ):
                response.raise_for_status()
                data = bytearray()
                async for chunk in response.aiter_raw():
                    data.extend(chunk[: 8192 - len(data)])
                    if len(data) == 8192:
                        break
                observed = json.loads(data)
            return isinstance(observed, dict) and all(
                observed.get(key) == value for key, value in identity.items()
            )

    try:
        return asyncio.run(probe())
    except (OSError, ValueError, httpx.HTTPError):
        return False


def stop_child(process: subprocess.Popen) -> None:
    # Only the process group created by this launch is ours to stop.
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=2)


def launch(
    reports_dir: Path, samples_dir: Path, timeout: float
) -> tuple[int, Path | None]:
    identity = reviewer_identity(reports_dir, samples_dir)
    key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:16]
    scratch = REPOSITORY / ".scratch/rag-reviewer"
    scratch.mkdir(parents=True, exist_ok=True)
    state_path = scratch / f"{key}.json"
    deadline = time.monotonic() + timeout
    with (scratch / f"{key}.lock").open("a") as lock:
        # Serialize launches for one configuration, including readiness checks.
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise RuntimeError(
                        "Timed out waiting for another RAG reviewer launch."
                    )
                time.sleep(min(0.1, max(0, deadline - time.monotonic())))
        try:
            state = json.loads(state_path.read_text())
        except (OSError, ValueError):
            state = {}
        port = state.get("port") if isinstance(state, dict) else None
        if isinstance(port, int) and matching_server(
            port, identity, min(0.5, deadline - time.monotonic())
        ):
            recorded_log = state.get("log")
            try:
                log_path = Path(recorded_log) if isinstance(recorded_log, str) else None
                if log_path is not None and not log_path.is_file():
                    log_path = None
            except (OSError, ValueError):
                log_path = None
            return port, log_path
        if matching_server(8765, identity, min(0.5, deadline - time.monotonic())):
            return 8765, None
        if time.monotonic() >= deadline:
            raise RuntimeError(
                f"RAG reviewer was not ready within {timeout:g} seconds."
            )

        descriptor, log_name = tempfile.mkstemp(
            prefix=f"{key}-", suffix=".log", dir=scratch
        )
        log_path = Path(log_name)
        # The server binds port zero itself, so no other process can claim a
        # selected port between discovery and binding.
        with os.fdopen(descriptor, "wb") as log:
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    f"RAG reviewer was not ready within {timeout:g} seconds. Log: {log_path}"
                )
            process = subprocess.Popen(
                [
                    "uv",
                    "run",
                    "--no-sync",
                    "python",
                    "-u",
                    str(REPOSITORY / "scripts/review_chat_eval.py"),
                    "--mode",
                    "rag",
                    "--port",
                    "0",
                    "--reports-dir",
                    str(reports_dir.resolve()),
                    "--samples-dir",
                    str(samples_dir.resolve()),
                ],
                cwd=REPOSITORY,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        try:
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError(
                        f"RAG reviewer exited with status {process.returncode}."
                    )
                match = URL_PATTERN.search(log_path.read_text(errors="replace"))
                if match:
                    port = int(match[1])
                    remaining = deadline - time.monotonic()
                    if remaining > 0 and matching_server(
                        port, identity, min(0.5, remaining)
                    ):
                        state_path.write_text(
                            json.dumps({"port": port, "log": str(log_path)})
                        )
                        return port, log_path
                time.sleep(min(0.1, max(0, deadline - time.monotonic())))
            raise RuntimeError(
                f"RAG reviewer was not ready within {timeout:g} seconds."
            )
        except RuntimeError as error:
            stop_child(process)
            raise RuntimeError(f"{error} Log: {log_path}") from error
        except BaseException:
            stop_child(process)
            raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reports-dir", type=Path, default=REPOSITORY / "evals/reports"
    )
    parser.add_argument(
        "--samples-dir", type=Path, default=REPOSITORY / "evals/chunk-samples"
    )
    parser.add_argument(
        "--timeout", type=float, default=30, help="readiness deadline in seconds"
    )
    args = parser.parse_args()
    if not 0 < args.timeout <= 300:
        parser.error("--timeout must be greater than zero and at most 300 seconds")
    try:
        port, log_path = launch(args.reports_dir, args.samples_dir, args.timeout)
    except (OSError, RuntimeError) as error:
        print(error, file=sys.stderr)
        sys.exit(1)
    print(f"Ready: http://127.0.0.1:{port}/")
    print(f"Checkout: {REPOSITORY.resolve()}")
    print(f"Reports: {args.reports_dir.resolve()}")
    print(f"Samples: {args.samples_dir.resolve()}")
    print(
        f"Log: {log_path if log_path is not None else 'unavailable for reused server'}"
    )


if __name__ == "__main__":
    main()
