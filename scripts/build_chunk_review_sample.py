"""Freeze a balanced random sample from each retrieval attempt's fused top ten."""

import argparse
import asyncio
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv
from neo4j import AsyncGraphDatabase

from knowledge_map.adapters.evidence import EvidenceStore
from knowledge_map.evaluation.chunk_review import (
    candidate_pools,
    project_sample,
    sample_pairs,
)


async def build_sample(paths: list[Path], *, size: int, seed: int) -> dict:
    sources, pools = [], []
    for path in paths:
        content = path.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        if any(source["sha256"] == digest for source in sources):
            raise ValueError("the same report cannot be sampled twice")
        document = json.loads(content)
        report_pools = candidate_pools(document, digest)
        sources.append(
            {
                "path": str(path),
                "sha256": digest,
                "attempts": len(report_pools),
                "eligible_per_attempt": [len(pool) for pool in report_pools],
            }
        )
        pools.extend(report_pools)
    selected = sample_pairs(pools, size=size, seed=seed)
    missing = [c for c in selected if c["output"]["text"] is None]
    if missing:
        load_dotenv()
        async with AsyncGraphDatabase.driver(
            os.environ.get("NEO4J_URI", "bolt://localhost:7687"),
            auth=(
                os.environ.get("NEO4J_USERNAME", "neo4j"),
                os.environ.get("NEO4J_PASSWORD", ""),
            ),
        ) as driver:
            store = EvidenceStore(
                driver, database=os.environ.get("NEO4J_DATABASE", "neo4j")
            )
            loaded = {}
            for case in missing:
                metadata = case["metadata"]
                key = (metadata["chunk_id"], metadata["source_article_id"])
                if key not in loaded:
                    grounding = await store.load_chunk(
                        chunk_id=key[0], source_article_id=key[1]
                    )
                    loaded[key] = (grounding.text, datetime.now(UTC).isoformat())
                text, observed_at = loaded[key]
                case["output"]["text"] = text
                metadata.update(text_origin="graph", text_observed_at=observed_at)
    for case in selected:
        case["metadata"]["text_sha256"] = hashlib.sha256(
            case["output"]["text"].encode()
        ).hexdigest()
    sample = {
        "task": "chunk_relevance",
        "ran_at": datetime.now(UTC).isoformat(),
        "sampling": {
            "version": 1,
            "ranking": "fused",
            "k": 10,
            "seed": seed,
            "size": size,
            "population": sum(map(len, pools)),
            "method": "balanced_random_per_attempt_then_shuffled",
            "source_reports": sources,
        },
        "report": {"cases": selected},
    }
    project_sample(sample)
    return sample


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, action="append", required=True)
    parser.add_argument("--size", type=int, default=200)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("sample already exists; use a new output to preserve its labels")
    sample = asyncio.run(build_sample(args.report, size=args.size, seed=args.seed))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as file:
        json.dump(sample, file, ensure_ascii=False, indent=2)
        file.write("\n")
    print(f"Wrote {len(sample['report']['cases'])} pairs to {args.output}")
    print(
        f"Graph-loaded text: {sum(c['metadata']['text_origin'] == 'graph' for c in sample['report']['cases'])}"
    )


if __name__ == "__main__":
    main()
