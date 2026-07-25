# Inbox

This is the capture point for defects, questions, ideas, and risks that have not
yet been accepted as executable work. An inbox entry is not a commitment.

During triage, move an item into an existing project issue, create a new project
or initiative, mark it resolved with evidence, or deliberately discard it.

## Reconciliation state

The executable tracker was reconciled on 2026-07-24. Parent project labels now
reflect their unresolved child work, legacy checked tickets are labeled
`completed`, and the Model Evaluation dependency chain is visible in
[README.md](README.md).

The entries below came primarily from the July 9 audit. They remain
`needs-triage` candidates collectively: they have not been promoted into
executable issues merely because they were captured here. Before promotion,
verify the observation against the current code, remove overlap with completed
evaluation infrastructure, and attach it to one bounded project.

## Extraction and graph integrity

- **P0:** Preserve multiple labels for extracted graph nodes.
- **P0:** Require all Article Chunks to extract successfully before any complete
  Source Article result is persisted to the graph.
- **P1:** Define a tolerant Structural Identity Check boundary for harmless
  leading-text differences without weakening identity guarantees.
- **P1:** Bound retry context and retain a compact failure history.
- **P1:** Introduce a shared typed hierarchy for model-call failures.
- **P1:** Version and refine the Entity Extraction ontology and prompts.
- **P2:** Decide whether `extract_from_chunks` belongs on the Entity Extraction
  protocol.
- **Question:** Decide whether Neo4j vector-index readiness is a connection
  invariant or an explicit startup/migration concern.

## Model reliability and evaluation

- **P0:** Define a common retry policy for transport errors, timeouts, malformed
  output, and rate limits across model-backed workflows.
- **P0:** Establish trustworthy Evaluation Gold Sets backed by real labeled
  examples.
- **P1:** Complete component-specific evaluations for Relevance Filter,
  Selector Healing, Coreference Resolution, Entity Extraction, and fallbacks.
- **P1:** Record complete model, prompt, temperature, and execution metadata.
- **P1:** Keep deterministic contract tests distinct from model-quality
  evaluations.

Related work:
[Model Evaluation initiative](initiatives/model-evaluation/MAP.md).

## Scraping and validation

- **P0:** Verify current CalMatters extraction quality against retained fixtures
  or live evidence before treating content noise as a confirmed defect.
- **P1:** Define precedence when JSON-LD, Open Graph, Twitter, and other metadata
  disagree.
- **P1:** Give Article Validator results an explicit valid, invalid, or
  unvalidatable shape with supporting evidence.
- **P1:** Document the repeatable workflow for inspecting, proposing, approving,
  and applying Selector Versions.
- **P1:** Decide whether selector rejection applies to one field or the complete
  selector set.
- **P1:** Record Generator and Critic prompt versions in selector proposals.
- **P1:** Define the acceptable word-count ratio used during validation.
- **P2:** Reassess negative selectors, model factories, author normalization,
  and opaque discovery configuration only when a concrete use case requires it.

## Ingestion and operations

- **P0:** Encode continuation rules for article-scoped, transient dependency,
  and system-scoped failures.
- **P0:** Stop representing infrastructure failure as if the Source Article
  itself were defective.
- **P1:** Make adapter failure contracts consistent: typed results or typed
  exceptions, not both ambiguously.
- **P1:** Ensure intentionally skipped and permanent failures remain observable.
- **P1:** Use Neo4j adapter context managers consistently.
- **P1:** Decide whether Janitor should resume the pipeline after a successful
  health check.
- **P2:** Localize log ownership and avoid duplicate events.
- **P2:** Put console notification behind an adapter if non-terminal delivery is
  needed.

## Relevance classification

- **P0:** Establish and preserve a human-labeled relevance dataset with explicit
  provenance.
- **P1:** Validate the complete classifier path and its cache ownership.
- **P1:** Explain or remove the single-worker executor bridge.
- **P1:** Document and evaluate static fallback examples.
- **P1:** Separate cache existence, relevance, validation, and processing state.
- **P1:** Add classification rationales only if review or evaluation needs them.
- **P2:** Compare heuristics and logistic regression only after the Evaluation
  Gold Set and protocol are stable.

## Retrieval and product exploration

These ideas came from the original vision and project-breakdown sketch. They
belong here until the retrieval outcome becomes a shaped initiative.

- Set up a simple graph query interface and chat interface.
- Define Cypher creation and validation boundaries.
- Explore an orchestration agent for graph queries.
- Evaluate graph retrieval and answer restriction.
- Compare entity-, edge-, neighborhood-, and community-oriented retrieval.
- Explore cross-encoder, graph-aware, and embedding-fusion reranking.
- Review graph entities, relationships, ontology, and evaluation results
  together as an iterative refinement loop.
- Decide what a hosted evaluation dashboard should show.
- Consider ETL for additional news sources after the current pipeline is
  dependable.
- Consider hosted Neo4j and pipeline deployment after local operational
  semantics are stable.

## Archived source

The July 9 audit contains resolved items, completed work, detailed evidence, and
historical observations that should not clutter the live inbox. It is preserved
verbatim at
[archive/imports/project-notes-2026-07-09.md](archive/imports/project-notes-2026-07-09.md).
