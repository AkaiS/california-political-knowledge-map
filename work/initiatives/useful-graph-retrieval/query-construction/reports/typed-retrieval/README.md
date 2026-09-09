# Typed parameterized retrieval prototype

This throwaway terminal prototype asks whether a model can map the unchanged
target question set onto a closed catalog of typed retrieval queries, while
keeping evidence, temporal ambiguity, decline, and deferral visible. It also
runs five deterministic checks against the primary ontology. Those checks do
not claim the corresponding nodes exist in the populated News Ontology graph.

Run the live model selection and read-only graph queries:

```sh
uv run python -m knowledge_map.prototypes.typed_retrieval.run
```

Run one or more authored cases with `--cases E1-2 C-1`.

If the model or graph is unavailable, inspect wiring without making empirical
claims:

```sh
uv run python -m knowledge_map.prototypes.typed_retrieval.run --offline-demo
```

The JSON report is written beside this README as `observed-report.json` by default.

The first live request failed before inference because llama.cpp could not parse
the JSON Schema grammar generated for regex-constrained optional date strings.
`first-run-failure.json` records the server response. The working version keeps
the same `YYYY-MM-DD` check in Pydantic after-validation, where it does not enter
the server grammar.

Before the observed run, all twelve fixed query templates were sent to Neo4j
with `EXPLAIN`. Neo4j classified every template as a read query. Warnings were
limited to known absent funding properties and the deprecated `id()` function.

## Observed result

The default local `gemma4:26b` deployment processed the 42 questions as
separate bounded calls in 151.9 seconds. A runner serialization bug occurred
after each successful model result, but the report retained every final raw
response. `recover.py` parsed those responses without another model run. It
recovered 29 type-valid selections and left 13 structured-output failures
unchanged. Those failures exhausted two correction attempts because the model
kept omitting a required parameter. Final-response usage for recovered cases is
a lower bound of 16,632 input and 2,117 output tokens. Retry usage is unknown.

Of the 29 recovered selections, 14 agreed with the authored question family.
Treat this as a heuristic, since the outcome-5 disposition is unsettled. Four
queries returned evidence and fifteen matched no seed or covered edge. The
Steve Hilton dossier returned two grounded rows. Proposition 38 campaign
funding returned one evidence-bearing edge, but the edge has no amount or date
Claim Key. The same-side case correctly stopped at a coverage gap because all
populated stance edges lack alignment.

Two wrong selections returned plausible but unrelated graph evidence. The
Texas question ran a California housing sweep, and the repeated-opposition
question ran a global policy-area distribution. A typed catalog prevents
invented Cypher, but type validity alone does not make routing safe. The model
also supplied `"measure"` as an Organization sub-label, which shows that those
parameters need closed ontology values rather than plain strings.

The two-case post-fix smoke is in `smoke-report.json`. Steve Hilton completed in
two model requests and returned two grounded rows. The policy-area distribution
still exhausted bounded correction because it omitted `topic="*"`, confirming
that the correction failure belongs to model output rather than the recovered
runner bug.

## Verified-question follow-up

The follow-up keeps every original report above intact and uses the 25 questions
in `questions.yaml`. That file copies only question text from the verified case
guide. Reference queries, parameters, results, and evidence stay outside the
constructor's input.

The model receives one opaque question id, one question, the construction
instruction from the case guide, the persisted `news-ontology.md`, and the
closed query catalog. It cannot decline or defer a case. Fourteen reusable
templates cover entity and measure reporting, Policy Area retrieval, recorded
relationships, co-mentions, funded Campaign targets, reported votes, and Bill
referrals. The runner records the exact instruction and hashes, every model
response and repair, cumulative usage, timings, selected parameters, full graph
rows, and resolved Grounding Evidence.

Compile every template without calling the model:

```sh
UV_CACHE_DIR=/private/tmp/ca-map-uv-cache uv run --no-sync python \
  -m knowledge_map.prototypes.typed_retrieval.run --explain-only
```

Run the 25 model selections and graph reads sequentially:

```sh
UV_CACHE_DIR=/private/tmp/ca-map-uv-cache uv run --no-sync python \
  -m knowledge_map.prototypes.typed_retrieval.run
```

The new run writes `verified-question-report.json`. A graph row is only an
observation. Semantic review must compare the requested entities, articles,
counts, and evidence for each claim with the evaluator-only references.

The first complete follow-up batch is preserved in that report. It took 246.7
seconds. Seventeen selections reached the graph, twelve returned rows, and eight
ended when cumulative use exceeded the 12,000-token case limit during bounded
correction. [verified-question-assessment.md](verified-question-assessment.md)
records the semantic review and measurement limits.
