"""Bound saved retrieval reports, preserving their originals under .scratch."""

from __future__ import annotations

import argparse
import hashlib
import json
from copy import deepcopy
from pathlib import Path

from knowledge_map.evaluation.retrieval_report import compact_retrieval_report


def compact_file(path: Path, *, backup_dir: Path) -> tuple[int, int]:
    original = path.read_bytes()
    document = json.loads(original)
    if document.get("task") != "retrieval":
        raise ValueError(f"{path} is not a retrieval report")
    if "retrieval_report" in document:
        return len(original), len(original)
    previous_scores = {
        case["name"]: deepcopy(case["scores"]) for case in document["report"]["cases"]
    }
    compact_retrieval_report(document, rescore=True)
    for case in document["report"]["cases"]:
        changed = {
            name: score["value"]
            for name, score in previous_scores[case["name"]].items()
            if score["value"] != case["scores"][name]["value"]
        }
        if changed:
            case["attributes"]["legacy_identity_budget_scores"] = changed
        case["attributes"]["retrieval_metric_version"] = document["retrieval_report"][
            "metric_version"
        ]
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / path.name
    if backup.exists() and backup.read_bytes() != original:
        raise ValueError(f"refusing to overwrite a different backup at {backup}")
    backup.write_bytes(original)
    document["retrieval_report"]["migration"] = {
        "source_sha256": hashlib.sha256(original).hexdigest(),
        "previous_metric_version": "unique-evidence-identity-budget-v1",
        "rescored": True,
        "original_report_backup": str(backup),
    }
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    return len(original), path.stat().st_size


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", type=Path, nargs="*")
    parser.add_argument(
        "--backup-dir",
        type=Path,
        default=Path(".scratch/rag-evaluation/unbounded-report-backups"),
    )
    args = parser.parse_args()
    paths = args.paths or sorted(Path("evals/reports/retrieval").glob("*.json"))
    for path in paths:
        before, after = compact_file(path, backup_dir=args.backup_dir)
        print(f"{path}: {before:,} -> {after:,} bytes")


if __name__ == "__main__":
    main()
