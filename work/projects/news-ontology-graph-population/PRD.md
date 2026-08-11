# Product Requirements: News Ontology and Graph Population

Labels: ready-for-agent

Parent: [Update the extraction prompt to the settled ontology and populate the graph](../../initiatives/useful-graph-retrieval/issues/01-populate-graph-with-settled-ontology.md)

## Problem Statement

The graph currently in Neo4j was built against an ontology that predates
[`ontology.md`](../../../ontology.md). Every retrieval decision on the
[Useful Graph Retrieval map](../../initiatives/useful-graph-retrieval/MAP.md)
is blocked until a graph conforming to the settled ontology exists to design and
prototype against.

The write path and the Extraction Prompt disagree with the settled ontology in
ways that are individually small and collectively disqualifying:

1. **Sub-labels are silently discarded.** The Extraction Prompt instructs the
   model to emit `sub_labels`, but the extraction schema has no such field, so
   Pydantic drops them before they reach the Graph Database Adapter. The three
   labels the ontology defines by their sub-label — `LegislativeEvent`,
   `Campaign`, `Organization` — arrive as bare base labels.
2. **The Extraction Prompt refers the model to a file it cannot see.** Two of
   its instructions say to use the property names and endpoint types "defined by
   `ontology.md`". The model is never shown that file, so both instructions are
   inert and the ontology's per-label property assignments are conveyed as one
   undifferentiated list.
3. **Nothing enforces the closed sets.** The node label validator accepts any
   identifier-shaped string, so an off-ontology label reaches Neo4j and creates a
   node nobody can find by an ontology query.
4. **Write-path names disagree with the ontology.** The Graph Database Adapter
   writes `:Article`, and `(Chunk)-[:BELONGS_TO]->(Article)` where the ontology
   specifies `:NewsArticle` and `(NewsArticle)-[:HAS_CHUNK]->(Chunk)`.
5. **Entities have no identity of their own.** Everything is merged on `name`.
   The map requires project-minted primary keys so that news-derived nodes can
   later reconcile against external authorities rather than being rewritten.
6. **Bills have no session, and bill numbers recycle every session.** The
   gathered Source Articles already demonstrate the collision: a 2026 article
   links `201920200AB218` and another links `201720180SB54`. Merging those with
   current-session bills of the same number silently conflates distinct bills,
   which is disqualifying for the historical retrieval this map is designed for.
7. **Large parts of the ontology are structurally unreachable from news.**
   `LegislativeTenure`'s primary key needs a chamber and a start year;
   `District`'s needs a redistricting cycle year. News prose supplies neither,
   yet the ontology hangs every vote, committee assignment, and district edge off
   those nodes. There is currently no way to state what the news pipeline can and
   cannot produce, so the gap is rediscovered by every reader.

## Solution

Introduce a **News Ontology**: a machine-readable statement of what the news
extraction pipeline can produce, defined as a subset of the primary ontology plus
a small number of explicit **shortcut rules** where the news pipeline collapses a
path the primary ontology models in full. A check asserts that every News
Ontology label and relationship either exists in the primary ontology or is a
declared shortcut, so the two cannot drift apart silently.

`ontology.md` is not edited. It remains the destination shape that later
authoritative ingestion fills in, and the News Ontology is the record of how far
short of it news alone falls.

The News Ontology becomes the single source for the Extraction Prompt's ontology
section and for the conformance rules applied to model output. Off-ontology
labels, relationship types, endpoint pairings, and property names are dropped and
logged rather than raised, so one bad entity never costs an Article Chunk its
other twelve. The Graph Database Adapter is renamed to the ontology's vocabulary,
mints deterministic primary keys, and stamps provenance on everything the
extractor produces. Bill sessions are resolved from the hyperlinks already stored
alongside each Story rather than guessed from prose. The existing Neo4j database
is dropped and the gathered Source Articles re-ingested.

## User Stories

1. As a developer, I want a machine-readable News Ontology, so that what the news
   pipeline can produce is a lookup rather than an investigation.
2. As a developer, I want the News Ontology checked against the primary ontology
   automatically, so that the two cannot drift apart when either is edited.
3. As a developer, I want the primary ontology left untouched, so that the
   destination shape that later authoritative ingestion fills in survives this
   work unchanged.
4. As a developer, I want each place where the news pipeline collapses a path in
   the primary ontology declared as a named shortcut rule, so that the
   reconciliation work later ingestion must perform is written down in advance.
5. As a developer, I want the Extraction Prompt's ontology section generated from
   the News Ontology, so that editing the ontology cannot leave the prompt stale.
6. As a developer, I want the Extraction Prompt's hand-tuned instructions to stay
   editable as prose, so that prompt engineering does not require a code change.
7. As a developer, I want the model told which properties belong to which label,
   so that it stops being shown one flat list spanning every entity type.
8. As a developer, I want sub-labels to survive extraction and become real Neo4j
   labels, so that a query can match a labor union directly rather than scanning
   every organization's properties.
9. As a developer, I want a sub-label required for a Legislative Event and a
   Campaign but optional for an Organization, so that a model that cannot choose
   between "vote" and "hearing" is treated as having misread, while an advocacy
   coalition whose structural type the article never states is still recorded.
10. As a developer, I want off-ontology labels, relationship types, and property
    names dropped rather than raised, so that one bad entity does not send an
    otherwise good Article Chunk to the dead letter queue.
11. As a developer, I want a relationship dropped when its endpoint labels
    violate the News Ontology, so that the graph does not accumulate edges whose
    shape no query anticipates.
12. As a developer, I want a per-run adherence report naming every dropped label,
    relationship type, and property with counts and an example chunk, so that I
    can see whether a prompt edit helped.
13. As a developer, I want every node to carry a deterministic, readable primary
    key, so that re-ingestion is idempotent without a lookup table and I can
    still recognize nodes by eye while inspecting the graph.
14. As a developer, I want the Source Article and Article Chunk nodes owned by
    the write path rather than extracted, so that metadata the pipeline already
    holds exactly is never guessed by a model.
15. As a developer, I want the article-to-chunk and entity-to-chunk edges created
    automatically at ingestion, so that provenance to a Source Article is
    structural rather than dependent on the model remembering to emit it.
16. As a developer investigating California politics, I want every extracted
    entity linked back to the Article Chunk it was mentioned in, so that any
    retrieved fact can be traced to its source.
17. As a developer, I want a Policy Area drawn from a closed vocabulary, so that
    the topic hub actually aggregates instead of fragmenting into four
    single-edge variants of "climate".
18. As a developer, I want the Policy Area vocabulary derived from the
    legislature's subject-matter standing committees, so that it has an
    authoritative source rather than being invented.
19. As a developer, I want process committees excluded from the Policy Area
    vocabulary, so that a bill dying in Appropriations is not recorded as being
    about the policy area of appropriations.
20. As a developer, I want a Policy Area appearing in an Article Chunk's
    extraction to automatically produce a topic edge from that chunk, so that
    thematic retrieval works without the model referencing a node it cannot see.
21. As a developer, I want a Bill's legislative session resolved from the
    hyperlinks the article actually contains, so that bills from different
    sessions sharing a number stay distinct nodes.
22. As a developer, I want link-derived sessions matched on the parsed bill
    number rather than the link's anchor text, so that matching is exact on links
    whose anchor text reads "a bill" or "June budget".
23. As a developer, I want a Bill with no matching link to fall back to a session
    derived from the article's publication date, so that unlinked bill mentions —
    the majority — still get a findable identity.
24. As a developer, I want link-resolved and date-inferred sessions distinguished
    by a flag on the node, so that I can measure exactly how much of the bill
    layer is guessing.
25. As a developer, I want a bill number that resolves to two different sessions
    within one article left without a session and flagged, so that an ambiguity
    is visible rather than arbitrarily decided.
26. As a developer, I want session resolution performed once per Source Article
    rather than once per Article Chunk, so that the same links are not parsed
    repeatedly.
27. As a developer, I want the Graph Database Adapter to receive resolved
    sessions as plain data, so that it never acquires a dependency on the SQLite
    document store.
28. As a developer, I want every node and relationship the extractor produces
    stamped with its provenance, so that later authoritative ingestion can find
    news-derived structure by query.
29. As a developer, I want shortcut edges to record which node they skip, so that
    later ingestion knows exactly which intermediate node to insert and which
    edge to re-anchor.
30. As a developer, I want the existing Neo4j database dropped rather than
    migrated, so that no node built against the superseded ontology survives into
    the new graph.
31. As a developer, I want the gathered Source Articles re-chunked, re-embedded,
    and re-ingested, so that the graph is rebuilt end-to-end under the new rules.
32. As a developer, I want the existing pipeline and graph adapter tests updated
    to the new vocabulary, so that the suite continues to describe the system
    that exists.
33. As a developer, I want the record of which ontology labels and relationship
    types materialized, and at what counts, captured on the parent ticket, so
    that the tickets deciding which subgraph is retrievable now have facts to
    work from.

## Implementation Decisions

### Ontology representation

- A new `ontology` package under the knowledge map holds a **primary ontology**
  module mirroring `ontology.md`, a **News Ontology** module, and the conformance
  check relating them. `ontology.md` itself is not modified.
- The primary ontology module carries the label set, the sub-label map, per-label
  property *names* (names only — no types; encoding a full property schema is
  explicitly not attempted), and a relationship table mapping each relationship
  type to its permitted source and target labels.
- The News Ontology declares its label set, its relationship set, its per-label
  property names, the Policy Area vocabulary, and its **shortcut rules**.
- A shortcut rule names the primary-ontology path it collapses and the direct
  relationship it produces. The one family of shortcuts this project introduces
  collapses the tenure hop:

  ```
  Politician -HELD_TENURE-> LegislativeTenure -VOTED_NO-> LegislativeEvent
    ⇒ Politician -VOTED_NO-> LegislativeEvent   (skips: LegislativeTenure)
  ```

  applied to `VOTED_AYE`, `VOTED_NO`, `ABSTAINED`, `SERVES_ON`, `CHAIRS`, and
  `VICE_CHAIRS`.
- The conformance check asserts that every News Ontology label exists in the
  primary ontology, and that every News Ontology relationship either appears in
  the primary relationship table with matching endpoint labels or is produced by
  a declared shortcut rule whose collapsed path exists in the primary ontology.
- A human-readable `news-ontology.md` is **generated** from the News Ontology
  module. It is never hand-edited; generation is what keeps a fourth artifact
  from becoming a fourth drift risk.
- Vocabulary note: the term for a collapsed path is **shortcut**, and the
  property recording it is `skips`. "Elided" is not used.

### News Ontology contents

- **Excluded labels**: `LegislativeTenure`, `District`, `RedistrictingCycle`.
  Their primary keys require facts (chamber plus start year; redistricting cycle
  year) that news prose does not supply, and a partially-keyed node is a node
  later ingestion must find and delete.
- **Excluded relationships**: `HELD_TENURE`, `REPRESENTS_DISTRICT`,
  `TRANSITIONED_BY`, `EVOLVED_INTO`.
- **Shortcut relationships**: the six tenure-anchored relationships listed above
  are re-sourced from `Politician`.
- **Retained**: `LegislativeEvent` with its `ACTION_ON` edge to `Bill`. It is the
  one place a reliable date lives — the article's own date is poor evidence for
  when something was said, but a stated event date ("voted Thursday on SB 32") is
  direct evidence. Flattening votes onto `Bill` would discard that and would
  conflate a bill's multiple votes.
- **Property change**: `current_party` remains on `Politician`. The tenure-scoped
  `party_affiliation` has no home in the News Ontology and is removed from the
  Extraction Prompt, along with the instruction distinguishing the two.
- **Policy Area vocabulary**: a closed list derived from the Assembly and Senate
  subject-matter standing committees, deduplicated across chambers and renamed to
  their topic (an "Assembly Transportation Committee" contributes a
  `transportation` policy area, not a committee-named one). Process committees —
  Appropriations, Rules, Budget, Elections and similar — are excluded. The list is
  authored as part of this work and reviewed before commit. `PolicyArea` remains
  a distinct label from `Committee`; the committee rosters are the *source* of the
  vocabulary, not the nodes themselves.
- **Not in scope for extraction**: `ExternalIdentifier` and `HAS_IDENTIFIER`.
  External identifiers are to be derived deterministically from structured
  sources, never extracted from prose.

### Extraction schema and conformance

- The extraction node schema gains a `sub_labels` field. Sub-label values are
  validated against the News Ontology's whitelist before any Cypher is
  constructed.
- A sub-label is **required** for `LegislativeEvent` and `Campaign` — an article
  that describes an event nearly always identifies it as a vote, hearing, or
  amendment, and a campaign is for a candidate or a measure with no third option,
  so a model that cannot choose has misread. A sub-label is **optional** for
  `Organization`, whose eleven structural types are frequently not stated at all;
  requiring one would silently delete real organizations for failing a question
  the article never answered.
- **Conformance lives in the Entity Extraction Adapter**, the boundary where
  untrusted model output enters the system. The `EntityExtractionAdapter`
  protocol keeps its shape — it takes chunk text and returns an extraction
  result — but the result it returns is conformed.
- Conformance **drops and logs**; it never raises. Raising would send an entire
  Article Chunk to the dead letter queue over one mislabeled entity, which is
  unaffordable against a nine-article corpus, and would leave the parent ticket's
  question about prompt/ontology disagreement unanswerable. Dropped items are:
  unknown labels, unknown or missing-where-required sub-labels, unknown
  relationship types, relationships whose endpoint labels violate the News
  Ontology relationship table, relationships left dangling by a dropped node, and
  unknown property names.
- The adapter accumulates an **adherence report** across a run — counts keyed by
  rejected label, relationship type, and property name, each with one example
  chunk identifier. The batch ingestion service writes it as JSON to `.scratch/`
  at the end of a run. It is per-run and regenerated on every run; a cumulative
  record buys nothing at this corpus size.
- Long term, whether the extraction agent produces the extractions we want is a
  question for the evaluation suite, which currently has no extraction coverage.
  Building that coverage is not part of this project.

### Extraction Prompt

- `extraction_prompt.txt` remains a file and retains its hand-tuned prose — the
  role framing, the output contract, and rules such as not inferring endorsement
  from quotation or resolving pronouns only when the antecedent is unambiguous.
  These have no machine source and want to be edited as text.
- The file carries a placeholder into which the generated ontology section is
  injected at load time: the label set, the sub-label rules, per-label property
  names, the relationship list with endpoint types, and the Policy Area
  vocabulary. Nothing about the ontology is stated twice.
- Removed from the prompt: `NewsArticle`, `Chunk`, `HAS_CHUNK`, and the
  entity-to-chunk edge — all now write-path-owned; the excluded tenure, district,
  and redistricting labels and relationships; and the two instructions referring
  the model to `ontology.md`.

### Write path and the Graph Database Adapter

- `:Article` becomes `:NewsArticle`. `(Chunk)-[:BELONGS_TO]->(Article)` becomes
  `(NewsArticle)-[:HAS_CHUNK]->(Chunk)`. The entity-to-chunk edge is
  `MENTIONED_IN`, directed from the core entity to the chunk, matching the
  current `ontology.md`.
- The write path owns `NewsArticle` and `Chunk` nodes entirely. Both keep their
  existing natural keys — the article URL, and the article URL plus chunk index.
- All other nodes are merged on a **deterministic derived primary key** of the
  form `label:slug(name)`, with `name` retained as a property. Readability is a
  deliberate choice: the graph will be inspected by hand to produce the parent
  ticket's answer. Known limitation, recorded rather than solved: name-derived
  keys leave "Newsom" and "Gavin Newsom" as separate nodes. That is Entity
  Resolution, which the map places out of scope.
- Sub-labels are written as additional Neo4j labels on the node, after whitelist
  validation, so that label-indexed matching works.
- `MENTIONED_IN` is created automatically for every extracted entity, and
  `DISCUSSES_TOPIC` automatically from the Article Chunk to every `PolicyArea`
  node in that chunk's extraction. The topic edge carries no properties and no
  nuance — the topic's presence in the chunk is the entire edge — so a dedicated
  output field would buy nothing over the node already being present.
  Article-level `DISCUSSES_TOPIC` is not materialized.
- **Provenance is structural, not a stamped property** *(amended — this paragraph
  originally required a provenance property on every node and relationship, and
  rejected reachability from a chunk; the decision was taken the other way)*. No
  provenance property is written on news-derived structure. Traceability is
  carried by the graph's own shape and is already complete: every extracted
  entity carries `MENTIONED_IN` to the Article Chunk it was found in, and every
  extractor-produced relationship carries the list of chunks that asserted it.
  That chunk list is **load-bearing**, not an unspecified addition — it is the
  only traceability an extractor-produced edge has, so removing it strips the
  edge of its provenance outright. Shortcut relationships additionally carry
  `skips` naming the primary-ontology node they bypass. What an edge may carry
  beyond this is settled by
  [ADR 0013 — A news-derived relationship asserts existence and identity, not
  payload](../../../docs/adr/0013-a-news-derived-relationship-asserts-existence-and-identity-not-payload.md).

### Bill session resolution

- The `Story` domain model already carries the hyperlinks found in an article's
  body. `SourceArticle` gains the same links so the pipeline can reach them; the
  batch ingestion service populates them when building the Source Article.
- A pure URL parser recognizes the two known bill URL schemes and yields a
  session, chamber, and number. Both encode the same triple:
  `.../bills/ca_202520260ab1776` and `...bill_id=201920200AB218`.
- Matching is on the **parsed bill number**, not the link's anchor text. Anchor
  text in the gathered articles is largely unusable — "June budget", "with a
  bill", "sanctuary law." — while the number is exact and present in every case.
- Resolution tiers:
  1. A link whose parsed number matches an extracted `Bill`'s number supplies the
     session authoritatively; the node is flagged session-verified.
  2. No matching link: the session is derived from the article's publication date
     under California's two-year, odd-year-start session convention; the node is
     flagged session-inferred. This tier exists because dropping unlinked bills
     would discard the majority of bill mentions, and leaving them session-less
     would create a second identity shape that a later correct-session ingest
     could not find in order to fix.
  3. Two links in one article resolving the same number to different sessions:
     no session is assigned and the node is flagged for review.
- The session participates in the `Bill` primary key.
- Known error mode, accepted and recorded: an article discussing a prior-session
  bill without linking it will be mis-sessioned by tier 2. This is rarer than the
  collisions tier 1 and 2 together prevent, and is detectable later by joining
  against authoritative bill data.
- Resolution runs **once per Source Article** in the Story Pipeline. The
  `DatabaseAdapter.ingest_chunk_extraction` signature gains the resolved session
  map as plain data, keeping the Graph Database Adapter free of any SQLite
  dependency and testable without either database.

### Migration

- No migration. The existing Neo4j database was populated under a superseded
  ontology and is dropped. The gathered Source Articles are re-chunked,
  re-embedded, and re-ingested from the SQLite document store, which retains
  their content.

## Testing Decisions

A good test here asserts external behavior at a boundary that already exists: the
graph shape that reaches Neo4j, the extraction result that leaves the adapter, the
data that reaches the database adapter. It does not assert the internal structure
of the ontology modules, the intermediate form of the prompt string, or the call
sequence within a conformance pass.

**No new seams are introduced.** All three testing seams already exist in the
codebase.

### Seam 1 — the Story Pipeline with mock adapters

Prior art: `tests/test_pipeline.py`, which already exercises the pipeline through
mock implementations of every adapter protocol.

Covers bill session resolution end to end. A Source Article carrying links
produces a resolved session map that reaches the mock database adapter. URL
parsing for both schemes, all three resolution tiers, the session-verified and
session-inferred flags, and once-per-article rather than once-per-chunk execution
are all observable at this seam without a dedicated unit for the parser.

### Seam 2 — the Entity Extraction Adapter driven by a scripted model

Prior art: `tests/test_extraction.py`, and the existing use of pydantic-ai's
function-backed model in `tests/test_pipeline.py`.

Covers the whole ontology-to-prompt-to-conformance loop with no live model: the
prompt carries the injected label set and Policy Area vocabulary; an off-ontology
label, relationship type, endpoint pairing, or property name is dropped; the
conforming entities in the same response survive; a required sub-label missing on
a Legislative Event drops the node while an absent Organization sub-label does
not; the adherence report accumulates the expected counts and example chunks.

### Seam 3 — the Graph Database Adapter with a captured driver

Prior art: `tests/test_graph_db.py`, which drives the adapter with a mock driver
and inspects the Cypher and parameters issued.

Covers the emitted graph shape: `:NewsArticle`, the `HAS_CHUNK` direction, the
`MENTIONED_IN` direction, sub-labels written as real labels, derived primary keys
including the session component on bills, the provenance and `skips` properties,
and automatic `DISCUSSES_TOPIC` creation.

### The one non-seam test

The News Ontology conformance check — that every News Ontology label and
relationship exists in the primary ontology or is a declared shortcut — is a test
over two data structures, not a seam. It runs in the suite so that editing either
ontology fails loudly.

### Existing tests to update

`tests/test_graph_db.py` and `tests/test_pipeline.py` assert the superseded
`:Article` and `BELONGS_TO` vocabulary and are updated in place. No new Neo4j
integration tests are added beyond these renames.

## Out of Scope

- **The full outcome-2 write-path migration.** Only what is needed to produce a
  retrievable graph rides on this work.
- **Entity Resolution.** Name-derived primary keys leave name variants as
  separate nodes. This project settles only that news-derived nodes carry
  provenance so reconciliation stays possible.
- **`ExternalIdentifier` and `HAS_IDENTIFIER`.** No identifier nodes are
  materialized. Note for the ticket that settles identifier representation: the
  gathered Source Articles already contain deterministic legislator identifiers
  in their links, in the same table the bill parser reads. They are not used
  here because matching a legislator URL to an extracted `Politician` has no
  structural key — the anchor text is the only link, which is exactly the weak
  matching the bill parser avoids by using the number. Doing it correctly
  requires name normalization, which is Entity Resolution.
- **Extraction evaluation.** Whether the agent extracts what we want is the
  evaluation suite's question; it currently has no extraction coverage, and
  building that coverage belongs to the
  [Model Evaluation map](../../initiatives/model-evaluation/MAP.md).
- **A reporting CLI command.** The parent ticket's label and relationship counts
  are produced by hand-run Cypher and recorded once. They are a one-time
  inventory, not a recurring metric.
- **Editing `ontology.md`.** The primary ontology is a fixed input.
- **CAL-ACCESS and Open States ingestion**, which would fill the tenure, district,
  and campaign-finance layers. Roadmap outcome 5.

## Further Notes

- **Nine Source Articles is a thin basis for conclusions about label coverage.**
  The parent ticket asks which ontology labels materialized and which stayed
  empty. At this corpus size an empty label may mean the ontology is
  news-unreachable, or merely that nine articles did not happen to mention one.
  The record should distinguish structurally-empty labels — those the News
  Ontology excludes outright — from labels that are in the News Ontology but
  produced nothing.
- The shortcut rules are, in effect, the reconciliation specification for later
  authoritative ingestion written in advance: each one names the intermediate
  node that ingestion must insert and the edge it must re-anchor.
- The parent ticket's question about where the Extraction Prompt and the ontology
  disagreed is answered by the generated `news-ontology.md` rather than by a
  separate report. That document *is* the divergence record, and generating it
  from the same source the prompt reads is what stops it rotting on the first
  prompt edit.
- Article content in the document store is plain prose with no inline links,
  which is why session resolution reads the stored link table rather than asking
  the model to report URLs it never sees. Preserving markdown links through
  content extraction would open a different design; it is not attempted here.
