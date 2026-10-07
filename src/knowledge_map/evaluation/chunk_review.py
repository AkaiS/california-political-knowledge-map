"""Sample query–chunk pairs and keep human relevance labels independent of RAG verdicts."""

from __future__ import annotations

import hashlib
import random
from typing import Any

from knowledge_map.schemas.fusion import FusionConfig

from .retrieval_report import replay_fusion


def candidate_pools(document: dict[str, Any], report_sha256: str) -> list[list[dict]]:
    """Recover the actual fused top ten, including chunks outside selected context."""
    if document.get("task") != "retrieval" or not document.get("retrieval_report"):
        raise ValueError(
            "chunk sampling requires a compact retrieval report with replayable ranks"
        )
    configurations = document["retrieval_report"]["configurations"]
    pools = []
    for case in document["report"]["cases"]:
        output = case["output"]
        config = FusionConfig.model_validate(
            configurations[output["configuration_index"]]["fusion_settings"]
        )
        ranked = replay_fusion(output["branches"], config)[:10]
        evidence = output.get("evidence") or {}
        texts = {
            p["chunk_id"]: p["text"]
            for source in evidence.get("sources", [])
            for p in source["passages"]
        }
        question = case["inputs"]["question"]
        pool = []
        for candidate in ranked:
            chunk_id = candidate["chunk_id"]
            identity = "\0".join((report_sha256, case["name"], chunk_id))
            text = texts.get(chunk_id)
            pool.append(
                {
                    "name": hashlib.sha256(identity.encode()).hexdigest(),
                    "inputs": {"question": question},
                    "output": {"text": text},
                    "metadata": {
                        "report_sha256": report_sha256,
                        "case_id": case["name"],
                        "chunk_id": chunk_id,
                        "source_article_id": candidate["source_article_id"],
                        "rank": candidate["rank"],
                        "text_origin": "report" if text is not None else None,
                        "text_observed_at": document.get("ran_at")
                        if text is not None
                        else None,
                        "question_group": hashlib.sha256(question.encode()).hexdigest(),
                    },
                }
            )
        pools.append(pool)
    return pools


def sample_pairs(pools: list[list[dict]], *, size: int, seed: int) -> list[dict]:
    """Allocate evenly across attempts, then sample uniformly within each top ten."""
    populated = [pool for pool in pools if pool]
    if not populated:
        raise ValueError("no top-ten candidates are available")
    if not len(populated) <= size <= sum(map(len, populated)):
        raise ValueError(
            "sample size must cover every nonempty attempt and fit the candidate population"
        )
    rng = random.Random(seed)
    order = list(range(len(populated)))
    rng.shuffle(order)
    quotas = [0] * len(populated)
    remaining = size
    while remaining:
        for i in order:
            if remaining and quotas[i] < len(populated[i]):
                quotas[i] += 1
                remaining -= 1
    selected = [
        item
        for pool, quota in zip(populated, quotas, strict=True)
        for item in rng.sample(pool, quota)
    ]
    rng.shuffle(selected)
    return selected


def project_sample(document: dict[str, Any]) -> dict[str, Any]:
    """Hide ranks, provenance and existing relevance references during labeling."""
    cases = document["report"]["cases"]
    names = [c["name"] for c in cases]
    if document.get("task") != "chunk_relevance" or len(names) != len(set(names)):
        raise ValueError("expected a chunk sample with distinct pair IDs")
    if any(
        not isinstance(c["inputs"]["question"], str)
        or not c["inputs"]["question"].strip()
        or not isinstance(c["output"]["text"], str)
        or not c["output"]["text"].strip()
        for c in cases
    ):
        raise ValueError("every sample item needs its question and full chunk text")
    return {
        "task": "chunk_relevance",
        "review_kind": "chunks",
        "ran_at": document.get("ran_at"),
        "review_identity": document.get("review_identity"),
        "report": {
            "cases": [
                {
                    "name": c["name"],
                    "inputs": {"question": c["inputs"]["question"]},
                    "output": {"text": c["output"]["text"]},
                }
                for c in cases
            ]
        },
    }


def validate_chunk_review(review: dict[str, Any]) -> None:
    if set(review) != {"verdict", "note"} or review["verdict"] not in (
        None,
        "pass",
        "fail",
        "defer",
    ):
        raise ValueError("expected High, Low, Defer or an unmarked chunk")
    if not isinstance(review["note"], str) or len(review["note"]) > 20_000:
        raise ValueError("invalid chunk description")


def export_labels(document: dict[str, Any], reviews: dict[str, Any]) -> list[dict]:
    """Export resolved human labels with question groups for leakage-safe splits."""
    examples = []
    for case in document["report"]["cases"]:
        review = reviews.get(case["name"], {"verdict": None, "note": ""})
        validate_chunk_review(review)
        if review["verdict"] not in ("pass", "fail"):
            continue
        examples.append(
            {
                "id": case["name"],
                "question": case["inputs"]["question"],
                "chunk": case["output"]["text"],
                "label": "high" if review["verdict"] == "pass" else "low",
                "description": review["note"],
                "metadata": case["metadata"],
            }
        )
    return examples
