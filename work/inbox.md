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

## Model reliability and evaluation

- **ME-01 · P0:** Define a common retry policy for transport errors, timeouts,
  malformed output, and rate limits across model-backed workflows.
- **ME-02 · P0:** Establish trustworthy Evaluation Gold Sets backed by real
  labeled examples.
- **ME-03 · P1:** Complete component-specific evaluations for Relevance Filter,
  Selector Healing, Coreference Resolution, Entity Extraction, and fallbacks.
- **ME-04 · P1:** Record complete model, prompt, temperature, and execution
  metadata.
- **ME-05 · P1:** Keep deterministic contract tests distinct from model-quality
  evaluations.

Related work exists under the excluded
[Model Evaluation initiative](initiatives/model-evaluation/MAP.md); this queue
will not modify that initiative.

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
  Evaluation Gold Set and protocol are stable.

## Retrieval and product exploration

These ideas came from the original vision and project-breakdown sketch. They
remain speculative unless current code or product requirements demonstrate a
concrete need.

- **RP-01 · P3:** Set up a simple graph query interface and chat interface.
- **RP-02 · P2:** Define Cypher creation and validation boundaries.
- **RP-03 · P4:** Explore an orchestration agent for graph queries.
- **RP-04 · P3:** Evaluate graph retrieval and answer restriction.
- **RP-05 · P4:** Compare entity-, edge-, neighborhood-, and
  community-oriented retrieval.
- **RP-06 · P4:** Explore cross-encoder, graph-aware, and embedding-fusion
  reranking.
- **RP-07 · P3:** Review graph entities, relationships, ontology, and evaluation
  results together as an iterative refinement loop.
- **RP-08 · P4:** Decide what a hosted evaluation dashboard should show.
- **RP-09 · P4:** Consider ETL for additional news sources after the current
  pipeline is dependable.
- **RP-10 · P4:** Consider hosted Neo4j and pipeline deployment after local
  operational semantics are stable.

## Imported loose-note concerns

These entries were extracted from `## Loose Notes` in the immutable July 9
source note. Struck-through findings are intentionally omitted from the active
queue and will be accounted for in the final reconciliation trail.

- **LN-01 · P3:** Decide whether every Evaluation Comparison Operation needs an
  explicit version and when custom comparison logic is warranted.
- **LN-02 · P0:** Normalize runtime task exceptions into provider-neutral,
  conservatively redacted `TaskFailure` values with truthful category and
  retryability; keep large or sensitive raw evidence outside relational
  outcome JSON.
- **LN-03 · P2:** Reassess whether a separate component-owned Evaluation
  Requirement Catalog is necessary when Evaluation Requirement Bindings carry
  overlapping information.
- **LN-04 · P0:** Prove Evaluation Run completion requires all terminal task,
  case-evaluator, report-evaluator, and manifest evidence—not merely completed
  case evaluation.
- **LN-05 · P2:** Remove compatibility shims that permit tests or nonexistent
  ledger records to bypass production invariants.
- **LN-06 · P2:** Centralize Evaluation Case–Suite compatibility predicates so
  preflight accumulation and fail-fast validation cannot drift.
- **LN-07 · P2:** Eliminate redundant case validation between Suite execution,
  evaluator resolution, preflight, and durable execution.
- **LN-08 · P2:** Make durable Evaluation Run execution consume the Resolved
  Evaluation Plan produced by preflight instead of independently deriving
  evaluator assignments.
- **LN-09 · P2:** Construct Evaluation Runs from the Resolved Evaluation Plan
  rather than accepting and revalidating duplicated plan-derived fields.
- **LN-10 · P1:** Require a Resolved Evaluation Plan at the Suite execution
  boundary when execution semantics depend on preflight.
- **LN-11 · P1:** Ensure the report-evaluator adapter does not silently discard
  evaluator failures.
- **LN-12 · P1:** Remove or reject the `run()` release-gate parameter if Release
  Gates execute only during Evaluation Finalization.
- **LN-13 · P2:** Measure and, if confirmed, optimize slow terminal recovery in
  `assert_run_is_complete`.
- **LN-14 · P2:** Consolidate repetitive guards that prevent report evaluation
  before case completion or outside the durable runner.
- **LN-15 · P1:** Define and enforce robust Evaluation Artifact reads,
  including integrity and missing-location behavior.
- **LN-16 · P2:** Consolidate duplicated synchronous and asynchronous recording
  behavior in case- and report-evaluator adapters.
- **LN-17 · P1:** Use one canonical checkpoint document and hash implementation
  for checkpoint writes and integrity verification.
- **LN-18 · P2:** Move framework-report materialization out of the Evaluation
  Ledger persistence façade while preserving its atomic transaction boundary.
- **LN-19 · P1:** Atomically checkpoint evaluator-produced artifacts with their
  evaluator execution and observations.
- **LN-20 · P1:** Allow same-run recovery when aggregate-manifest freezing fails
  after the case phase has completed.
- **LN-21 · P2:** Persist Evaluation Run Issues raised during a case in the same
  atomic checkpoint as that case.
- **LN-22 · P2:** Keep the component-owned Evaluation Requirement Catalog out of
  unrelated Evaluation Suite revision content.
- **LN-23 · P0:** Validate structured metric values before JSON normalization so
  forbidden Python containers and non-string mapping keys cannot be silently
  coerced into accepted shapes.
- **LN-24 · P0:** Prevent direct `ResolvedSchemaBinding` construction from
  bypassing the explicit allowlisted Schema Registry.
- **LN-25 · P0:** Honor a controlled stop after the final—or only—report
  evaluator and before any Release Gate begins.
- **LN-26 · P2:** Consolidate duplicated replay-consistency algorithms for
  evaluator executions and observations.
- **LN-27 · P1:** Bound retryable finalization-renewal contention by the last
  confirmed live authority interval. This is already represented by excluded
  project work and must not be duplicated here.

## Archived source

The July 9 audit contains resolved items, completed work, detailed evidence, and
historical observations. It remains preserved verbatim at
[archive/imports/project-notes-2026-07-09.md](archive/imports/project-notes-2026-07-09.md).
