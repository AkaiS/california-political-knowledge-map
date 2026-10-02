"""Retain the evidence needed to explain bounded retrieval scores."""

from __future__ import annotations

import json
from math import fsum
from typing import Any

from knowledge_map.schemas.fusion import FusionConfig
from knowledge_map.schemas.retrieval import RetrievalBranch

CHUNK_BUDGET = 50
METRIC_VERSION = "unique-chunk-budget-v2"
REPORT_VERSION = 1


def _best_ranks(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    best = {}
    for candidate in candidates:
        chunk = candidate["chunk_id"]
        rank = candidate["ranking"]["rank"]
        if chunk not in best or rank < best[chunk]["rank"]:
            best[chunk] = {
                "chunk_id": chunk,
                "source_article_id": candidate["source_article_id"],
                "rank": rank,
            }
    return sorted(best.values(), key=lambda c: (c["rank"], c["chunk_id"]))


def compact_branches(
    outcomes: list[dict[str, Any]], config: FusionConfig
) -> list[dict[str, Any]]:
    """Keep branch budgets and only the extra ranks that affect fusion."""
    ranked = {o["branch"]: _best_ranks(o.get("candidates", [])) for o in outcomes}
    eligible_by_branch = {
        branch: records[: getattr(config, f"{branch}_candidate_limit")]
        for branch, records in ranked.items()
    }
    eligible = {
        r["chunk_id"] for records in eligible_by_branch.values() for r in records
    }
    compact = []
    for outcome in outcomes:
        branch = outcome["branch"]
        records = ranked[branch]
        kept = records[:CHUNK_BUDGET]
        summary = {k: v for k, v in outcome.items() if k != "candidates"}
        summary.update(
            candidates=kept,
            retrieved_count=len(outcome.get("candidates", [])),
            unique_chunk_count=len(records),
            extra_fusion_ranks=[
                r for r in records[CHUNK_BUDGET:] if r["chunk_id"] in eligible
            ],
        )
        # Nondefault larger production budgets still need their eligibility
        # recorded. This does not enlarge the 50-chunk evaluation budget.
        if getattr(config, f"{branch}_candidate_limit") > CHUNK_BUDGET:
            summary["fusion_eligible_chunk_ids"] = [
                r["chunk_id"] for r in eligible_by_branch[branch]
            ]
        compact.append(summary)
    return compact


def replay_fusion(
    branches: list[dict[str, Any]], config: FusionConfig
) -> list[dict[str, Any]]:
    """Recover production RRF ordering without candidate provenance or text."""
    eligible = set()
    ranks: dict[str, dict[str, int]] = {}
    articles = {}
    for branch in branches:
        name = branch["branch"]
        records = branch["candidates"]
        eligible.update(
            branch.get(
                "fusion_eligible_chunk_ids",
                [
                    r["chunk_id"]
                    for r in records[: getattr(config, f"{name}_candidate_limit")]
                ],
            )
        )
        for r in records + branch["extra_fusion_ranks"]:
            ranks.setdefault(r["chunk_id"], {})[name] = r["rank"]
            articles[r["chunk_id"]] = r["source_article_id"]
    ranked = sorted(
        (
            (
                chunk,
                fsum(
                    getattr(config, f"{branch.value}_weight")
                    / (config.rank_constant + contributions[branch.value])
                    for branch in RetrievalBranch
                    if branch.value in contributions
                ),
            )
            for chunk, contributions in ranks.items()
            if chunk in eligible
        ),
        key=lambda pair: (-pair[1], pair[0]),
    )
    return [
        {
            "chunk_id": chunk,
            "source_article_id": articles[chunk],
            "rank": rank,
            "fusion_score": score,
        }
        for rank, (chunk, score) in enumerate(ranked[: config.fused_candidate_limit], 1)
    ]


def _diagnostics(observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    keep = (
        "branch",
        "stage",
        "status",
        "failure_kind",
        "failure_stage",
        "diagnostic",
        "attempts_consumed",
        "attempt",
        "row_count",
        "candidate_count",
        "exception_type",
    )
    diagnostics = []
    failed = any(
        s.get("attributes", {}).get("status") == "failed" for s in observations
    )
    for span in observations:
        attrs = span.get("attributes", {})
        preceding_counts = (
            failed
            and "stage" in attrs
            and any(k in attrs for k in ("row_count", "candidate_count"))
        )
        if attrs.get("status") != "failed" and not preceding_counts:
            continue
        diagnostic = {k: attrs[k] for k in keep if k in attrs}
        diagnostic["terminal_branch_failure"] = (
            span["name"] == "chat_session.retrieval_branch"
        )
        if diagnostic not in diagnostics:
            diagnostics.append(diagnostic)
    return diagnostics


def _snippet(value: Any) -> str:
    text = value if isinstance(value, str) else json.dumps(value, sort_keys=True)
    return text if len(text) <= 3000 else text[:3000] + " [truncated]"


def _corrections(exchanges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep new correction feedback and its response, never cumulative prompts."""
    corrections = []
    for exchange in exchanges:
        messages = exchange.get("messages", [])
        requests = [m for m in messages if m.get("kind") == "request"]
        response = next(
            (m for m in reversed(messages) if m.get("kind") == "response"), {}
        )
        retries = [
            _snippet(p.get("content"))
            for p in (requests[-1].get("parts", []) if requests else [])
            if p.get("part_kind") == "retry-prompt"
        ]
        record = {
            "component": exchange.get("component"),
            "request_index": exchange.get("request_index"),
            "status": exchange.get("status"),
            "feedback": retries,
            "response": [
                _snippet(p.get("content", p.get("args")))
                for p in response.get("parts", [])
                if p.get("part_kind") in ("text", "tool-call")
            ],
        }
        if exchange.get("exception_type"):
            record["exception_type"] = exchange["exception_type"]
        corrections.append(record)
    # Successful exchanges are useful only when the component needed a
    # correction. Failed exchanges are diagnostic even without a response.
    corrected = {c["component"] for c in corrections if c["feedback"]}
    return [
        c for c in corrections if c["component"] in corrected or c["status"] == "failed"
    ]


def recompute_case_scores(case: dict[str, Any], config: FusionConfig) -> None:
    """Use the same evaluator rules for live reports and historical migration."""
    from .tasks.retrieval import RetrievalExpectation, retrieval_scores

    expected = RetrievalExpectation.model_validate(case["expected_output"])
    output = case["output"]
    grain_key = "chunk_id" if expected.grain == "article_chunk" else "source_article_id"
    sources = output["evidence"].get("sources", []) if output["evidence"] else []
    context_ids = tuple(
        p["chunk_id"]
        if expected.grain == "article_chunk"
        else s["citation"]["source_article_id"]
        for s in sources
        for p in s["passages"]
    )
    for branch in output["branches"]:
        if branch["status"] == "skipped":
            continue
        found = tuple(r[grain_key] for r in branch["candidates"])
        scores = retrieval_scores(
            found, expected, prefix=branch["branch"], ks=(1, 5, 10, 50)
        )
        for k, v in scores.items():
            case["scores"].setdefault(k, {}).update(value=v.value, reason=v.reason)
    fused = replay_fusion(output["branches"], config)
    scores = retrieval_scores(
        tuple(r[grain_key] for r in fused), expected, prefix="fused", ks=(1, 5, 10, 50)
    )
    for k, v in scores.items():
        case["scores"].setdefault(k, {}).update(value=v.value, reason=v.reason)
    k = max(1, len(context_ids))
    scores = retrieval_scores(context_ids, expected, prefix="context", ks=(k,))
    for metric in ("recall", "complete_evidence"):
        score = scores[f"context_{metric}_at_{k}"]
        case["scores"].setdefault(f"context_{metric}", {}).update(
            value=score.value, reason=score.reason
        )


def compact_retrieval_report(
    document: dict[str, Any], *, rescore: bool = False
) -> dict[str, Any]:
    """Project the framework report at its existing serialization boundary."""
    if document.get("retrieval_report", {}).get("version") == REPORT_VERSION:
        return document
    configurations = []
    for case in document["report"]["cases"]:
        output = case["output"]
        settings = dict(output.get("settings", {}))
        observed_at = settings.pop("coverage_observed_at", None)
        if settings not in configurations:
            configurations.append(settings)
        config = FusionConfig.model_validate(settings.get("fusion_settings", {}))
        result = output.get("result")
        if result and "fusion_settings" not in settings:
            raise ValueError("exact fusion replay requires recorded fusion settings")
        branches = (
            compact_branches(result["execution"]["outcomes"], config) if result else []
        )
        evidence = None
        if result:
            evidence = {
                k: v for k, v in result.items() if k not in ("execution", "sources")
            }
            if "sources" in result:
                evidence["sources"] = [
                    {
                        "citation": s["citation"],
                        "passages": [
                            {
                                "chunk_id": p["candidate"]["chunk_id"],
                                "text": p["text"],
                                "provenance": p["provenance"],
                            }
                            for p in s["passages"]
                        ],
                    }
                    for s in result["sources"]
                ]
        observations = case["attributes"].pop("stage_observations", [])
        case["attributes"]["retrieval_diagnostics"] = _diagnostics(observations)
        case["output"] = {
            "configuration_index": configurations.index(settings),
            "coverage_observed_at": observed_at,
            "chat_session_id": output.get("chat_session_id"),
            "failure": output.get("failure"),
            "branches": branches,
            "evidence": evidence,
            "model_corrections": _corrections(output.get("messages", [])),
        }
        if rescore:
            recompute_case_scores(case, config)
    document["retrieval_report"] = {
        "version": REPORT_VERSION,
        "metric_version": METRIC_VERSION,
        "chunk_budget": CHUNK_BUDGET,
        "configurations": configurations,
        "fusion_replay": "exact_from_retained_best_branch_ranks",
    }
    return document
