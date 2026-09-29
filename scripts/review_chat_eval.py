"""Serve a chat evaluation report for local, case-by-case human review."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


def load_report(path: Path) -> dict[str, Any]:
    report = json.loads(path.read_text())
    if report.get("task") != "chat" or not isinstance(
        report.get("report", {}).get("cases"), list
    ):
        raise ValueError("expected a chat evaluation report with report.cases")
    return report


def load_reviews(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    reviews = json.loads(path.read_text())
    if not isinstance(reviews, dict):
        raise TypeError("review file must contain a JSON object")
    return reviews


def save_reviews(path: Path, reviews: dict[str, Any]) -> None:
    """Replace the review file only after the new JSON is fully written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w") as temporary:
            json.dump(reviews, temporary, ensure_ascii=False, indent=2, sort_keys=True)
            temporary.write("\n")
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def make_handler(
    report: dict[str, Any], reviews_path: Path, page: bytes
) -> type[BaseHTTPRequestHandler]:
    case_names = {case["name"] for case in report["report"]["cases"]}

    class Handler(BaseHTTPRequestHandler):
        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            if self.path == "/":
                self._send(200, page, "text/html; charset=utf-8")
            elif self.path == "/api/report":
                body = json.dumps(report, ensure_ascii=False).encode()
                self._send(200, body, "application/json; charset=utf-8")
            elif self.path == "/api/reviews":
                body = json.dumps(
                    load_reviews(reviews_path), ensure_ascii=False
                ).encode()
                self._send(200, body, "application/json; charset=utf-8")
            else:
                self._send(404, b"Not found", "text/plain; charset=utf-8")

        def do_POST(self) -> None:
            if self.path != "/api/reviews":
                self._send(404, b"Not found", "text/plain; charset=utf-8")
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if size < 1 or size > 1_000_000:
                    raise ValueError("invalid review payload size")
                payload = json.loads(self.rfile.read(size))
                if not isinstance(payload, dict) or set(payload) != {"name", "review"}:
                    raise ValueError("expected name and review")
                name, review = payload["name"], payload["review"]
                if name not in case_names or not isinstance(review, dict):
                    raise ValueError("unknown case or invalid review")
                if set(review) != {"verdict", "note"}:
                    raise ValueError("expected verdict and note")
                if review["verdict"] not in (None, "pass", "fail", "defer"):
                    raise ValueError("invalid verdict")
                if not isinstance(review["note"], str) or len(review["note"]) > 20_000:
                    raise ValueError("invalid note")
                reviews = load_reviews(reviews_path)
                reviews[name] = review
                save_reviews(reviews_path, reviews)
            except (ValueError, TypeError, json.JSONDecodeError) as error:
                self._send(400, str(error).encode(), "text/plain; charset=utf-8")
                return
            self._send(200, b"{}", "application/json; charset=utf-8")

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path, help="chat evaluation report JSON")
    parser.add_argument("--reviews", type=Path, help="review JSON output path")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    report = load_report(args.report)
    reviews_path = args.reviews or args.report.with_suffix(".reviews.json")
    page = Path(__file__).with_name("chat_eval_review.html").read_bytes()
    server = ThreadingHTTPServer(
        ("127.0.0.1", args.port), make_handler(report, reviews_path, page)
    )
    print(
        f"Review {len(report['report']['cases'])} cases at http://127.0.0.1:{server.server_port}/"
    )
    print(f"Reviews save to {reviews_path}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()


if __name__ == "__main__":
    main()
