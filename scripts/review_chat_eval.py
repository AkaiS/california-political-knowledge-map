"""Browse chat evaluation runs and review their cases locally."""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import sys
import tempfile
import threading
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

import yaml
from markdown_it import MarkdownIt
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import TextLexer, get_lexer_by_name
from pygments.util import ClassNotFound

# A script launched with another checkout's editable install must still use the
# report model shipped beside this reviewer.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from knowledge_map.evaluation.tasks.chat import compact_retrieval_for_report

REPOSITORY = Path(__file__).resolve().parents[1]


def render_markdown(text: str) -> str:
    """Render captured text without model HTML, images, or unsafe links."""
    formatter = HtmlFormatter(nowrap=True)

    def code(source: str, language: str, _attributes: str) -> str:
        try:
            lexer = get_lexer_by_name(language)
        except ClassNotFound:
            lexer = TextLexer()
        return (
            '<pre class="code-highlight"><code>'
            + highlight(source, lexer, formatter)
            + "</code></pre>"
        )

    parser = MarkdownIt("commonmark", {"html": True, "highlight": code}).enable("table")
    parser.renderer.rules["html_inline"] = lambda *_: ""
    parser.renderer.rules["html_block"] = lambda *_: ""
    parser.renderer.rules["image"] = lambda *_: ""

    def link(tokens, index, options, env):
        token = tokens[index]
        try:
            scheme = urlsplit(token.attrGet("href") or "").scheme
        except ValueError:
            scheme = ""
        if scheme not in ("http", "https"):
            token.attrs.pop("href", None)
        else:
            token.attrSet("target", "_blank")
            token.attrSet("rel", "noopener noreferrer")
        return parser.renderer.renderToken(tokens, index, options, env)

    parser.renderer.rules["link_open"] = link
    return parser.render(text)


def reference_content(case: dict[str, Any]) -> dict[str, Any] | None:
    reference = case.get("metadata", {}).get("reference_artifact")
    if not isinstance(reference, str) or not reference:
        return None
    path = (REPOSITORY / reference).resolve()
    if (
        Path(reference).is_absolute()
        or not path.is_relative_to(REPOSITORY)
        or path.suffix.lower() not in (".json", ".md", ".txt", ".csv", ".yaml", ".yml")
    ):
        return {
            "path": reference,
            "error": "Reference must be a repository-relative text artifact.",
        }
    try:
        if path.stat().st_size > 1_000_000:
            raise ValueError("Reference exceeds the 1 MB display limit.")
        text = path.read_text()
        content: Any = text
        if path.suffix.lower() == ".json":
            content = json.loads(text)
            if isinstance(content, dict) and isinstance(content.get("cases"), list):
                source_id = (
                    case.get("metadata", {}).get("source_case_id") or case["name"]
                )
                matches = [
                    item for item in content["cases"] if item.get("id") == source_id
                ]
                if not matches:
                    return {
                        "path": reference,
                        "error": f"No reference entry for {source_id}.",
                    }
                content = {
                    **{k: v for k, v in content.items() if k != "cases"},
                    "cases": matches,
                }
        elif path.suffix.lower() == ".csv":
            content = list(csv.DictReader(io.StringIO(text)))
        elif path.suffix.lower() in (".yaml", ".yml"):
            content = json.loads(json.dumps(yaml.safe_load(text), default=str))
        return {"path": reference, "content": content}
    except (OSError, UnicodeError, ValueError, TypeError, yaml.YAMLError) as error:
        return {"path": reference, "error": str(error)}


def presentation_for(report: dict[str, Any]) -> dict[str, Any]:
    rendered: dict[str, str] = {}
    code = {}

    def collect(value: Any, depth: int = 0) -> None:
        if depth > 30:
            return
        if isinstance(value, str):
            if value not in rendered:
                rendered[value] = render_markdown(value)
                try:
                    decoded = json.loads(value)
                except (ValueError, TypeError):
                    return
                if isinstance(decoded, (dict, list)):
                    collect(decoded, depth + 1)
        elif isinstance(value, dict):
            for child in value.values():
                collect(child, depth + 1)
        elif isinstance(value, list):
            for child in value:
                collect(child, depth + 1)

    references = {}
    for case in report["report"]["cases"]:
        output = case.get("output") or {}
        collect(output.get("rendered_text"))
        collect(output.get("messages", []))
        collect(case.get("attributes", {}))
        for stage in case.get("attributes", {}).get("stage_observations", []):
            query = stage.get("attributes", {}).get("validated_query")
            if isinstance(query, str):
                code[query] = render_markdown("```cypher\n" + query + "\n```")
        collect(case.get("metadata", {}))
        collect(case.get("expected_output"))
        reference = reference_content(case)
        if reference:
            references[case["name"]] = reference
            collect(reference.get("content"))
    return {
        "html": rendered,
        "references": references,
        "code": code,
        "code_css": HtmlFormatter().get_style_defs(".code-highlight"),
    }


def load_report(path: Path) -> dict[str, Any]:
    report = json.loads(path.read_text())
    if report.get("task") != "chat" or not isinstance(
        report.get("report", {}).get("cases"), list
    ):
        raise ValueError("expected a chat evaluation report with report.cases")
    for case in report["report"]["cases"]:
        output = case.get("output")
        if not isinstance(output, dict):
            continue
        for key in ("answer", "retrieval"):
            if isinstance(output.get(key), dict):
                compact_retrieval_for_report(output[key])
    return report


@lru_cache(maxsize=8)
def _cached_report(path: Path, mtime_ns: int, size: int) -> dict[str, Any]:
    return load_report(path)


def report_for(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return _cached_report(path, stat.st_mtime_ns, stat.st_size)


def run_path(reports_dir: Path, run_id: str) -> Path | None:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", run_id):
        return None
    path = reports_dir / f"{run_id}.json"
    return path if path.is_file() and not path.name.endswith(".reviews.json") else None


def list_runs(reports_dir: Path) -> list[dict[str, Any]]:
    runs = []
    for path in reports_dir.glob("*.json"):
        if path.name.endswith(".reviews.json"):
            continue
        report = report_for(path)
        cases = report["report"]["cases"]
        case_names = {case["name"] for case in cases}
        reviews = load_reviews(path.with_suffix(".reviews.json"))
        verdicts = [
            review.get("verdict")
            for name, review in reviews.items()
            if name in case_names and isinstance(review, dict)
        ]
        runs.append(
            {
                "id": path.stem,
                "ran_at": report.get("ran_at"),
                "model": report.get("deployment", {}).get("model")
                or report.get("model"),
                "deployment": report.get("deployment", {}).get("kind"),
                "split": report.get("split"),
                "case_count": len(cases),
                "reviewed_count": sum(v in ("pass", "fail", "defer") for v in verdicts),
                "pass_count": verdicts.count("pass"),
                "fail_count": verdicts.count("fail"),
                "defer_count": verdicts.count("defer"),
            }
        )
    return sorted(runs, key=lambda run: run["ran_at"] or "", reverse=True)


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
    reports_dir: Path, runs_page: bytes, reviewer_page: bytes
) -> type[BaseHTTPRequestHandler]:
    reviews_lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _trusted_host(self) -> bool:
            if self.headers.get("Host") == f"127.0.0.1:{self.server.server_port}":
                return True
            self._send(403, b"Invalid host", "text/plain; charset=utf-8")
            return False

        def do_GET(self) -> None:
            if not self._trusted_host():
                return
            path = urlsplit(self.path).path
            if path == "/":
                self._send(200, runs_page, "text/html; charset=utf-8")
            elif path == "/api/runs":
                body = json.dumps(list_runs(reports_dir), ensure_ascii=False).encode()
                self._send(200, body, "application/json; charset=utf-8")
            else:
                parts = [unquote(part) for part in path.strip("/").split("/")]
                if not (
                    (len(parts) == 2 and parts[0] == "runs")
                    or (len(parts) == 4 and parts[:2] == ["api", "runs"])
                ):
                    self._send(404, b"Not found", "text/plain; charset=utf-8")
                    return
                run_id = parts[-1] if len(parts) == 2 else parts[2]
                report_path = run_path(reports_dir, run_id)
                if report_path is None:
                    self._send(404, b"Not found", "text/plain; charset=utf-8")
                elif len(parts) == 2:
                    self._send(200, reviewer_page, "text/html; charset=utf-8")
                elif parts[3] == "report":
                    body = json.dumps(
                        report_for(report_path), ensure_ascii=False
                    ).encode()
                    self._send(200, body, "application/json; charset=utf-8")
                elif parts[3] == "reviews":
                    body = json.dumps(
                        load_reviews(report_path.with_suffix(".reviews.json")),
                        ensure_ascii=False,
                    ).encode()
                    self._send(200, body, "application/json; charset=utf-8")
                elif parts[3] == "presentation":
                    body = json.dumps(
                        presentation_for(report_for(report_path)), ensure_ascii=False
                    ).encode()
                    self._send(200, body, "application/json; charset=utf-8")
                else:
                    self._send(404, b"Not found", "text/plain; charset=utf-8")

        def do_POST(self) -> None:
            if not self._trusted_host():
                return
            origin = self.headers.get("Origin")
            if origin and origin != f"http://127.0.0.1:{self.server.server_port}":
                self._send(403, b"Invalid origin", "text/plain; charset=utf-8")
                return
            content_type = (
                self.headers.get("Content-Type", "").partition(";")[0].strip().lower()
            )
            if content_type != "application/json":
                self._send(
                    415, b"Expected application/json", "text/plain; charset=utf-8"
                )
                return
            parts = [
                unquote(part) for part in urlsplit(self.path).path.strip("/").split("/")
            ]
            if len(parts) != 4 or parts[:2] != ["api", "runs"] or parts[3] != "reviews":
                self._send(404, b"Not found", "text/plain; charset=utf-8")
                return
            report_path = run_path(reports_dir, parts[2])
            if report_path is None:
                self._send(404, b"Not found", "text/plain; charset=utf-8")
                return
            reviews_path = report_path.with_suffix(".reviews.json")
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if size < 1 or size > 1_000_000:
                    raise ValueError("invalid review payload size")
                payload = json.loads(self.rfile.read(size))
                if not isinstance(payload, dict) or set(payload) != {"name", "review"}:
                    raise ValueError("expected name and review")
                name, review = payload["name"], payload["review"]
                case_names = {
                    case["name"] for case in report_for(report_path)["report"]["cases"]
                }
                if name not in case_names or not isinstance(review, dict):
                    raise ValueError("unknown case or invalid review")
                if set(review) != {"verdict", "note"}:
                    raise ValueError("expected verdict and note")
                if review["verdict"] not in (None, "pass", "fail", "defer"):
                    raise ValueError("invalid verdict")
                if not isinstance(review["note"], str) or len(review["note"]) > 20_000:
                    raise ValueError("invalid note")
                with reviews_lock:
                    reviews = load_reviews(reviews_path)
                    reviews[name] = review
                    save_reviews(reviews_path, reviews)
            except (ValueError, TypeError, json.JSONDecodeError) as error:
                self._send(400, str(error).encode(), "text/plain; charset=utf-8")
                return
            except OSError:
                self._send(
                    500, b"Could not write review file", "text/plain; charset=utf-8"
                )
                return
            self._send(200, b"{}", "application/json; charset=utf-8")

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reports-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "evals/reports/chat",
        help="directory containing chat evaluation reports",
    )
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    args.reports_dir.mkdir(parents=True, exist_ok=True)
    runs_page = Path(__file__).with_name("chat_eval_runs.html").read_bytes()
    reviewer_page = Path(__file__).with_name("chat_eval_review.html").read_bytes()
    server = ThreadingHTTPServer(
        ("127.0.0.1", args.port),
        make_handler(args.reports_dir, runs_page, reviewer_page),
    )
    print(f"Browse chat evals at http://127.0.0.1:{server.server_port}/")
    print(f"Reports: {args.reports_dir}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()


if __name__ == "__main__":
    main()
