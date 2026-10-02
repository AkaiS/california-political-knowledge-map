"""Derive provisional retrieval labels from the 25 verified Cypher cases."""

import argparse
import hashlib
import json
from pathlib import Path

import yaml

from knowledge_map.evaluation.data_set import load_data_set
from knowledge_map.evaluation.tasks import task_named

REFERENCE_DIR = Path("work/initiatives/useful-graph-retrieval/query-construction")


def build_document(cases_path: Path, reference_path: Path) -> dict:
    source = yaml.safe_load(cases_path.read_text())
    reference = json.loads(reference_path.read_text())
    if reference["cases_sha256"] != hashlib.sha256(cases_path.read_bytes()).hexdigest():
        raise ValueError("reference results do not match the authored case file")
    if not reference["all_cases_verified"] or reference["unresolved_evidence_ids"]:
        raise ValueError("reference evidence has not been fully resolved")
    by_id = {c["id"]: c for c in reference["cases"]}
    if set(by_id) != {c["id"] for c in source["cases"]}:
        raise ValueError("reference results must cover exactly the authored cases")
    evidence = {e["id"]: e for e in reference["evidence"]}
    document = {
        "task": "retrieval",
        "description": (
            "25 existing Cypher questions with Codex-derived provisional silver retrieval labels. "
            "Labels describe stored graph evidence, not independently verified political facts. "
            "All cases are training because they have already informed query construction. "
            "The task generates final guidance from the selected evidence for human review. "
            "Question rewriting and assessment are evaluated separately by chat."
        ),
        "cases": [],
    }
    for source_case in source["cases"]:
        observed = by_id[source_case["id"]]
        if observed["question"] != source_case["question"] or not observed["rows"]:
            raise ValueError("reference questions must match and return nonempty rows")
        grain = "source_article" if source_case["family"] == "E3" else "article_chunk"
        answers = []
        for row in observed["rows"]:
            groups = []
            for group in row["evidence_groups"]:
                ids = sorted(
                    {
                        evidence[id]["article_id"] if grain == "source_article" else id
                        for id in group["ids"]
                    }
                )
                groups.append({"kind": group["kind"], "ids": ids})
            answers.append({"groups": groups})
        relevant = sorted({id for a in answers for g in a["groups"] for id in g["ids"]})
        document["cases"].append(
            {
                "id": source_case["id"],
                "description": source_case["scope_note"],
                "split": "training",
                "task_input": {
                    "question": source_case["question"],
                    "relational": source_case["family"] not in ("E1", "E2"),
                    "assessment": {"status": "allowed"},
                },
                "expected_output": {
                    "grain": grain,
                    "relevant_ids": relevant,
                    "answers": answers,
                },
                "metadata": {
                    "family": source_case["family"],
                    "scope_note": source_case["scope_note"],
                    "reference_artifact": str(reference_path),
                    "reference_sha256": hashlib.sha256(
                        reference_path.read_bytes()
                    ).hexdigest(),
                    "reference_checked_at": reference["checked_at"],
                    "annotation_guideline": "docs/evaluation/retrieval.md",
                    "label_quality": "silver",
                    "annotator": "Codex",
                },
                "tags": [source_case["family"], "reference-derived"],
            }
        )
    return document


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reference", type=Path, default=REFERENCE_DIR / "verified-results.json"
    )
    parser.add_argument(
        "--output", type=Path, default=Path("evals/silver/retrieval.yaml")
    )
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output already exists; choose a new --output and review the diff")
    document = build_document(REFERENCE_DIR / "cases.yaml", args.reference)
    task = task_named("retrieval")
    # Validate before writing so malformed reference evidence leaves no file.
    from knowledge_map.evaluation.data_set import EvaluationDataSet

    EvaluationDataSet[
        task.input_type, task.output_type, task.metadata_type
    ].model_validate(document)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        yaml.safe_dump(document, sort_keys=False, allow_unicode=True, width=100)
    )
    load_data_set(
        args.output,
        input_type=task.input_type,
        output_type=task.output_type,
        metadata_type=task.metadata_type,
    )
    print(f"Wrote {len(document['cases'])} training cases to {args.output}")


if __name__ == "__main__":
    main()
