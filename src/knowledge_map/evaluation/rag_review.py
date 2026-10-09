"""Present selected context and generation for scoped human RAG judgments."""

from __future__ import annotations

from statistics import mean
from typing import Any

from knowledge_map.schemas.fusion import FusionConfig

from .retrieval_report import replay_fusion, selected_semantic_results

AXES = ("context_relevance", "answer_relevance", "faithfulness")
VERDICTS = (None, "pass", "fail", "defer")
CUTOFFS = (1, 5, 10, 50)
METRICS = {
    "recall": "Recall@k",
    "precision": "Reference precision@k",
    "reciprocal_rank": "MRR within 50 chunks",
    "ndcg": "NDCG@k",
    "two_hop_recall": "Two-hop Recall@k",
}
DEFINITIONS = {
    "recall": "Reference identities recovered within the first k unique chunks. Article coverage is measured after applying the chunk budget.",
    "precision": "Top-k unique chunks matching the reference labels, divided by k. For article-grain references, each chunk from a listed article counts. Missing slots count as zero. Unlisted chunks may still be useful; this measures agreement with provisional references, not exhaustive relevance.",
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
    if set(review) not in (fields, fields | {"execution_note"}):
        raise ValueError("expected the three RAG judgments and their supporting notes")
    execution_note = review.get("execution_note", "")
    if not isinstance(execution_note, str) or len(execution_note) > 20_000:
        raise ValueError("invalid execution note")
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
    if not axes:
        return bool((review.get("execution_note") or "").strip())
    return all(review.get(axis) in ("pass", "fail") for axis in axes)


def review_cases(document: dict[str, Any]) -> list[dict[str, Any]]:
    """Include failed and unfinished attempts without fabricating task outputs."""
    cases = {case["name"]: case for case in document["report"]["cases"]}
    for failure in document["report"].get("failures", []):
        cases[failure["name"]] = {
            **failure,
            "output": {
                "failure": {
                    "stage": "execution",
                    "diagnostic": failure.get(
                        "error_message", "Task execution failed."
                    ),
                }
            },
        }
    selected = (document.get("evaluation_run") or {}).get("selected_cases", [])
    for case in selected:
        if case["name"] not in cases:
            cases[case["name"]] = {
                **case,
                "output": {"execution_status": "unresolved"},
                "unresolved": True,
            }
    order = [case["name"] for case in selected] or list(cases)
    return [cases[name] for name in dict.fromkeys([*order, *cases])]


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
    relevant = set(expected.get("relevant_ids") or [])
    two_hop = bool(answers) and all(len(answer["groups"]) == 2 for answer in answers)
    fused = []
    replayable = "branches" in output and expected.get("grain") in (
        "article_chunk",
        "source_article",
    )
    if replayable and branches:
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
                if metric == "two_hop_recall" and two_hop and value is None:
                    complete = scores.get(f"{branch}_complete_evidence_at_{k}")
                    if isinstance(complete, dict):
                        value = complete.get("value")
                        reason = complete.get("reason")
                if (
                    metric == "precision" and value is None and replayable and relevant
                ) or (
                    metric == "two_hop_recall"
                    and value is None
                    and two_hop
                    and replayable
                    and branches
                ):
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
                    if metric == "precision":
                        matches = sum(record[key] in relevant for record in ordered[:k])
                        value = matches / k
                        reason = (
                            f"Reference-based {expected['grain']} precision: "
                            f"{matches}/{k} chunk slots match the reference set. "
                            "Computed from this execution's retained ranks; "
                            "unlisted chunks may still be useful."
                        )
                    else:
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
                        "precision": "Unavailable: this run has neither a recorded precision score nor reference labels with replayable ranks.",
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
    for case in review_cases(document):
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
        failure = output.get("failure") or {}
        # A failure/decline message is not a generated Retrieval Answer.
        has_generation = bool(
            generation and output.get("answer") and "introduction" in output["answer"]
        )
        decision = output.get("assessment") or output.get("preparation") or {}
        decision_status = decision.get("status")
        assessment_outcomes = (
            "declined",
            "deferred",
            "needs_edit",
            "needs_clarification",
        )
        status = (
            "unresolved"
            if case.get("unresolved")
            else "failed"
            if failure
            else decision_status
            if decision_status in assessment_outcomes
            else "answer_generated"
            if has_generation
            else "context_only"
            if sources
            else "no_answer"
        )
        cases.append(
            {
                "name": case["name"],
                "question": question,
                "scope": (case.get("metadata") or {}).get("scope_note"),
                "grain": (case.get("expected_output") or {}).get("grain"),
                "metrics": _metric_rows(case, output, configurations),
                "execution": {
                    "status": status,
                    "message": (decision.get("explanation") or decision.get("message"))
                    if status in assessment_outcomes
                    else None,
                    "failure": {
                        key: failure.get(key)
                        for key in ("stage", "exception_type", "diagnostic")
                    }
                    if failure
                    else None,
                    "evaluator_errors": [
                        {key: error.get(key) for key in ("name", "error_message")}
                        for error in case.get("evaluator_failures", [])
                    ],
                },
                "output": {
                    "sources": sources,
                    "semantic_context": selected_semantic_results(evidence),
                    "context_limits": evidence.get("context"),
                    "generation": generation if has_generation else None,
                    "has_context": any(source["passages"] for source in sources),
                    "has_generation": has_generation,
                    "generation_failure": {
                        key: failure.get(key)
                        for key in ("stage", "exception_type", "diagnostic")
                    }
                    if failure.get("stage")
                    in ("guidance", "rendering", "retrieval_and_guidance")
                    else None,
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
        "split": document.get("split"),
        "model": (document.get("deployment") or {}).get("model")
        or document.get("model"),
        "deployment": {"kind": (document.get("deployment") or {}).get("kind")},
        "review_identity": document.get("review_identity"),
        "specs": specs,
        "metrics": summaries,
        "evaluation_run": {
            key: value
            for key, value in (document.get("evaluation_run") or {}).items()
            if key
            in (
                "status",
                "selected_count",
                "terminal_count",
                "failure_count",
                "unresolved_case_ids",
            )
        },
        "report": {"cases": cases},
    }
