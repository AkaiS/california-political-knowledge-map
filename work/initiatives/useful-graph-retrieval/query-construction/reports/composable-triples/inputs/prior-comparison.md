# Construction comparison on the verified questions

Follow-up to [issue 05](../issues/05-prototype-query-construction-and-validation.md)
and the [original comparison](../prototype-comparison.md).

## Shared inputs and boundaries

Two Sol agents at medium reasoning adapt the existing throwaway prototypes in
separate worktrees. Both receive the same 25 natural-language questions,
construction instruction, and persisted News Ontology. Family identifiers,
reference Cypher, reference parameters, expected results, and evidence remain
outside the model prompts. Every question has a verified retrieval path;
deferral counts as failure to attempt construction in this batch.

The coordinator reran the read-only reference verifier on 2026-09-08.
[The fresh inspection](rechecked-results.json) matches
[the saved reference](verified-results.json) in every field except the inspection
timestamp, including all 25 case results, the label inventory, the original M4
path count, and 533 distinct supporting Article Chunks.

The local model runs sequentially across prototypes to avoid resource
contention. Code preparation and read-only graph checks may run in parallel.
External telemetry export stays disabled. The original reports remain preserved.

These are graph-backed construction examples, not a Gold Set. Successful
execution and nonempty results are measured separately from correct retrieval.
Semantic comparison accepts equivalent result grouping and checks the requested
subjects, article sets, counts, and evidence for each relationship in a path.
The reference graph can contain extraction errors, so agreement is evidence
about retrieval against this graph, not independent verification of political
claims.

## Generated Cypher results

The frozen batch completed all 25 cases in 638.12 seconds. The driver API smoke
passed before inference, and no model-stage failures occurred. Initial queries
returned rows in ten cases; final queries returned rows in eleven. The remaining
final outcomes were six empty results, four plans stopped by validation, and
four execution-time type errors. Eight cases entered one bounded repair.
The raw report's `empty_results: 10` combines the six executed empties with four
unexecuted validation failures; the counts here separate them using the case
records.

The coordinator's manual retrieval audit finds nine complete initial retrievals
and ten complete final retrievals, allowing the valid Proposition 38 alias
expansion described below. Q17 is partial despite matching the peer names.
The other fourteen final cases fail to retrieve the requested answer. This is
an agent audit of these known-answerable examples, not a Gold Set score.

All eight initial critic rejections coincide with deterministic rejections.
The critic independently flags no additional initial query. Repair recovers
one complete retrieval, Q05, but this combined-feedback run cannot establish
whether the critic caused that improvement. It has no deterministic-only repair
arm. The critic misses reversed edges, wrong seed properties, and evidence
type errors, and sometimes gives false provenance advice.

| Stage | Requests | Input plus output tokens | Summed call time |
| --- | ---: | ---: | ---: |
| Initial generation | 25 | 91,609 | 287.55 seconds |
| Repair generation | 8 | 32,440 | 49.54 seconds |
| Initial critic | 25 | 90,518 | 217.55 seconds |
| Post-repair critic | 8 | 30,803 | 81.21 seconds |

The critic uses 121,321 tokens and 298.76 seconds across its 33 calls. Generation
and repair use 124,049 tokens and 337.09 seconds. These are local inference usage
and time observations, not dollar costs.

## Typed retrieval results

The frozen typed batch completed in 246.73 seconds. Seventeen cases reached a
fixed query, twelve returned rows, and five returned none. Eight cases stopped
at the 12,000-token per-case limit during output correction. No fixed query
failed during graph execution.

All twelve nonempty outputs equal the reference rows after normalizing list
order, including their evidence groups. Eleven also respect the question's
scope. C-R2-02 omits the requested session and happens to return the reference's
two lobbyists on this graph; that is an underconstrained query, not a complete
construction success.

The five empty queries show routing and value-resolution failures:

- The two temporal topic queries use `housing` and `labor` where the graph stores
  full Policy Area names.
- The labor-union position question chooses lobbying instead of recorded stance,
  and omits both the union filter and session.
- The endorsement question chooses campaign funding and shortens the campaign
  name, despite the catalog offering endorsement retrieval.
- The campaign-funder question chooses a forward funding-chain query seeded
  with the literal string `Organization`.

The retained failed-case responses show missing required parameters, invalid
values, and repetitive output. However, they do not contain the response that
triggered each token-limit error. The installed Pydantic AI implementation
increments usage and checks the limit before appending that response to the
captured history. It is therefore unknown whether those final responses could
have validated if the budget permitted them.

The report retains 35 responses totaling 146,130 input-plus-output tokens.
Combining the eight exception messages' cumulative token totals with the
successful cases' traces reconstructs 184,933 tokens, including 38,803 tokens
missing from captured history. This implies 43 responses, with eight bodies and
their input/output breakdown unavailable. Treating 146,130 as full usage would
understate the cost. The frozen report is preserved with this limitation.

## What this comparison supports

| Outcome | Generated Cypher with critic | Typed retrieval |
| --- | ---: | ---: |
| Cases | 25 | 25 |
| Complete retrievals in coordinator audit | 10 | 11 |
| Partial or underconstrained nonempty result | 1 | 1 |
| Executed query returned no rows | 6 | 5 |
| Final query stopped by validation | 4 | 0 |
| Graph execution errors | 4 | 0 |
| Model-run token-limit failures | 0 | 8 |
| Batch duration | 638.12 seconds | 246.73 seconds |
| Input plus output tokens | 245,370 | 184,933 reconstructed |

These are development examples, with one run per approach. The typed catalog
was adapted to these questions and includes an explicit July 2026 date-bound
example that the generated prompt lacks. Both use the same ontology and neutral
storage notes, but their prompts, output schemas, token limits, and correction
policies differ. This is not a held-out or controlled causal comparison of
architectures.

The typed catalog prevents Cypher construction errors after a valid selection,
but the model still misroutes questions, omits constraints, and struggles to
fill its broad parameter object. Generated Cypher handles several direct
retrievals and the article-level topic cases, while its critic misses basic
direction and provenance errors. Neither run justifies settling the production
retrieval architecture or adopting this critic.

A next experiment should first make the typed parameter requirements visible
in each output variant, expose canonical Policy Area values, and retain usage
and responses on token-limit failures. For generated queries, test deterministic
repair alone against the combined critic path, and include execution-type
errors in repair feedback. Keep new runs separate from these frozen reports.

## Preserved assets and verification

The generated prototype is on `codex/prototype-generated-cypher`, implementation
and frozen report commit `5cce14a`, with the offline count correction committed
as `ecc9946`. Its worktree is
`/private/tmp/ca-map-prototype-generated-cypher-20260908`.

- [Generated analysis](/private/tmp/ca-map-prototype-generated-cypher-20260908/src/knowledge_map/prototypes/results/generated-cypher-verified-analysis.md)
- [Generated full report](/private/tmp/ca-map-prototype-generated-cypher-20260908/src/knowledge_map/prototypes/results/generated-cypher-verified-report.json)
- [Generated run instructions](/private/tmp/ca-map-prototype-generated-cypher-20260908/src/knowledge_map/prototypes/README.md)

The typed prototype is on `codex/prototype-typed-retrieval` at `8f975fc`. Its
worktree is `/private/tmp/ca-map-prototype-typed-retrieval-20260908`.

- [Typed assessment](/private/tmp/ca-map-prototype-typed-retrieval-20260908/src/knowledge_map/prototypes/typed_retrieval/verified-question-assessment.md)
- [Typed full report](/private/tmp/ca-map-prototype-typed-retrieval-20260908/src/knowledge_map/prototypes/typed_retrieval/verified-question-report.json)
- [Typed run instructions](/private/tmp/ca-map-prototype-typed-retrieval-20260908/src/knowledge_map/prototypes/typed_retrieval/README.md)

From the corresponding worktree roots, run:

```sh
UV_CACHE_DIR=/private/tmp/ca-map-uv-cache uv run --no-sync python -m knowledge_map.prototypes.generated_cypher_verified --output .scratch/generated-cypher-new-run.json
```

```sh
UV_CACHE_DIR=/private/tmp/ca-map-uv-cache uv run --no-sync python -m knowledge_map.prototypes.typed_retrieval.run --output .scratch/typed-retrieval-new-run.json
```

Both prototype worktrees were clean after committing. Each agent checked Ruff,
formatting, compilation, and whitespace. The generated runner passed a live
read-only driver smoke after fixing `tx.run(Query(...))`. All fourteen typed
templates passed `EXPLAIN` as read queries, and its graph/evidence smoke passed.
The coordinator independently checked the reference recheck, generated result
sets and counts, all twelve nonempty typed results against the references, and
the reported usage totals and limitations. No browser verification was used.

This task's checkout contains documentation and the transferred reference
artifacts. The previous coordinator checkout's uncommitted work remains intact;
prototype code stays on the two throwaway branches.

## Audit notes from the generated batch

The report's scalar-set overlap is a diagnostic proxy, not an answer score.
For example, returning `chunk_id` instead of `evidence_groups` can make its
evidence score zero despite returning the exact expected Chunks. The coordinator
therefore compares returned values and query paths directly.

- Q01 and Q02 return exactly the reference Chunk sets for Steve Hilton and
  Gail Pellerin.
- Q03 reverses `MENTIONED_IN` and returns no rows. The critic accepts it.
- Q04 retrieves the 20 reference Chunks plus five from the alias node
  `Prop:prop-38`, named `Prop. 38`. A separate graph query confirmed the two
  identities. Those five Chunks belong to the same two Source Articles as the
  reference, and their text explicitly discusses Prop. 38. An exact-reference
  score would punish broader alias retrieval.
- Q05 starts with invalid Cypher and a first-day-only date filter. Repair
  retrieves all nine expected articles and all 242 expected Chunks. Because
  deterministic validation also rejected the initial query, this does not
  isolate the critic's contribution.
- Q06 retrieves all six expected labor articles and all 208 expected Chunks.
  Its 208 rows are an equivalent grouping of the reference's six article rows.
- Q07 returns all 26 expected Policy Area counts. Its use of distinct Neo4j
  nodes rather than project ids happens to match this graph's article counts.
  Every per-area Source Article id set also matches.
- Q08 treats `LaborUnion` as `industry_sector`, returns no rows, and passes
  the critic. Q09 duplicates the same Reform California endorsement row;
  its subject and evidence match after deduplication. Q10 retrieves the four
  expected AB 186 lobbyists and their evidence.
- Q11 treats `relationship.chunks` strings as objects and fails during execution.
  The critic accepts it. Execution-time type errors do not enter this runner's
  repair loop when `EXPLAIN` passes.
- Q13's critic incorrectly denies the availability of relationship-level
  `chunks` provenance. Q14 and Q15's repaired queries repeat the string-as-object
  error. These are model and repair failures, separate from the fixed driver API
  defect.
- Q17 retrieves the expected three peer names, but uses general organization
  mentions and omits the named organization's lobbying link. Matching names
  alone does not supply evidence for both sides of the intersection.
- Q18 retrieves the expected organization and shared Chunk twice. Q19 reverses
  `HAS_CHUNK`, returns no rows, and passes the critic.
- Q22 and Q23 use an unpopulated `last_name` property and return no rows. Q23
  also returns the event type where the question requests the vote position.
- Q24's validator misreads a list expression as relationship names, and the
  critic invents a relationship-to-Chunk traversal in response. The initial
  query also has a real string-as-object bug, so the validator false positives
  do not make that initial query correct.
- Q25 retrieves both expected committees and the referral evidence.
