"""Prepare immutable review content, trace features, and a diverse initial sample."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path

import numpy as np
from markdown_it import MarkdownIt
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parents[1]


class VisibleText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def pretty(value):
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def save(path, value):
    path.write_text(pretty(value) + "\n")


def prepare(report_path: Path, data_dir: Path, telemetry_path: Path | None):
    report_bytes = report_path.read_bytes()
    report = json.loads(report_bytes)
    digest = hashlib.sha256(report_bytes).hexdigest()
    if (data_dir / "manifest.json").exists():
        previous = json.loads((data_dir / "manifest.json").read_text())
        if previous["report_sha256"] != digest:
            raise ValueError("Use a new data directory for a different report")
    cases = report["report"]["cases"]
    evidence_path = ROOT / cases[0]["metadata"]["reference_artifact"]
    evidence = json.loads(evidence_path.read_text())
    references = {c["id"]: c for c in evidence["cases"]}
    chunks = {e["id"]: e for e in evidence["evidence"]}
    telemetry = json.loads(telemetry_path.read_text()) if telemetry_path else None
    remote = telemetry["results"]["operational_details"]["rows"] if telemetry else []
    repeated = Counter(
        m.get("instructions", "")
        for c in cases
        for exchange in c["output"]["messages"]
        for m in exchange["messages"]
        if m.get("instructions")
    )
    parser = MarkdownIt("commonmark", {"html": False}).enable("table")
    parser.renderer.rules["image"] = lambda *_: ""

    def block(
        record,
        section,
        label,
        text,
        role="tool",
        format="prose",
        collapsed=False,
        **extra,
    ):
        if not isinstance(text, str):
            text = pretty(text)
            format = "code"
        body = parser.render(text) if format == "markdown" else html.escape(text)
        visible = VisibleText()
        visible.feed(body)
        item = {
            "id": "question"
            if label == "Original question"
            else f"block-{len(record['blocks'])}",
            "section": section,
            "label": label,
            "role": role,
            "format": format,
            "text": text,
            "html": body,
            "anchor_text": "".join(visible.parts),
            "collapsed": collapsed,
            **extra,
        }
        record["blocks"].append(item)

    records = []
    feature_rows = []
    families = sorted({references[c["name"]]["feature"] for c in cases})
    scenarios = sorted({references[c["name"]]["scenario"] for c in cases})
    familiarity = sorted({references[c["name"]]["domain_familiarity"] for c in cases})
    outcomes = ["answer_prepared", "declined", "stage_failure"]
    raw_features = []
    for case in cases:
        output = case["output"]
        reference = references[case["name"]]
        outcome = (
            "stage_failure"
            if output["failure"]
            else "answer_prepared"
            if output["answer"]
            else output["preparation"]["status"]
        )
        record = {
            "id": case["name"],
            "question": output["question"],
            "outcome": outcome,
            "feature": reference["feature"],
            "scenario": reference["scenario"],
            "familiarity": reference["domain_familiarity"],
            "exchange_count": len(output["messages"]),
            "duration": case["task_duration"],
            "trace_url": case["attributes"].get("chat_session_url")
            or report["trace_url"],
            "flags": [],
            "blocks": [],
        }
        block(
            record,
            "Question and output",
            "Original question",
            output["question"],
            "user",
        )
        block(
            record,
            "Question and output",
            "Prepared output" if output["rendered_text"] else "Attempt stopped",
            output["rendered_text"] or output["failure"],
            "assistant",
            "markdown" if output["rendered_text"] else "code",
        )
        preparation = output["preparation"] or {}
        approval = preparation.get("approval", {})
        block(
            record,
            "Question preparation",
            "Proposed rewrite" if approval else "Preparation result",
            approval.get("question") or preparation.get("message") or preparation,
            "assistant",
        )
        if approval:
            block(
                record,
                "Question preparation",
                "Policy and coverage explanation",
                approval.get("explanation", ""),
                "assistant",
            )
            block(
                record,
                "Question preparation",
                "Recoverable portion",
                approval.get("recoverable_portion")
                or "No recoverable portion recorded",
                "assistant",
            )
        block(
            record,
            "Question preparation",
            "Driver behavior",
            "The evaluation automatically approved the first rewrite proposal. It did not simulate a person correcting the question or resolving ambiguity.",
            "system",
            collapsed=True,
        )
        answer = output["answer"] or output["retrieval"] or {}
        grounding = answer.get("evidence", answer)
        execution = grounding.get("execution", {})
        for branch in execution.get("outcomes", []):
            candidates = branch.get("candidates", [])
            overview = {k: v for k, v in branch.items() if k != "candidates"}
            overview["retained_candidate_count"] = len(candidates)
            block(
                record,
                "Retrieval and selected evidence",
                branch["branch"] + " branch",
                overview,
            )
            if candidates:
                block(
                    record,
                    "Retrieval and selected evidence",
                    branch["branch"] + " retained candidates",
                    candidates,
                    collapsed=True,
                )
        for source in grounding.get("sources", []):
            citation = source["citation"]
            block(record, "Retrieval and selected evidence", "Source Article", citation)
            for passage in source["passages"]:
                block(
                    record,
                    "Retrieval and selected evidence",
                    "Selected Article Chunk · " + passage["candidate"]["chunk_id"],
                    passage["text"],
                )
                block(
                    record,
                    "Retrieval and selected evidence",
                    "Candidate contributions and routes",
                    passage["candidate"],
                    collapsed=True,
                )
        block(
            record,
            "Corpus reference",
            "Authored evidence condition",
            {
                "evidence_requirement": reference["evidence_requirement"],
                "validation": reference["validation"],
                "interpretation": "This is a source-backed input condition, not a human-reviewed answer or quality label.",
            },
        )
        for chunk_id in reference["validation"].get("evidence_ids", []):
            chunk = chunks[chunk_id]
            block(
                record,
                "Corpus reference",
                "Reference Article Chunk · " + chunk_id,
                chunk["text"],
            )
            block(
                record,
                "Corpus reference",
                "Reference citation",
                {k: v for k, v in chunk.items() if k != "text"},
                collapsed=True,
            )
        if reference["validation"].get("basis") != "source_text":
            block(
                record,
                "Corpus reference",
                "Coverage and question policy",
                {
                    "coverage": evidence["coverage_basis"],
                    "question_policy": evidence["question_policy_basis"],
                },
                collapsed=True,
            )
        stages = case["attributes"].get("stage_observations", [])
        block(
            record,
            "Application stages",
            "Stage sequence",
            [
                {
                    "stage": s["name"],
                    "started_at": s["started_at"],
                    "finished_at": s["finished_at"],
                    "status": s["attributes"].get("status"),
                }
                for s in stages
            ],
        )
        for stage in stages:
            block(
                record,
                "Application stages",
                stage["name"] + " · captured attributes",
                stage["attributes"],
                collapsed=True,
            )
        case_remote = [
            row
            for row in remote
            if row["attributes"].get("chat_session_id") == output["chat_session_id"]
            or row["parent_span_id"] in {s["span_id"] for s in stages}
        ]
        if case_remote:
            block(
                record,
                "Application stages",
                "Live Logfire observations · queried for this run",
                case_remote,
                collapsed=True,
            )
        for index, exchange in enumerate(output["messages"]):
            exchange_name = f"{index + 1}. {exchange['component']} · {exchange['status']} · {exchange['started_at']}"
            for message in exchange["messages"]:
                if message.get("instructions"):
                    text = message["instructions"]
                    block(
                        record,
                        "Model exchanges",
                        "Instructions",
                        text,
                        "system",
                        collapsed=True,
                        boilerplate=repeated[text] > 1,
                        exchange=exchange_name,
                    )
                for part in message["parts"]:
                    kind = part["part_kind"]
                    role = (
                        "user"
                        if kind == "user-prompt"
                        else "thinking"
                        if kind == "thinking"
                        else "tool"
                        if kind.startswith("tool-")
                        else "system"
                        if kind == "system-prompt"
                        else "assistant"
                    )
                    content = part.get("content", part.get("args", part))
                    format = "thinking" if kind == "thinking" else "prose"
                    if isinstance(content, str):
                        try:
                            content = json.loads(content)
                        except ValueError:
                            pass
                    block(
                        record,
                        "Model exchanges",
                        kind
                        + (" · " + part["tool_name"] if part.get("tool_name") else ""),
                        content,
                        role,
                        format,
                        collapsed=role == "tool"
                        and len(str(content)) > 1500
                        or kind == "user-prompt"
                        and len(str(content)) > 8000,
                        exchange=exchange_name,
                    )
            block(
                record,
                "Model exchanges",
                "Request settings and structured output schema",
                {
                    "model_settings": exchange["model_settings"],
                    "request_parameters": exchange["request_parameters"],
                    "exception_type": exchange.get("exception_type"),
                },
                "system",
                collapsed=True,
                exchange=exchange_name,
            )
        primary_length = len(output["rendered_text"] or "")
        selected_chunks = sum(len(s["passages"]) for s in grounding.get("sources", []))
        structural_failures = sum(
            b["status"] == "failed" for b in execution.get("outcomes", [])
        )
        numbers = [
            len(output["question"]),
            primary_length,
            len(output["messages"]),
            selected_chunks,
            case["task_duration"],
            structural_failures,
        ]
        raw_features.append(numbers)
        feature_rows.append(
            [np.log1p(v) for v in numbers]
            + [int(reference["feature"] == f) for f in families]
            + [int(reference["scenario"] == s) for s in scenarios]
            + [int(reference["domain_familiarity"] == f) for f in familiarity]
            + [int(outcome == o) for o in outcomes]
        )
        records.append(record)

    # Only one flag per genuine upper-tail structural outlier; ties at the cutoff
    # do not turn a common outcome into an outlier.
    raw = np.asarray(raw_features)
    for i, record in enumerate(records):
        for column, label in [
            (1, "output characters"),
            (3, "selected chunks"),
            (4, "seconds"),
        ]:
            percentile = float(np.mean(raw[:, column] < raw[i, column]))
            if percentile >= 0.9:
                record["flags"] = [
                    f"{raw[i, column]:.0f} {label} · more than {percentile:.0%} of cases"
                ]
                break
    matrix = StandardScaler().fit_transform(np.asarray(feature_rows))
    model = KMeans(n_clusters=8, random_state=20260930, n_init=20).fit(matrix)
    projection = PCA(n_components=2, random_state=20260930).fit_transform(matrix)
    representatives = []
    for cluster in range(8):
        members = np.flatnonzero(model.labels_ == cluster)
        ranked = sorted(
            members,
            key=lambda i: float(
                np.linalg.norm(matrix[i] - model.cluster_centers_[cluster])
            ),
        )
        representatives.append(int(ranked[0]))
        first = records[ranked[0]]
        second = next(
            (
                int(i)
                for i in ranked[1:]
                if (
                    records[i]["scenario"],
                    records[i]["familiarity"],
                    records[i]["outcome"],
                )
                != (first["scenario"], first["familiarity"], first["outcome"])
            ),
            None,
        )
        if second is not None:
            representatives.append(second)
    # 16 centroid representatives plus 8 random nonrepresentatives = 24 cases.
    # Singleton clusters can reduce the representative count.
    representatives = list(dict.fromkeys(representatives))[:16]
    rng = np.random.default_rng(20260930)
    remaining = [i for i in range(len(records)) if i not in representatives]
    random_count = max(8, round(len(representatives) / 2))
    random_indices = [
        int(i) for i in rng.choice(remaining, size=random_count, replace=False)
    ]
    selected = representatives + random_indices
    data_dir.mkdir(parents=True, exist_ok=True)
    save(data_dir / "records.json", records)
    save(
        data_dir / "graph.json",
        {
            "cluster_count": 8,
            "method": "KMeans on standardized features; PCA 2D projection",
            "seed": 20260930,
            "feature_names": [
                "log question length",
                "log output length",
                "log exchange count",
                "log selected chunks",
                "log duration",
                "log failed branch count",
            ]
            + families
            + scenarios
            + familiarity
            + outcomes,
            "points": [
                {
                    "id": r["id"],
                    "question": r["question"],
                    "scenario": r["scenario"],
                    "outcome": r["outcome"],
                    "cluster": int(model.labels_[i]),
                    "x": float(projection[i, 0]),
                    "y": float(projection[i, 1]),
                }
                for i, r in enumerate(records)
            ],
        },
    )
    if not (data_dir / "samples.json").exists():
        save(
            data_dir / "samples.json",
            {
                "record_ids": [records[i]["id"] for i in selected],
                "selection": {
                    "seed": 20260930,
                    "method": "centroid representatives plus seeded random cases",
                    "representatives": [records[i]["id"] for i in representatives],
                    "random": [records[i]["id"] for i in random_indices],
                    "purpose": "failure discovery; not prevalence estimation",
                },
            },
        )
    for name in ["annotations", "patterns", "suggestions"]:
        if not (data_dir / (name + ".json")).exists():
            save(data_dir / (name + ".json"), [])
    save(
        data_dir / "manifest.json",
        {
            "report": str(report_path.relative_to(ROOT)),
            "report_sha256": digest,
            "case_count": len(records),
            "model": report["model"],
            "trace_url": report["trace_url"],
            "ran_at": report["ran_at"],
            "outcomes": dict(Counter(r["outcome"] for r in records)),
            "constant_fields": [
                "deployment",
                "model",
                "approval_mode",
                "label_quality",
            ],
            "content": "question, preparation, output, selected evidence, corpus references, model exchanges",
            "dimensions": "authored feature/scenario/familiarity, stage outcome, length, exchanges, passages, duration",
            "hypotheses_to_inspect": [
                "rewrite changes the requested result or time scope",
                "coverage explanation claims absence before retrieval",
                "policy blocks a source-supported reporting question",
                "selected passages fail to satisfy the question",
                "guidance cannot pass output validation",
            ],
            "hypotheses_are_labels": False,
        },
    )
    if telemetry:
        save(data_dir / "logfire-observations.json", telemetry)
    chosen = [records[i] for i in selected]
    print(
        f"Prepared {len(records)} cases; {len(representatives)} centroid representatives + {len(random_indices)} random cases"
    )
    print("Sample outcomes:", dict(Counter(r["outcome"] for r in chosen)))
    print("Sample scenarios:", dict(Counter(r["scenario"] for r in chosen)))
    print("Data:", data_dir)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--telemetry", type=Path)
    args = parser.parse_args()
    prepare(args.report.resolve(), args.data_dir.resolve(), args.telemetry)


if __name__ == "__main__":
    main()
