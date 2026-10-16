# Inbox

This is the capture point for defects, questions, ideas, and risks that have not
yet been accepted as executable work. An inbox entry is not a commitment.

During triage, move an item into a standalone issue, mark it resolved with
evidence, or deliberately discard it. This cleanup intentionally excludes work
already tracked under `projects/`, `initiatives/`, and other `archive/`
documents.

## Priority scale

- **P0:** Active correctness, security, data-integrity, or reliable-operation
  risk.
- **P1:** Important behavior or reliability work for the next dependable
  iteration.
- **P2:** Concrete maintainability, performance, or design debt.
- **P3:** Product or architecture exploration without a demonstrated current
  failure.
- **P4:** Speculative future option with no present use case.

## Reconciliation state

The executable tracker was reconciled on 2026-07-24. Parent project labels now
reflect their unresolved child work, legacy checked tickets are labeled
`completed`, and the Model Evaluation dependency chain is visible in
[README.md](README.md).

The queue below came from the July 9 audit and its `Loose Notes` section. Before
promotion, each observation must be checked against the current code and tests.
Stable IDs prevent bundled or duplicate notes from disappearing during that
reconciliation.

On 2026-07-25 the imported loose notes, previously held in a single
undifferentiated `LN-*` list, were classified into the four evaluation-framework
categories below and renumbered under category prefixes matching the rest of
this queue: `EC`, `EP`, `ER`, and `ED`. Their wording is unchanged, and the
[loose-note ID crosswalk](#loose-note-id-crosswalk) maps every retired `LN-*`
identifier to its replacement so each entry still traces back to `## Loose
Notes` in the immutable July 9 source note. Struck-through findings in that
source remain intentionally omitted from this queue.

## Extraction and graph integrity

- **IG-01 · P0:** Preserve multiple labels for extracted graph nodes.
- **IG-02 · P0:** Require all Article Chunks to extract successfully before any
  complete Source Article result is persisted to the graph.
- **IG-03 · P1:** Define a tolerant Structural Identity Check boundary for
  harmless leading-text differences without weakening identity guarantees.
- **IG-04 · P1:** Bound retry context and retain a compact failure history.
- **IG-05 · P1:** Introduce a shared typed hierarchy for model-call failures.
- **IG-06 · P1:** Version and refine the Entity Extraction ontology and prompts.
- **IG-07 · P2:** Decide whether `extract_from_chunks` belongs on the Entity
  Extraction protocol.
- **IG-08 · P3:** Decide whether Neo4j vector-index readiness is a connection
  invariant or an explicit startup/migration concern.
- **IG-09 · P1:** Define reversal semantics for a Source Article whose relevance
  flips away from `RELEVANT` after ingestion has completed. Manual review
  (`classifier label`) calls `delete_uningested_story`, which deliberately
  spares a `COMPLETED` Story. That row therefore survives at null validation,
  knowingly breaking the
  [issue 05](projects/pipeline-stage-ownership/issues/05-enforce-the-story-invariant-in-the-validation-loop.md)
  invariant that a Story exists exactly when validation is `'VALIDATED'`, and
  the article's Neo4j nodes stay live with no reversal signal on the relational
  side. The validation loop calls the same writer but cannot reach this case —
  it selects only `validation = 'PENDING'`, and every writer of that value also
  sets `relevance_status` to `'RELEVANT'`, so a `COMPLETED` Story never reaches
  the reversal branch there. Manual review is the live trigger. Decide what the
  reversal should mean — retract the graph nodes, mark the Story retracted while
  retaining it, or accept the divergence and record it as an explicit exception
  to the invariant — and make the skipped deletion observable either way; today
  it returns `False` and nothing logs it. Scoped out of
  [Pipeline Stage Ownership](projects/pipeline-stage-ownership/PRD.md)
  as "Removing Neo4j nodes for articles whose relevance is reversed after
  ingestion," so this is the capture point for the deferred decision.
- **IG-10 · P3:** Decide whether the News Ontology needs a term for an enacted
  law. `ABOUT_TOPIC` admits only `Bill` and `Prop` as its source labels, so the
  Topic Assignment Data Set annotates the National Alzheimer's Project Act — a
  federal statute enacted in 2011 — as a `Bill` to make the topic edge
  expressible at all. That is a modelling gap rather than an annotation error:
  the vocabulary has no way to say "a law that already passed", and federal
  statutes are the case that exposes it. Surfaced while recording both topic
  stages in `GLOSSARY.md`
  ([issue 07](projects/policy-area-staging/issues/07-record-the-two-stages.md)),
  and deliberately left out of that vocabulary ticket, which describes the
  pipeline that shipped rather than redesigning the ontology.

## Model reliability and evaluation

- **ME-01 · P0:** Define a common retry policy for transport errors, timeouts,
  malformed output, and rate limits across model-backed workflows.
- **ME-02 · P0:** Establish trustworthy Evaluation Data Sets backed by real
  labeled examples.
- **ME-03 · P1:** Complete component-specific evaluations for Relevance Filter,
  Selector Healing, Coreference Resolution, Entity Extraction, and fallbacks.
- **ME-04 · P1:** Record complete model, prompt, temperature, and execution
  metadata.
- **ME-05 · P1:** Keep deterministic contract tests distinct from model-quality
  evaluations.
- **ME-06 · P3:** Cover retrieval failure and low-relevance context in RAG
  retrieval-specific evaluations. Keep these out of the scenario dimension for
  end-to-end Chat Session synthetic inputs, which varies request and evidence
  conditions. A required data source not yet ingested is a coverage condition,
  distinct from retrieval failing to return relevant evidence that is available.
  Captured on 2026-09-30 during synthetic Evaluation Case planning.

This category covers whether the models themselves are good and dependable.
Whether the evaluation framework that measures them is itself correct is a
separate concern, held in the four evaluation-framework categories below.

Related work exists under the excluded
[Model Evaluation initiative](initiatives/model-evaluation/MAP.md); this queue
will not modify that initiative.

## Evaluation population integrity

- **EG-01 · P1:** Replace destructive removal of Evaluation Cases from later
  Evaluation Data Set revisions with an explicit retirement or invalidation
  state. Preserve each retired case's business identity, exact revision, prior
  split, and reason while excluding it from future Evaluation Runs. Define
  reintroduction semantics at the business-identity level so a formerly
  `held-out` or `calibration` case cannot later enter `training` and pollute
  evaluations merely because its intervening membership was retired. Retirement
  is recorded through the Evaluation Ledger transaction facade
  ([ADR 0010](../docs/adr/0010-keep-one-evaluation-ledger-transaction-facade.md)),
  so this spans the Data Set revision API and the ledger together.

## Scraping and validation

- **SV-01 · P0:** Verify current CalMatters extraction quality against retained
  fixtures or live evidence before treating content noise as a confirmed
  defect.
- **SV-02 · P1:** Define precedence when JSON-LD, Open Graph, Twitter, and other
  metadata disagree.
- **SV-03 · P1:** Give Article Validator results an explicit valid, invalid, or
  unvalidatable shape with supporting evidence.
- **SV-04 · P1:** Document the repeatable workflow for inspecting, proposing,
  approving, and applying Selector Versions.
- **SV-05 · P1:** Decide whether selector rejection applies to one field or the
  complete selector set.
- **SV-06 · P1:** Record Generator and Critic prompt versions in selector
  proposals.
- **SV-07 · P1:** Define the acceptable word-count ratio used during
  validation.
- **SV-08 · P3:** Reassess negative selectors when a concrete layout variant
  demonstrates a need.
- **SV-09 · P3:** Consolidate model factories when their duplication creates a
  concrete maintenance problem.
- **SV-10 · P4:** Normalize authors only after an independent-author query use
  case exists.
- **SV-11 · P4:** Promote opaque discovery configuration only after a field
  needs independent querying.
- **SV-12 · P2:** Make logging less verbose, don't allow failed validation to log entire html pages

## Ingestion and operations

- **IO-01 · P0:** Encode continuation rules for article-scoped, transient
  dependency, and system-scoped failures.
- **IO-02 · P0:** Stop representing infrastructure failure as if the Source
  Article itself were defective.
- **IO-03 · P1:** Make adapter failure contracts consistent: typed results or
  typed exceptions, not both ambiguously.
- **IO-04 · P1:** Ensure intentionally skipped and permanent failures remain
  observable.
- **IO-05 · P1:** Use Neo4j adapter context managers consistently.
- **IO-06 · P2:** Decide whether Janitor should resume the pipeline after a
  successful health check.
- **IO-07 · P2:** Localize log ownership and avoid duplicate events.
- **IO-08 · P3:** Put console notification behind an adapter if non-terminal
  delivery is needed.

## Relevance classification

- **RC-01 · P0:** Establish and preserve a human-labeled relevance dataset with
  explicit provenance.
- **RC-02 · P1:** Validate the complete classifier path and its cache ownership.
- **RC-03 · P1:** Explain or remove the single-worker executor bridge.
- **RC-04 · P1:** Document and evaluate static fallback examples.
- **RC-05 · P1:** Separate cache existence, relevance, validation, and
  processing state.
- **RC-06 · P3:** Add classification rationales only if review or evaluation
  needs them.
- **RC-07 · P4:** Compare heuristics and logistic regression only after the
  Evaluation Data Set and protocol are stable.

## Evaluation contract and schema integrity

Whether an authored evaluation definition means one unambiguous thing, and
whether declared contracts can be bypassed.

- **EC-01 · P0:** Validate structured metric values before JSON normalization so
  forbidden Python containers and non-string mapping keys cannot be silently
  coerced into accepted shapes.
- **EC-02 · P0:** Prevent direct `ResolvedSchemaBinding` construction from
  bypassing the explicit allowlisted Schema Registry.
- **EC-03 · P2:** Reassess whether a separate component-owned Evaluation
  Requirement Catalog is necessary when Evaluation Requirement Bindings carry
  overlapping information.
- **EC-04 · P2:** Remove compatibility shims that permit tests or nonexistent
  ledger records to bypass production invariants.
- **EC-05 · P2:** Keep the component-owned Evaluation Requirement Catalog out of
  unrelated Evaluation Suite revision content.
- **EC-06 · P3:** Decide whether every Evaluation Comparison Operation needs an
  explicit version and when custom comparison logic is warranted.

## Evaluation planning and validation

Whether preflight produces a Resolved Evaluation Plan that the rest of execution
actually trusts, instead of rederiving and revalidating the same decisions.

- **EP-01 · P1:** Require a Resolved Evaluation Plan at the Suite execution
  boundary when execution semantics depend on preflight.
- **EP-02 · P2:** Centralize Evaluation Case–Suite compatibility predicates so
  preflight accumulation and fail-fast validation cannot drift.
- **EP-03 · P2:** Eliminate redundant case validation between Suite execution,
  evaluator resolution, preflight, and durable execution.
- **EP-04 · P2:** Make durable Evaluation Run execution consume the Resolved
  Evaluation Plan produced by preflight instead of independently deriving
  evaluator assignments.
- **EP-05 · P2:** Construct Evaluation Runs from the Resolved Evaluation Plan
  rather than accepting and revalidating duplicated plan-derived fields.

EP-01 through EP-05 were shaped on 2026-07-27 into
[Unified Evaluation Execution Path](projects/unified-evaluation-execution/PRD.md).
They remain listed here as the origin of that project, not as open candidates.

## Evaluation run lifecycle and finalization

Whether a run starts, stops, fails, and completes at the moments its contract
says it should, and whether those transitions are reported truthfully.

- **ER-01 · P0:** Normalize runtime task exceptions into provider-neutral,
  conservatively redacted `TaskFailure` values with truthful category and
  retryability; keep large or sensitive raw evidence outside relational
  outcome JSON.
- **ER-02 · P0:** Prove Evaluation Run completion requires all terminal task,
  case-evaluator, report-evaluator, and manifest evidence—not merely completed
  case evaluation.
- **ER-03 · P0:** Honor a controlled stop after the final—or only—report
  evaluator and before any Release Gate begins.
- **ER-04 · P1:** Ensure the report-evaluator adapter does not silently discard
  evaluator failures.
- **ER-05 · P1:** Remove or reject the `run()` release-gate parameter if Release
  Gates execute only during Evaluation Finalization.
- **ER-06 · P1:** Allow same-run recovery when aggregate-manifest freezing fails
  after the case phase has completed.
- **ER-07 · P1:** Bound retryable finalization-renewal contention by the last
  confirmed live authority interval. This is already represented by excluded
  project work and must not be duplicated here.
- **ER-08 · P2:** Measure and, if confirmed, optimize slow terminal recovery in
  `assert_run_is_complete`.
- **ER-09 · P2:** Consolidate repetitive guards that prevent report evaluation
  before case completion or outside the durable runner.
- **ER-10 · P1:** Retry a case whose task failed for a transient reason (IO or
  API) within its own Evaluation Run, so one flaky call does not force the whole
  caseload to be re-run later. Desired behavior; no such mechanism exists today.
  A transient failure lands as a terminal `FAILED` disposition on first attempt,
  and the runner's only retry loops are SQLite contention and finalization
  persistence. This does not conflict with the point-in-time Evaluation Run: the
  run has not reached terminal evidence and no new run is created, so it is not
  the resumption GLOSSARY.md reserves for Evaluation Finalization. Open question
  before shaping: whether a case that exhausts its transient retries is `FAILED`
  with the run still completing, or leaves the run incomplete. Depends on
  truthful retryability from ER-01.

## Evaluation durability and artifacts

Whether the Evaluation Ledger, its checkpoints, and its artifacts survive
interruption without losing or corrupting evidence.

- **ED-01 · P1:** Define and enforce robust Evaluation Artifact reads,
  including integrity and missing-location behavior.
- **ED-02 · P1:** Use one canonical checkpoint document and hash implementation
  for checkpoint writes and integrity verification.
- **ED-03 · P1:** Atomically checkpoint evaluator-produced artifacts with their
  evaluator execution and observations.
- **ED-04 · P2:** Consolidate duplicated synchronous and asynchronous recording
  behavior in case- and report-evaluator adapters.
- **ED-05 · P2:** Move framework-report materialization out of the Evaluation
  Ledger persistence façade while preserving its atomic transaction boundary.
- **ED-06 · P2:** Persist Evaluation Run Issues raised during a case in the same
  atomic checkpoint as that case.
- **ED-07 · P2:** Consolidate duplicated replay-consistency algorithms for
  evaluator executions and observations.
- **ED-08 · P2:** Remove the one-off retrieval report migration, along with
  the rescoring path it alone uses and its test. Then update the retrieval
  guide's instruction to run it. The migration has already been applied: every
  committed retrieval report carries a compact `retrieval_report` block, and new
  runs are compacted when written. It rewrites committed reports in place,
  which conflicts with ADR 0024's unchanged historical reports and with
  ADR 0026's frozen run result. Captured 2026-10-16 during the
  [Evaluation headline metrics](projects/evaluation-headline-metrics/PRD.md)
  spec.

## Retrieval and product exploration

These ideas came from the original vision and project-breakdown sketch. They
remain speculative unless current code or product requirements demonstrate a
concrete need.

- **RP-01 · P3:** Set up a simple graph query interface and chat interface.
- **RP-02 · P2:** Define Cypher creation and validation boundaries.
- **RP-03 · P4:** Explore an orchestration agent for graph queries.
- **RP-04 · P3:** Evaluate graph retrieval and answer restriction.
- **RP-05 · P4:** ~~Compare entity-, edge-, neighborhood-, and
  community-oriented retrieval.~~ Superseded: the
  [target question set](initiatives/useful-graph-retrieval/issues/02-target-question-set.md)
  settles the taxonomy as entity lookup, relationship lookup, and multi-hop
  traversal, and rules community-oriented retrieval out of scope.
- **RP-06 · P4:** Explore cross-encoder, graph-aware, and embedding-fusion
  reranking.
- **RP-07 · P3:** Review graph entities, relationships, ontology, and evaluation
  results together as an iterative refinement loop.
- **RP-08 · P4:** Decide what a hosted evaluation dashboard should show.
- **RP-09 · P4:** Consider ETL for additional news sources after the current
  pipeline is dependable.
- **RP-10 · P4:** Consider hosted Neo4j and pipeline deployment after local
  operational semantics are stable.

## UI/UX fixes

Captured from hands-on Source Guides feedback on 2026-10-09. Related project:
[Source Guides](projects/source-guides/PRD.md).

- **UX-01:** Make the transition from running to completed more evident.
  Promoted to [completion notice](issues/08-source-guide-completion-notice.md)
  on 2026-10-10. The issue owns its enhancement, `ready-for-agent` labels.
- **UX-02:** Prototype layout alternatives to stacking everything in a single
  vertical view.
  Labels: enhancement, needs-info
- **UX-03:** Provide links that take readers to the relevant portion of an
  article. The reported experience describes a section but leaves the reader
  to find it themselves.
  Labels: bug, needs-info
- **UX-04:** Transition from the ask-question view to a looking-for-sources
  view after submission, and reset the question input.
  Promoted to [submission transition](issues/09-source-guide-submission-transition.md)
  on 2026-10-10. The issue owns its enhancement, `ready-for-agent` labels.
- **UX-05:** Show articles in pro and against sections in the contrastive view.
  Labels: enhancement, needs-info
- **Browser repeats stopped-attempt wording.** `outcomeLabels` in
  `src/knowledge_map/resources/source-guides/guide.js` repeats the cancelled
  and interrupted messages that the Source Guide projection owns in
  `chat_presentation.py`, and hides `guide.message` when it equals the label.
  A wording change in the projection would leave the browser label stale.
  Found in the 2026-10-16 review of
  [Source Guide projection](projects/source-guide-projection/PRD.md), which
  excluded browser presentation. P2.
  Labels: needs-triage

### Triage findings, 2026-10-09

> *This was generated by AI during triage.*

These are the initial recommendations. The maintainer approved the split on
2026-10-10. UX-01 and UX-04 now have standalone agent briefs, and UX-02, UX-03,
and UX-05 are `needs-info`. The entries above record their current disposition.

The redundancy check covered the Source Guide reader's HTML, CSS, submission,
polling, outcome rendering, reading-view ordering, and article rendering;
`SourceGuide` and `GuideArticle`; the original-Story section-link projection;
and application tests for sections, groups, and execution. It also covered the
completed Source Guides tickets 03, 07, 08, and 09, the saved-guide navigation
correction, the Source Guides PRD's latest clarification, and the domain terms
Source Guide and Article Group. There is no `.out-of-scope/` knowledge base in
this checkout. The relevant existing scope boundaries are in the Source Guides
PRD. No duplicate open implementation issue was found for these presentation
requests.

- **UX-01: enhancement, proposed `ready-for-agent`.** Running and terminal
  labels already exist, and polling refreshes them. Completion currently changes
  ordinary outcome and metadata text; it has no dedicated transition notice.
  This supports a presentation improvement, not a claim that execution fails
  to complete. Suggested scope: give the selected attempt a clear, accessible
  completion notice once when it becomes terminal. Distinguish successful
  completion, empty results, and unsuccessful outcomes. Preserve the reader's
  scroll position and distinguish an update's outcome from retained reading.
  Visual prominence still needs reader verification; none was performed here.
- **UX-02: enhancement, proposed `needs-info`.** The reader places the question
  form, complete saved-guide list, and selected guide vertically inside one
  narrow main column. The completed navigation correction brings an explicitly
  opened saved guide into view but does not change this layout. Before writing
  a prototype brief, choose the problem to test: access to saved guides, the
  question-to-search transition, comparison of reading groups, or a combination.
  Also choose whether the experiment targets desktop, mobile, or both. A
  prototype should compare alternatives against a named reader task before a
  production layout is selected.
- **UX-03: bug, proposed `needs-info`.** The reported navigation problem is
  not yet reproduced. Verified original-text links already ship as
  `GuideArticle.section_links` and appear as nearby numbered highlights. An
  unchanged, unambiguous selected passage produces a text-fragment URL; missing
  original Story content, changed coreference wording, or ambiguous matches
  deliberately leave the ordinary article link. Reopening a saved guide does
  not regenerate targets. A guide/question, affected article URL, and the
  observed behavior are needed to distinguish absent links, an irrelevant
  target, an undiscoverable highlight control, or publisher/browser navigation
  failure. Describe whether a highlight was present and what happened on click.
  Do not close this reported experience as already implemented merely because
  the general capability exists. Guaranteed live-page highlighting and an
  ingestion overhaul for DOM locations remain outside the current PRD.
- **UX-04: enhancement, proposed `ready-for-agent`.** Static inspection confirms
  the successful submission handler displays the saved guide but never clears
  `question.value` or hides the question form. The API already returns a saved
  identity while execution runs independently. Suggested scope: after confirmed
  submission, clear the input and display a dedicated search view containing
  the submitted question, status, and Cancel control. Keep New question and
  Edit question available. Preserve the draft until submission is confirmed;
  an uncertain submission must retain the existing guidance to check saved
  guides before trying again. Navigation must not cancel independent searches.
- **UX-05: enhancement, proposed `needs-info`.** Contrast Article Groups already
  exist. The reader offers their labels in a selector, orders related articles
  first, and displays each group's reading directions beside each article. It
  does not render separate pro/against sections. The current domain model
  allows one article in several groups and does not assign an article a
  political position. The maintainer's latest PRD clarification also requires
  one ordinary link per article. Before promotion, decide whether sections mean
  reporting about supporting/opposing arguments, and where an article that
  covers both belongs while appearing once. Decide how ungrouped articles and
  differing accounts without a pro/against division should remain available.
  These are revisable product choices, not a reason to reject the request.

Verification: `UV_CACHE_DIR=/tmp/ca-map-triage-uv-cache uv run --no-sync pytest -q
tests/test_source_guide_sections.py tests/test_source_guide_groups.py
tests/test_source_guide_execution.py` passed all 52 tests. These deterministic
HTTP/SQLite checks establish existing capabilities, not the quality of the
reported live reader experience. No browser, computer-use, model calls, or live
publisher navigation were performed during this triage.

### Triage notes, 2026-10-10

> *This was generated by AI during triage.*

The maintainer approved the recommended split. No application code was changed.
The following questions remain before the three `needs-info` entries can be
shaped into executable work.

#### UX-02

**What we've established so far:**

- The current layout stacks the form, saved list, and selected guide vertically.
- Explicit saved-guide navigation already brings that guide into view.
- This request is for comparing layout alternatives, not selecting a production
  layout without a prototype.

**What we still need from the maintainer:**

- Which reader task should the prototype improve first: finding saved guides,
  moving from question to search, or comparing reading groups?
- Should the prototype target desktop, mobile, or both? Recommended starting
  scope is saved-guide navigation on both, since the long list currently sits
  between the input and the selected guide.

#### UX-03

**What we've established so far:**

- Verified original-text highlight links exist and pass deterministic checks.
- Uncertain original locations deliberately keep ordinary-link fallback.
- The reported reader experience has not been reproduced and remains open.

**What we still need from the maintainer:**

- Which saved guide/question and article URL exhibited the problem?
- Was a Relevant highlight link present? If so, which one, in which browser,
  and did it fail to scroll/highlight or target a different portion of the
  article? If absent, identify the reading direction whose section was missing.

#### UX-05

**What we've established so far:**

- Article Groups can describe supporting/opposing arguments without assigning
  the reporting article a political position.
- One article can serve multiple groups and currently appears once as an
  ordinary link, with all of its reading directions nearby.
- Contrast groups currently reorder a single list rather than create sections.

**What we still need from the maintainer:**

- Should pro/against mean reporting about supporting/opposing arguments?
  That interpretation preserves the current Article Group meaning.
- For an article covering both, should it appear once in a shared Both section,
  or should the one-link rule change to permit a copy in each section?
  Recommended starting point is a shared Both section, with all reading
  directions retained and ungrouped articles in an Other relevant reporting
  section. Questions contrasting accounts without opposing arguments should
  keep their question-specific group labels rather than force pro/against.

## Loose-note ID crosswalk

The `LN-*` identifiers were retired on 2026-07-25. Use this table to resolve any
external reference to the retired identifier; it is a historical index, not a
work queue.

| Retired | Current | Retired | Current | Retired | Current |
| --- | --- | --- | --- | --- | --- |
| LN-01 | EC-06 | LN-10 | EP-01 | LN-19 | ED-03 |
| LN-02 | ER-01 | LN-11 | ER-04 | LN-20 | ER-06 |
| LN-03 | EC-03 | LN-12 | ER-05 | LN-21 | ED-06 |
| LN-04 | ER-02 | LN-13 | ER-08 | LN-22 | EC-05 |
| LN-05 | EC-04 | LN-14 | ER-09 | LN-23 | EC-01 |
| LN-06 | EP-02 | LN-15 | ED-01 | LN-24 | EC-02 |
| LN-07 | EP-03 | LN-16 | ED-04 | LN-25 | ER-03 |
| LN-08 | EP-04 | LN-17 | ED-02 | LN-26 | ED-07 |
| LN-09 | EP-05 | LN-18 | ED-05 | LN-27 | ER-07 |

## Archived source

The July 9 audit contains resolved items, completed work, detailed evidence, and
historical observations. It remains preserved verbatim at
[archive/imports/project-notes-2026-07-09.md](archive/imports/project-notes-2026-07-09.md).
