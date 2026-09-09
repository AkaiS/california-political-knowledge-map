# Keyed selector, composer, and binder prototype

This throwaway prototype tests three separate stages over the same 25 verified graph-retrieval questions.

1. A selector returns only stable integer keys for ontology triples, unbound filters, outputs, distinct roles, and the supported grouped count.
2. Code resolves those pieces and enumerates compiler-valid complete wirings. Code bypasses the composer model only when exactly one canonical wiring remains across joins, filter targets, output roles, distinctness, and aggregation. With 2 through 50 candidates, a composer model chooses one offered id. Larger sets fail explicitly.
3. The existing required-slot binder fills values from the question. There is no graph-backed entity resolver.

The catalog has 89 pieces: 47 triple pieces, 14 filters, 15 outputs, 12 distinct-role pieces, and one grouped count. It is generated from the supported labels, properties, operators, and News Ontology relationships. It has no whole-question templates, case matching, expected values, or reference data. Code owns direction, handles, joins offered to the composer, slot names, aliases, Cypher, and Grounding Evidence traversal.

Run the no-model interface and all-25 authored-piece coverage check:

```sh
UV_CACHE_DIR=/private/tmp/ca-map-uv-cache uv run --no-sync python -m knowledge_map.prototypes.selector_composer_binder.smoke
```

Run a fresh end-to-end batch only when a new experiment is intended:

```sh
UV_CACHE_DIR=/private/tmp/ca-map-uv-cache uv run --no-sync python -m knowledge_map.prototypes.selector_composer_binder.run
```

Build the offline assessment of the frozen report:

```sh
UV_CACHE_DIR=/private/tmp/ca-map-uv-cache uv run --no-sync python -m knowledge_map.prototypes.selector_composer_binder.audit
```

The primary frozen run is [results/full-report.json](results/full-report.json), and its offline assessment is [results/assessment.json](results/assessment.json). The full report contains the exact catalog, prompts, JSON schemas, raw HTTP requests and responses, usage, compositions, compiled queries, bindings, execution rows, and evaluator references. [results/interface-smoke.json](results/interface-smoke.json) proves all 25 evaluator-authored patterns are representable without making model or graph calls.

[results/supplied-key-composer-diagnostic.json](results/supplied-key-composer-diagnostic.json) is a separate Q16/Q17 stage check. It bypasses the failed selector with evaluator-authored keys to exercise the two-choice composer. It is privileged diagnostic evidence and is excluded from the primary end-to-end score.

The driver uses the repository's local configured model sequentially, disables external telemetry with the test context, and performs only read-only Neo4j calls. References enter reports only after all model calls finish. Do not rerun failed cases to improve the frozen result.
