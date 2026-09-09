# Query construction prototype comparison

Construction and observations for [issue 05](issues/05-prototype-query-construction-and-validation.md), started on 2026-09-08 from commit `85275ab`.

Follow-up: the maintainer requested construction questions substantiated by the
data actually present. [The new 25-case set](query-construction/README.md)
preserves the question families and supplies executed references with reporting.
Use it for the next construction comparison. The baseline below still records
the original 42-question experiment; no new model run has been substituted into it.

The [25-question follow-up comparison](query-construction/comparison.md) is now
complete and records its results separately.

Raw reports, failed attempts, and recovered results are now preserved in the
[report archive](query-construction/reports/README.md). Historical implementation
paths below refer to the prototype commits; the archive links work from main.

## Experiment

Two Sol agents at medium reasoning construct separate throwaway prototypes. The generated-Cypher prototype asks the configured model to write queries, then compares deterministic checks with a model critic and bounded repair. The typed-retrieval prototype asks the same model to select fixed parameterized retrieval primitives.

Both use the authored [target questions](question-set.md) without rewording or removing them. Family questions use identifiers such as `E1-1`; the seven Declined examples use `D-1` through `D-7`, and the four Deferred examples use `F-1` through `F-4`. The date anchor is 2026-09-08. Synthetic ontology probes are separate from errors observed in model output. These are prototype observations, without a Gold Set or a settled retrieval contract.

The orchestrator compared both case loaders after construction. All 42 identifiers and question strings match: 30 family questions, seven Declined examples, four Deferred examples, and the committee-activity question as `C-1`. Expected family and disposition annotations stay outside model prompts and repair feedback.

## Shared runtime baseline

The orchestrator inspected the local services read-only on 2026-09-08. Neo4j reported version `2026.07.1`, Community edition, with Cypher 5 and 25. The local llama.cpp endpoint returned HTTP 200 and listed `gemma4:26b`. A model listing confirms availability, while the prototype runs establish whether generation succeeds.

| Graph item | Count |
| --- | ---: |
| NewsArticle | 98 |
| Chunk | 2,407 |
| Bill | 84 |
| Politician | 241 |
| Organization | 679 |
| LaborUnion | 36 |
| Prop | 33 |
| Campaign | 41 |
| LegislativeEvent | 37 |
| Vote | 17 |
| PolicyArea | 26 |
| LegislativeTenure, District, RedistrictingCycle | 0 each |

Article publication dates range from 2023-06-15 through 2026-09-05. All 98 `published_date` values are strings, so comparisons to Cypher dates need an explicit conversion. Of 84 Bills, 62 have a session and 22 carry `needs_review`. The graph has one exact `SB 9` name match, in session `2025-2026`. That does not settle the session intended by a question that names none.

All 278 `DISCUSSES_TOPIC` edges start at `NewsArticle`. The 24 `ABOUT_TOPIC` edges carry article provenance in `articles`. News relationship provenance uses `chunks`. All 265 chunk references on stance, funding and lobbying edges resolve to existing Chunks.

All 174 `DECLARED_STANCE` edges have `chunks` and `needs_review`, with no stance Claim Key. All 12 `FUNDED` edges have the same two properties, with no amount or date. None of those edges lack chunk provenance. The 28 `LOBBIED_AGAINST` and 11 `LOBBIED_FOR` edges also have chunk provenance, and none carries `needs_review`. The prototypes must distinguish retrieving this reporting from deriving a same-side comparison or funding total from missing values.

Both `CAMPAIGN_FOR` target alternatives materialized, with 19 edges to Politicians and three to Props. No Organization sub-label node checked under `LaborUnion`, `PAC`, or `Corporation` lacked the parent `Organization` label. `SHOW CONSTRAINTS` returned no constraints.

`MATCH (:LaborUnion)` and `MATCH (:Organization:LaborUnion)` both return 36 nodes. A query does not need to restate every label on a stored node. Rejecting a query merely because it uses the sub-label alone would be a validator false positive.

## Interpretation rules

The authored question set predates [ADR 0020](../../../docs/adr/0020-a-topic-edge-hangs-off-the-source-article-not-the-article-chunk.md). Its E3 topic path must now reach Chunks through `NewsArticle` and `HAS_CHUNK`. Preserve the question wording and record the corrected traversal in each prototype.

The primary ontology routes votes and committee assignments through `LegislativeTenure`; the News Ontology declares direct Politician shortcuts. A validator must know which ontology it checks. Primary-ontology stress probes cannot establish retrieval coverage for labels absent from the news graph.

Empty results, executable Cypher, and a critic's acceptance are observations rather than evidence of a correct answer. Record missing data, ambiguous subjects, unsupported primitives, declined questions, and query errors separately. Read-only graph execution must inspect the query type before executing model-generated Cypher.

The prototypes have different offline scoring assumptions for outcome-5 questions. The generated-Cypher prototype expects deferral, while the typed prototype's family mapping names a retrieval primitive. [Issue 04](issues/04-retrievable-subgraph-now.md) has not decided when partial news evidence is an acceptable fallback. Neither scoring assumption settles that policy, and their mismatch counts cannot be compared as answer accuracy.

## Assets and findings

The generated-Cypher prototype is committed as `6633c18` on `codex/prototype-generated-cypher`. Its worktree is `/private/tmp/ca-map-prototype-generated-cypher-20260908`. The branch contains `src/knowledge_map/prototypes/README.md`, the runnable `generated_cypher.py`, and `results/generated-cypher-report.json` beneath that directory.

Run it from that worktree with:

```sh
UV_CACHE_DIR=/private/tmp/ca-map-uv-cache uv run python -m knowledge_map.prototypes.generated_cypher --case E1-2
```

Omit `--case E1-2` to run all 42 questions. The prototype uses the local model and graph, and disables external telemetry export. The agent verified compilation, Ruff, and whitespace checks. The orchestrator independently checked the committed report's counts and timing and confirmed the worktree is clean.

### Generated Cypher baseline

All 42 questions produced `deferred` plans. No Cypher reached `EXPLAIN` or execution, and no bounded repair ran. The critic accepted 32 deferrals and rejected ten. Its rejections are decisions about deferral, not detected Cypher errors.

| Stage | Requests | Input plus output tokens | Summed call time |
| --- | ---: | ---: | ---: |
| Generator | 42 | 63,971 | 266.8 seconds |
| Critic | 42 | 59,104 | 176.9 seconds |

The critic added about 92% to the generator's token count and 66% to its call time. It accepted the two deferrals independently contradicted by existing graph paths, `E1-2` and `E3-1`. Its `R1-2` and `R3-2` verdicts set `valid=false` while their explanations endorse the plan's reasoning. On `M1-1`, it identified a usable path from Uber to Policy Areas, but returned `should_repair=false`; this prototype does not repair non-query dispositions.

This run does not establish whether a model can construct correct Cypher, whether a schema validator detects generated errors, or whether repair converges. The generation step never reached those operations. The authored structural probes exercise the prototype's deterministic checks separately; they are not model performance evidence.

### Typed retrieval baseline

The typed prototype is committed as `2509811` on `codex/prototype-typed-retrieval`. Its worktree is `/private/tmp/ca-map-prototype-typed-retrieval-20260908`. The branch contains the catalog, runner, README, and reports under `src/knowledge_map/prototypes/typed_retrieval/`.

Run one or more cases from that worktree with:

```sh
UV_CACHE_DIR=/private/tmp/ca-map-uv-cache uv run python -m knowledge_map.prototypes.typed_retrieval.run --cases E1-2 C-1
```

Omit `--cases E1-2 C-1` to run all 42. `--offline-demo` demonstrates the catalog without model or graph calls. The agent verified Ruff, formatting, compilation, offline execution, and whitespace checks. The orchestrator independently sent all 12 authored query templates to Neo4j with `EXPLAIN`; all compiled as read queries.

The per-question run took 151.9 seconds. Thirteen cases exhausted two output-correction attempts while omitting required parameters. The other 29 produced type-valid selections, but the runner then failed while recording usage. The agent fixed the runner and recovered those unchanged choices from the retained responses for graph replay. `observed-report.raw.json` preserves the original failures, and `observed-report.json` records recovery and replay. Final-response token counts for recovered cases total 16,632 input and 2,117 output tokens. They exclude failed cases and retry responses, so they are a lower bound and cannot support a cost comparison with the complete generated-Cypher report.

| Outcome | Cases |
| --- | ---: |
| Required-parameter validation exhausted | 13 |
| Valid query, no matching seed or covered edge | 15 |
| Query returned rows | 4 |
| Same-side query stopped at missing-alignment coverage gap | 1 |
| Model selected decline or defer | 9 |

Two of the four queries with rows follow useful paths: `E1-2` returned the two Steve Hilton chunks, and `R3-1` returned one Proposition 38 funding edge with its reporting. The other two demonstrate why row counts cannot score correctness. `D-1`, about Texas, returned California housing evidence. `M2-3`, about repeated opposition, returned a global Policy Area distribution. The catalog prevents the model from writing new Cypher but does not prevent these semantic mistakes.

The corrected runner's separate two-case smoke is in `smoke-report.json`. `E1-2` succeeded in two model requests and returned two rows. `E3-3` exhausted two correction attempts because it omitted the required `topic="*"`. This demonstrates both convergence and exhaustion for typed parameter correction on those two cases, without claiming a general repair rate.

## Verdict and handoff

Both runnable prototypes and their reports are preserved on separate branches. Issue 05 remains open. These observations do not justify choosing generated Cypher or typed primitives as the retrieval architecture, and they provide no demonstrated benefit from adopting this critic.

The observed failure classes to carry into topology and contract work are:

- Deferral without looking up available news evidence, and confusion between permanent Declined questions and temporary Deferred coverage.
- Critic acceptance of false deferrals, plus contradictions between its boolean verdict and explanation.
- Missing required primitive parameters after bounded correction.
- Valid primitive selection with the wrong meaning, including an out-of-domain question returning plausible California evidence.
- Literal seeds that cannot resolve descriptive measure names, and incomplete Claim Keys that prevent structural answers.

Keep runtime failures separate. llama.cpp returned HTTP 400 with `Failed to initialize samplers: failed to parse grammar` for a schema pattern on optional date strings. Moving that check to Pydantic validation allowed generation. The large typed batch then failed to validate, and a runner usage-serialization defect required replay of the per-question run. The preserved artifacts identify which failure occurred at each stage.

The next construction experiment should isolate generating a query for an in-scope question from deciding whether to defer it. That would reach the Cypher and repair operations this baseline never exercised. A typed follow-up should examine required parameter schemas and semantic routing before extending the catalog. Neither requires changing the authored questions or accepting a graph row as an answer.
