# Graph-backed entity-resolution prototype

This throwaway prototype asks whether a read-only candidate-resolution stage fixes value binding when the retrieval pattern is already correct. Both arms use the same evaluator-authored pattern and the same first binder response. The control executes the binder's literal value. The resolver queries candidate project identities under the pattern's exact node label and same-node scope, asks for explicit selection, ambiguity, or no-match, then binds the selected project id.

Candidate rows are deduplicated by project id. They include every stored name for that identity, labels, Bill session where present, and a Campaign's stored target metadata. The resolver cannot change the label or relax a session. It cannot bind a candidate or measure id where the pattern requires a Campaign.

Run deterministic read-only graph checks without a model call:

```sh
UV_CACHE_DIR=/private/tmp/ca-map-uv-cache uv run --no-sync python -m knowledge_map.prototypes.entity_resolution.run --smoke
```

Run the fresh 25-case comparison after the coordinator grants the inference slot:

```sh
UV_CACHE_DIR=/private/tmp/ca-map-uv-cache uv run --no-sync python -m knowledge_map.prototypes.entity_resolution.run --output src/knowledge_map/prototypes/entity_resolution/results/fresh-report.json
```

References enter the report only after every model call. Runtime binding and candidate selection cannot read evaluator queries, parameters, rows, or evidence.

Audit the frozen output after the run:

```sh
UV_CACHE_DIR=/private/tmp/ca-map-uv-cache uv run --no-sync python -m knowledge_map.prototypes.entity_resolution.audit src/knowledge_map/prototypes/entity_resolution/results/fresh-report.json
```

The candidate shortlist is bounded at eight project identities. The report retains the full identity count, cutoff ties, and whether a top-score tie crossed the cutoff. Lexical top-eight recall on these development cases does not establish semantic recall for new questions.

The untouched frozen output is [fresh-report.json](results/fresh-report.json). [fresh-audit.json](results/fresh-audit.json) is the evaluator-side semantic audit, [reference-recheck.json](results/reference-recheck.json) is the pre-inference graph snapshot, and [findings.md](findings.md) records the verdict and per-case outcomes. Replay or rescue inference must use a new output path.
