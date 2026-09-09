# Compiler-assigned pattern-selection prototype

This throwaway experiment asks whether moving handles, claim ids, binding slots,
descriptions, and projection aliases into the compiler reduces malformed semantic
plans without dropping joins, filters, unions, sub-labels, output fields, or
per-claim Grounding Evidence. It runs the same 25 development questions through
the model-selected structure plus the original binder and a privileged supplied-
structure diagnostic control. It has no graph-backed entity resolver.

Run the deterministic interface smoke:

```sh
UV_CACHE_DIR=/private/tmp/ca-map-uv-cache uv run --no-sync python -m knowledge_map.prototypes.pattern_selection.run --smoke
```

Run and preserve a fresh full batch:

```sh
UV_CACHE_DIR=/private/tmp/ca-map-uv-cache uv run --no-sync python -m knowledge_map.prototypes.pattern_selection.run --arm all --output src/knowledge_map/prototypes/pattern_selection/results/full-report.json
```

References enter the report only after inference. Do not overwrite the frozen
report for a fix or replay; use a new output path.

Audit the frozen batch without model or graph calls:

```sh
UV_CACHE_DIR=/private/tmp/ca-map-uv-cache uv run --no-sync python -m knowledge_map.prototypes.pattern_selection.audit
```

The frozen run failed its prospective gate: 2/25 model-selected retrievals were
complete and 18/25 patterns were rejected, compared with 11/25 complete and
13/25 rejected in the corrected prior baseline. See `findings.md` and
`results/assessment.json` for every case and the preserved usage totals.
