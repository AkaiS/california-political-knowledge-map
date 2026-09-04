"""`ca-map eval` — collect an Evaluation Data Set's candidates, and run it.

`collect` writes the file the author then edits; `run` reads that file and
writes one report.  Neither touches a database — see ADR 0017.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from contextlib import nullcontext
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from knowledge_map.evaluation import (
    EvaluationSplit,
    data_set_path,
    load_data_set,
    run_commit,
    run_data_set,
    trace_url,
    write_report,
)
from knowledge_map.evaluation.tasks import task_named, task_names
from knowledge_map.schemas import DeploymentKind, ModelDeployment
from knowledge_map.utils.deployments import deployment_from_environment
from knowledge_map.utils.models import (
    DEFAULT_LOCAL_CHAT_MODEL,
    openrouter_admission_ceiling,
)


def select_deployment(
    task: Any,
    *,
    kind: str | DeploymentKind = DeploymentKind.OPENROUTER,
    model_override: str | None = None,
) -> ModelDeployment:
    """Build the command-selected chat deployment before evaluation starts.

    OpenRouter configuration is deliberately checked at this boundary so a
    malformed command cannot execute part of a Data Set before it fails.
    ``model_override`` is kept verbatim when supplied; an empty override is
    therefore rejected as an invalid requested model rather than replaced by
    an ambient setting.
    """

    load_dotenv()
    return deployment_from_environment(
        kind,
        default_local_model=(
            getattr(task, "default_model", None) or DEFAULT_LOCAL_CHAT_MODEL
        ),
        model_override=model_override,
        command_name="evaluation",
    )


def add_parser(subparsers: Any) -> None:
    """Register `eval` and its two subcommands on the top-level parser."""
    parser = subparsers.add_parser("eval", help="Run an Evaluation Data Set")
    actions = parser.add_subparsers(dest="eval_action", required=True)

    collect = actions.add_parser(
        "collect", help="Write a Data Set file from the project's own labeled data"
    )
    collect.add_argument("task", choices=task_names())
    collect.add_argument("--data-set", type=Path, default=None)
    collect.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing Data Set file, discarding hand edits",
    )

    run = actions.add_parser("run", help="Run a Data Set and write one report")
    run.add_argument("task", choices=task_names())
    run.add_argument("--data-set", type=Path, default=None)
    run.add_argument(
        "--deployment",
        choices=("local", "openrouter"),
        default="openrouter",
        help="Chat Model Deployment to evaluate against (default: openrouter)",
    )
    run.add_argument(
        "--model",
        default=None,
        help="Overrides the selected deployment's configured model",
    )
    run.add_argument(
        "--split",
        choices=[member.value for member in EvaluationSplit],
        default=None,
        help="Defaults to every case in the file",
    )
    run.add_argument("--max-concurrency", type=_positive_int, default=1)
    run.add_argument(
        "--no-report",
        action="store_true",
        help="Print the report without writing a file",
    )


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be an integer") from error
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be greater than 0")
    return parsed


def dispatch(args: argparse.Namespace) -> None:
    if args.eval_action == "collect":
        _collect(args)
    else:
        _run(args)


def _collect(args: argparse.Namespace) -> None:
    task = task_named(args.task)
    if task.collect is None:
        sys.exit(f"{task.name} has no labeled data to collect from; author the file by hand")

    path = args.data_set or data_set_path(task.data_set_stem, task.label_quality)
    if path.exists() and not args.force:
        sys.exit(
            f"{path} already exists. Editing it is the authoring step; pass --force "
            "to discard those edits and rewrite it."
        )

    collected = task.collect()
    cases, skipped = collected.cases, collected.skipped_urls
    if not cases:
        sys.exit(f"{task.name} has no labeled rows to collect")

    document = {
        "task": task.name,
        "description": f"Hand-labeled cases for {task.name}, collected from the project's own data.",
        "cases": cases,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(document, sort_keys=False, allow_unicode=True, width=100))
    print(f"Wrote {len(cases)} cases to {path}")

    labels = Counter(case["expected_output"]["classification"] for case in cases)
    print("Labels: " + ", ".join(f"{label} {count}" for label, count in labels.most_common()))
    _warn_if_one_label_dominates(labels)

    if skipped:
        print(f"\nSkipped {len(skipped)} labeled rows with no headline:")
        for url in skipped:
            print(f"  {url}")

    print("\nReview every case and assign its split, then commit the file.")


def _warn_if_one_label_dominates(labels: Counter) -> None:
    """Say so when the population makes a constant answer look good.

    Printed at the end of `collect`, where the author can still fix it.
    """
    total = sum(labels.values())
    if not total:
        return
    label, count = labels.most_common(1)[0]
    if count / total < 0.8:
        return
    print(
        f"\nWarning: {count} of {total} cases are {label}. Always answering "
        f"{label} scores {count / total:.0%} on this Data Set, so agreement "
        "will not tell you whether the classifier works. Label more of the "
        "other class before trusting a run."
    )


def _run(args: argparse.Namespace) -> None:
    task = task_named(args.task)
    try:
        deployment = select_deployment(
            task,
            kind=getattr(args, "deployment", None) or DeploymentKind.OPENROUTER,
            model_override=args.model,
        )
    except ValueError as error:
        sys.exit(str(error))

    path = args.data_set or data_set_path(task.data_set_stem, task.label_quality)
    if not path.exists():
        sys.exit(f"{path} does not exist. Run `ca-map eval collect {task.name}` first.")

    data_set = load_data_set(
        path,
        input_type=task.input_type,
        output_type=task.output_type,
        metadata_type=task.metadata_type,
    )
    split = EvaluationSplit(args.split) if args.split else None

    admission_scope = (
        openrouter_admission_ceiling(args.max_concurrency)
        if deployment.kind is DeploymentKind.OPENROUTER
        else nullcontext()
    )
    with admission_scope:
        report = run_data_set(
            data_set,
            task=task.build(deployment, data_set),
            evaluators=task.evaluators,
            split=split,
            max_concurrency=args.max_concurrency,
            experiment_metadata={
                "task": task.name,
                "deployment": deployment.model_dump(mode="json"),
                "commit": run_commit(),
                "prompts": task.prompt_digests(),
                "data_set": str(path),
                "label_quality": task.label_quality.value,
                "split": split.value if split else None,
            },
        )
    report.print(include_input=False, include_output=False)

    # Printed before the failure check below: a run that failed is exactly the
    # one whose trace the author needs.
    trace = trace_url(report)
    if trace:
        print(f"\nTrace: {trace}")

    if report.failures:
        # A failed case is not a completed Evaluation Run; do not persist a
        # report whose cases would be mistaken for a complete Data Set result.
        raise SystemExit("Evaluation Run failed; no report was written.")

    if args.no_report:
        return
    written = write_report(
        report,
        task=task.name,
        deployment=deployment,
        data_set_path=path,
        label_quality=task.label_quality,
        split=split.value if split else None,
    )
    print(f"\nWrote {written}")
    print("Commit it — a run whose report is not committed did not happen.")
