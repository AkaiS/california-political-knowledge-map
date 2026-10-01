"""Serve a prepared Chat Session discovery workspace using only the stdlib."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit


def read_json(path: Path):
    return json.loads(path.read_text())


def write_json(path: Path, value) -> None:
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(descriptor, "w") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def make_handler(data_dir: Path):
    records = {r["id"]: r for r in read_json(data_dir / "records.json")}
    manifest = read_json(data_dir / "manifest.json")
    lock = threading.RLock()
    html = Path(__file__).with_name("error_discovery_chat.html").read_bytes()

    def validate_anchor(item):
        record = records.get(item.get("record_id"))
        if record is None:
            raise ValueError("Unknown record")
        block = next(
            (b for b in record["blocks"] if b["id"] == item.get("block_id")), None
        )
        if block is None:
            raise ValueError("Unknown content block")
        start, end = item.get("start"), item.get("end")
        if not isinstance(start, int) or not isinstance(end, int):
            raise TypeError("Offsets must be integers")
        # Offsets are browser UTF-16 code units, including surrogate pairs.
        visible = block["anchor_text"].encode("utf-16-le")
        if not 0 <= start < end <= len(visible) // 2:
            raise ValueError("Invalid text range")
        quote = visible[2 * start : 2 * end].decode("utf-16-le")
        if quote != item.get("quote"):
            raise ValueError("Quote does not match the captured content")
        if not isinstance(item.get("note"), str) or not item["note"].strip():
            raise ValueError("Write a note before saving")
        if not isinstance(item.get("id"), str) or len(item["id"]) > 150:
            raise ValueError("Invalid annotation ID")

    class Handler(BaseHTTPRequestHandler):
        def send(self, status, value, content_type="application/json"):
            body = value if isinstance(value, bytes) else json.dumps(value).encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type + "; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def trusted(self):
            host = self.headers.get("Host", "")
            expected = {
                f"127.0.0.1:{self.server.server_port}",
                f"localhost:{self.server.server_port}",
            }
            origin = self.headers.get("Origin")
            return host in expected and (
                origin is None or origin in {"http://" + h for h in expected}
            )

        def do_GET(self):
            if not self.trusted():
                return self.send(403, {"error": "Use this server's loopback address"})
            path = unquote(urlsplit(self.path).path)
            if path == "/":
                return self.send(200, html, "text/html")
            with lock:
                if path == "/api/samples":
                    sample = read_json(data_dir / "samples.json")
                    summaries = [
                        {k: v for k, v in records[i].items() if k != "blocks"}
                        for i in sample["record_ids"]
                    ]
                    return self.send(
                        200, {**sample, "manifest": manifest, "records": summaries}
                    )
                if path in {
                    "/api/annotations",
                    "/api/graph",
                    "/api/patterns",
                    "/api/suggestions",
                }:
                    return self.send(
                        200, read_json(data_dir / (path.rsplit("/", 1)[1] + ".json"))
                    )
                if path.startswith("/api/records/"):
                    record = records.get(path.rsplit("/", 1)[1])
                    return self.send(
                        200 if record else 404, record or {"error": "Unknown record"}
                    )
            self.send(404, {"error": "Not found"})

        def do_POST(self):
            if not self.trusted():
                return self.send(403, {"error": "Cross-origin writes are not accepted"})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 4_000_000:
                    raise ValueError("Invalid request size")
                body = json.loads(self.rfile.read(length))
                path = urlsplit(self.path).path
                with lock:
                    if path == "/api/samples":
                        ids = body.get("record_ids", [])
                        if (
                            not isinstance(ids, list)
                            or not ids
                            or len(set(ids)) != len(ids)
                            or any(i not in records for i in ids)
                        ):
                            raise ValueError(
                                "Samples must contain unique known record IDs"
                            )
                        value = {
                            "record_ids": ids,
                            "selection": body.get(
                                "selection", {"method": "agent update"}
                            ),
                        }
                    elif path == "/api/annotations":
                        value = read_json(data_dir / "annotations.json")
                        if "delete" in body:
                            value = [a for a in value if a["id"] != body["delete"]]
                        else:
                            item = body["annotation"]
                            validate_anchor(item)
                            value = [a for a in value if a["id"] != item["id"]] + [item]
                    elif path == "/api/patterns":
                        value = body
                        annotation_ids = {
                            a["id"] for a in read_json(data_dir / "annotations.json")
                        }
                        if not isinstance(value, list) or any(
                            not isinstance(p.get("name"), str)
                            or any(
                                i not in annotation_ids
                                for i in p.get("annotation_ids", [])
                            )
                            for p in value
                        ):
                            raise ValueError(
                                "Patterns must refer to existing annotations"
                            )
                    elif path == "/api/suggestions":
                        if isinstance(body, list):
                            for item in body:
                                validate_anchor(item)
                                if item.get("status", "pending") not in {
                                    "pending",
                                    "accepted",
                                    "dismissed",
                                }:
                                    raise ValueError("Invalid suggestion state")
                            value = body
                        else:
                            value = read_json(data_dir / "suggestions.json")
                            ids = set(body["ids"])
                            action = body["action"]
                            if action not in {"accept", "dismiss"}:
                                raise ValueError("Unknown suggestion action")
                            annotations = read_json(data_dir / "annotations.json")
                            for item in value:
                                if (
                                    item["id"] in ids
                                    and item.get("status", "pending") == "pending"
                                ):
                                    item["status"] = (
                                        "accepted"
                                        if action == "accept"
                                        else "dismissed"
                                    )
                                    if action == "accept":
                                        promoted = {
                                            **item,
                                            "id": "accepted-" + item["id"],
                                            "author": "agent_accepted",
                                        }
                                        validate_anchor(promoted)
                                        annotations = [
                                            a
                                            for a in annotations
                                            if a["id"] != promoted["id"]
                                        ] + [promoted]
                            write_json(data_dir / "annotations.json", annotations)
                    else:
                        return self.send(404, {"error": "Not found"})
                    write_json(data_dir / (path.rsplit("/", 1)[1] + ".json"), value)
                    self.send(200, value)
            except (ValueError, KeyError, TypeError, UnicodeError) as error:
                self.send(400, {"error": str(error)})

        def log_message(self, *_):
            pass

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    server = ThreadingHTTPServer(
        ("127.0.0.1", args.port), make_handler(args.data_dir.resolve())
    )
    print(f"Error discovery: http://127.0.0.1:{server.server_port}/", flush=True)
    print(f"Annotations: {args.data_dir.resolve() / 'annotations.json'}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
