# Code Review: News Ontology and Graph Population, issues 02–07

Labels: ready-for-agent

Reviews: [02](../issues/02-ontology-package-and-conformance-check.md),
[03](../issues/03-generate-extraction-prompt-from-news-ontology.md),
[04](../issues/04-sub-labels-and-extraction-conformance.md),
[05](../issues/05-write-path-ontology-vocabulary-rename.md),
[06](../issues/06-node-identity-provenance-and-topic-edges.md),
[07](../issues/07-bill-session-resolution.md) of the
[News Ontology and Graph Population PRD](../PRD.md).

Blocks: [08 Rebuild the graph and record the label inventory](../issues/08-rebuild-graph-and-record-label-inventory.md).

## Problem Statement

Issues 02–07 are all marked complete, and issue 08 is ready to drop the Neo4j
database and re-ingest the gathered Source Articles against what they built. A
two-axis review of those six commits found eighteen findings. Three of them mean
the graph issue 08 produces would be wrong, and two acceptance criteria are
ticked for work that was not done:

1. **An Article Chunk still dies over one bad entity.** Conformance admits a
   model-emitted `NewsArticle` or `Chunk` node because it checks the full News
   Ontology label set, while the write path rejects the same node because it
   checks the extracted-label subset. The rejection raises, so the whole chunk
   reaches the dead letter queue — the precise outcome the PRD forbids: "one bad
   entity never costs an Article Chunk its other twelve."
2. **Legislative Events and Campaigns are systematically dropped.** The
   generated ontology section tells the model a sub-label is required for both,
   but the hand-written output contract in the Extraction Prompt shows an entity
   object with no `sub_labels` field. The model is shown a contract with nowhere
   to put the value it is required to supply.
3. **Relationship properties are silently overwritten.** Only two relationship
   types declare identifying properties, so every other type merges on endpoints
   alone, and the write path ends with an unconditional property assignment.
   Two articles asserting the same relationship with different detail produce one
   edge holding whichever was ingested last, with no record that they differed.
4. **Two acceptance criteria are ticked but false.** Issue 06 claims every node
   and relationship the extractor produces is stamped with provenance; nothing is
   stamped anywhere. Issue 02 claims `ontology.md` is unmodified; it was changed.

The remaining findings are conformance gaps, adapter-boundary types that breach
[ADR 0002](../../../../docs/adr/0002-story-pipeline-architecture.md), duplicated
write paths, undeclared domain vocabulary, and an unguarded hand-copied mirror
of `ontology.md` — the exact drift the ontology package exists to prevent, left
unprotected at its own root.

This review is not part of the build toward the PRD. It establishes that the
build matched the PRD's intent before the graph is rebuilt against it.

## Solution

Close all eighteen findings across four sequenced runs, before issue 08 executes.

The central change is a decision about what a relationship means. A News
Ontology relationship asserts that a claim exists and what identifies it —
nothing more. Its declared properties, and only those, form its **Claim Key**;
anything else an article said about the relationship stays in the Article Chunk
the edge points back to. This deletes the parallel identifying-property table,
removes the overwrite, and shrinks property normalization to the one job it was
introduced for: making two articles' claims comparable.

Two decisions follow from it. Node primary keys become a shared importable
contract rather than expressions inlined at their call sites, because a later
authoritative ingester must mint byte-identical keys or it will create duplicate
nodes beside the news-derived ones. And a `LegislativeEvent` keeps its
name-derived key: its date is recorded as a reconciliation property and never
guessed into an identity, because a wrong key conflates distinct events
irrecoverably while a weak key merely fragments one event into two.

Provenance is settled the other way from the PRD. No provenance property is
stamped. Traceability is structural and already complete: every extracted entity
carries `MENTIONED_IN` to its Article Chunk, and every extractor-produced
relationship carries the chunk list that makes edge merging possible. The PRD's
paragraph rejecting reachability is amended rather than implemented, and the
chunk list on relationships is reclassified from an unspecced addition to a
load-bearing one.

`ontology.md` is corrected where it is wrong, twice, and the standing that makes
that permissible is recorded as an ADR rather than left as a contradiction
between a PRD that says the file is frozen and a history that shows otherwise.

## User Stories

1. As a developer, I want conformance and the write path to agree on which
   labels an extractor may produce, so that a model-emitted `NewsArticle` is
   dropped and logged rather than dead-lettering its Article Chunk.
2. As a developer, I want the extracted-label subset to be the single gate on
   model output, so that the write path's rejection becomes an internal
   invariant that can never fire in production.
3. As a developer, I want conformance to be a pure function over an extraction
   result, so that I can test the whole ontology-to-conformance loop without
   constructing an adapter or a model.
4. As a developer, I want the Extraction Prompt's output contract to show the
   `sub_labels` field, so that a model required to supply a sub-label has
   somewhere to put it.
5. As a developer, I want Legislative Events and Campaigns to survive
   extraction, so that the label inventory issue 08 records measures the
   ontology rather than a prompt defect.
6. As a developer, I want unknown relationship property names dropped like
   unknown node property names, so that the PRD's drop-and-log rule holds on
   both sides of an edge.
7. As a developer, I want relationship properties owned by the write path, so
   that the only values on an edge are ones the system put there deliberately.
8. As a developer, I want a relationship's declared properties to be exactly its
   Claim Key, so that one table decides edge identity instead of two tables that
   can disagree.
9. As a developer, I want two articles asserting the same relationship at
   different values to produce two edges, so that a disagreement between sources
   is visible rather than resolved by ingestion order.
10. As a developer, I want two articles asserting the same relationship at the
    same values to produce one edge accumulating both chunks, so that a story
    repeating a relationship across many chunks does not produce an edge per
    mention.
11. As a developer, I want an edge to carry no free payload, so that no property
    can be silently overwritten by a later ingestion.
12. As a developer investigating California politics, I want an edge's nuance
    retrievable through the Article Chunks it points to, so that dropping
    payload from the edge costs me no information.
13. As a developer, I want `sequence_number` recorded on the Legislative Event
    rather than on each vote edge, so that a value identical for every voter at
    one event is stored once rather than duplicated across every edge into it.
14. As a developer, I want vote relationships to declare no properties at all,
    so that a news-derived vote edge and a later legislative-derived vote edge
    share an empty Claim Key and merge instead of duplicating.
15. As a developer, I want the News Ontology to declare that news-derived vote
    edges carry no roll-call position and no event discrimination, so that
    whoever writes the legislative ingester learns the gap by lookup.
16. As a developer, I want event type discrimination to stay on the Legislative
    Event sub-label rather than being collapsed into a single terminal-event
    assumption, so that the shape of the data decides the model rather than a
    guess made before ingestion.
17. As a developer, I want one relationship-writing routine shared by both
    ingestion entry points, so that a change to edge semantics cannot land in
    one path and miss the other.
18. As a developer, I want node primary key minting exported as an importable
    contract, so that a later legislative ingester mints byte-identical keys and
    enriches a news-derived node instead of creating a duplicate beside it.
19. As a developer, I want the Bill primary key derived by that same shared
    function, so that the expression is not re-derived at each call site.
20. As a developer, I want a Legislative Event's date recorded as a property
    with its source flagged, so that later reconciliation has the fact it needs.
21. As a developer, I want a Legislative Event's date kept out of its primary
    key, so that an inferred date cannot fragment one event into one node per
    article.
22. As a developer, I want a single identity shape for Legislative Events, so
    that a later correct-date ingest can find every node it must fix.
23. As a developer, I want the resolved bill sessions crossing the Graph
    Database Adapter to be a typed domain model, so that the adapter boundary
    obeys ADR 0002 instead of passing a nested dictionary of objects.
24. As a developer, I want the Adherence Report to be a typed model with a
    closed set of drop categories, so that a mistyped category name fails loudly
    instead of silently creating a new bucket.
25. As a developer, I want no provenance property stamped on news-derived
    structure, so that the graph carries no field duplicating what the chunk
    edges already establish.
26. As a developer, I want the chunk list on relationships recognized as
    load-bearing, so that nobody removes the only traceability an
    extractor-produced edge has.
27. As a developer, I want the PRD's provenance paragraph amended to the
    decision actually taken, so that the spec and the build do not contradict
    each other.
28. As a developer, I want issue 06's provenance acceptance criterion rewritten,
    so that a ticked box does not assert work that was never done.
29. As a developer, I want issue 02's "`ontology.md` is unmodified" criterion
    corrected, so that the record matches the history.
30. As a developer, I want a test asserting the primary ontology module matches
    `ontology.md`, so that the hand-copied mirror cannot drift from the document
    it mirrors.
31. As a developer, I want `ontology.md` corrections held to a high bar and
    recorded, so that editing the primary ontology stays a last resort rather
    than becoming a habit.
32. As a developer, I want the vocabulary this project introduced defined in the
    domain glossary, so that News Ontology, Shortcut Rule, Divergence, Bill
    Session Resolution, Adherence Report, Claim Key and Policy Area are lookups
    rather than investigations.
33. As a developer, I want the Divergence module reduced to what is actually
    called, so that three unused helpers and a multi-source framing no source
    needs stop implying capability that does not exist.
34. As a developer, I want the misleading claim in the relationship-query
    docstring corrected, so that a reader is not told input never reaches the
    query when the relationship type does.
35. As a developer, I want `news-ontology.md` regenerated after these changes,
    so that the generated divergence record describes the ontology that exists.
36. As a developer, I want the durable decisions recorded as ADRs, so that a
    future reader finds the reasoning rather than re-deriving it from a diff.

## Implementation Decisions

### Run 1 — Conformance and the Extraction Prompt

- Conformance gates node labels on the **extracted-label subset** — the News
  Ontology labels minus the write-path-owned `NewsArticle` and `Chunk` — so a
  model-emitted article or chunk node is dropped and recorded in the Adherence
  Report like any other off-ontology output. The Graph Database Adapter's
  label rejection stays as an internal invariant that conformance now guarantees
  cannot fire.
- Conformance moves out of the Entity Extraction Adapter into the ontology
  package as a **pure function**: it takes an extraction result and a chunk
  identifier and returns the conformed result together with the drops it made.
  The adapter calls it and tallies the drops into the Adherence Report. This
  satisfies the PRD's requirement that conformance happen at the untrusted-input
  boundary — the boundary calls it — while making it testable in isolation.
- The Extraction Prompt's hand-written output contract gains the `sub_labels`
  field. The contract stays prose; only the missing field is added.
- **Relationship properties become write-path-owned.** Model-supplied
  relationship properties that are not declared by the relationship's shape are
  dropped and recorded, symmetric with node properties.

### Run 2 — What a relationship means

- **The Claim Key is a relationship's declared property set.** The separate
  identifying-property table is deleted. The rule that replaces it: if two
  different values mean two different claims, the property is declared and
  therefore identifying; if they do not, the property does not belong on the
  edge.
- An edge carries exactly its Claim Key, the chunk list, `skips` where it is a
  shortcut, and `needs_review` where an article asserted the claim without a
  value the key depends on. The unconditional property assignment at the end of
  the relationship query is removed.
- Property normalization survives, scoped to Claim Key properties. It exists so
  two articles' claims can be compared, which is now its only job.
- **`sequence_number` moves from the three vote relationships onto
  `LegislativeEvent`,** in both `ontology.md` and the primary ontology module.
  It is identical for every voter at one event, so it describes the event's
  position in the bill's lifecycle, not one legislator's claim, and belongs
  beside the event's existing `type` and `date`. The vote relationships are then
  left with no declared properties and an empty Claim Key.
- The News Ontology declares neither `sequence_number` on events nor any vote
  relationship property; news supplies neither.
- A **Divergence** is declared for the vote relationships: a news-derived vote
  edge carries no roll-call position and no event discrimination. No claim is
  made that news reports only terminal votes — the corpus is too small to
  support it, and event discrimination remains on the sub-label.
- The two ingestion entry points fold onto one relationship-writing routine.
- The relationship-query docstring is corrected: key names come from the
  ontology, but the relationship type is interpolated from conformed model
  output.

### Run 3 — Identity and adapter boundaries

- Node primary key minting becomes an **ontology-level contract**: a module
  exporting the general derived key and the Bill key, imported by any ingester.
  Both existing Bill key call sites import it. This is not speculative
  generality — a key two ingesters must agree on byte-for-byte is the difference
  between a later legislative ingester enriching a news-derived Bill and
  creating a second one beside it.
- `LegislativeEvent` records a `date`: the event's stated date where the article
  supplies one, otherwise the article's published date, with the source flagged
  the same way Bill Session Resolution flags verified against inferred.
- **The date is never part of the key.** The `Bill` precedent does not transfer:
  bill numbers collide across sessions by design and the failure is conflation,
  which is unrecoverable, whereas a Legislative Event's failure is fragmentation,
  which a later join on date and bill can repair. A guessed date in the key
  would trade the recoverable failure for the unrecoverable one, and a
  date-in-key-only-when-verified rule would create the second identity shape the
  PRD explicitly refuses.
- Bill Session Resolution and the Adherence Report become **typed models** at
  the adapter boundary, per ADR 0002. The Adherence Report's drop categories
  become a closed enumeration, removing the string-indexed lookup repeated at
  every drop site.
- The Divergence module keeps the declarations that conformance and the
  generator read; the three uncalled helpers and the unused resolvable-label
  alias are deleted, and the module's framing narrows from every extraction
  source to news.

### Run 4 — Record, guards, and documentation

- A test parses `ontology.md` and asserts that the primary ontology module's
  labels, per-label property names, and relationship table match it. The
  document remains the authored source and the module remains its mirror; the
  test is what makes the mirror trustworthy.
- The domain glossary gains **News Ontology**, **Shortcut Rule**, **Divergence**,
  **Bill Session Resolution**, **Adherence Report**, **Claim Key**, and **Policy
  Area**.
- **ADR — a news-derived relationship asserts existence and identity, not
  payload.** Records the Claim Key rule, with the shared minting contract and the
  Legislative Event key decision as its consequences.
- **ADR — the primary ontology is authored, not frozen.** Correcting
  `ontology.md` is a last resort, not a first move: the default is to work
  around it, and correction requires a fundamental flaw — a property on the
  wrong entity, or a key that cannot identify — never a naming preference or
  convenience. Both corrections made here are cited as the worked examples: the
  article property alignment, and `sequence_number` sitting on a relationship
  when it describes an event.
- The PRD's provenance paragraph is amended to the decision taken: traceability
  is structural, through the entity-to-chunk edge for nodes and the chunk list
  for relationships, and the chunk list is therefore load-bearing rather than an
  unspecified addition.
- The PRD's justification for retaining `LegislativeEvent` is softened. Avoiding
  the conflation of a bill's multiple votes is only half the reason; the event is
  also the one place a reliable date lives.
- Issue 06's provenance acceptance criterion and issue 02's
  "`ontology.md` is unmodified" criterion are rewritten to what was decided,
  each pointing at the ADR or amendment that supersedes it.
- `news-ontology.md` is regenerated.

### Findings closed without code change

- The News Ontology's per-label property projection is kept. It is the lookup
  conformance reads, and inlining it would make every call site worse.

## Testing Decisions

A good test here asserts external behavior at a seam that already exists: the
extraction result that leaves the Entity Extraction Adapter, the graph shape
that reaches Neo4j, the data that reaches the Graph Database Adapter. It does
not assert the internal structure of the ontology modules, the intermediate form
of the prompt string, or the call sequence within a conformance pass.

**No new seams are introduced.** The PRD's three seams carry every change here.

### Seam 1 — the Entity Extraction Adapter driven by a scripted model

Prior art: `tests/test_extraction.py`.

Covers Run 1 entirely. A model-emitted `NewsArticle` node is dropped and
recorded rather than raising, and the conforming entities in the same response
survive. An undeclared relationship property is dropped. The Extraction Prompt
carries a `sub_labels` field in its output contract, and a Legislative Event
emitted with a sub-label survives conformance. The Adherence Report accumulates
the expected counts and example chunks under typed categories.

### Seam 2 — the Graph Database Adapter with a captured driver

Prior art: `tests/test_graph_db.py`.

Covers Runs 2 and 3. Two extractions asserting one relationship at equal Claim
Key values produce one edge accumulating both chunks; at differing values, two
edges. No property outside the Claim Key, the chunk list, `skips`, and
`needs_review` reaches an edge. A vote relationship carries no properties. A
`LegislativeEvent` carries its date and source flag, and its primary key does
not contain the date. Bill keys match the exported minting contract.

The three existing assertions that a provenance property is absent are kept
deliberately, and gain a comment naming the decision, so that a future
reintroduction is a conscious reversal rather than an accident.

### Seam 3 — the Story Pipeline with mock adapters

Prior art: `tests/test_pipeline.py`.

Covers the typed Bill Session Resolution reaching the Graph Database Adapter,
unchanged in behavior from what issue 07 built.

### The non-seam tests

The News Ontology conformance check is a test over two data structures rather
than a seam, and already runs in the suite. It gains a sibling: the parse of
`ontology.md` asserted against the primary ontology module. Both exist so that
editing either artifact fails loudly.

## Out of Scope

- **Rebuilding the graph.** Issue 08 drops the Neo4j database and re-ingests the
  gathered Source Articles. This review only ensures it will build the right
  graph; it runs afterwards.
- **Entity Resolution.** Name-derived keys still leave name variants as separate
  nodes, and a `LegislativeEvent` still fragments across articles that describe
  it differently. Both are recorded, neither is solved.
- **Legislative ingestion.** The shared minting contract and the vote Divergence
  exist so that ingestion can reconcile later. Building it is roadmap outcome 5.
- **Reconciling news-derived Legislative Events with authoritative ones.** The
  facts a later reconciliation needs — date, source flag, sub-label, the article
  links — are recorded here. The reconciliation itself is a later problem.
- **Extraction evaluation.** Whether the agent extracts what we want remains the
  evaluation suite's question.
- **Any change to the Extraction Prompt's hand-tuned prose** beyond adding the
  missing `sub_labels` field to its output contract.

## Further Notes

- The runs are sequenced because Run 2 changes what a relationship is and Runs 3
  and 4 record and guard that decision. Run 1 is independent and could land
  first on its own; it is ordered first because two of its findings are the ones
  that would corrupt issue 08's label inventory.
- Two of the eighteen findings were disagreements with the PRD rather than
  departures from it, and both are resolved by amending the PRD. This is the
  reason the review lives outside `issues/`: an issue implements the spec, while
  this establishes whether the spec was implemented and, twice, that the spec was
  wrong.
- The review found no defect in issues 03 and 05. Issue 03's generated prompt
  section is correct; the defect is in the hand-written contract beside it.
  Issue 05's vocabulary rename is clean.
- Nine Source Articles remain a thin basis for conclusions about label coverage.
  That caveat belongs to issue 08 and is unchanged by this review, except that
  fixing the sub-label contract removes one systematic reason a label would read
  as empty.
