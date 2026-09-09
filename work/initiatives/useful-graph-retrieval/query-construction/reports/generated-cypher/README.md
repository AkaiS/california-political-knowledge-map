# Generated Cypher prototype

This throwaway terminal prototype asks whether the repository's default chat
Model Deployment can construct safe, useful Cypher for the 42 authored target
questions, and whether a model critic catches enough errors to justify a second
call. It uses `gemma4:26b` through the repository model factory. Generator and
critic share that deployment. External Logfire export is disabled because the
run combines authored questions, generated queries, and graph-derived rows.

Run the complete batch from the repository root:

```console
UV_CACHE_DIR=/private/tmp/ca-map-uv-cache uv run python \
  -m knowledge_map.prototypes.generated_cypher \
  --output .scratch/generated-cypher-report.json
```

Use `--case E1-1` to run one case or `--list-cases` to inspect the exact case
inventory. Each model call has a 90-second timeout and a 1,200-token output
limit. The runner continues after a model-stage failure. It permits one repair,
but only after the generator constructs a query that deterministic validation
or the critic rejects. Before execution, Neo4j must accept `EXPLAIN` and classify
the statement as read-only. The session also uses read access mode.

## Baseline result

The untouched 2026-09-08 baseline is in
[`results/generated-cypher-report.json`](results/generated-cypher-report.json).
All 42 generator outputs chose `deferred`. None contained Cypher, so no generated
query reached `EXPLAIN`, repair, or graph execution. This means the run measured
a routing and coverage-assumption failure before it measured Cypher construction.
It gives no observed convergence rate and no evidence that generated Cypher is
correct.

The offline expected dispositions are a prototype heuristic, not a Gold Set.
They mark the 23 news-populated cases as queries, the seven Declined examples as
declined, and outcome-5 plus Deferred examples as deferred. Ticket 04 has not
settled the outcome-5 behavior, so those expectation mismatches are not accuracy
scores. Two live counterexamples do establish false deferral without relying on
that heuristic: `E1-2` deferred "Who is Steve Hilton?" even though the graph has
an exact `Politician` with two Chunks in two NewsArticles, and `E3-1` deferred the
housing sweep even though its Policy Area reaches 29 NewsArticles and 752 Chunks.

The generator also returned `deferred` for every Declined question. It therefore
lost the contract distinction between permanent refusal and a data gap. The
committee case `C-1` deferred on an alleged authoritative-data dependency even
though the news ontology declares `LegislativeEvent-HELD_BY->Committee` and
`Bill-REFERRED_TO->Committee`.

The critic cost 59,104 tokens and 176.9 seconds, compared with 63,971 tokens and
266.8 seconds for generation. Median calls were 3.78 and 6.26 seconds. It rejected
10 plans, but eight rejection explanations said the deferral was correct or
sound while setting `valid=false`. The two useful objections were `M1-1`, where
it noticed that the ontology supports a query for Uber's policy areas, and
`F-2`, where it caught the plan's false statement that the ontology omitted
`FUNDED.amount` and `FUNDED.date`. Neither led to repair because both generator
plans were non-query dispositions. The critic accepted the false `E1-2` and
`E3-1` deferrals.

That is a poor trade in this baseline. The critic added about 92% as many tokens
and 66% as much latency as generation, did not unlock repair, contradicted its
own verdict in most rejections, and missed verified false deferrals. Deterministic
checks remain necessary for read-only enforcement, ontology names, required
parameters, temporal District scope, and Neo4j compilation. The separate stress
probes in the report show those authored checks rejecting a direct primary-
ontology vote path, an incompatible structural/sub-label pair, a `CAMPAIGN_FOR`
edge to `Bill`, and a cycle-blind District match. They are authored probes, not
model-generated error observations.

`grounding_evidence_count` is only a field-name heuristic over returned values.
It counts non-empty keys containing `chunk`, `text`, or `article`; it does not
prove that a Chunk supports an answer. The baseline has no returned rows, and
the report makes no supported-answer claims. The JSON retains every initial
plan, critic verdict, latency, usage record, limitation, and stress probe so the
result can be audited without repeating model calls.

## Verified-answerable rerun

The preserved follow-up report is
[`results/generated-cypher-verified-report.json`](results/generated-cypher-verified-report.json),
with its manual audit in
[`results/generated-cypher-verified-analysis.md`](results/generated-cypher-verified-analysis.md).
It uses the 25 graph-backed construction cases in
[`query_construction_cases.yaml`](query_construction_cases.yaml). The generator
sees only the common construction instruction, natural-language question, the
generated `news-ontology.md`, and four neutral notes about persisted dates,
provenance, article-level topics, and Bill designation/session. Source ids,
families, scope notes, reference queries, expected rows, and evidence are kept
out of both model prompts. `query_construction_expected.json` is a compact
evaluator-only projection of the coordinator's verified result file.

Run the complete batch from the repository root:

```console
UV_CACHE_DIR=/private/tmp/ca-map-uv-cache uv run python \
  -m knowledge_map.prototypes.generated_cypher_verified \
  --output src/knowledge_map/prototypes/results/generated-cypher-verified-report.json
```

This batch is frozen as the first complete new-set run. Reruns after prompt or
validator changes need a different output name and `run_kind`; overwriting it
would erase the baseline needed to measure those changes.

Use the manual audit's outcome counts rather than the raw report's
`empty_results` summary. That field conflates six queries that executed and
returned no rows with four repaired plans stopped by final deterministic or
`EXPLAIN` validation. The frozen case records contain enough provenance to
separate them without another model run.
