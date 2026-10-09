"""Run an established Evaluation Data Set, then account for every selected case.

Use --plan to validate selection without model calls; use --report PATH to
produce the same summary from a saved (including interrupted) attempt.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import shlex
from collections import Counter, defaultdict
from pathlib import Path
from statistics import fmean
from typing import Any
from urllib.parse import quote

import yaml

from knowledge_map.cli import evaluate
from knowledge_map.evaluation.data_set import data_set_path, load_data_set
from knowledge_map.evaluation.rag_review import project_report
from knowledge_map.evaluation.tasks import task_named, task_names

REFERENCE_DIR = Path("work/initiatives/useful-graph-retrieval/query-construction")
RAG_CASE_COUNT = 25
BRANCHES = ("full_text", "dense", "structural")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _validate_rag(data_set: Any, reference_dir: Path) -> None:
    """Catch an accidentally replaced benchmark before inference starts."""
    source_path = reference_dir / "cases.yaml"
    reference_path = reference_dir / "verified-results.json"
    source = yaml.safe_load(source_path.read_text())
    reference = json.loads(reference_path.read_text())
    authored = [case["id"] for case in source["cases"]]
    observed = [case["id"] for case in reference["cases"]]
    actual = [case.id for case in data_set.cases]
    if (
        len(authored) != RAG_CASE_COUNT
        or len(set(authored)) != RAG_CASE_COUNT
        or len(observed) != RAG_CASE_COUNT
        or set(actual) != set(authored)
        or set(observed) != set(authored)
    ):
        raise ValueError(
            "RAG Data Set must contain exactly the 25 established authored case IDs"
        )
    if (
        reference["cases_sha256"] != _sha256(source_path)
        or not reference["all_cases_verified"]
        or reference["unresolved_evidence_ids"]
    ):
        raise ValueError(
            "RAG reference artifact is incomplete or does not match authored cases"
        )
    digest = _sha256(reference_path)
    for case in data_set.cases:
        if case.expected_output is None:
            raise ValueError(f"{case.id}: RAG reference labels are required")
        if not case.metadata or case.metadata.reference_sha256 != digest:
            raise ValueError(
                f"{case.id}: RAG reference artifact checksum does not match"
            )


def resolve_plan(
    target: str,
    *,
    root: Path = Path("."),
    sample: int | None = None,
    seed: int = 42,
    case_ids: list[str] | None = None,
    deployment: str = "local",
    model: str | None = None,
    max_concurrency: int = 1,
    reviewer_port: int = 8766,
) -> dict[str, Any]:
    if not 1 <= reviewer_port <= 65535:
        raise ValueError("Reviewer port must be between 1 and 65535")
    task = task_named("retrieval" if target == "rag" else target)
    path = root / data_set_path(task.data_set_stem, task.label_quality)
    data_set = load_data_set(
        path,
        input_type=task.input_type,
        output_type=task.output_type,
        metadata_type=task.metadata_type,
    )
    if data_set.task != task.data_set_stem:
        raise ValueError(
            f"Data Set task {data_set.task!r} does not match {task.data_set_stem!r}"
        )
    if task.label_quality.value != "unlabeled" and any(
        case.expected_output is None for case in data_set.cases
    ):
        raise ValueError(
            "Every labeled Evaluation Data Set case requires its expected output"
        )
    if task.name == "retrieval":
        _validate_rag(data_set, root / REFERENCE_DIR)
    resolved_deployment = evaluate.select_deployment(
        task, kind=deployment, model_override=model
    )
    authored = [case.id for case in data_set.cases]
    if sample is not None and case_ids is not None:
        raise ValueError("Choose either an explicit sample or explicit case IDs")
    if sample is not None:
        if not 1 <= sample <= len(authored):
            raise ValueError(f"Sample must be between 1 and {len(authored)}")
        selected = set(random.Random(seed).sample(sorted(authored), sample))
    elif case_ids is not None:
        selected = set(case_ids)
        if not selected or len(selected) != len(case_ids):
            raise ValueError("Explicit case IDs must be nonempty and unique")
        if unknown := selected - set(authored):
            raise ValueError("Unknown case IDs: " + ", ".join(sorted(unknown)))
    else:
        selected = set(authored)
    if max_concurrency < 1:
        raise ValueError("max_concurrency must be greater than 0")
    return {
        "task": task.name,
        "data_set": str(path),
        "data_set_sha256": _sha256(path),
        "deployment": deployment,
        "resolved_deployment": resolved_deployment.model_dump(mode="json"),
        "prompts": task.prompt_digests(),
        "model_override": model,
        "max_concurrency": max_concurrency,
        "reviewer_port": reviewer_port,
        "selection": {
            "scope": "full" if sample is None and case_ids is None else "subset",
            "method": "sample"
            if sample is not None
            else "cases"
            if case_ids is not None
            else "all",
            "seed": seed if sample is not None else None,
            "authored_count": len(authored),
            "case_ids": [case_id for case_id in authored if case_id in selected],
        },
    }


def _metric_names(document: dict[str, Any], selected: list[dict]) -> set[str]:
    names = {
        name
        for case in document["report"].get("cases", [])
        for name in case.get("scores", {})
    }
    if document.get("task") == "retrieval":
        from knowledge_map.evaluation.tasks.retrieval import (
            RetrievalExpectation,
            retrieval_scores,
        )

        expected = next(
            (
                case.get("expected_output")
                for case in selected
                if case.get("expected_output")
            ),
            None,
        )
        if expected:
            labels = RetrievalExpectation.model_validate(expected)
            for branch in (*BRANCHES, "fused"):
                names.update(
                    retrieval_scores((), labels, prefix=branch, ks=(1, 5, 10, 50))
                )
            names.update(("context_recall", "context_complete_evidence"))
        for branch in (*BRANCHES, "fused"):
            names.update(f"{branch}_ndcg_at_{k}" for k in (1, 5, 10, 50))
    return names


def summarize_report(
    path: Path, *, expected_ids: list[str] | None = None, reviewer_port: int = 8766
) -> dict[str, Any]:
    """Keep missing measurements visible instead of shrinking their populations."""
    if not 1 <= reviewer_port <= 65535:
        raise ValueError("Reviewer port must be between 1 and 65535")
    document = json.loads(path.read_text())
    report = document["report"]
    run = document.get("evaluation_run", {})
    cases = report.get("cases", [])
    failures = report.get("failures", [])
    selected = run.get("selected_cases", [])
    recorded_ids = run.get("selected_case_ids")
    selected_ids = expected_ids if expected_ids is not None else recorded_ids
    if selected_ids is None:
        # Historical reports have no selection manifest; the reported cases
        # are known outcomes, not evidence that the entire file was selected.
        selected_ids = [case["name"] for case in cases + failures]
    outcomes = cases + failures
    counts = Counter(case["name"] for case in outcomes)
    expected_set = set(selected_ids)
    extra = sorted(set(counts) - expected_set)
    duplicate = sorted(name for name, count in counts.items() if count != 1)
    mismatch = (
        recorded_ids is not None
        and expected_ids is not None
        and set(recorded_ids) != expected_set
    )
    unresolved = [case_id for case_id in selected_ids if case_id not in counts]
    completed_answers = 0
    declined = 0
    stage_failures: Counter[str] = Counter()
    branches: dict[str, Counter] = {name: Counter() for name in BRANCHES}
    for case in cases:
        output = case.get("output")
        output = output if isinstance(output, dict) else {}
        failure = output.get("failure")
        if failure:
            stage_failures[failure.get("stage", "unknown")] += 1
        elif output.get("failure_type"):
            stage_failures[f"task:{output['failure_type']}"] += 1
        answer = output.get("answer") or {}
        if output.get("rendered_text") and answer and "introduction" in answer:
            completed_answers += 1
        decision = output.get("assessment") or output.get("preparation") or {}
        if decision.get("status") == "declined":
            declined += 1
        outcomes = output.get("branches")
        if outcomes is None:
            evidence = (
                answer.get("evidence")
                or output.get("retrieval")
                or output.get("result")
                or {}
            )
            outcomes = evidence.get("execution", {}).get("outcomes", [])
        for branch in outcomes:
            if branch.get("branch") in branches:
                branches[branch["branch"]][branch.get("status", "unknown")] += 1
    if failures:
        stage_failures["framework"] = len(failures)
    metric_values: dict[str, list[float]] = defaultdict(list)
    metric_reasons: dict[str, set[str]] = defaultdict(set)
    for case in cases:
        for name, score in case.get("scores", {}).items():
            value = score.get("value") if isinstance(score, dict) else score
            if isinstance(value, (float, int)):
                metric_values[name].append(float(value))
            elif isinstance(score, dict) and score.get("reason"):
                metric_reasons[name].add(score["reason"])
    metrics = {}
    for name in sorted(_metric_names(document, selected or cases)):
        values = metric_values[name]
        reason = None
        if not values:
            if "ndcg" in name:
                reason = "NDCG is not computed by the established evaluator; the RAG references have no relevance grades."
            elif document.get("label_quality") == "unlabeled":
                reason = "This Data Set has no reference judgments."
            else:
                reason = (
                    "; ".join(sorted(metric_reasons[name]))
                    or "No selected case recorded this measurement; inspect failures and evaluator errors."
                )
        metrics[name] = {
            "mean": fmean(values) if values else None,
            "scored_cases": len(values),
            "selected_cases": len(selected_ids),
            "missing_cases": max(0, len(selected_ids) - len(values)),
            "inclusion_policy": "Unweighted mean of recorded numeric case scores. Unscored failures and unresolved cases are missing, never silently counted as successes or zero.",
            "unavailable_reason": reason,
        }
    if document["task"] in ("retrieval", "chat"):
        projection = project_report(document)
        for row in projection["metrics"]:
            name = (
                row["metric"]
                if row["branch"] == "context"
                else f"{row['branch']}_{row['metric']}"
                + (f"_at_{row['k']}" if row["k"] is not None else "")
            )
            existing = metrics.get(name, {})
            metrics[name] = {
                **existing,
                "mean": row["value"],
                "scored_cases": row["scored_cases"],
                "applicable_cases": row["applicable_cases"],
                "selected_cases": len(selected_ids),
                "missing_cases": max(0, len(selected_ids) - row["scored_cases"]),
                "inclusion_policy": "Existing RAG reviewer measurement rules; unweighted mean of recorded or exactly replayed case scores. Failures and unresolved measurements remain missing.",
                "unavailable_reason": row["reason"] if row["value"] is None else None,
            }
    experiment = (
        document.get("experiment_metadata") or report.get("experiment_metadata") or {}
    )
    selection = experiment.get("selection", {})
    integrity_errors = {
        "unexpected_case_ids": extra,
        "duplicate_case_ids": duplicate,
        "selection_manifest_mismatch": mismatch,
    }
    status = run.get("status", "historical_selection_unknown")
    if extra or duplicate or mismatch or unresolved:
        status = "incomplete"
    started = run.get("started_case_ids", [])
    assertions = {}
    assertion_names = {name for case in cases for name in case.get("assertions", {})}
    for name in sorted(assertion_names):
        values = [
            case["assertions"][name]["value"]
            for case in cases
            if isinstance(case.get("assertions", {}).get(name), dict)
            and isinstance(case["assertions"][name].get("value"), bool)
        ]
        assertions[name] = {
            "passed": sum(values),
            "failed": len(values) - sum(values),
            "scored_cases": len(values),
            "selected_cases": len(selected_ids),
            "missing_cases": max(0, len(selected_ids) - len(values)),
            "pass_rate": fmean(values) if values else None,
            "inclusion_policy": "Recorded boolean evaluator assertions only; missing, failed execution, and unresolved measurements remain explicit.",
        }
    reports_dir = (
        path.resolve().parent.parent if path.parent.name == document["task"] else None
    )
    reviewable = document["task"] in ("retrieval", "chat") and reports_dir is not None
    reviewer_command = (
        shlex.join(
            [
                "uv",
                "run",
                str(Path(__file__).resolve().with_name("review_chat_eval.py")),
                "--mode",
                "rag",
                "--reports-dir",
                str(reports_dir),
                "--port",
                str(reviewer_port),
            ]
        )
        if reviewable
        else None
    )
    summary = {
        "task": document["task"],
        "scope": selection.get("scope", "unknown"),
        "status": status,
        "recorded_status": run.get("status"),
        "interruption_reason": run.get("interruption_reason"),
        "counts": {
            "selected": len(selected_ids),
            "attempted": len(set(started) | set(counts)),
            "terminal": len(expected_set & set(counts)),
            "completed_answers": completed_answers,
            "declined": declined,
            "execution_failures": sum(stage_failures.values()),
            "unresolved": len(unresolved),
            "evaluator_errors": sum(len(c.get("evaluator_failures", [])) for c in cases)
            + len(report.get("report_evaluator_failures", [])),
        },
        "failures_by_stage": dict(sorted(stage_failures.items())),
        "unresolved_case_ids": unresolved,
        "integrity": integrity_errors,
        "case_ids": selected_ids,
        "branch_completion": {
            name: {
                **dict(sorted(count.items())),
                "selected_cases": len(selected_ids),
                "unrecorded": len(selected_ids) - sum(count.values()),
                "inclusion_policy": "Recorded branch outcomes / selected cases; declines and earlier failures have unrecorded branches.",
            }
            for name, count in branches.items()
        }
        if document["task"] in ("retrieval", "chat")
        else {},
        "metrics": metrics,
        "assertions": assertions,
        "metric_population_note": "Scores use the existing evaluator's reference and slot denominators; this summary reports the case population used in each mean.",
        "metrics_unavailable_reason": "This Data Set has no reference judgments."
        if all(metric["mean"] is None for metric in metrics.values())
        and document.get("label_quality") == "unlabeled"
        else None,
        "provenance": {
            key: document.get(key)
            for key in (
                "data_set",
                "data_set_sha256",
                "deployment",
                "commit",
                "dirty",
                "label_quality",
                "ran_at",
            )
        }
        | {
            "experiment_metadata": experiment,
            "retrieval_settings": document.get("retrieval_report", {}).get(
                "configurations"
            ),
        },
        "report_path": str(path.resolve()),
        "reviewer_url": f"http://127.0.0.1:{reviewer_port}/runs/{quote(document['task'] + '--' + path.stem)}"
        if reviewable
        else None,
        "reviewer_command": reviewer_command,
        "reviewer_reports_dir": str(reports_dir) if reviewable else None,
        "reviewer_status": "unverified; run the reviewer command or verify the existing server serves this exact reports directory"
        if reviewable
        else "unavailable; reviewer supports chat/retrieval reports in TASK/*.json layout",
        "trace_url": document.get("trace_url"),
    }
    return summary


def execute_plan(plan: dict[str, Any]) -> tuple[dict[str, Any] | None, int]:
    path = Path(plan["data_set"])
    if _sha256(path) != plan["data_set_sha256"]:
        raise ValueError(
            "Data Set changed after selection; resolve and validate it again"
        )
    task = task_named(plan["task"])
    deployment = evaluate.select_deployment(
        task, kind=plan["deployment"], model_override=plan["model_override"]
    )
    if (
        deployment.model_dump(mode="json") != plan["resolved_deployment"]
        or task.prompt_digests() != plan["prompts"]
    ):
        raise ValueError(
            "Deployment or prompt resources changed after planning; resolve the plan again"
        )
    written: list[Path] = []
    args = argparse.Namespace(
        eval_action="run",
        task=plan["task"],
        data_set=path,
        deployment=plan["deployment"],
        model=plan["model_override"],
        split=None,
        max_concurrency=plan["max_concurrency"],
        case_ids=plan["selection"]["case_ids"],
        no_report=False,
        run_metadata={"selection": plan["selection"]},
        report_written_callback=lambda report_path: written.append(Path(report_path)),
    )
    exit_code = 0
    try:
        returned = evaluate._run(args)
        if returned is not None and not written:
            written.append(returned)
    except (SystemExit, KeyboardInterrupt) as error:
        exit_code = 130 if isinstance(error, KeyboardInterrupt) else 1
        print(str(error))
    except Exception:
        # The CLI has already checkpointed before execution; retain the same
        # reporting route even when a task setup or infrastructure call raises.
        if not written:
            raise
        exit_code = 1
    if not written:
        return None, exit_code or 1
    summary = summarize_report(
        written[-1],
        expected_ids=plan["selection"]["case_ids"],
        reviewer_port=plan["reviewer_port"],
    )
    if (
        summary["status"] != "completed"
        or summary["counts"]["execution_failures"]
        or summary["counts"]["evaluator_errors"]
    ):
        exit_code = exit_code or 1
    return summary, exit_code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", nargs="?", choices=("rag", *task_names()))
    subset = parser.add_mutually_exclusive_group()
    subset.add_argument("--sample", type=int, help="Explicit reproducible subset size")
    subset.add_argument(
        "--case",
        action="append",
        dest="case_ids",
        help="Explicit authored case ID; repeat for several",
    )
    parser.add_argument(
        "--seed", type=int, default=42, help="Sampling seed (default: 42)"
    )
    parser.add_argument(
        "--deployment", choices=("local", "openrouter"), default="local"
    )
    parser.add_argument("--model")
    parser.add_argument(
        "--reviewer-port",
        type=int,
        default=8766,
        help="Port for the exact report reviewer link and command (server status is unverified)",
    )
    parser.add_argument("--max-concurrency", type=int, default=1)
    parser.add_argument(
        "--plan",
        action="store_true",
        help="Validate selection and print it without execution",
    )
    parser.add_argument(
        "--report", type=Path, help="Summarize a saved attempt without execution"
    )
    args = parser.parse_args(argv)
    if args.report:
        if args.target or args.plan or args.sample is not None or args.case_ids:
            parser.error(
                "--report summarizes a saved attempt; provide no selection arguments"
            )
        try:
            summary = summarize_report(args.report, reviewer_port=args.reviewer_port)
        except ValueError as error:
            parser.error(str(error))
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0
    if not args.target:
        parser.error("Choose the evaluation task established by context")
    try:
        plan = resolve_plan(
            args.target,
            sample=args.sample,
            seed=args.seed,
            case_ids=args.case_ids,
            deployment=args.deployment,
            model=args.model,
            max_concurrency=args.max_concurrency,
            reviewer_port=args.reviewer_port,
        )
    except (ValueError, FileNotFoundError) as error:
        parser.error(str(error))
    print(json.dumps({"evaluation_plan": plan}, indent=2, sort_keys=True), flush=True)
    if args.plan:
        return 0
    summary, exit_code = execute_plan(plan)
    if summary is not None:
        print(
            json.dumps({"evaluation_summary": summary}, indent=2, sort_keys=True),
            flush=True,
        )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
