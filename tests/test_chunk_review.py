"""Chunk samples cover attempted retrievals without leaking reference labels."""

import copy
import hashlib
import importlib.util
import json
import threading
from collections import Counter
from contextlib import contextmanager
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
from test_chat_eval_review import review_server
from test_retrieval import candidate
from test_retrieval_eval_task import expectation
from test_retrieval_report import execution, raw_document

from knowledge_map.evaluation.chunk_review import (
    candidate_pools,
    export_labels,
    project_sample,
    sample_pairs,
    validate_chunk_review,
)
from knowledge_map.evaluation.retrieval_report import compact_retrieval_report
from knowledge_map.schemas.retrieval import RetrievalBranch


def sample_document():
    return {
        "task": "chunk_relevance",
        "ran_at": "2026-10-06",
        "sampling": {"seed": 42},
        "report": {
            "cases": [
                {
                    "name": f"pair-{i}",
                    "inputs": {"question": f"Question {i}?"},
                    "output": {"text": f"Exact chunk {i} <script>danger</script>"},
                    "metadata": {
                        "rank": i + 1,
                        "chunk_id": "same-chunk",
                        "reference": "secret",
                        "question_group": f"query-{i}",
                    },
                }
                for i in range(3)
            ]
        },
    }


def test_top_ten_sampling_includes_unselected_chunks_and_hides_reference_labels():
    ft = RetrievalBranch.FULL_TEXT
    doc = raw_document(
        execution(tuple(candidate(ft, chunk=str(i), rank=i) for i in range(1, 21))),
        expectation(),
    )
    case = doc["report"]["cases"][0]
    case["inputs"] = {"question": "Approved question"}
    compact_retrieval_report(doc)
    pools = candidate_pools(doc, "source-hash")
    assert len(pools[0]) == 10
    assert [c["metadata"]["rank"] for c in pools[0]] == list(range(1, 11))
    assert all(c["output"]["text"] is None for c in pools[0])
    assert "relevant_ids" not in json.dumps(pools)
    assert "fusion_score" not in json.dumps(pools)


def test_startup_failures_record_empty_pools_without_fusion_settings():
    doc = raw_document(
        execution((candidate(RetrievalBranch.FULL_TEXT),)), expectation()
    )
    case = doc["report"]["cases"][0]
    case["inputs"] = {"question": "Approved question"}
    failed = copy.deepcopy(case)
    failed["name"] = "startup-failure"
    failed["output"].update(settings={}, result=None)
    doc["report"]["cases"].append(failed)
    compact_retrieval_report(doc)
    pools = candidate_pools(doc, "source-hash")
    assert len(pools[0]) == 1
    assert pools[1] == []
    assert sample_pairs(pools, size=1, seed=42) == pools[0]


@pytest.mark.parametrize("size,quota", [(100, 4), (200, 8)])
def test_balanced_random_sample_is_deterministic_and_contains_each_question(
    size, quota
):
    pools = [
        [
            {"name": f"{query}-{rank}", "query": query, "rank": rank}
            for rank in range(1, 11)
        ]
        for query in range(25)
    ]
    selected = sample_pairs(pools, size=size, seed=42)
    assert selected == sample_pairs(pools, size=size, seed=42)
    assert selected != sample_pairs(pools, size=size, seed=43)
    assert len({s["name"] for s in selected}) == size
    assert Counter(s["query"] for s in selected) == {q: quota for q in range(25)}
    assert any(s["rank"] == 10 for s in selected)
    assert selected != sorted(selected, key=lambda s: (s["query"], s["rank"]))


def test_short_and_empty_attempts_are_not_silently_replaced_or_overfilled():
    pools = [[], [{"name": "one"}], [{"name": str(i)} for i in range(10)]]
    selected = sample_pairs(pools, size=8, seed=42)
    assert len(selected) == 8 and {"name": "one"} in selected
    for size in (0, 1, 12):
        with pytest.raises(ValueError):
            sample_pairs(pools, size=size, seed=42)
    with pytest.raises(ValueError):
        sample_pairs([[]], size=10, seed=42)


def test_same_chunk_for_different_questions_has_distinct_annotation_identity():
    doc = raw_document(
        execution((candidate(RetrievalBranch.FULL_TEXT),)), expectation()
    )
    doc["report"]["cases"][0]["inputs"] = {"question": "First question"}
    other = copy.deepcopy(doc["report"]["cases"][0])
    other["name"] = "other"
    other["inputs"]["question"] = "Second question"
    doc["report"]["cases"].append(other)
    compact_retrieval_report(doc)
    pools = candidate_pools(doc, "hash")
    assert pools[0][0]["name"] != pools[1][0]["name"]
    assert (
        pools[0][0]["metadata"]["question_group"]
        != pools[1][0]["metadata"]["question_group"]
    )


def test_blind_projection_and_exports_preserve_text_and_exclude_deferred_examples():
    doc = sample_document()
    projected = project_sample(doc)
    assert "secret" not in json.dumps(projected) and "rank" not in json.dumps(projected)
    assert (
        projected["report"]["cases"][0]["output"]["text"]
        == doc["report"]["cases"][0]["output"]["text"]
    )
    rows = export_labels(
        doc,
        {
            "pair-0": {"verdict": "pass", "note": "Useful"},
            "pair-1": {"verdict": "fail", "note": "Wrong subject"},
            "pair-2": {"verdict": "defer", "note": "Uncertain"},
        },
    )
    assert [r["label"] for r in rows] == ["high", "low"]
    assert rows[1]["description"] == "Wrong subject"
    assert rows[1]["metadata"]["question_group"] == "query-1"
    invalid = copy.deepcopy(doc)
    invalid["report"]["cases"][0]["output"]["text"] = None
    with pytest.raises(ValueError):
        project_sample(invalid)


def test_sample_builder_preserves_recorded_text_and_records_graph_hydration(
    monkeypatch, tmp_path
):
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    spec = importlib.util.spec_from_file_location(
        "build_chunk_review_sample", Path("scripts/build_chunk_review_sample.py")
    )
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    pair = sample_document()["report"]["cases"][0]
    pair["metadata"].update(
        chunk_id="a", source_article_id="article", text_origin="report"
    )
    missing = copy.deepcopy(pair)
    missing["name"] = "missing"
    missing["output"]["text"] = None
    missing["metadata"]["chunk_id"] = "b"
    monkeypatch.setattr(builder, "candidate_pools", lambda *_: [[pair, missing]])
    driver = MagicMock()
    driver.__aenter__ = AsyncMock(return_value=driver)
    driver.__aexit__ = AsyncMock()
    monkeypatch.setattr(builder.AsyncGraphDatabase, "driver", lambda *a, **kw: driver)
    store = SimpleNamespace(
        load_chunk=AsyncMock(return_value=SimpleNamespace(text="Loaded exact text"))
    )
    monkeypatch.setattr(builder, "EvidenceStore", lambda *a, **kw: store)
    report = tmp_path / "report.json"
    report.write_text("{}")
    result = asyncio.run(builder.build_sample([report], size=2, seed=42))
    found = {c["name"]: c for c in result["report"]["cases"]}
    assert found["pair-0"]["output"]["text"] == pair["output"]["text"]
    assert found["missing"]["output"]["text"] == "Loaded exact text"
    assert found["missing"]["metadata"]["text_origin"] == "graph"
    assert found["missing"]["metadata"]["text_observed_at"]
    assert (
        found["missing"]["metadata"]["text_sha256"]
        == hashlib.sha256(b"Loaded exact text").hexdigest()
    )
    store.load_chunk.assert_awaited_once_with(chunk_id="b", source_article_id="article")
    with pytest.raises(ValueError, match="twice"):
        asyncio.run(builder.build_sample([report, report], size=2, seed=42))


@contextmanager
def serve(tmp_path):
    samples = tmp_path / "samples"
    samples.mkdir()
    p = samples / "sample.json"
    p.write_text(json.dumps(sample_document()))
    handler = review_server.make_handler(
        tmp_path, b"runs", b"rag", mode="rag", samples_dir=samples
    )
    http = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=http.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{http.server_port}", p
    finally:
        http.shutdown()
        http.server_close()
        thread.join()


def test_chunk_api_roundtrip_and_export_do_not_touch_rag_reviews(tmp_path):
    with serve(tmp_path) as (base, path):
        rag = path.with_suffix(".rag-reviews.json")
        rag.write_text('{"untouched":true}')
        with urlopen(base + "/api/chunks/sample/report") as r:
            doc = json.load(r)
        assert "secret" not in json.dumps(doc)
        for name, verdict in [
            ("pair-0", "pass"),
            ("pair-1", "fail"),
            ("pair-2", "defer"),
        ]:
            payload = {
                "name": name,
                "review": {"verdict": verdict, "note": f"{verdict} reason"},
                "review_identity": doc["review_identity"],
            }
            req = Request(
                base + "/api/chunks/sample/reviews",
                json.dumps(payload).encode(),
                {"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(req) as r:
                assert r.status == 200
        saved = json.loads(path.with_suffix(".chunk-reviews.json").read_text())
        assert saved["pair-2"]["verdict"] == "defer"
        assert rag.read_text() == '{"untouched":true}'
        with urlopen(base + "/api/chunks/sample/export") as r:
            assert r.headers.get_content_type() == "application/x-ndjson"
            assert r.headers["Content-Disposition"].startswith("attachment;")
            assert len(r.read().splitlines()) == 2
        with urlopen(base + "/api/chunks") as r:
            assert len(json.load(r)) == 1
        with urlopen(base + "/chunks/sample") as r:
            assert b"Chunk relevance review" in r.read()
        payload["review_identity"] = "stale"
        with pytest.raises(HTTPError) as e:
            urlopen(
                Request(
                    base + "/api/chunks/sample/reviews",
                    json.dumps(payload).encode(),
                    {"Content-Type": "application/json"},
                    method="POST",
                )
            )
        assert e.value.code == 409
        for route in ("/api/chunks/sample.chunk-reviews/report", "/chunks/..%2Fsample"):
            with pytest.raises(HTTPError) as e:
                urlopen(base + route)
            assert e.value.code == 404


@pytest.mark.parametrize(
    "review",
    [
        {"verdict": "high", "note": ""},
        {"verdict": "pass", "note": 123},
        {"verdict": "defer", "note": "", "other": True},
    ],
)
def test_invalid_chunk_reviews_are_rejected(review):
    with pytest.raises(ValueError):
        validate_chunk_review(review)
