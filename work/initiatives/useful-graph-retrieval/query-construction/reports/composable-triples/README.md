# Composable semantic triples prototype

This throwaway prototype tests whether a model can describe retrieval as connected News Ontology triples while deterministic code owns stored direction, labels, provenance, parameterization, read-only classification, and execution. It does not expose Cypher to either model stage.

The three arms use the same 25 opaque model-side questions, persisted News Ontology, store notes, and canonical Policy Area vocabulary. Reference Cypher, parameters, rows, and evidence stay evaluator-only. The oracle arm supplies an authored semantic shape but no expected binding values or results. The two-stage arm derives a small Pydantic binding model only after its pattern compiles. The single-call arm emits the same pattern plus a generic slot/value list in one response. That last schema is intentionally less constrained, so it is an ablation of the added call rather than a perfectly symmetric interface.

Run one arm from the repository root:

```sh
UV_CACHE_DIR=/private/tmp/ca-map-uv-cache uv run --no-sync python -m knowledge_map.prototypes.composable_triples.run --arm oracle
```

```sh
UV_CACHE_DIR=/private/tmp/ca-map-uv-cache uv run --no-sync python -m knowledge_map.prototypes.composable_triples.run --arm two-stage
```

```sh
UV_CACHE_DIR=/private/tmp/ca-map-uv-cache uv run --no-sync python -m knowledge_map.prototypes.composable_triples.run --arm single
```

Run compiler and live graph smokes without model calls:

```sh
UV_CACHE_DIR=/private/tmp/ca-map-uv-cache uv run --no-sync python -m knowledge_map.prototypes.composable_triples.run --smoke
```

Replay the five frozen plans affected by the projection deduplication fix without model calls:

```sh
UV_CACHE_DIR=/private/tmp/ca-map-uv-cache uv run --no-sync python -m knowledge_map.prototypes.composable_triples.replay_duplicate_projections
```

The frozen run is [full-report.json](results/full-report.json). [duplicate-projection-replay.json](results/duplicate-projection-replay.json) keeps the original error beside each replay. [interface-smoke.json](results/interface-smoke.json) is the pre-freeze one-case run that exposed the endpoint-order burden. [findings.md](findings.md) records the result and limits.

Bindings use literal extraction from the question plus the shared canonical Policy Area vocabulary. This run did not add a graph candidate-resolution tool. The driver sets the repository's test context before agent construction so Logfire does not export telemetry. Its transport wrapper captures every local HTTP response, including structured-output retries that Pydantic AI can omit from run history after a token-limit check.
