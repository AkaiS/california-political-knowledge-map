# Work

This directory is the authoritative home for planned, active, and completed work
on the California Political Knowledge Map.

Start here when deciding what to work on. Use [roadmap.md](roadmap.md) for the
direction of the product and [inbox.md](inbox.md) for ideas and problems that
have not yet been shaped into executable work.

## Current attention

### Ready for human

- [Build the initial relevance Evaluation Gold Set](initiatives/model-evaluation/issues/03-build-initial-relevance-evaluation-gold-set.md)
- [Review Relevance Filter evaluations](projects/scraping-pipeline/issues/13-relevance-evals.md)
- [Review Selector Healing evaluations](projects/scraping-pipeline/issues/14-healer-evals.md)

### Ready for agent

- [Graph-Prioritized Retrieval](projects/graph-prioritized-retrieval/PRD.md),
  `ready-for-agent` as of 2026-09-16. A stronger Query Rewriter produces the
  approved question consumed by concurrent full-text, dense, and conditional
  typed structural retrieval. Weighted reciprocal-rank fusion favors structural
  evidence, and a deterministic Evidence Assembler returns provenance-rich
  evidence to the Chat Agent. Broken into nine issues below.
- [Reprocessing an article leaves its old chunk extractions in the graph](issues/02-chunk-extraction-retains-stale-decisions.md), `ready-for-agent` as of 2026-09-03.
  A standalone defect, found while fixing the article-level topic write. The
  chunk write path is merge-only, so a re-run strands the tail chunks of a
  shorter article, keeps relationship claims no extraction still makes, and
  leaves entity nodes nothing mentions. Carries the orphan decision the topic
  fix did not have to make.
- [Bill Designation Recovery](projects/bill-designation-recovery/PRD.md), `ready-for-agent` as of 2026-08-17.
  Two of thirteen `Bill` nodes in the graph carry a session. Extraction is asked
  for a bill number it cannot supply, normalization rejects every spelled-out
  form, a parse failure is written as silence rather than as `needs_review`, and
  a character-sliced chunk overlap cut `Senate Bill 623` into a second node named
  `ll 623`. Broken into five issues on 2026-08-17; the frontier is below.
- [Coreference Resolution via Mention Spans](projects/coreference-mention-spans/PRD.md), `ready-for-agent` as of 2026-08-17. Replaces whole-article `<ref>` tag rewriting with structured Mention Spans anchored to numbered sentences, and gives the Coreference Critic per-reference verdicts. Broken into seven issues on 2026-08-17; the frontier is below.
- [Retry Layering and a Deps-Driven Coreference Resolver](projects/coreference-retry-layering/PRD.md), `ready-for-agent` as of 2026-08-20.
  Three unrelated failures share the word `retries`, and the pipeline's copy is
  at the wrong layer: a connection reset during a Coreference Critic round
  discards the annotation and every accepted verdict, then re-runs the Source
  Article. HTTP retries move into the model factory's httpx transport; the
  Coreference Adapter's plumbing becomes dependencies, a state model, and
  narrowed exceptions. Broken into six tickets on 2026-08-20; the frontier is
  below.
- [News Ontology and Graph Population](projects/news-ontology-graph-population/PRD.md), specifying [Useful Graph Retrieval issue 01](initiatives/useful-graph-retrieval/issues/01-populate-graph-with-settled-ontology.md). Broken into eight issues on 2026-08-05; the frontier is below.

### Graph-Prioritized Retrieval frontier

Issue 01 is takeable now. Issue 02 turns the settled retrieval and answer
semantics into concrete types. Once 02 lands, the three retrieval branches,
parameterized fusion, and Evidence Assembly can advance. Configurable initial
weights and limits are enough for final integration. Later reranking measurement
does not block this project.

- [01 Query Rewrite and approval](projects/graph-prioritized-retrieval/issues/01-query-rewrite-and-approval.md), takeable. A separately configured stronger model produces the user-approved Query Rewrite and internal relational route.
- [02 Retrieval execution and evidence contracts](projects/graph-prioritized-retrieval/issues/02-retrieval-execution-and-evidence-contracts.md), blocked by 01.
- [03 Full-text retrieval from an approved rewrite](projects/graph-prioritized-retrieval/issues/03-full-text-retrieval.md), blocked by 02.
- [04 Dense retrieval from an approved rewrite](projects/graph-prioritized-retrieval/issues/04-dense-retrieval.md), blocked by 02.
- [05 Typed structural retrieval to Grounding Evidence](projects/graph-prioritized-retrieval/issues/05-typed-structural-retrieval.md), blocked by 02.
- [06 Bounded multi-hop structural retrieval](projects/graph-prioritized-retrieval/issues/06-bounded-multi-hop-structural-retrieval.md), blocked by 05.
- [07 Graph-prioritized reciprocal-rank fusion](projects/graph-prioritized-retrieval/issues/07-graph-prioritized-reciprocal-rank-fusion.md), blocked by 02. It supplies configurable initial weights and limits plus an unweighted measurement baseline.
- [08 Deterministic Evidence Assembly](projects/graph-prioritized-retrieval/issues/08-deterministic-evidence-assembly.md), blocked by 02.
- [09 Concurrent retrieval and Chat Agent handoff](projects/graph-prioritized-retrieval/issues/09-concurrent-retrieval-and-chat-agent-handoff.md), blocked by 01, 03, 04, 06, 07, and 08.

### Bill Designation Recovery frontier

Two issues are takeable now. The bill chain is linear; the chunking ticket is
independent of it.

- [01 Chunk text excludes the overlap](projects/bill-designation-recovery/issues/01-chunk-text-excludes-overlap.md), takeable. The chunk's text is its own body; the overlap travels as context, the embedder and chunk write consume both, extraction receives the text alone.
- [02 Bill Designation parsing, four forms only](projects/bill-designation-recovery/issues/02-bill-designation-parsing.md), takeable. `SB`, `AB`, `Senate Bill`, `Assembly Bill` and nothing else; `number` leaves the News Ontology and is supplied by resolution.
- [03 Every extracted Bill gets a resolution](projects/bill-designation-recovery/issues/03-resolution-covers-every-bill.md), blocked by 02. The map is keyed by name and covers unidentifiable bills; the adapter stops deciding.
- [04 Recover a Bill Designation from the Source Article](projects/bill-designation-recovery/issues/04-recover-designation-from-article.md), blocked by 03. `ll 623` reaches `Senate Bill 623`'s node before any key is minted.
- [05 Record the Bill Designation vocabulary](projects/bill-designation-recovery/issues/05-record-bill-designation-vocabulary.md), blocked by 04. `CONTEXT.md` gains **Bill Designation**; the primary ontology's `SB-32` example is reconciled. No ADR.

### Retry Layering frontier

Three tickets are takeable now. 01 and 02 are an expand-and-contract pair on the
transport; 03 and 04 both rewrite the resolver loop and will conflict if worked
in parallel.

- [01 A retrying HTTP client behind every Ollama model](projects/coreference-retry-layering/issues/01-retrying-http-client.md), takeable. Adds only: the retry happens at the failed request, and the pipeline's own retry stops firing.
- [02 The Story Pipeline stops retrying stage calls](projects/coreference-retry-layering/issues/02-pipeline-stops-retrying-stage-calls.md), blocked by 01. The contract half: `_execute_with_retry`, `classify_api_error`, and the four `time.sleep` backoff tests are deleted.
- [03 Coreference agents take dependencies](projects/coreference-retry-layering/issues/03-agents-take-dependencies.md), takeable. One rendering of the numbered Source Article; a correction round continues the annotator's conversation. Costs tokens rather than saving them.
- [04 Prefactor: the resolution loop's state becomes a model](projects/coreference-retry-layering/issues/04-resolution-state-is-a-model.md), takeable. No behavior change; the last-write-wins invariant stops being a docstring.
- [05 Only model-output failures are recorded as validation failures](projects/coreference-retry-layering/issues/05-only-model-output-failures-are-validation-failures.md), blocked by 04. A socket timeout stops being archived as a prompt-quality problem.
- [06 An annotator whose Mention Spans cannot be located is asked again](projects/coreference-retry-layering/issues/06-correct-unlocatable-mention-spans.md), blocked by 03. Changes what reaches the Dead Letter Queue, so it lands last.

### Coreference Resolution via Mention Spans frontier

A linear chain. Only issue 01 is takeable now; each later issue is gated by the
one before it.

- [01 Numbered sentence splitter](projects/coreference-mention-spans/issues/01-numbered-sentence-splitter.md), takeable. Pure utility, no model: sentences with exact character ranges whose concatenation reproduces the article.
- [02 Mention Span schema, validation, and substitution](projects/coreference-mention-spans/issues/02-mention-span-schema-validation-substitution.md), blocked by 01. The deterministic core — Python derives every character offset.
- [03 Annotator returns Mention Spans, wired end to end](projects/coreference-mention-spans/issues/03-annotator-returns-mention-spans.md), blocked by 02. The Structural Identity Check leaves the resolution path. Resolution is unchecked until 04.
- [04 Per-Mention-Span Critic verdicts and targeted retry](projects/coreference-mention-spans/issues/04-per-mention-critic-verdicts.md), blocked by 03. One misread pronoun stops costing its neighbours.
- [05 Zero-survivor failures and Dead Letter Queue payload](projects/coreference-mention-spans/issues/05-zero-survivor-failures-and-dlq-payload.md), blocked by 04. Three failure types, and the discard proportion that a partial-discard threshold will later be set from.
- [06 Delete the tag machinery](projects/coreference-mention-spans/issues/06-delete-tag-machinery.md), blocked by 05. The contract step; deletion only.
- [07 Domain vocabulary and ADR](projects/coreference-mention-spans/issues/07-context-and-adr.md), blocked by 06. `CONTEXT.md` gains **Mention Span**; a new ADR supersedes ADR 0001's markup decision.

### News Ontology and Graph Population frontier

Issue 01 is complete. Two issues are takeable now; the rest declare their
blockers.

- [01 Author and review the Policy Area vocabulary](projects/news-ontology-graph-population/issues/01-author-policy-area-vocabulary.md), `completed` on 2026-08-06. Its deliverable is [the Policy Area vocabulary](projects/news-ontology-graph-population/policy-area-vocabulary.md): 27 topic slugs derived from the Assembly and Senate subject-matter standing committees, reviewed and accepted.
- [05 Write-path ontology vocabulary rename](projects/news-ontology-graph-population/issues/05-write-path-ontology-vocabulary-rename.md), takeable. A mechanical prefactor: `:Article` becomes `:NewsArticle` and `BELONGS_TO` becomes `HAS_CHUNK`.
- [02 Ontology package and conformance check](projects/news-ontology-graph-population/issues/02-ontology-package-and-conformance-check.md), takeable — unblocked by 01. Everything else in the project reads the News Ontology it introduces.
- [03 Extraction Prompt generated from the News Ontology](projects/news-ontology-graph-population/issues/03-generate-extraction-prompt-from-news-ontology.md), blocked by 02.
- [04 Sub-labels and extraction conformance](projects/news-ontology-graph-population/issues/04-sub-labels-and-extraction-conformance.md), blocked by 02.
- [06 Node identity, provenance, and topic edges](projects/news-ontology-graph-population/issues/06-node-identity-provenance-and-topic-edges.md), blocked by 02, 04, and 05.
- [07 Bill session resolution](projects/news-ontology-graph-population/issues/07-bill-session-resolution.md), blocked by 06.
- [Code review of issues 02–07](projects/news-ontology-graph-population/code-review/README.md), `ready-for-agent` as of 2026-08-07. Eighteen findings from a standards-and-spec review of the six completed issues. Three would corrupt the graph 08 builds, and two acceptance criteria are ticked for work that was not done. Broken into [fourteen tickets](projects/news-ontology-graph-population/code-review/issues/) on 2026-08-08; tickets 01, 03, 04, 05, and 07 are takeable now and the rest declare their blockers.
- [08 Rebuild the graph and record the label inventory](projects/news-ontology-graph-population/issues/08-rebuild-graph-and-record-label-inventory.md), blocked by 03, 04, 06, 07, and the code review. Produces the label and relationship counts the Useful Graph Retrieval map waits on.

### Useful Graph Retrieval frontier

The [Useful Graph Retrieval map](initiatives/useful-graph-retrieval/MAP.md) was
charted on 2026-07-29 and holds ten tickets. Issues 04 through 07 are complete.
Issue 08's semantics are settled; Graph-Prioritized Retrieval issue 02 supplies
its remaining concrete types. Issue 09 waits for working retrieval branches and
parameterized fusion so it can measure real rankings.

- [Update the extraction prompt to the settled ontology and populate the graph](initiatives/useful-graph-retrieval/issues/01-populate-graph-with-settled-ontology.md), `ready-for-agent` as of 2026-08-05, specified by the [News Ontology and Graph Population PRD](projects/news-ontology-graph-population/PRD.md). Population work remains open, but the current graph inventory is sufficient for the retrieval prototype to proceed.
- [Decide the target question set for California political retrieval](initiatives/useful-graph-retrieval/issues/02-target-question-set.md): the authored question set is available as an input to the prototype.
- [Survey graph retrieval patterns and available tooling](initiatives/useful-graph-retrieval/issues/03-survey-graph-retrieval-patterns.md), `completed` on 2026-08-05; facts live in [the findings](initiatives/useful-graph-retrieval/research/03-graph-retrieval-patterns-findings.md).
- [Decide which subgraph is retrievable now and which is deferred](initiatives/useful-graph-retrieval/issues/04-retrievable-subgraph-now.md), `completed` on 2026-09-08. Scope, librarian presentation, and coverage policy are settled against the live inventory.
- [Prototype query construction and validation against the ontology](initiatives/useful-graph-retrieval/issues/05-prototype-query-construction-and-validation.md), `completed` on 2026-09-14. The atomic semantic constructor preserved at `511eaeee` is the selected structural construction shape.
- [Decide the retrieval modes and the index inventory they require](initiatives/useful-graph-retrieval/issues/06-retrieval-modes-and-index-inventory.md), `completed` on 2026-09-08. Full-text search, chunk vectors, and typed traversal contribute combined chunk candidates. External-identifier implementation and Policy Area vectors are deferred.
- [Decide the retrieval agent topology and orchestration](initiatives/useful-graph-retrieval/issues/07-retrieval-agent-topology.md), `completed` on 2026-09-16. The accepted design is specified for implementation by [Graph-Prioritized Retrieval](projects/graph-prioritized-retrieval/PRD.md).
- [Define the retrieval and answer contract](initiatives/useful-graph-retrieval/issues/08-retrieval-and-answer-contract.md), blocked by Graph-Prioritized Retrieval issue 02. Its behavior is settled; the remaining work records the concrete Pydantic types produced by implementation.
- [Prototype graph-aware reranking](initiatives/useful-graph-retrieval/issues/09-prototype-graph-aware-reranking.md), blocked by Graph-Prioritized Retrieval issues 03, 04, 06, and 07. It measures real branch outputs and may recommend later configuration changes; it does not block the implementation project.

### Pydantic-Native Evaluation Routing

The linear expand-contract chain completed on 2026-09-03.

- [01 Separate model telemetry from Request Provenance](projects/pydantic-native-evaluation-routing/issues/01-separate-model-telemetry-from-request-provenance.md), `completed` on 2026-09-03. Adds the missing provider span attribute and narrows HTTP capture while preserving the current report.
- [02 Add Model Route Summaries to completed reports](projects/pydantic-native-evaluation-routing/issues/02-add-model-route-summaries-to-completed-reports.md), `completed` on 2026-09-03. Derives the compact case summary from Pydantic Evals while the old report fields remain temporarily.
- [03 Remove Request Provenance](projects/pydantic-native-evaluation-routing/issues/03-remove-request-provenance.md), `completed` on 2026-09-03. Deletes the parallel recorder and leaves the final report contract.

### Blocked initiative chain

The [Model Evaluation map](initiatives/model-evaluation/MAP.md) is the current
large-scale investigation. Its remaining specification branches are ordered,
not parallel:

1. [Specify Relevance Filter evaluation](initiatives/model-evaluation/issues/04-specify-relevance-filter-evaluation.md), blocked by the human Gold Set work.
2. [Specify Selector Healing evaluation](initiatives/model-evaluation/issues/05-specify-selector-healing-evaluation.md), blocked by the Relevance Filter specification.
3. [Specify Coreference Resolution evaluation](initiatives/model-evaluation/issues/06-specify-coreference-evaluation.md), blocked by the Selector Healing specification.
4. [Specify Entity Extraction evaluation](initiatives/model-evaluation/issues/07-specify-entity-extraction-evaluation.md), blocked by the Coreference Resolution specification.

These retain `needs-triage` until their blockers are resolved; they are not
currently executable. After ADR 0017 each of them is a smaller question than
when it was written: what a case looks like for that component and what scores
it, not how the run is persisted.

## Project state

| Triage state | Projects |
| --- | --- |
| `ready-for-agent` | [Bill Designation Recovery](projects/bill-designation-recovery/PRD.md); [Graph-Prioritized Retrieval](projects/graph-prioritized-retrieval/PRD.md); [News Ontology and Graph Population](projects/news-ontology-graph-population/PRD.md); [Retry Layering and a Deps-Driven Coreference Resolver](projects/coreference-retry-layering/PRD.md) |
| `ready-for-human` | [Scraping Pipeline](projects/scraping-pipeline/PRD.md) |
| `completed` | [Article Chunking and Coreference Resolution](projects/article-chunking-coreference/PRD.md); [Batch Ingestion Orchestration](projects/batch-ingestion-orchestration/PRD.md); [Coreference Reliability](projects/coreference-reliability/PRD.md); [Flexible Category Filtering](projects/flexible-category-filtering/PRD.md); [Influence Graph Playground](projects/influence-graph-playground/PRD.md); [OpenRouter Model Deployments](projects/openrouter-model-deployments/PRD.md); [Pipeline Stage Ownership](projects/pipeline-stage-ownership/PRD.md); [Policy Area Staging](projects/policy-area-staging/PRD.md); [Pydantic-Native Evaluation Routing](projects/pydantic-native-evaluation-routing/PRD.md); [Relevance Classification](projects/relevance-classification/PRD.md); [Story Pipeline Coordinator](projects/story-pipeline-coordinator/PRD.md) |
| `superseded` | Eight evaluation-contract projects, moved to [work/archive/superseded-by-adr-0017/](archive/superseded-by-adr-0017/README.md) |

## Reconciliation record

On 2026-07-24, project labels were reconciled with child acceptance criteria
and the current test suite:

- Stale parent labels were closed when every child issue was complete.
- Checked Case Evaluation Requirements issues 10–12 and all Structured Metric
  Observation tickets were relabeled `completed`.
- The checked Scraping Pipeline Relevance Filter ticket was relabeled
  `completed`; the project remains `ready-for-human` for its two evaluation
  datasets.
- Renewable Evaluation Finalization remains `ready-for-agent` because its
  focused contention-boundary follow-up is unchecked.
- The full deterministic suite passed: `453 passed`.
- Historical observations in [inbox.md](inbox.md) remain untriaged candidates,
  not executable tickets.

On 2026-07-29, after the Unified Evaluation Execution Path collapsed to a single
runner-only execution seam:

- The full deterministic suite passed: `489 passed`.
- The per-issue counts in that project's issues 10, 14, and 15 (`482`, `493`,
  `489`) are dated observations of the suite at those moments. They are a
  before-and-after record, not invariants: each is left as measured, and an
  unexplained movement between them is the signal to investigate.

On 2026-08-05, the `ready-for-agent` queue was reconciled against the issue
files and the code:

- The four issues listed under "Ready for agent" were already labeled
  `completed` in their own files; the README listing was stale, as were both
  "gated" paragraphs — Pipeline Stage Ownership 04–10 and Data Set Construction
  01–03 are all `completed`.
- [Bound transient renewal contention](projects/renewable-evaluation-finalization-authority/issues/01-bound-transient-renewal-contention-by-confirmed-authority.md)
  was implemented but never relabeled. The heartbeat compares the ledger clock
  against the last confirmed expiry with strict inequality, before and after the
  ownership query, and
  `test_transient_renewal_and_ownership_contention_stop_at_confirmed_expiry`
  covers the contended-through-expiry case. Relabeled `completed`, and the
  parent PRD with it.
- Pipeline Stage Ownership and Evaluation Data Set Construction were relabeled
  `completed`; every child of both is complete. No project is `ready-for-agent`.
- The only remaining agent-takeable ticket is the Useful Graph Retrieval survey,
  which has produced no `research/` output yet.
- The full deterministic suite passed: `544 passed`.

On 2026-08-19, [ADR 0017](../docs/adr/0017-git-is-the-evaluation-versioning-system.md)
removed the Evaluation Ledger:

- Eight projects specifying the ledger and its contract were archived as
  `superseded` under [work/archive/superseded-by-adr-0017/](archive/superseded-by-adr-0017/README.md).
  They were built, most of them to completion, and then removed. They are not
  relabeled `completed`, because the thing they completed no longer exists.
- The evaluation package went from 9,008 lines to 570, of which 289 are the
  `tasks/` package added afterwards to define the relevance task. `CONTEXT.md`
  went from 91 terms to 60, and from 37 evaluation terms to 6.
- The deterministic suite went from `648 passed` to `399 passed` as the 249
  ledger tests were removed with the code they covered, then to `410 passed`
  with the eleven covering the replacement.
- [Build the initial relevance Evaluation Gold Set](initiatives/model-evaluation/issues/03-build-initial-relevance-evaluation-gold-set.md)
  is unblocked and is now the whole of the evaluation work: a YAML file of
  hand-labeled headlines.

On 2026-09-02, Policy Area Staging was built and closed:

- All seven issues are `completed`, and the project with them. Each was
  implemented test-first and then reviewed on the standards and spec axes by a
  reader who had not written it; five of the seven reviews found something to
  fix.
- The deterministic suite went from `733 passed` to `850 passed`.
- One acceptance criterion is left unchecked rather than ticked. Issue 01's "The
  SQLite adapter satisfies the Protocol" has no target: `sqlite_db.py` provides
  `SQLiteStatusTracker`, which implements `StatusTracker`, and `Neo4jAdapter` is
  the only `DatabaseAdapter` in the repository. Its intent is covered by a test
  that walks every Protocol method and compares parameter names.
- Topic Assignment shipped reading the Source Article's raw content while both
  of its other inputs were derived from the coreference-resolved text. Two
  reviews of the stage missed it; building the Data Set in 06 surfaced it,
  because a case cannot record what a stage is given without saying which text
  that is. Fixed in `d5bbfeb`.
- The areas-per-article distribution issue 02 deferred was measured over the
  twenty silver cases: 57 labels across 20 articles, mean 2.85, maximum 5. No
  cap was introduced, which is what the measurement was for.
- [IG-10](inbox.md) records what the Topic Assignment Data Set surfaced and did
  not settle: `ABOUT_TOPIC` admits only `Bill` and `Prop`, so an enacted federal
  statute is annotated as a `Bill`. A modelling gap, not an annotation error.

## Information model

| Level | Purpose | Location |
| --- | --- | --- |
| Roadmap | Product outcomes and strategic sequence | `roadmap.md` |
| Initiative | A large uncertain area that needs investigation | `initiatives/<slug>/` |
| Project | A bounded deliverable described by a PRD | `projects/<slug>/` |
| Issue | An independently completable change or investigation | A project's `issues/` directory or `issues/` |
| Code review | Whether a project's build matched its PRD | `projects/<slug>/code-review/` |
| Inbox | Unshaped ideas, defects, questions, and observations | `inbox.md` |
| Archive | Superseded plans and immutable imported source notes | `archive/` |

Supporting knowledge remains outside this hierarchy:

- [`CONTEXT.md`](../CONTEXT.md) defines the domain language.
- [`docs/adr/`](../docs/adr/) records durable architectural decisions.
- `.scratch/` contains disposable runtime output, not project plans.

## Label convention

`Labels:` is the only state header. Do not add a separate `Status:` field.

Each work item should have exactly one triage-state label:

- `needs-triage`
- `needs-info`
- `ready-for-agent`
- `ready-for-human`
- `completed`
- `wontfix`

Additional descriptive labels may share the same comma-separated line. For
example:

```text
Labels: wayfinder:research, ready-for-human
```

The triage-state label says what should happen next. Other labels describe the
kind of work.

## Archive

- `archive/imports/` contains verbatim snapshots of the two Obsidian notes used
  to seed this structure.
- `archive/legacy-plans/` contains completed or superseded standalone plans
  formerly located at the repository root.
