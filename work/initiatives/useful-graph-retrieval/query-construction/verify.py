"""Recheck the authored construction cases against the current graph, read-only."""

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import yaml
from dotenv import load_dotenv
from neo4j import GraphDatabase, Query
from neo4j.exceptions import Neo4jError

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]


def canonical(value):
    if isinstance(value, dict):
        return {key: canonical(item) for key, item in sorted(value.items())}
    if isinstance(value, list):
        items = [canonical(item) for item in value]
        return sorted(items, key=lambda item: json.dumps(item, sort_keys=True))
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / ".scratch/query-construction/verification.json",
    )
    args = parser.parse_args()
    path = HERE / "cases.yaml"
    data = yaml.safe_load(path.read_text())
    load_dotenv(ROOT / ".env")
    report = {
        "checked_at": datetime.now(UTC).isoformat(),
        "cases_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "interpretation": "Reference retrieval results against the stored graph, not independently verified political facts or a formal Gold Set.",
        "cases": [],
    }
    evidence_ids = set()
    with (
        GraphDatabase.driver(
            os.getenv("NEO4J_URI", "bolt://localhost:7687"),
            auth=(
                os.getenv("NEO4J_USERNAME", os.getenv("NEO4J_USER", "neo4j")),
                os.getenv("NEO4J_PASSWORD"),
            ),
            connection_timeout=10,
        ) as driver,
        driver.session(
            default_access_mode="READ", database=os.getenv("NEO4J_DATABASE", "neo4j")
        ) as session,
    ):

        def inspect(tx):
            report["labels"] = tx.run(
                "MATCH (n) UNWIND labels(n) AS label RETURN label,count(*) AS count ORDER BY label"
            ).data()
            report["original_m4_path_count"] = tx.run(
                "MATCH (:Organization)-[:FUNDED]->(:Campaign)-[:CAMPAIGN_FOR]->(:Politician)-[:DECLARED_STANCE]->(:Bill) RETURN count(*) AS count"
            ).single()["count"]
            for case in data["cases"]:
                query = case["reference"]["cypher"]
                parameters = case["reference"]["parameters"]
                entry = {
                    "id": case["id"],
                    "family": case["family"],
                    "question": case["question"],
                }
                try:
                    summary = tx.run(
                        Query("EXPLAIN " + query, timeout=20), parameters
                    ).consume()
                    if summary.query_type != "r":
                        raise ValueError(
                            f"Expected read query, got {summary.query_type}"
                        )
                    result = tx.run(Query(query, timeout=30), parameters)
                    rows = canonical(result.data())
                    if not rows:
                        raise ValueError("Reference query returned no rows")
                    for row in rows:
                        groups = row.get("evidence_groups", [])
                        if not groups or any(not group.get("ids") for group in groups):
                            raise ValueError(
                                "A result is missing evidence for a path segment"
                            )
                        for group in groups:
                            evidence_ids.update(group["ids"])
                    entry.update(row_count=len(rows), rows=rows)
                except (Neo4jError, ValueError) as error:
                    entry["error"] = f"{type(error).__name__}: {error}"
                report["cases"].append(entry)
                print(
                    entry["id"], entry.get("row_count", entry.get("error")), flush=True
                )
            chunks = tx.run(
                Query(
                    """
                MATCH (c:Chunk) WHERE c.id IN $ids
                OPTIONAL MATCH (a:NewsArticle)-[:HAS_CHUNK]->(c)
                RETURN c.id AS id,c.text AS text,a.id AS article_id,
                       a.title AS article_title,a.published_date AS published_date
            """,
                    timeout=30,
                ),
                ids=sorted(evidence_ids),
            ).data()
            return chunks

        chunks = inspect(session)
    by_id = {chunk["id"]: chunk for chunk in chunks}
    report["evidence"] = canonical(chunks)
    report["unresolved_evidence_ids"] = sorted(
        id
        for id in evidence_ids
        if id not in by_id or not by_id[id]["text"] or not by_id[id]["article_id"]
    )
    report["all_cases_verified"] = not report["unresolved_evidence_ids"] and all(
        "error" not in case for case in report["cases"]
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(
        f"Verified: {report['all_cases_verified']}; distinct evidence chunks: {len(by_id)}"
    )
    if not report["all_cases_verified"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
