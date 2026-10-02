"""Discovery notes must retain exact anchors and survive server restarts."""

import importlib.util
import json
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

spec = importlib.util.spec_from_file_location(
    "error_discovery_chat",
    Path(__file__).parents[1] / "scripts/error_discovery_chat.py",
)
review = importlib.util.module_from_spec(spec)
spec.loader.exec_module(review)


@pytest.fixture
def workspace(tmp_path):
    record = {
        "id": "case-1",
        "question": "A question",
        "blocks": [
            {"id": "question", "anchor_text": "A 🗳 vote", "text": "A 🗳 vote"},
        ],
    }
    files = {
        "records": [record],
        "manifest": {"report_sha256": "test"},
        "samples": {"record_ids": ["case-1"]},
        "annotations": [],
        "patterns": [],
        "suggestions": [],
        "graph": {"points": []},
    }
    for name, data in files.items():
        review.write_json(tmp_path / (name + ".json"), data)
    return tmp_path


@pytest.fixture
def server(workspace):
    instance = ThreadingHTTPServer(("127.0.0.1", 0), review.make_handler(workspace))
    thread = threading.Thread(target=instance.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{instance.server_port}"
    instance.shutdown()
    instance.server_close()
    thread.join()


def request(server, path, body=None, origin=None):
    headers = {"Content-Type": "application/json"}
    if origin:
        headers["Origin"] = origin
    data = json.dumps(body).encode() if body is not None else None
    with urlopen(Request(server + path, data=data, headers=headers)) as response:
        return json.load(response)


def note(**extra):
    return {
        "id": "note-1",
        "record_id": "case-1",
        "block_id": "question",
        "start": 2,
        "end": 4,
        "quote": "🗳",
        "note": "Observation",
        **extra,
    }


def test_save_edit_delete_persist_exact_browser_offsets(server, workspace):
    annotation = note()
    request(server, "/api/annotations", {"annotation": annotation})
    assert review.read_json(workspace / "annotations.json") == [annotation]
    annotation["note"] = "Revised observation"
    assert request(server, "/api/annotations", {"annotation": annotation}) == [
        annotation
    ]
    assert request(server, "/api/annotations") == [annotation]
    request(server, "/api/annotations", {"delete": annotation["id"]})
    assert review.read_json(workspace / "annotations.json") == []


@pytest.mark.parametrize(
    "annotation",
    [note(quote="wrong"), note(end=900), note(record_id="other"), note(note="")],
)
def test_invalid_anchor_cannot_overwrite_notes(server, workspace, annotation):
    with pytest.raises(HTTPError) as error:
        request(server, "/api/annotations", {"annotation": annotation})
    assert error.value.code == 400
    assert review.read_json(workspace / "annotations.json") == []


def test_suggestion_acceptance_is_idempotent_and_dismissal_adds_no_note(server):
    request(
        server, "/api/suggestions", [note(id="suggestion-1"), note(id="suggestion-2")]
    )
    request(server, "/api/suggestions", {"ids": ["suggestion-1"], "action": "accept"})
    request(server, "/api/suggestions", {"ids": ["suggestion-1"], "action": "accept"})
    request(server, "/api/suggestions", {"ids": ["suggestion-2"], "action": "dismiss"})
    saved = request(server, "/api/annotations")
    assert len(saved) == 1
    assert saved[0]["author"] == "agent_accepted"
    assert [s["status"] for s in request(server, "/api/suggestions")] == [
        "accepted",
        "dismissed",
    ]


def test_samples_and_patterns_only_reference_existing_evidence(server):
    request(server, "/api/samples", {"record_ids": ["case-1"]})
    samples = request(server, "/api/samples")
    assert samples["record_ids"] == ["case-1"]
    assert "blocks" not in samples["records"][0]
    assert request(server, "/api/records/case-1")["blocks"]
    with pytest.raises(HTTPError):
        request(server, "/api/samples", {"record_ids": ["missing"]})
    with pytest.raises(HTTPError):
        request(
            server,
            "/api/patterns",
            [{"name": "Unsupported", "annotation_ids": ["missing"]}],
        )
    request(server, "/api/annotations", {"annotation": note()})
    request(
        server,
        "/api/patterns",
        [{"name": "Observed pattern", "annotation_ids": ["note-1"]}],
    )
    assert request(server, "/api/patterns")[0]["annotation_ids"] == ["note-1"]


def test_cross_origin_write_cannot_change_review(server, workspace):
    with pytest.raises(HTTPError) as error:
        request(
            server,
            "/api/annotations",
            {"annotation": note()},
            origin="http://example.com",
        )
    assert error.value.code == 403
    assert review.read_json(workspace / "annotations.json") == []
