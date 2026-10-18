"""Run an established Evaluation Data Set, then account for every selected case.

Use --plan to validate selection without model calls; use --report PATH to
produce the same summary from a saved (including interrupted) attempt.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from pathlib import Path
from typing import Any

import yaml

from knowledge_map.cli import evaluate
from knowledge_map.evaluation.data_set import data_set_path, load_data_set
from knowledge_map.evaluation.run_report import (
    DEFAULT_REVIEWER_PORT,
    ReportDocument,
    Scorecard,
)
from knowledge_map.evaluation.tasks import task_named, task_names

REFERENCE_DIR = Path("work/initiatives/useful-graph-retrieval/query-construction")
RAG_CASE_COUNT = 25


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
    reviewer_port: int = DEFAULT_REVIEWER_PORT,
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


def summarize_report(
    path: Path,
    *,
    expected_ids: list[str] | None = None,
    reviewer_port: int = DEFAULT_REVIEWER_PORT,
) -> Scorecard:
    """A planned run's single-axis Scorecard."""
    return Scorecard.build(
        [ReportDocument.load(path, expected_case_ids=expected_ids)],
        baseline="none",
        reviewer_port=reviewer_port,
    )


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
    scorecard = summarize_report(
        written[-1],
        expected_ids=plan["selection"]["case_ids"],
        reviewer_port=plan["reviewer_port"],
    )
    return scorecard.to_json(), exit_code or scorecard.exit_code


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
        default=DEFAULT_REVIEWER_PORT,
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
            scorecard = summarize_report(args.report, reviewer_port=args.reviewer_port)
        except ValueError as error:
            parser.error(str(error))
        print(json.dumps(scorecard.to_json(), indent=2, sort_keys=True))
        return scorecard.exit_code
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
