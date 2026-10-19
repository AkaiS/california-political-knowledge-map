# Evaluate retrieval evidence

Use the repository's `run-evaluation` skill or the maintained script for ordinary
runs. It validates the established 25-case RAG population before calling models,
runs the complete set by default, and reports every selected outcome:

```sh
uv run scripts/run_evaluation.py rag --plan
uv run scripts/run_evaluation.py rag
```

An explicitly requested mini set uses `--sample 5 --seed 42`; one named case uses
`--case C-M1-01`. Summarize an existing attempt with
`uv run scripts/run_evaluation.py --report PATH`; repeat `--report` for one
scorecard axis per attempt. The summary is JSON unless you pass
`--format markdown`. Each axis is compared against the newest earlier
Comparable Run unless `--baseline PATH` names a report or `--baseline none`
skips the comparison. New runs save an initial
population manifest and atomic progress snapshots to one report path. Failed and
interrupted attempts remain inspectable, with unresolved cases and nonzero exit
status distinguished from completed answers. See
[ADR 0024](../adr/0024-evaluations-preserve-the-selected-population-and-progress.md).

The `retrieval` task runs the production full-text, dense and structural
branches, weighted fusion, Evidence Assembly and final Chat Agent guidance.
It starts with an authored, approved Query Rewrite, then passes the assembled
evidence to the production answer function and renderer. It skips the Query
Rewriter and question assessment. The [chat task](chat-answer-review.md)
exercises those preparation stages as part of the whole Chat Session.

New runs use the shared Jev structural retriever for every approved question,
including reporting-only questions. Branch scores follow the execution's recorded
routing, and run provenance records the active Jev prompt versions. Historical
runs retain their original branch selection and scores.

Startup failures receive zero scores for all three production branches. Their
empty candidate pools remain in chunk-sampling manifests. Compact reports retain
selected graph facts passed to generation, but discard Jev construction audits
and graph results outside the selected context.

The first Data Set preserves all 25 questions and IDs from the
[Cypher construction set](../../work/initiatives/useful-graph-retrieval/query-construction/cases.yaml).
Codex mapped its executed reference results to retrieval labels. These are
provisional Silver Set labels derived from model-extracted graph claims, not
human relevance judgements or independently verified political facts. All 25
cases are training because the questions have already informed implementation.
There is no held-out accuracy estimate.

## Error analysis before metrics

I inspected all five attempts in the
[September 29 chat report](../../evals/reports/chat/20260929T003318Z-52f7337-local-gemma4-26b-1499ceec2201.json),
including retrieved passages and the failed case's retained context.

| Case | Observed evidence | Evaluation implication |
| --- | --- | --- |
| C-E1-01 | A request for stored mentions of Steve Hilton was declined before retrieval. | Hold the question fixed for retrieval measurement. Review rewriting and assessment separately. |
| C-R1-01 | Structural retrieval failed, but the final context included the nurses article's chunk 54, which explicitly says California Nurses Association endorsed AB 1018. Six other selected sources did not supply that union's position on that bill. | Score branch completion alongside reference recall and final-context recall. A branch failure need not mean all evidence was lost. |
| C-M2-01 | Structural retrieval failed. Hollywood article chunk 10 names SkyDance, Walt Disney and SAG-AFTRA as supporting AB 186; chunk 7 describes Creative Artists Agency's support. Both reached final context, alongside unrelated reporting. | Preserve evidence for the seed and each peer. Inspect guidance relevance separately from evidence availability. |
| Q-D-03 | A voting-advice question was rewritten into a positions question before it was declined. | An end-to-end decline is insufficient to check preservation of intent. Keep this control in chat review. |
| Q-F-01 | ADA bill reporting reached the final context, but guidance cited one article twice as a disagreement and failed validation. The passages do not supply a complete roll call. | Generation failure and missing coverage must not be conflated with retrieval failure. |

This sample establishes observed failure examples, not their frequency. It does
not justify tuning chunking yet. The saved chat report trims the full-text
candidate list, so it cannot reconstruct complete branch recall or fusion.
New retrieval reports retain bounded branch ranks and the extra ranks needed
to reconstruct production fusion.

## Initial smoke result

On September 30, 2026, I rechecked all 25 reference queries against the live
graph. Their rows and all 533 supporting chunks, including text and source
metadata, matched the saved snapshot. The
[C-R1-01 smoke report](../../evals/reports/retrieval/20261001T001308Z-e17ffc5-local-gemma4-26b-1499ceec2201.json)
then measured full-text and dense Recall@5 of 1.0, structural Recall@5 of 0.0,
and final-context recall of 1.0. Structural retrieval failed; the text branches
still recovered the reference witness. This one training case is an execution
check, not a 25-case baseline or an estimate of retrieval quality.

## First 25-case baseline

The [full local baseline report](../../evals/reports/retrieval/20261001T002500Z-e17ffc5-local-gemma4-26b-1499ceec2201.json)
ran on September 30, 2026, with local `gemma4:26b`, after the reference recheck.
All 25 attempts returned evidence packages, with no task or evaluator failures.
The report records revision `e17ffc5` with a dirty worktree because this
evaluation implementation was not yet committed.

| Stage | Completed | Mean Recall@5 | Mean Recall@50 |
| --- | --- | --- | --- |
| Full-text | 25/25 | 0.636 | 0.825 |
| Dense | 25/25 | 0.531 | 0.725 |
| Structural | 0/21 requested | 0.000 | 0.000 |
| Fusion | 25/25 | 0.618 | 0.832 |

Mean final-context recall was 0.683, and mean final-context complete evidence
was 0.711. These are unweighted means across training cases with different
evidence grains and coverage demands. They measure agreement with the reference
labels, not a voter-facing answer success rate. Generation was not run.

All 21 structural attempts failed at `schema_filtering`. Stage diagnostics
classify them as `transport`, and captured requests report `ModelAPIError`.
Those fields do not establish the root cause; inspect the
[native run trace](https://logfire-us.pydantic.dev/akais/california-political-knowledge-map?q=trace_id%3D%2701a0f4d86f17d359eb557977587d7004%27)
and local service diagnostics before changing the retrieval design.

Follow-up diagnosis on October 1 reproduced the production ontology-filter
request and captured its HTTP response. The local server rejected it with
HTTP 400, `JSON schema conversion failed`, because
`filter_properties.propertyNames` still referenced `#/$defs/SemanticLabel`
after the configured `InlineDefsJsonSchemaTransformer` removed `$defs`. Its
object walker does not visit `propertyNames`. All 21 failed cases supplied the
same output schema. Replacing just that reference with the inline label enum
made the same wire request return HTTP 200. This confirms the request-schema
blocker, not successful structural retrieval: the control's generated selection
subsequently failed Pydantic validation on its filter keys.

The local retry transport retries every `HTTPStatusError`, including this
deterministic 400, and raises it inside the SDK's send path. The resulting
`ModelAPIError` says `Connection error.`; structural retrieval groups that
exception under `transport`. Consequently the baseline report conceals the
server's more specific schema-conversion error. Diagnostic requests and raw
responses are disposable artifacts under `.scratch/rag-evaluation/`.

The subsequent request-schema fix makes `OntologySelection` emit inline label
constraints for dictionary keys through Pydantic's schema metadata. A wire-level
regression test covers the real model factory. The same production ontology
filter now receives HTTP 200 on all three attempts. The replay still exhausts
output corrections because it returns catalog piece IDs in `relationships`,
which requires semantic relationship names. This is a separate validation
failure. The historical baseline above remains unchanged; no improved retrieval
score is claimed from this request-schema check.

The largest coverage demands expose selection limits. E3-03's article-count
question had fused Recall@50 of 0.330, final-context recall of 0.106 and no
complete count row. Both M4 influence-chain cases found only one of their two
required evidence identities, even at fused k=50, so their complete-evidence
scores remained zero. C-C1-01 found its reference witness at fused k=50 but
omitted it from final context. Conversely, C-R1-01 and both M2 peer questions
retained all reference evidence despite structural failure.

M1 illustrates why recall and complete evidence are separate. Its topic groups
allow many alternative article witnesses. Finding only a small fraction of
their listed chunks can still supply a witness for every required group.
Investigate structural availability before using this baseline to choose a
chunking change. Then compare matching cases at each selection stage.

## Evaluation after the request-schema fix

The [October 1 local report](../../evals/reports/retrieval/20261001T210816Z-e17ffc5-local-gemma4-26b-1499ceec2201.json)
reran all 25 training cases with the inline dictionary-key schema. A fresh
reference check matched all 25 reference query results and all 533 supporting
chunks. Inputs, labels, metadata and production settings matched the baseline,
apart from the coverage observation timestamp. Both reports record revision
`e17ffc5` with a dirty worktree. This run used sequential cases and completed
with no task or evaluator failures.

| Measurement | Baseline | After schema fix |
| --- | --- | --- |
| Structural branches completed | 0/21 | 3/21 |
| Mean structural Recall@5 | 0.000 | 0.095 |
| Mean fused Recall@5 | 0.618 | 0.618 |
| Mean fused Recall@50 | 0.832 | 0.832 |
| Mean final-context recall | 0.683 | 0.683 |
| Mean final-context complete evidence | 0.711 | 0.711 |
| Evidence packages assembled | 25/25 | 25/25 |

Full-text and dense Recall@5 also remained exactly unchanged. Structural
retrieval completed for C-R3-01, C-R3-02 and C-C1-02. C-R3-01 returned no
candidates. Each of the other two returned two candidates and recovered all
reference evidence, which the text branches already supplied. Consequently
this run shows improved structural availability without an improvement in
fused or final-context reference coverage.

There were no structural transport failures, and the captured exchanges now
include generated model outputs. The remaining 18 terminal structural failures
were:

| Failure stage | Cases | Observed failure |
| --- | --- | --- |
| Schema filtering | 10 | Three exhausted corrections for invalid output shapes, including property names used as dictionary keys. Seven exhausted semantic validation, including catalog piece IDs used where relationship names were required. |
| Wiring | 5 | Invalid connections between selected roles. For example, C-R1-02 repeatedly failed `wire relationships between two distinct selected roles`. |
| Binding validation | 2 | C-M2-01 exhausted corrections after `use positional values when there is at most one Bill-name slot`. C-M4-02 also encountered that rejection, then ended with `bind a nonempty value to every filter slot`. |
| Hydration | 1 | C-E3-03 executed Cypher and returned 7,319 rows, then failed conversion to retrieval candidates. The retained stage diagnostic does not identify the rejected row or field. |

These counts describe terminal branch outcomes. Individual rejected correction
attempts also create failed validation spans, including in branches that later
succeed, so counting every failed span would overstate branch failures.
The [native run trace](https://logfire-us.pydantic.dev/akais/california-political-knowledge-map?q=trace_id%3D%2701a0f94591cfbb292cf6ff36d3eae06b%27)
contains the full stage observations. The report keeps branch outcomes,
failed-stage diagnostics and concise model correction feedback and responses.
The request-schema blocker is cleared; the output-contract and hydration
failures remain separate work. These results still use provisional silver
training labels, and generation was not evaluated.

## Run the current pipeline

Start the configured Neo4j, embedding and model services. Shared chat startup
also constructs and checks the Query Rewriter deployment, although this task
does not call it. Then run:

```sh
uv run ca-map eval run retrieval --deployment local --split training
```

Use `--deployment openrouter` to select the configured structural models,
`--case C-R1-01` for a smoke case, and `--max-concurrency` to bound parallel
cases. The report goes to `evals/reports/retrieval/` through the existing
Pydantic Evals runner. It records deployment, commit, dirty state, label quality,
run configuration, coverage observation time, bounded branch ranks, selected
passages and failure diagnostics. Commit a report when keeping it as experiment
evidence.

The 25 inputs supply `allowed` assessments solely to isolate retrieval. E1 and
E2 discover reporting and therefore use non-relational routing; the remaining
families depend on typed relationships. These fixtures do not change approval
or policy behavior in live chat. Reference queries, results and labels never
enter a model request.

## Read the metrics

For full-text, dense, structural when requested, and fusion, the task reports
Recall@1, @5, @10 and @50. Recall is the fraction of unique reference identities
found in the first k unique Article Chunks. Rank follows the recorded branch
ranking, not the native score or serialized list order. Duplicate appearances
of one chunk count once at its best rank. Reciprocal rank measures the first
relevant chunk within the first 50 unique chunks; the mean of case scores is
MRR within that budget. Evidence appearing deeper in a branch cannot improve
these metrics.

E3 measures Source Article identities because `DISCUSSES_TOPIC` is an
article-level claim. Their article coverage is measured after applying the
chunk budget. Fifty chunks from one article cover one article, even if chunk
51 belongs to another relevant article. Other cases measure exact Article
Chunk identities.
Retrieving another passage from the same article does not satisfy a chunk
label. Recall against reference IDs is agreement with the stored reference,
not proof that every unlisted passage is irrelevant. Reference precision@k
counts chunk slots matching these same labels, divided by k. Missing result
slots count as zero. For E3, each retrieved chunk from a listed Source Article
counts as a reference match, even when several chunks share that article.
Reference precision measures agreement with provisional labels; unlisted
chunks may still be useful. NDCG is unavailable until graded relevance
judgments exist. Fusion is weighted reciprocal rank fusion, not a learned
reranker.

`complete_evidence_at_k` scores the fraction of reference answer rows with at
least one witness from every evidence group. Multiple IDs inside a group are
alternative witnesses; groups within a row are all required. For a two-hop
row this is two-hop recall. The same chunk may witness both links. M1's topic
witnesses navigate to an article-level claim; they do not imply that every
listed chunk states the topic. E3-03 requires every counted article for a
complete area-count row.

`context_recall` and `context_complete_evidence` use all passages actually
selected for the Chat Agent, without a new k limit. Compare branch, fused and
context results to locate retrieval misses, fusion loss and assembly loss.
Reasons list missing reference IDs. `*_completed` distinguishes an empty
successful branch from a failed branch. Startup failures remain in the
population with zero recall. Skipped structural branches are unscored.
`evidence_assembled` and `retrieval_attempt_completed` describe execution,
not answer quality.

## Bounded report evidence

The retrieval-only projection runs at the existing Pydantic Evals report writer.
It keeps the framework's scores, assertions, usage metrics, case IDs, labels,
model route summaries and trace references. Each case retains:

- The first 50 unique chunks per branch, with chunk ID, Source Article ID and
  original best branch rank, plus aggregate retrieved and unique-chunk counts.
- Extra best branch ranks only for chunks eligible for production fusion.
- The passages selected for the Chat Agent, with exact text and source citations.
  Context limits and coverage describe what that evidence package supplied.
- Branch status, failed-stage diagnostics, useful preceding stage counts and
  concise correction feedback with
  relevant model responses. A failed correction is distinguished from a terminal
  branch failure, so a recovered branch remains successful.

`retrieval_report.configurations` stores each distinct run configuration once.
Cases refer to it through `output.configuration_index`; coverage observation
timestamps remain case-specific. It includes the full code revision, model
deployments and settings, prompt hashes, embedding settings, RRF weights and
limits, and Evidence Assembly limits. The dataset reference stays at run level.

The report omits candidate routes and claims, repeated contributions, fused
objects, catalogs, cumulative prompts and most successful stage observations.
`replay_fusion` in `knowledge_map.evaluation.retrieval_report` reconstructs exact
production scores and ordering from the compact branch records and configuration.
Production's `fuse_candidates` and report replay share the private ranking policy
in `knowledge_map.core.fusion`. `compact_branches` uses that same policy's ordered
best branch ranks and nominations to choose retained records. These three
interfaces keep their existing signatures and return types. The report adapter
still owns Source Article identity, serialized fields, counts and bounded retention.

Each branch's configured candidate limit establishes eligibility, but an eligible
chunk can still receive a contribution from a deeper rank in another branch.
Compaction retains the first 50 unique chunks per branch and only those extra
contributing ranks. Larger configured fusion budgets also record explicit eligible
IDs, without changing the 50-chunk metric budget. Replay honors those IDs when
present and otherwise derives nominations from the retained first-50 population;
extra ranks cannot nominate discarded candidates. Historical reports need no
rewrite. Missing historical fusion settings prevent compaction rather than
inventing a configuration.

These records support branch failure diagnosis, reference misses within the
retrieval budget, fusion loss and context-selection loss. They do not support
larger retrospective candidate budgets, arbitrary discarded-candidate inspection
or every ranking experiment after graph changes. Those investigations require
another retrieval run.

On October 1 the three existing retrieval reports were compacted, preserving
their original bytes under `.scratch/rag-evaluation/unbounded-report-backups/`.
The full baseline fell from 35.86 MB to 1.98 MB and the schema-fix run from
37.96 MB to 2.03 MB. Their fusion ordering and scores reconstructed exactly.
The migration also rescored article-grain cases within the chunk budget and
bounded reciprocal rank to 50. The tables above use the corrected metric
definition, `unique-chunk-budget-v2`; the earlier identity-budget numbers are
not directly comparable. Migration provenance records the prior definition,
source hash and backup location. Changed old values remain clearly labeled
under `legacy_identity_budget_scores`, outside current scores. Final-context
recall and branch completion did not change. This migration does not claim a
new model or retrieval run. The one-off migration script was removed once it
had been applied (inbox ED-08); new runs are compacted when written.

## Reference freshness and annotation

The checked graph snapshot is dated September 8, 2026. Git versions the labels
and implementation, but the live graph can change independently. Recheck before
interpreting a new baseline:

```sh
uv run python work/initiatives/useful-graph-retrieval/query-construction/verify.py
```

This read-only check writes `.scratch/query-construction/verification.json`.
Compare rows, evidence IDs and text with the saved reference. To propose labels
from that fresh snapshot without overwriting hand edits:

```sh
uv run python scripts/build_retrieval_eval.py \
  --reference .scratch/query-construction/verification.json \
  --output .scratch/retrieval-proposal.yaml
```

The builder checks the authored question-file hash, exact case coverage and
resolved evidence. It preserves IDs and refuses to overwrite an existing file.
Review its diff against `evals/silver/retrieval.yaml` before adopting changes.
A missing or changed target is reference drift to investigate, not automatically
a retriever regression. Compare runs with matching corpus and configuration.

For human annotation, read each target chunk's text against the question and
scope note. Check session, direction of lobbying or stance, and whether each
hop is supported. A graph edge alone does not establish a political fact.
Add alternative answer-bearing chunks after inspecting them; preserve separate
groups for distinct claims. For article-discovery questions, label relevant
Source Articles instead of requiring every chunk. Author new calibration and
held-out questions from real usage with those labels; do not relabel these
already-used training cases as held-out. Keep model-authored labels silver.

## Review generation from the same run

Use [RAG review](rag-review.md) to judge selected context and final generation
without the end-to-end Chat Session panels. The run dashboard shows retrieval
specifications, measured scores and explicitly unavailable metrics. Each case
records context relevance, answer relevance and answer faithfulness separately;
there is no general critique or omission label in this view.

New `retrieval` runs include final generation from the same selected evidence.
The existing command runs all 25 cases, including the answer call:

```sh
uv run ca-map eval run retrieval --deployment local --model gemma4:26b
```

Open the completed run using [the RAG launcher](rag-review.md#start-the-reviewer).

Use `--case C-R1-01` for a smoke run. Older retrieval reports remain evidence-only;
rerun them to obtain answers. Reference labels never enter the model request.
The report retains generated guidance and the rendered answer, with bounded
branch ranks and selected context. It stores no duplicate answer evidence tree.
`answer_generated` records validated output, not semantic quality. A generation
failure retains retrieval scores and context, with its guidance-stage diagnostic.

The [October 2 run](../../evals/reports/retrieval/20261002T233848Z-e237389-local-gemma4-26b-1499ceec2201.json)
used local `gemma4:26b` on all 25 training cases. All 25 retained assembled
evidence and retrieval scores; 23 produced validated, rendered answers.
`C-M1-01` and `C-C1-01` failed validation in the guidance stage. Their answer
relevance and faithfulness remain unjudgeable, while context relevance remains
available. The run records execution results, not semantic quality judgments.

For every case, record separate binary observations, with the exact
passage or model claim that explains a failure:

- Faithfulness passes when every factual guidance claim is supported by the
  selected context and the citations support that claim. Unsupported facts,
  overstated enacted status, invented positions or misrepresented relationships
  fail even if outside knowledge says they are true.
- Relevance passes when the selected sources and guidance address the approved
  question's named subjects, session and requested relationship. A caveat alone
  does not explain relevant reporting when that reporting is available.

An assembly failure or absent generated answer is unjudgeable for semantic
faithfulness and relevance; record its execution failure instead of a pass.
Do not turn a whole-case verdict into both component labels. Use recurring
human-reviewed failure categories to write binary judges, then calibrate them
against held-out human labels before publishing generation quality scores.

If retrieval is the measured bottleneck, compare chunking configurations only
after re-indexing each corpus and remapping labels to stable source facts or
spans. Current chunk IDs are meaningful only for the existing chunking. Keep
generation settings fixed during retrieval experiments.

The evaluator uses Pydantic Evals' native result-with-reason format described
in its [custom evaluator documentation](https://pydantic.dev/docs/ai/evals/evaluators/custom/).
