# Composable ontology triples experiment

Follow-up to the [generated-Cypher and typed-query comparison](comparison.md)
for [issue 05](../issues/05-prototype-query-construction-and-validation.md).

## Question and experiment

Can a model express the requested graph pattern using allowed ontology triples
and named variables, leaving Cypher construction and Grounding Evidence
retrieval to deterministic code? Does a second model call for entity and
property bindings help?

The maintainer requested a separate worktree and a Sol agent at medium reasoning.
The throwaway branch is `codex/prototype-composable-triples`, based on `85275ab`,
at `/private/tmp/ca-map-prototype-composable-triples-20260908`. The repository
setup script completed with frozen uv dependencies.

The coordinator reran all 25 reference queries on 2026-09-08. Every saved field
except inspection time matches the original verification, including all case
results, label counts, and 533 supporting Article Chunks.

The proposed measurement arms are:

- Supply a correct, authored semantic pattern and ask the model only for
  bindings. The pattern is privileged input in this arm; expected values and
  results remain hidden.
- Ask one model call for the pattern, derive the required binding slots, then
  ask a second call for bindings.
- Ask one model call for both pattern and bindings, using the same compiler.

All model calls run sequentially on the local deployment. The models receive
questions with opaque identifiers, ontology-derived choices, and neutral
storage rules. Reference Cypher, parameter values, and expected results remain
evaluator-only. These are development cases, not held-out evidence.

The audit will distinguish compilation or binding failures, executed empty
results, correctly scoped retrieval, and results that merely match the current
graph by accident. Grounding Evidence must support each claim in a composed
path. Different row layouts and equivalent evidence representations are allowed.

## Interface checks before the batch

Six live compiler smokes passed: shared-Bill intersection with inequality,
funding chains to both target labels, mixed Chunk/article provenance, a vote
predicate union, and grouped article counts. The mixed-provenance smoke caught
an implicit Cypher aggregation problem, which was fixed before inference.

A preserved model interface smoke on the same-side case showed two avoidable
interface problems. A model could reverse endpoints even where the ontology
uniquely determined direction, and optional constraint lists could be omitted
while constraints appeared only in prose. The coordinator requested unique
ontology-based orientation and required structured constraint lists before the
full batch. Those changes apply equally across arms; the preliminary smoke
remains separate from the frozen batch.

The compiler may normalize an edge's orientation when only one orientation is
permitted by the declared endpoint labels. It must not change the selected
relationship, joins, or filters based on the question. Ambiguous or invalid
orientations remain explicit failures.

## Implemented responsibilities

The pattern contract declares node variables, predicate choices, joins through
shared variables, constraints, id inequalities, return fields, and one grouped
distinct-count operation. The compiler validates a supported subset against
the News Ontology and generates Cypher from those declarations. It does not
inspect question text or case ids to select query structure.

For each compiled pattern, the binder receives only the required slot names
and their descriptions, together with the original question and shared context.
Its Pydantic output schema makes those slots required. Canonical Policy Area
names and a generic half-open calendar-month rule appear consistently in the
shared context. There is no graph-backed candidate-resolution tool in this run.

The single-call arm uses the same pattern contract and compiler, but emits a
generic list of slot/value bindings because its pattern is not yet known when
the call starts. This output-schema difference is part of the tested design;
the comparison cannot attribute a result gap to call count alone.

The runner captures HTTP request and response bodies locally before Pydantic AI
validates output or checks cumulative token usage. That preserves the responses
which the prior typed runner lost at its token limit. References enter only the
offline report assembly after model calls.

## Frozen batch findings

All 75 case/arm combinations completed in 663.95 seconds. The runner captured
90 provider responses, including all output-correction responses and the
single-call arm's token-limit failure. No model calls were repeated after the
batch to improve its results.

| Frozen outcome | Supplied pattern + binder | Two-stage | Single-call |
| --- | ---: | ---: | ---: |
| Complete retrievals in coordinator audit | 22 | 8 | 6 |
| Executed empty query | 3 | 1 | 3 |
| Compiler-generated duplicate-column error | 0 | 3 | 2 |
| Pattern rejected before execution | 0 | 13 | 10 |
| Binding rejected before execution | 0 | 0 | 3 |
| Model token-limit failure | 0 | 0 | 1 |

Every nonempty result has exactly the reference set of evidence ids. The
coordinator also inspected the selected relationships and constraints in the
successful model-selected patterns. Equivalent grouping is allowed: the
supplied-pattern housing and labor outputs use one row per Chunk, while the
single-call outputs group by article.

The supplied-pattern arm retrieves 22 complete answers, including both votes,
both shared-side intersections, both campaign-target alternatives, all 26
Policy Area counts, and the topic/time cases. Its three failures shorten
`Steve Hilton campaign`, `Yes on Proposition 38 campaign`, and
`Ed Musgrove campaign` by dropping `campaign`. Required fields solve missing
bindings, but literal extraction does not solve entity resolution.

The two-stage arm produces twelve compiler-valid patterns, and all twelve
binding calls return schema-valid bindings. Thirteen other patterns are rejected
for undeclared node references, unsupported connections, invalid aggregate
projections, repeated claim names, or a return target naming an undeclared
variable. Most are malformed model plans, not absent capabilities in the
compiler. The supplied-pattern arm demonstrates that the same compiler can
execute those question families.

The single-call arm has three exact-slot mismatches, ten pattern rejections,
and one token-limit failure in addition to executed outcomes. Its generic
binding list admits extra entries that the pattern-specific binder schema
rejects at output validation.

Pattern-stage descriptions sometimes contain concrete values from the question,
despite instructions to omit binding values. This is not reference leakage,
but it means the two stages do not maintain a strict division of work. For
example, the shortened `Steve Hilton` campaign name appears in the selected
slot description and the binding agent repeats it.

## Captured inference cost

| Stage | Provider responses | Input plus output tokens | Summed HTTP time |
| --- | ---: | ---: | ---: |
| Supplied-pattern binding | 25 | 87,451 | 21.75 seconds |
| Two-stage pattern selection | 25 | 101,770 | 254.59 seconds |
| Two-stage binding | 12 | 41,808 | 12.56 seconds |
| Single-call pattern and binding | 28 | 127,999 | 368.95 seconds |

These sum to 359,028 tokens across 90 captured provider responses. The separate
prechange interface smoke is excluded. The two-stage total is 143,578 tokens
across 37 responses. HTTP time includes response-body retrieval; it is distinct
from full batch wall time and is sensitive to local prompt caching and arm order.

## Compiler correction and offline replay

The frozen batch exposed a compiler defect: repeated projections passed
validation but generated duplicate result-column names. The compiler now
deduplicates identical projections. Five affected cases were replayed against
the graph using their saved patterns and bindings, with no model calls and no
reference substitutions. All five executed with the exact expected evidence
sets. The original report remains unchanged.

| Complete retrievals | Frozen run | With compiler-only replay |
| --- | ---: | ---: |
| Supplied pattern + binder | 22/25 | 22/25 |
| Two-stage pattern + binder | 8/25 | 11/25 |
| Single-call pattern + bindings | 6/25 | 8/25 |

The recovered cases are two-stage Q01, Q02, Q04 and single-call Q01, Q02.
The coordinator independently confirmed their unchanged bindings, correct
query scope, and exact reference evidence sets. This correction isolates a
compiler defect from model quality; it is not a new inference run.

## Interpretation

This supports continuing the experiment. Required, pattern-specific binding
schemas worked on every supplied structure, and 22 produced the requested
retrieval. The three remaining binding misses need entity resolution rather
than more Cypher generation.

Pattern selection is still the main obstacle. Asking the model to maintain
node aliases, references, claim names, projections, joins, and filters creates
many ways to produce an invalid plan. A next interface should let deterministic
code assign variable and evidence identifiers, while the model selects allowed
triples and explicit joins. Repeated claim names should not carry more semantic
responsibility than the question requires.

The two-stage arm has three more complete retrievals than the single-call arm
after the compiler replay, but the small case set and different binding schemas
do not establish a general two-agent advantage. Neither arm is a held-out
benchmark, and these observations do not settle the production architecture.

The ontology-based orientation logic was exercised on the preserved interface
smoke. No compiler-valid pattern in the frozen full batch needed an orientation
reversal, so this run does not measure its contribution to the final score.

## Artifacts and reproduction

Branch: `codex/prototype-composable-triples`.
Committed as `2da6872`. The [archive](reports/README.md) records the persistent
tag, original paths, and blob hashes.

- [Run instructions](reports/composable-triples/README.md)
- [Per-case findings](reports/composable-triples/findings.md)
- [Frozen full report](reports/composable-triples/results/full-report.json)
- [Compiler-only replay](reports/composable-triples/results/duplicate-projection-replay.json)
- [Prechange interface smoke](reports/composable-triples/results/interface-smoke.json)

From a worktree at that prototype commit, run any one arm with a fresh output path:

```sh
UV_CACHE_DIR=/private/tmp/ca-map-uv-cache uv run --no-sync python -m knowledge_map.prototypes.composable_triples.run --arm two-stage --output .scratch/triples-two-stage-new.json
```

Replace `two-stage` with `oracle`, `single`, or `all` for the other modes.
The README also gives the no-model compiler smoke and offline replay commands.
The final compiler includes projection deduplication, so a new run differs from
the frozen batch's compiler in that documented respect.

Final checks passed: Ruff, formatting, compilation, whitespace, report integrity,
and all six live compiler smokes. The coordinator independently verified the
reference snapshot, evidence sets across nonempty results, article counts and
source sets, selected query scope, replay bindings, and captured usage totals.
No browser verification was used. Prototype code remains at the tagged
experiment commit. The [next-experiment plan](next-experiment.md) records the
proposed pattern-selection and entity-binding work.
