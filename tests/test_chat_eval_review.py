"""Human case reviews remain attached to the selected report."""

import importlib.util
import json
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "review_chat_eval.py"
SPEC = importlib.util.spec_from_file_location("review_chat_eval", SCRIPT)
assert SPEC and SPEC.loader
review_server = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(review_server)


def test_review_file_preserves_case_verdict_and_note(tmp_path):
    path = tmp_path / "reviews.json"
    reviews = {
        "case-1": {
            "verdict": "fail",
            "note": "Citation does not support the claim.",
        }
    }

    review_server.save_reviews(path, reviews)

    assert review_server.load_reviews(path) == reviews
    assert json.loads(path.read_text()) == reviews
    assert not list(tmp_path.glob(".reviews.json.*"))


def test_reviewer_rejects_non_chat_report(tmp_path):
    path = tmp_path / "report.json"
    path.write_text(json.dumps({"task": "extraction", "report": {"cases": []}}))

    with pytest.raises(ValueError, match="chat evaluation report"):
        review_server.load_report(path)


def test_reviewer_compacts_legacy_report_without_changing_it(tmp_path):
    path = tmp_path / "report.json"
    report = {
        "task": "chat",
        "report": {
            "cases": [
                {
                    "name": "case-1",
                    "output": {
                        "answer": {
                            "evidence": {
                                "execution": {
                                    "outcomes": [
                                        {
                                            "branch": "full_text",
                                            "status": "succeeded",
                                            "candidates": [
                                                {
                                                    "chunk_id": f"ft-{rank}",
                                                    "ranking": {
                                                        "rank": rank,
                                                        "score": float(rank),
                                                    },
                                                }
                                                for rank in (1, 2, 3)
                                            ],
                                        },
                                        {
                                            "branch": "dense",
                                            "status": "succeeded",
                                            "candidates": [{"chunk_id": "dense-1"}],
                                        },
                                    ]
                                }
                            }
                        }
                    },
                }
            ]
        },
    }
    path.write_text(json.dumps(report))

    loaded = review_server.load_report(path)
    full_text = loaded["report"]["cases"][0]["output"]["answer"]["evidence"][
        "execution"
    ]["outcomes"][0]

    assert len(full_text["candidates"]) == 1
    assert full_text["candidate_summary"]["total_retrieved"] == 3
    assert (
        len(
            json.loads(path.read_text())["report"]["cases"][0]["output"]["answer"][
                "evidence"
            ]["execution"]["outcomes"][0]["candidates"]
        )
        == 3
    )


def test_run_list_tracks_saved_verdicts_and_new_reports(tmp_path):
    first = tmp_path / "first.json"
    first.write_text(
        json.dumps(
            {
                "task": "chat",
                "ran_at": "2026-09-28T00:00:00+00:00",
                "model": "model-a",
                "report": {"cases": [{"name": "a"}, {"name": "b"}]},
            }
        )
    )
    review_server.save_reviews(
        first.with_suffix(".reviews.json"),
        {
            "a": {"verdict": "fail", "note": "Wrong citation"},
            "b": {"verdict": None, "note": "Still reading"},
            "stale": {"verdict": "pass", "note": "Different run"},
        },
    )

    runs = review_server.list_runs(tmp_path)
    assert runs[0]["id"] == "first"
    assert runs[0]["case_count"] == 2
    assert runs[0]["reviewed_count"] == 1
    assert (runs[0]["pass_count"], runs[0]["fail_count"], runs[0]["defer_count"]) == (
        0,
        1,
        0,
    )

    second = tmp_path / "second.json"
    second.write_text(
        json.dumps(
            {
                "task": "chat",
                "ran_at": "2026-09-29T00:00:00+00:00",
                "model": "model-b",
                "report": {"cases": [{"name": "c"}]},
            }
        )
    )
    assert [run["id"] for run in review_server.list_runs(tmp_path)] == [
        "second",
        "first",
    ]


def test_run_routes_keep_reviews_with_their_report(tmp_path):
    for run_id in ("first", "second"):
        (tmp_path / f"{run_id}.json").write_text(
            json.dumps({"task": "chat", "report": {"cases": [{"name": "case-1"}]}})
        )
    handler = review_server.make_handler(tmp_path, b"runs page", b"review page")
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        assert urlopen(f"{base}/").read() == b"runs page"
        assert urlopen(f"{base}/runs/first").read() == b"review page"
        assert json.load(urlopen(f"{base}/api/runs/first/report"))["task"] == "chat"
        payload = json.dumps(
            {"name": "case-1", "review": {"verdict": "pass", "note": "Supported"}}
        ).encode()
        response = urlopen(
            Request(
                f"{base}/api/runs/first/reviews",
                data=payload,
                headers={"Content-Type": "application/json"},
            )
        )
        assert response.status == 200
        assert (
            json.load(urlopen(f"{base}/api/runs/first/reviews"))["case-1"]["verdict"]
            == "pass"
        )
        assert json.load(urlopen(f"{base}/api/runs/second/reviews")) == {}
        runs = json.load(urlopen(f"{base}/api/runs"))
        assert next(run for run in runs if run["id"] == "first")["reviewed_count"] == 1
        with pytest.raises(HTTPError) as error:
            urlopen(f"{base}/api/runs/%2e%2e/report")
        assert error.value.code == 404
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
