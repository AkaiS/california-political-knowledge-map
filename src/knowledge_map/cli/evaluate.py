"""`ca-map eval` — collect a Gold Set's candidates, and run it.

`collect` writes the file the author then edits; `run` reads that file and
writes one report.  Neither touches a database — see ADR 0017.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from contextlib import nullcontext
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from knowledge_map.evaluation import (
    EvaluationSplit,
    gold_set_path,
    load_gold_set,
    run_gold_set,
    write_report,
)
from knowledge_map.evaluation.tasks import task_named, task_names
from knowledge_map.schemas import (
    DeploymentKind,
    ModelDeployment,
    OpenRouterProviderPolicy,
)
from knowledge_map.utils.models import (
    openrouter_admission_ceiling,
    resolve_chat_base_url,
)


def select_deployment(
    task: Any,
    *,
    kind: str | DeploymentKind = DeploymentKind.OPENROUTER,
    model_override: str | None = None,
) -> ModelDeployment:
    """Build the command-selected chat deployment before evaluation starts.

    OpenRouter configuration is deliberately checked at this boundary so a
    malformed command cannot execute part of a Gold Set before it fails.
    ``model_override`` is kept verbatim when supplied; an empty override is
    therefore rejected as an invalid requested model rather than replaced by
    an ambient setting.
    """

    load_dotenv()
    deployment_kind = DeploymentKind(kind)
    if deployment_kind is DeploymentKind.LOCAL:
        configured_model = os.environ.get("LLAMA_CPP_MODEL") or task.default_model
        model = configured_model if model_override is None else model_override
        return ModelDeployment(
            kind=deployment_kind,
            model=model,
            endpoint=resolve_chat_base_url(),
        )

    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    configured_model = os.environ.get("OPENROUTER_MODEL", "").strip()
    provider_text = os.environ.get("OPENROUTER_PROVIDERS", "")
    providers = tuple(
        provider.strip()
        for provider in provider_text.split(",")
    )
    missing: list[str] = []
    if not api_key:
        missing.append("OPENROUTER_API_KEY")
    if model_override is None:
        if not configured_model:
            missing.append("OPENROUTER_MODEL")
        model = configured_model
    else:
        model = model_override
    if not model or not model.strip():
        missing.append("--model")
    if not provider_text.strip() or any(not provider for provider in providers):
        missing.append("OPENROUTER_PROVIDERS")
    if missing:
        raise ValueError(
            "OpenRouter evaluation deployment is incomplete; set "
            + ", ".join(missing)
        )

    return ModelDeployment(
        kind=deployment_kind,
        model=model,
        provider_policy=OpenRouterProviderPolicy(providers=providers),
    )


def add_parser(subparsers: Any) -> None:
    """Register `eval` and its two subcommands on the top-level parser."""
    parser = subparsers.add_parser("eval", help="Run an Evaluation Gold Set")
    actions = parser.add_subparsers(dest="eval_action", required=True)

    collect = actions.add_parser(
        "collect", help="Write a Gold Set file from the project's own labeled data"
    )
    collect.add_argument("task", choices=task_names())
    collect.add_argument("--gold-set", type=Path, default=None)
    collect.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing Gold Set file, discarding hand edits",
    )

    run = actions.add_parser("run", help="Run a Gold Set and write one report")
    run.add_argument("task", choices=task_names())
    run.add_argument("--gold-set", type=Path, default=None)
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

    path = args.gold_set or gold_set_path(task.gold_set_stem)
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
        f"{label} scores {count / total:.0%} on this Gold Set, so agreement "
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

    path = args.gold_set or gold_set_path(task.gold_set_stem)
    if not path.exists():
        sys.exit(f"{path} does not exist. Run `ca-map eval collect {task.name}` first.")

    gold_set = load_gold_set(
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
        report = run_gold_set(
            gold_set,
            task=task.build(deployment, gold_set),
            evaluators=task.evaluators,
            split=split,
            max_concurrency=args.max_concurrency,
        )
    report.print(include_input=False, include_output=False)

    if args.no_report:
        return
    written = write_report(
        report,
        task=task.name,
        deployment=deployment,
        gold_set_path=path,
        split=split.value if split else None,
    )
    print(f"\nWrote {written}")
    print("Commit it — a run whose report is not committed did not happen.")
