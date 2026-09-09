# Prototype query construction and validation against the ontology

Labels: wayfinder:prototype, ready-for-human
Parent: [Useful Graph Retrieval](../MAP.md)
Inputs: [Target question set](02-target-question-set.md), [Retrievable scope and answer policy](04-retrievable-subgraph-now.md), [Current graph inventory](../research/04-graph-inventory-2026-09-08.md)

## Question

Can an LLM construct correct Cypher against this ontology, and does a validating
critic earn its cost?

This is the central architectural choice of the retrieval layer and it is
empirical, not arguable: generated Cypher over the ontology, versus a fixed set
of typed parameterized retrieval primitives the model selects among. Build
throwaway code against the real populated graph and run the target question set
through both.

For the next construction comparison, use the
[verified construction questions](../query-construction/README.md), which
instantiate the target families against the current populated graph. Keep
Declined and Deferred controls in a separate routing experiment.

Probe the indirections most likely to break generation:

- News Ontology Shortcut Rules: news connects `Politician` directly to a
  `LegislativeEvent` for votes and to a `Committee` for membership. The primary
  ontology routes those relationships through `LegislativeTenure`, which the
  current graph excludes. Queries must use the available news shape.
- The sub-label convention, where a node carries `:Organization` plus one or
  more of `:PAC`, `:LaborUnion`, and the rest.
- Relationships whose target is a union, such as `CAMPAIGN_FOR` reaching either
  a `Prop` or a `Politician`.
- Deferred questions requiring `District` and `RedistrictingCycle`, which the
  current graph excludes. Recognize the coverage limit and find partial news
  evidence where possible. Full event-time and redistricting semantics remain
  future work under issue 04.

Then answer the validation half: what classes of error appear, whether a critic
detects them, whether bounded repair converges, and whether validation is better
served by a model critic or by deterministic checks against the schema.

Link the prototype as an asset. Record the observed error classes — the agent
topology and the contract's failure states both depend on them.

## Starting conditions, 2026-09-08

The inventory provides a populated graph suitable for this experiment: 98
Source Articles and 2,407 embedded Article Chunks. Completing the remaining
population work is not a prerequisite for comparing query construction methods.
Use read-only queries against the observed graph; do not repair or reingest it
as part of this prototype.

Both approaches must receive the same available ontology and coverage context.
Their job is to retrieve Grounding Evidence for the librarian-style Retrieval
Answer agreed in issue 04. Keep query-construction failures separate from
coverage limits and defects already present in the data:

- All 174 stance edges lack alignment, and all 12 funding edges lack amount and
  date. Their chunks may still supply those details. Do not score missing graph
  properties as generation errors or treat shared stance topology as same-side
  evidence.
- Thirty-four Organization IDs are duplicated across 70 nodes, and 22 Bills
  lack sessions. Raw node counts and ambiguous cross-article joins do not
  establish real-world identities or exhaustive totals.
- The full M4 influence-chain path and the joined Bill–event–Committee path are
  empty. Some individual vote paths and committee referrals exist. Distinguish
  valid empty results from incorrect Cypher, and preserve Deferred coverage.
- Topic discovery uses `PolicyArea <- DISCUSSES_TOPIC - NewsArticle
  - HAS_CHUNK -> Chunk`, not a chunk-level topic edge.

The target questions remain unchanged. Label what each experiment can establish
from current evidence, including cases where only partial reporting is available.

## Blocking

- Blocks: Decide the retrieval agent topology and orchestration.

## Comments

### 2026-09-08: Prototype construction

Two Sol agents at medium reasoning constructed the alternatives in separate
worktrees from `85275ab`. The orchestrator records the shared live graph baseline,
comparison rules, and results in
[prototype-comparison.md](../prototype-comparison.md). Prototype code stays on
the throwaway branches `codex/prototype-generated-cypher` and
`codex/prototype-typed-retrieval`.

The generated-Cypher asset is committed as `6633c18`; the typed-retrieval asset
as `2509811`. Both contain run instructions and observed reports. The generated
baseline deferred all 42 questions, while the typed run yielded 29 type-valid
selections and 13 exhausted parameter-correction failures. Typed graph replay
returned rows for four questions, including two semantic misroutes. The critic
accepted independently verified false deferrals. The comparison records costs,
failure classes, runtime defects, and the limits of these measurements.

Prototype construction is complete and ready for review. The architectural
question remains open: this generated-Cypher baseline never generated a query,
so it did not measure Cypher correctness or repair convergence.

The local model and populated graph are available. The graph contains 98 Source
Articles and 2,407 Article Chunks, but no LegislativeTenure or District nodes.
All 174 stance edges lack their stance Claim Key and all 12 funding edges lack
amount and date. Their chunk provenance resolves. The comparison must account
for these coverage limits before interpreting empty query results or judging
the value of a critic.

### 2026-09-08: Ground the construction questions in retrievable data

At the maintainer's request, the next construction batch now has 25 concrete
questions preserving E1-E3, R1-R3, M1-M5, and committee lookups. Every reference
query executed read-only with nonempty results, and every evidence id resolves
to a Chunk and Source Article. The saved inspection includes 533 distinct Chunks.

[cases.yaml](../query-construction/cases.yaml) holds the questions and hidden
reference queries; [verified-results.json](../query-construction/verified-results.json)
holds observed outputs and reporting. [The case guide](../query-construction/README.md)
records the adjustments and how to recheck them. The original question set
remains the broader product target; these construction examples are not a formal
Evaluation Gold Set.

M2 uses explicit shared lobbying support. M4 tests the populated two-hop campaign
chain, while its full candidate-to-Bill extension remains empty. M5 uses
individually reported votes rather than a complete roll call. No missing graph
data was invented or ingested to make a question pass.

Both prototypes should receive the same natural-language questions and persisted
schema, without reference queries or expected results. All cases in this batch
are known to be retrievable, so a coverage decision must not stop construction.
No new model comparison has been run against this set yet.

### 2026-09-08: Run both prototypes on the verified construction questions

At the maintainer's request, two Sol agents at medium reasoning adapted the
throwaway prototypes and ran all 25 verified questions. The coordinator first
rechecked the live graph and confirmed exact agreement with the saved reference
results and evidence. Model runs were sequential, with shared ontology content
and storage notes and evaluator references excluded from model prompts.

The [new comparison](../query-construction/comparison.md) records the methods,
costs, case audits, and limitations. Generated Cypher retrieved ten complete
answers and one partial answer; typed retrieval retrieved eleven complete
answers and one underconstrained answer that happens to match this graph.
These are agent-audited development examples, not a Gold Set or a held-out
architecture benchmark.

The generated critic independently rejected no initial query beyond the eight
already flagged by deterministic checks. Combined repair recovered one complete
retrieval. The typed catalog avoided graph execution errors, but parameter
omissions, routing mistakes, and token-limit failures remain. The comparison
also records validator false positives and incomplete failed-response capture.

Prototype assets remain on `codex/prototype-generated-cypher` and
`codex/prototype-typed-retrieval`; exact follow-up commits and run commands are
listed in the comparison. The original 42-question reports are preserved.
The architecture decision remains open.

### 2026-09-08: Compose ontology triples, then bind entities

The maintainer proposed separating semantic pattern selection from entity and
property binding, with deterministic Cypher assembly. A Sol agent at medium
reasoning built and ran the experiment in a separate worktree on
`codex/prototype-composable-triples`.

All 25 questions ran through three arms. Supplying correct patterns produced
22 complete retrievals. Two-stage pattern selection and binding produced eight
complete retrievals in the frozen batch; a compiler-only replay of unchanged
outputs recovered three more. Single-call pattern and bindings produced six,
with two more recovered by the same compiler correction. The original report
and replay are preserved separately. No model calls were made for the replay.

The [composable-triples comparison](../query-construction/composable-triples-comparison.md)
records the interface, costs, failure stages, semantic audit, and artifact
pointers. The experiment supports small required binding schemas and
deterministic composition, while malformed pattern references and campaign-name
resolution remain obstacles. No production architecture was selected.

### 2026-09-09: Preserve the experiment history

The [report archive](../query-construction/reports/README.md) imports the three
prototypes' reports, assessments, input snapshots, and failure/replay evidence
without changing their source blobs. Its manifest records source commits and
hashes, and annotated experiment tags retain the implementations. The shared
reference cases, verifier, and comparisons remain alongside the archive.

The [next-experiment plan](../query-construction/next-experiment.md) proposes
compiler-assigned pattern identifiers and read-only candidate resolution for
bindings. This continues issue 05 and respects the modes and index inventory
settled in issue 06. It does not select a production architecture or authorize
merging graph identities.
