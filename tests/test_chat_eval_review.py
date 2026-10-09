"""Human case reviews remain attached to the selected report."""

import importlib.util
import json
import os
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
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


@contextmanager
def serve_reviewer(reports_dir):
    handler = review_server.make_handler(reports_dir, b"runs page", b"review page")
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_review_editing_module_is_served_only_at_its_exact_trusted_host_route(tmp_path):
    with serve_reviewer(tmp_path) as base:
        with urlopen(f"{base}/assets/chat_eval_review_editing.mjs") as response:
            assert response.read() == SCRIPT.with_name(
                "chat_eval_review_editing.mjs"
            ).read_bytes()
            assert response.headers.get_content_type() == "text/javascript"
            assert response.headers["Cache-Control"] == "no-store"

        request = Request(
            f"{base}/assets/chat_eval_review_editing.mjs",
            headers={"Host": "untrusted.example"},
        )
        with pytest.raises(HTTPError) as rejected:
            urlopen(request)
        assert rejected.value.code == 403

        for path in (
            "/assets/",
            "/assets/other.mjs",
            "/assets/chat_eval_review_editing.mjs/",
            "/assets/%63hat_eval_review_editing.mjs",
            "/assets/../review_chat_eval.py",
        ):
            with pytest.raises(HTTPError) as missing:
                urlopen(f"{base}{path}")
            assert missing.value.code == 404


def test_reviewer_uses_its_own_checkout_when_an_older_package_is_on_path(tmp_path):
    for package in (
        "knowledge_map",
        "knowledge_map/evaluation",
        "knowledge_map/evaluation/tasks",
    ):
        directory = tmp_path / package
        directory.mkdir(parents=True)
        (directory / "__init__.py").write_text("")
    environment = {**os.environ, "PYTHONPATH": str(tmp_path)}

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env=environment,
        check=False,
    )

    assert result.returncode == 0, result.stderr


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
    with serve_reviewer(tmp_path) as base:
        assert urlopen(f"{base}/").read() == b"runs page"
        assert urlopen(f"{base}/runs/first").read() == b"review page"
        assert json.load(urlopen(f"{base}/api/runs/first/report"))["task"] == "chat"
        payload = json.dumps(
            {
                "name": "case-1",
                "review": {"verdict": "pass", "note": "Supported"},
                "review_identity": review_server.report_for(tmp_path / "first.json")[
                    "review_identity"
                ],
            }
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


def test_reviewer_rejects_cross_origin_and_plain_text_writes(tmp_path):
    (tmp_path / "run.json").write_text(
        json.dumps({"task": "chat", "report": {"cases": [{"name": "case-1"}]}})
    )
    payload = json.dumps(
        {
            "name": "case-1",
            "review": {"verdict": "fail", "note": "Wrong answer"},
            "review_identity": review_server.report_for(tmp_path / "run.json")[
                "review_identity"
            ],
        }
    ).encode()
    with serve_reviewer(tmp_path) as base:
        url = f"{base}/api/runs/run/reviews"
        for headers, expected_status in (
            ({"Content-Type": "text/plain", "Origin": "https://other.example"}, 403),
            (
                {"Content-Type": "application/json", "Origin": "https://other.example"},
                403,
            ),
            ({"Content-Type": "text/plain", "Origin": base}, 415),
            ({"Content-Type": "application/json", "Host": "other.example"}, 403),
        ):
            with pytest.raises(HTTPError) as error:
                urlopen(Request(url, data=payload, headers=headers))
            assert error.value.code == expected_status
            assert not (tmp_path / "run.reviews.json").exists()

        response = urlopen(
            Request(
                url,
                data=payload,
                headers={"Content-Type": "application/json", "Origin": base},
            )
        )
        assert response.status == 200
        assert (
            review_server.load_reviews(tmp_path / "run.reviews.json")["case-1"][
                "verdict"
            ]
            == "fail"
        )


def test_concurrent_review_saves_preserve_different_cases(tmp_path, monkeypatch):
    (tmp_path / "run.json").write_text(
        json.dumps(
            {"task": "chat", "report": {"cases": [{"name": "a"}, {"name": "b"}]}}
        )
    )
    original_load = review_server.load_reviews
    first_read = threading.Event()
    second_read = threading.Event()
    count_lock = threading.Lock()
    read_count = 0

    def delayed_load(path):
        nonlocal read_count
        result = original_load(path)
        with count_lock:
            read_count += 1
            order = read_count
        if order == 1:
            first_read.set()
            second_read.wait(timeout=1)
        elif order == 2:
            second_read.set()
        return result

    monkeypatch.setattr(review_server, "load_reviews", delayed_load)
    with serve_reviewer(tmp_path) as base:

        def post(name):
            payload = json.dumps(
                {
                    "name": name,
                    "review": {"verdict": "pass", "note": name},
                    "review_identity": review_server.report_for(tmp_path / "run.json")[
                        "review_identity"
                    ],
                }
            ).encode()
            return urlopen(
                Request(
                    f"{base}/api/runs/run/reviews",
                    data=payload,
                    headers={"Content-Type": "application/json"},
                )
            ).status

        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(post, "a")
            assert first_read.wait(timeout=3)
            second = executor.submit(post, "b")
            assert first.result(timeout=5) == 200
            assert second.result(timeout=5) == 200

    assert set(original_load(tmp_path / "run.reviews.json")) == {"a", "b"}


def test_markdown_renders_native_content_without_model_html_or_tracking():
    rendered = review_server.render_markdown(
        "**Evidence** [source](https://example.org)\n\n"
        "| Claim | Status |\n| --- | --- |\n| A | Recorded |\n\n"
        '```python\nprint("safe")\n```\n\n'
        "<script>alert(1)</script>\n\n"
        "![tracking](https://example.org/pixel) "
        '<img src="https://example.org/html-pixel"> '
        "[unsafe](javascript:alert(1)) [local](file:///secret)"
    )
    assert "<strong>Evidence</strong>" in rendered
    assert "<table>" in rendered
    assert '<pre class="code-highlight"><code>' in rendered
    assert "<pre><code><div" not in rendered
    assert "<script" not in rendered
    assert "<img" not in rendered
    assert 'href="javascript:' not in rendered
    assert 'href="file:' not in rendered
    assert 'rel="noopener noreferrer"' in rendered


def test_reference_content_selects_source_case_and_rejects_escape(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(review_server, "REPOSITORY", tmp_path)
    artifact = tmp_path / "reference.json"
    artifact.write_text(
        json.dumps(
            {
                "interpretation": "Stored retrieval",
                "cases": [
                    {"id": "source-1", "rows": [1]},
                    {"id": "other", "rows": [2]},
                ],
            }
        )
    )
    case = {
        "name": "case-1",
        "metadata": {
            "source_case_id": "source-1",
            "reference_artifact": "reference.json",
        },
    }
    result = review_server.reference_content(case)
    assert result["content"]["cases"] == [{"id": "source-1", "rows": [1]}]
    assert result["content"]["interpretation"] == "Stored retrieval"
    for reference in ("../outside.md", str(artifact), "secret.env"):
        case["metadata"]["reference_artifact"] = reference
        assert "error" in review_server.reference_content(case)
    outside = tmp_path.parent / "outside.md"
    outside.write_text("private content")
    (tmp_path / "linked.md").symlink_to(outside)
    case["metadata"]["reference_artifact"] = "linked.md"
    assert "error" in review_server.reference_content(case)


def test_presentation_renders_decoded_model_content_and_structural_query():
    report = {
        "report": {
            "cases": [
                {
                    "name": "case-1",
                    "output": {
                        "messages": [
                            {
                                "messages": [
                                    {
                                        "parts": [
                                            {
                                                "content": '{"explanation":"**Relevant**"}'
                                            }
                                        ]
                                    }
                                ]
                            }
                        ]
                    },
                    "attributes": {
                        "stage_observations": [
                            {
                                "attributes": {
                                    "validated_query": "MATCH (a:Article) RETURN a"
                                }
                            }
                        ]
                    },
                }
            ]
        }
    }
    presentation = review_server.presentation_for(report)
    assert "<strong>Relevant</strong>" in presentation["html"]["**Relevant**"]
    assert "code-highlight" in presentation["code"]["MATCH (a:Article) RETURN a"]


def test_review_write_failure_returns_retryable_server_error(tmp_path, monkeypatch):
    (tmp_path / "run.json").write_text(
        json.dumps({"task": "chat", "report": {"cases": [{"name": "case-1"}]}})
    )

    def fail_write(*args):
        raise OSError("Disk unavailable")

    monkeypatch.setattr(review_server, "save_reviews", fail_write)
    with serve_reviewer(tmp_path) as base:
        payload = json.dumps(
            {
                "name": "case-1",
                "review": {"verdict": "pass", "note": ""},
                "review_identity": review_server.report_for(tmp_path / "run.json")[
                    "review_identity"
                ],
            }
        ).encode()
        with pytest.raises(HTTPError) as error:
            urlopen(
                Request(
                    f"{base}/api/runs/run/reviews",
                    data=payload,
                    headers={"Content-Type": "application/json"},
                )
            )
        assert error.value.code == 500


@pytest.mark.parametrize("entry", [None, "invalid", 7, []])
def test_malformed_reference_is_a_display_error(tmp_path, monkeypatch, entry):
    monkeypatch.setattr(review_server, "REPOSITORY", tmp_path)
    (tmp_path / "reference.json").write_text(
        json.dumps({"cases": [entry, {"id": "case-1", "rows": []}]})
    )
    case = {"name": "case-1", "metadata": {"reference_artifact": "reference.json"}}

    presentation = review_server.presentation_for({"report": {"cases": [case]}})

    assert "error" in presentation["references"]["case-1"]


def test_review_identity_distinguishes_report_path_and_contents(tmp_path):
    report = {"task": "chat", "report": {"cases": [{"name": "case-1"}]}}
    first = tmp_path / "first" / "run.json"
    second = tmp_path / "second" / "run.json"
    for path in (first, second):
        path.parent.mkdir()
        path.write_text(json.dumps(report))

    original = review_server.report_for(first)["review_identity"]
    assert review_server.report_for(first)["review_identity"] == original
    assert review_server.report_for(second)["review_identity"] != original
    report["report"]["cases"][0]["inputs"] = {"question": "A different question"}
    first.write_text(json.dumps(report))
    assert review_server.report_for(first)["review_identity"] != original


@pytest.mark.parametrize("identity", ["missing", "stale"])
def test_replaced_report_rejects_unbound_or_stale_review(tmp_path, identity):
    path = tmp_path / "run.json"
    report = {"task": "chat", "report": {"cases": [{"name": "case-1"}]}}
    path.write_text(json.dumps(report))
    original_id = review_server.report_for(path)["review_identity"]
    report["report"]["cases"][0]["inputs"] = {"question": "New question"}
    path.write_text(json.dumps(report))
    reviews_path = path.with_suffix(".reviews.json")
    existing = {"case-1": {"verdict": "pass", "note": "New report review"}}
    review_server.save_reviews(reviews_path, existing)
    payload = {"name": "case-1", "review": {"verdict": "fail", "note": "Old draft"}}
    if identity == "stale":
        payload["review_identity"] = original_id

    with serve_reviewer(tmp_path) as base:
        with pytest.raises(HTTPError) as error:
            urlopen(
                Request(
                    f"{base}/api/runs/run/reviews",
                    data=json.dumps(payload).encode(),
                    headers={"Content-Type": "application/json"},
                )
            )
        assert error.value.code == (409 if identity == "stale" else 400)
    assert review_server.load_reviews(reviews_path) == existing


def test_identity_endpoint_reports_resolved_configuration_and_rejects_untrusted_host(
    tmp_path,
):
    with serve_reviewer(tmp_path) as base:
        with urlopen(f"{base}/api/identity") as response:
            identity = json.load(response)
        assert identity == {
            "service": "ca-map-evaluation-reviewer-v1",
            "mode": "chat",
            "checkout": str(SCRIPT.parents[1].resolve()),
            "reports_dir": str(tmp_path.resolve()),
            "samples_dir": str((SCRIPT.parents[1] / "evals/chunk-samples").resolve()),
            "pid": os.getpid(),
        }
        with pytest.raises(HTTPError) as rejected:
            urlopen(
                Request(f"{base}/api/identity", headers={"Host": "untrusted.example"})
            )
        assert rejected.value.code == 403


def test_rag_startup_and_loading_never_import_evaluation_tasks(tmp_path):
    report = tmp_path / "report.json"
    report.write_text(json.dumps({"task": "retrieval", "report": {"cases": []}}))
    script = f"""
import importlib.abc, runpy, sys
class BlockTasks(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        if fullname.startswith("knowledge_map.evaluation.tasks"):
            raise AssertionError("RAG loaded evaluation tasks: " + fullname)
sys.meta_path.insert(0, BlockTasks())
reviewer = runpy.run_path({str(SCRIPT)!r})
reviewer["load_report"](reviewer["Path"]({str(report)!r}), "rag")
sys.argv = [{str(SCRIPT)!r}, "--mode", "rag", "--help"]
reviewer["main"]()
"""
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
