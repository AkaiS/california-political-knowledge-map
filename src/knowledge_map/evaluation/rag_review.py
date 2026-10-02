"""Present selected context and generation for scoped human RAG judgments."""

from __future__ import annotations

from statistics import mean
from typing import Any

from knowledge_map.schemas.fusion import FusionConfig

from .retrieval_report import replay_fusion

AXES = ("context_relevance", "answer_relevance", "faithfulness")
VERDICTS = (None, "pass", "fail", "defer")
CUTOFFS = (1, 5, 10, 50)
METRICS = {
    "recall": "Recall@k",
    "precision": "Precision@k",
    "reciprocal_rank": "MRR within 50 chunks",
    "ndcg": "NDCG@k",
    "two_hop_recall": "Two-hop Recall@k",
}
DEFINITIONS = {
    "recall": "Reference identities recovered within the first k unique chunks. Article coverage is measured after applying the chunk budget.",
    "precision": "Relevant results divided by k. Requires complete relevance judgments; unlisted silver witnesses cannot be assumed irrelevant.",
    "reciprocal_rank": "Mean reciprocal rank of the first reference-relevant result within 50 unique chunks. A case shows reciprocal rank, not a mean.",
    "ndcg": "Discounted graded relevance normalized by the ideal ranking. Requires graded relevance judgments.",
    "two_hop_recall": "Fraction of two-hop reference answers with a witness for each of their two evidence groups within k chunks. Alternatives within a group are interchangeable.",
}


def required_axes(case: dict[str, Any]) -> tuple[str, ...]:
    output = case["output"]
    axes = []
    if output["has_context"]:
        axes.append("context_relevance")
    if output["has_generation"]:
        axes.append("answer_relevance")
        if output["has_context"]:
            axes.append("faithfulness")
    return tuple(axes)


def validate_review(review: dict[str, Any], case: dict[str, Any]) -> None:
    fields = set(AXES) | {f"{axis}_note" for axis in AXES}
    if set(review) != fields:
        raise ValueError("expected the three RAG judgments and their supporting notes")
    applicable = required_axes(case)
    for axis in AXES:
        if review[axis] not in VERDICTS:
            raise ValueError("invalid RAG judgment")
        if axis not in applicable and review[axis] is not None:
            raise ValueError(f"{axis} cannot be judged from this case")
        note = review[f"{axis}_note"]
        if not isinstance(note, str) or len(note) > 20_000:
            raise ValueError("invalid judgment evidence")


def review_complete(review: dict[str, Any], case: dict[str, Any]) -> bool:
    axes = required_axes(case)
    return bool(axes) and all(review.get(axis) in VERDICTS[1:] for axis in axes)


def _evidence(output: dict[str, Any]) -> dict[str, Any]:
    # Reports from both tasks describe the package from that exact execution.
    # Do not splice a different retrieval run into a generated answer's context.
    answer = output.get("answer") or {}
    retrieval = (
        output.get("evidence") or output.get("retrieval") or output.get("result") or {}
    )
    return answer.get("evidence") or retrieval.get("evidence") or retrieval


def _sources(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "citation": source["citation"],
            "passages": [
                {
                    "chunk_id": passage.get("chunk_id")
                    or (passage.get("candidate") or {}).get("chunk_id"),
                    "text": passage["text"],
                }
                for passage in source.get("passages", [])
            ],
        }
        for source in evidence.get("sources", [])
    ]


def _metric_rows(
    case: dict[str, Any], output: dict[str, Any], configurations: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    scores = case.get("scores") or {}
    expected = case.get("expected_output") or {}
    branches = output.get("branches") or []
    answers = expected.get("answers") or []
    two_hop = bool(answers) and all(len(answer["groups"]) == 2 for answer in answers)
    fused = []
    if two_hop and branches:
        settings = configurations[output["configuration_index"]]
        fused = replay_fusion(
            branches, FusionConfig.model_validate(settings["fusion_settings"])
        )
    rows = []
    for branch in ("full_text", "dense", "structural", "fused"):
        if branch == "structural" and not any(
            key.startswith("structural_") for key in scores
        ):
            continue
        for metric, label in METRICS.items():
            for k in (None,) if metric == "reciprocal_rank" else CUTOFFS:
                name = f"{branch}_{metric}" + (f"_at_{k}" if k is not None else "")
                score = scores.get(name)
                value = score.get("value") if isinstance(score, dict) else None
                reason = score.get("reason") if isinstance(score, dict) else None
                if metric == "two_hop_recall" and two_hop and branches:
                    records = (
                        fused
                        if branch == "fused"
                        else next(
                            (
                                b["candidates"]
                                for b in branches
                                if b["branch"] == branch
                            ),
                            [],
                        )
                    )
                    key = (
                        "chunk_id"
                        if expected["grain"] == "article_chunk"
                        else "source_article_id"
                    )
                    ordered = sorted(
                        records, key=lambda record: (record["rank"], record["chunk_id"])
                    )
                    found = {record[key] for record in ordered[:k]}
                    value = mean(
                        all(
                            found.intersection(group["ids"])
                            for group in answer["groups"]
                        )
                        for answer in answers
                    )
                if value is None:
                    reason = {
                        "precision": "Unavailable: complete relevance judgments are not recorded.",
                        "ndcg": "Unavailable: graded relevance judgments are not recorded.",
                        "two_hop_recall": "Unavailable: no two-hop reference groups with replayable ranks.",
                    }.get(
                        metric,
                        "Unavailable: this run did not record retrieval reference scores.",
                    )
                rows.append(
                    {
                        "branch": branch,
                        "metric": metric,
                        "label": label,
                        "k": k,
                        "value": value,
                        "reason": reason,
                    }
                )
    for name, label in (
        ("context_recall", "Final-context recall"),
        ("context_complete_evidence", "Final-context complete evidence"),
    ):
        score = scores.get(name) or {}
        rows.append(
            {
                "branch": "context",
                "metric": name,
                "label": label,
                "k": None,
                "value": score.get("value"),
                "reason": score.get("reason")
                or "Unavailable: this run has no reference scores.",
            }
        )
    return rows


def project_report(document: dict[str, Any]) -> dict[str, Any]:
    """Keep judgment inputs and measurement specs; omit pipeline internals."""
    configurations = (document.get("retrieval_report") or {}).get("configurations", [])
    cases = []
    for case in document["report"]["cases"]:
        output = case.get("output") or {}
        evidence = _evidence(output)
        sources = _sources(evidence)
        rewrite = ((evidence.get("execution") or {}).get("request") or {}).get(
            "rewrite"
        ) or {}
        question = (
            rewrite.get("question")
            or (case.get("inputs") or {}).get("question")
            or output.get("question")
            or case["name"]
        )
        generation = output.get("rendered_text")
        # A failure/decline message is not a generated Retrieval Answer.
        has_generation = bool(
            generation
            and output.get("answer")
            and (output["answer"].get("introduction") is not None)
        )
        cases.append(
            {
                "name": case["name"],
                "question": question,
                "scope": (case.get("metadata") or {}).get("scope_note"),
                "grain": (case.get("expected_output") or {}).get("grain"),
                "metrics": _metric_rows(case, output, configurations),
                "output": {
                    "sources": sources,
                    "context_limits": evidence.get("context"),
                    "generation": generation if has_generation else None,
                    "has_context": any(source["passages"] for source in sources),
                    "has_generation": has_generation,
                },
            }
        )
    summaries = []
    if cases:
        keys = {
            (row["branch"], row["metric"], row["k"])
            for case in cases
            for row in case["metrics"]
        }
        for branch, metric, k in sorted(keys, key=str):
            rows = [
                row
                for case in cases
                for row in case["metrics"]
                if (row["branch"], row["metric"], row["k"]) == (branch, metric, k)
            ]
            values = [row["value"] for row in rows if row["value"] is not None]
            summaries.append(
                {
                    **rows[0],
                    "value": mean(values) if values else None,
                    "scored_cases": len(values),
                    "applicable_cases": len(rows),
                }
            )
    settings = configurations or [
        ((case.get("output") or {}).get("settings") or {})
        for case in document["report"]["cases"]
    ]
    specs = {
        "dataset": document.get("data_set"),
        "label_quality": document.get("label_quality"),
        "split": document.get("split"),
        "commit": document.get("commit"),
        "dirty": document.get("dirty"),
        "metric_version": (document.get("retrieval_report") or {}).get(
            "metric_version"
        ),
        "chunk_budget": (document.get("retrieval_report") or {}).get("chunk_budget"),
        "cutoffs": CUTOFFS,
        "definitions": DEFINITIONS,
        "configurations": list(
            {
                str(
                    {
                        key: setting.get(key)
                        for key in ("fusion_settings", "evidence_limits")
                    }
                ): {
                    key: setting.get(key)
                    for key in ("fusion_settings", "evidence_limits")
                }
                for setting in settings
            }.values()
        ),
    }
    return {
        "task": document["task"],
        "review_kind": "rag",
        "ran_at": document.get("ran_at"),
        "model": (document.get("deployment") or {}).get("model")
        or document.get("model"),
        "deployment": {"kind": (document.get("deployment") or {}).get("kind")},
        "review_identity": document.get("review_identity"),
        "specs": specs,
        "metrics": summaries,
        "report": {"cases": cases},
    }
