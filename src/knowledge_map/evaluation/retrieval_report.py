"""Retain the evidence needed to explain bounded retrieval scores."""

from __future__ import annotations

import json
from typing import Any

from knowledge_map.core.fusion import _prepare_ranking, _rank_candidates
from knowledge_map.schemas.fusion import FusionConfig
from knowledge_map.schemas.retrieval import RetrievalBranch

CHUNK_BUDGET = 50
METRIC_VERSION = "unique-chunk-budget-v2"
REPORT_VERSION = 1


def compact_branches(
    outcomes: list[dict[str, Any]], config: FusionConfig
) -> list[dict[str, Any]]:
    """Keep branch budgets and only the extra ranks that affect fusion."""
    ranks_by_branch = {
        RetrievalBranch(outcome["branch"]): [
            (candidate["chunk_id"], candidate["ranking"]["rank"])
            for candidate in outcome.get("candidates", [])
        ]
        for outcome in outcomes
    }
    best_ranks, eligible_by_branch = _prepare_ranking(ranks_by_branch, config=config)
    eligible = {chunk for chunks in eligible_by_branch.values() for chunk in chunks}
    compact = []
    for outcome in outcomes:
        branch = RetrievalBranch(outcome["branch"])
        articles = {}
        for candidate in outcome.get("candidates", []):
            articles.setdefault(
                (candidate["chunk_id"], candidate["ranking"]["rank"]),
                candidate["source_article_id"],
            )
        records = [
            {
                "chunk_id": chunk,
                "source_article_id": articles[chunk, rank],
                "rank": rank,
            }
            for chunk, rank in best_ranks[branch].items()
        ]
        kept = records[:CHUNK_BUDGET]
        summary = {
            k: outcome[k] for k in ("branch", "status", "reason") if k in outcome
        }
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
        if getattr(config, f"{branch.value}_candidate_limit") > CHUNK_BUDGET:
            summary["fusion_eligible_chunk_ids"] = eligible_by_branch[branch]
        compact.append(summary)
    return compact


def selected_semantic_results(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    """Keep the graph facts supplied with the selected passages to generation."""
    retained_ids = {
        passage.get("chunk_id") or (passage.get("candidate") or {}).get("chunk_id")
        for source in evidence.get("sources", [])
        for passage in source.get("passages", [])
    }
    branches = evidence.get("semantic_context")
    if branches is None:
        branches = (evidence.get("execution") or {}).get("outcomes", [])
    context = []
    for branch in branches:
        if branch.get("status", "succeeded") != "succeeded":
            continue
        rows = [
            row
            for row in branch.get("semantic_results", [])
            if row.get("evidence_chunk_ids")
            and set(row["evidence_chunk_ids"]) <= retained_ids
        ]
        if rows:
            context.append({"branch": branch["branch"], "semantic_results": rows})
    return context


def replay_fusion(
    branches: list[dict[str, Any]], config: FusionConfig
) -> list[dict[str, Any]]:
    """Recover production RRF ordering without candidate provenance or text."""
    ranks_by_branch = {}
    nomination_pools = {}
    recorded_eligibility = {}
    articles = {}
    for branch in branches:
        name = RetrievalBranch(branch["branch"])
        records = branch["candidates"]
        nomination_pools[name] = {r["chunk_id"] for r in records}
        if "fusion_eligible_chunk_ids" in branch:
            recorded_eligibility[name] = branch["fusion_eligible_chunk_ids"]
        ranks_by_branch[name] = [
            (r["chunk_id"], r["rank"]) for r in records + branch["extra_fusion_ranks"]
        ]
        for r in records + branch["extra_fusion_ranks"]:
            articles[r["chunk_id"]] = r["source_article_id"]
    best_ranks, eligible_by_branch = _prepare_ranking(
        ranks_by_branch,
        config=config,
        nomination_pools=nomination_pools,
        recorded_eligibility=recorded_eligibility,
    )
    ranked = _rank_candidates(best_ranks, eligible_by_branch, config=config)
    return [
        {
            "chunk_id": chunk,
            "source_article_id": articles[chunk],
            "rank": rank,
            "fusion_score": score,
        }
        for rank, (chunk, score) in enumerate(ranked, 1)
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


def compact_retrieval_report(document: dict[str, Any]) -> dict[str, Any]:
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
            evidence["semantic_context"] = selected_semantic_results(result)
        observations = case["attributes"].pop("stage_observations", [])
        case["attributes"]["retrieval_diagnostics"] = _diagnostics(observations)
        case["output"] = {
            "configuration_index": configurations.index(settings),
            "coverage_observed_at": observed_at,
            "chat_session_id": output.get("chat_session_id"),
            "failure": output.get("failure"),
            "branches": branches,
            "evidence": evidence,
            # Selected passages live in evidence once. The answer retains only
            # generated guidance, alongside the exact production presentation.
            "answer": {k: v for k, v in output["answer"].items() if k != "evidence"}
            if output.get("answer") is not None
            else None,
            "rendered_text": output.get("rendered_text"),
            "model_corrections": _corrections(output.get("messages", [])),
        }
    document["retrieval_report"] = {
        "version": REPORT_VERSION,
        "metric_version": METRIC_VERSION,
        "chunk_budget": CHUNK_BUDGET,
        "configurations": configurations,
        "fusion_replay": "exact_from_retained_best_branch_ranks",
    }
    return document
