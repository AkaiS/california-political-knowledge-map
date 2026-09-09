# Graph inventory, 2026-09-08

Read-only observation of the configured local Neo4j database, with SQLite opened
in read-only mode. No ingestion, graph writes, schema changes, or model calls
were performed. This is a current inventory, not certification that the planned
rebuild ran or that extraction is correct.

The graph contains **98 CalMatters Source Articles, 2,407 Article Chunks,
3,668 nodes, and 6,061 relationships**. Every News Ontology base label is
present. The database contains reported funding, votes, and committee activity,
but their presence does not establish complete public-record coverage.

## Observation and corpus

- Initial reads: 2026-09-08T19:15:18.775848+00:00 to 2026-09-08T19:15:19.938335+00:00.
- Traversal checks: 2026-09-08T19:16:37.109824+00:00 to 2026-09-08T19:16:37.727488+00:00.
- Server: Neo4j Community 2026.07.1, database `neo4j`.
- Ontology comparison: checkout `9c13484a17405c13509d6caf42f564c88b3be928`, with
  this session's documentation edits present.
- All 98 graph article URLs belong to `calmatters.org` and match SQLite Stories
  marked `COMPLETED`. No graph article lacks a matching Story.
- SQLite holds **103 Stories**: 98 `COMPLETED` and 5 `UNPROCESSED`. All five
  unprocessed Stories are absent from the graph. This is observed ingestion
  progress through stored Stories, not a Publication coverage percentage.
- Graph publication dates range from **2023-06-15 through 2026-09-05**, with no
  missing article dates. These are publication dates, not event-time coverage.
- Queries were sequential read operations, not a coordinated cross-database
  snapshot. Node and relationship totals were unchanged on the final check.
- [Raw results and exact Cypher](04-graph-inventory-2026-09-08.json) preserve the
  inventory and traversal checks. Counts below describe stored nodes and edges;
  duplicate identities can inflate them.

## Labels

Base-label counts sum to the distinct node total. Sub-label counts overlap their
base labels and must not be added to that total. Every node has exactly one
News Ontology base label, and no undeclared labels were observed.

| Base label | Nodes |
| --- | ---: |
| `Bill` | 84 |
| `Campaign` | 41 |
| `Chunk` | 2,407 |
| `Committee` | 22 |
| `LegislativeEvent` | 37 |
| `NewsArticle` | 98 |
| `Organization` | 679 |
| `PolicyArea` | 26 |
| `Politician` | 241 |
| `Prop` | 33 |

| Sub-label | Parent label | Nodes |
| --- | --- | ---: |
| `BallotMeasureCampaign` | `Campaign` | 8 |
| `CandidateCampaign` | `Campaign` | 33 |
| `Amendment` | `LegislativeEvent` | 2 |
| `Hearing` | `LegislativeEvent` | 18 |
| `Vote` | `LegislativeEvent` | 17 |
| `AdvocacyGroup` | `Organization` | 42 |
| `Corporation` | `Organization` | 90 |
| `EducationalInstitution` | `Organization` | 81 |
| `GovernmentAgency` | `Organization` | 202 |
| `GrassrootsMovement` | `Organization` | 9 |
| `IE_Committee` | `Organization` | 0 |
| `LaborUnion` | `Organization` | 36 |
| `MediaOrganization` | `Organization` | 16 |
| `NonProfit` | `Organization` | 134 |
| `PAC` | `Organization` | 9 |
| `TradeAssociation` | `Organization` | 31 |
| `TribalNation` | `Organization` | 3 |

**Included but empty:** no base labels; the `Organization` sub-label
`IE_Committee` has zero nodes. This says what this corpus produced, not whether
news can produce that sub-label.

**Excluded from the News Ontology and absent:** `District`, `ExternalIdentifier`,
`LegislativeTenure`, and `RedistrictingCycle`.

## Relationships

All observed endpoint label combinations conform to the current News Ontology.
No legacy `Article` label or `BELONGS_TO` relationship was observed.

| Relationship type | Edges |
| --- | ---: |
| `ABOUT_TOPIC` | 24 |
| `ABSTAINED` | 1 |
| `ACTION_ON` | 26 |
| `CAMPAIGN_FOR` | 22 |
| `CHAIRS` | 11 |
| `DECLARED_STANCE` | 174 |
| `DENOUNCED` | 3 |
| `DISCUSSES_TOPIC` | 278 |
| `ENDORSED` | 24 |
| `FUNDED` | 12 |
| `HAS_CHUNK` | 2,407 |
| `HELD_BY` | 2 |
| `LOBBIED_AGAINST` | 28 |
| `LOBBIED_FOR` | 11 |
| `MENTIONED_IN` | 3,026 |
| `REFERRED_TO` | 2 |
| `SERVES_ON` | 3 |
| `VICE_CHAIRS` | 0 |
| `VOTED_AYE` | 3 |
| `VOTED_NO` | 4 |

**Included but empty:** `VICE_CHAIRS`.

**Excluded from the News Ontology and absent:** `EVOLVED_INTO`, `HAS_IDENTIFIER`,
`HELD_TENURE`, `REPRESENTS_DISTRICT`, and `TRANSITIONED_BY`.

## Grounding and indexes

- Every article has Article Chunks, ranging from 6 to 63 per article. Every
  chunk has text, a 768-dimensional embedding, and a `HAS_CHUNK` connection
  from a Source Article.
- All 1,137 extracted-entity nodes have a `MENTIONED_IN` connection to a Chunk.
- Every extractor-produced semantic relationship has asserting chunk references.
  None of those references is dangling.
- All 24 `ABOUT_TOPIC` edges have Source Article references, with none dangling.
- The 278 `DISCUSSES_TOPIC` edges originate at `NewsArticle`. They have no
  separate `chunks` or `articles` list; the Source Article endpoint provides
  their grounding. This is not a missing-provenance finding.
- `chunk_vector_index` is `ONLINE`, with 768 dimensions, cosine similarity,
  and reported index population of 100%. That percentage describes the index,
  not corpus completeness. Only the two token lookup indexes accompany it.
  No full-text or property lookup index and no constraints were observed.
- Vector query relevance and end-to-end answering were not evaluated.

## Limits found in the stored graph

1. **All 174 `DECLARED_STANCE` edges lack `alignment`.** Every one has only
   `chunks` and `needs_review`, with the latter true. They reach reporting about
   a stance but cannot distinguish support from opposition in graph structure.
   Source passages may still state the direction.
2. **All 12 `FUNDED` edges lack both amount and date.** Every one has only
   `chunks` and `needs_review`, with the latter true. They reach reported
   funding but cannot supply monetary totals, funding dates, or donor rankings
   from their properties.
3. **22 of 84 Bills lack a resolved session and are flagged for review.**
   Retrieval must preserve that ambiguity rather than assume cross-article
   identity.
4. **34 Organization IDs occur on multiple nodes, affecting 70 nodes.**
   These are exact shared IDs within the same base label, not merely similar
   names. Two duplicate-ID groups also share the `NonProfit` sub-label; those
   are included in the Organization counts, not additional duplicates. No other
   labels have duplicate non-null IDs. The inventory does not establish the
   cause, and stored-node counts are not counts of distinct real organizations.

These observations do not remove the associated source text from retrieval.
They constrain claims and aggregates based on graph identity and properties.
No repair or reingestion was attempted.

## Target traversal availability

These are generic path counts across the graph, not evaluations of the named
natural-language questions. A path's existence does not establish that its
passages answer a particular question. Path counts can share nodes and chunks;
M2 counts ordered pairs and all counts retain any duplicate graph identities.

| Target | Observed structure | Consequence for retrieval |
| --- | --- | --- |
| E1 entity dossier | 241 Politicians, 772 mention paths, 607 distinct chunks | Entity-to-source discovery is available. |
| E2 measure lookup | 117 Bill/Prop nodes, 553 mention paths, 493 distinct chunks | Measure-to-source discovery is available; unresolved sessions remain explicit. |
| E3 Policy Area sweep | 26 areas connect 94 articles to 2,335 distinct chunks through 7,319 paths | Article-level topic discovery is available; four graph articles have no topic edge. |
| R1 stated positions and endorsements | 201 stance/endorsement/denunciation edges, 135 actor nodes, 83 target nodes | Reporting is reachable; `DECLARED_STANCE` cannot supply alignment. |
| R2 lobbying | 39 edges, 36 Organization nodes, 20 Bills | Reported lobbying is traversable, subject to identity and source checks. |
| R3 funding | 12 edges, 11 Organization nodes, 9 Campaigns | Reported funding is reachable; amounts and dates must come from source evidence. |
| M1 policy footprint | 32 paths, 11 Organization nodes, 5 Bills, 8 areas | Reported actor-to-policy connections exist; duplicate identities limit bare aggregates. |
| M2 who took the same side | 245 shared-Bill ordered stance paths; zero paths with matching non-null alignment | The topology finds candidate reporting; graph structure cannot answer same-side questions. |
| M3 reported alongside | 436 Politician–Chunk–Organization paths over 223 chunks | Co-reporting discovery is available and does not assert an alliance. |
| M4 influence chain | Zero complete Organization–FUNDED–Campaign–CAMPAIGN_FOR–Politician–DECLARED_STANCE–Bill paths | The required chain is empty even though its relationship types exist separately. |
| M5 roll calls | Seven Politician–vote–LegislativeEvent–ACTION_ON–Bill paths | Some reported votes are reachable; complete roll calls and non-votes remain unsupported. |
| Committee activity | Two Bill referrals; zero Bill–event–committee paths joining ACTION_ON and HELD_BY | Referral discovery is available. Event-to-committee edges exist separately, but the full hearing path is empty. |

The five primary-only relationship types listed above and the four
excluded labels remain unavailable through news ingestion. Embedding retrieval
can still locate reporting relevant to questions whose typed path is absent.

## Adherence record and rebuild status

The shared checkout's `.scratch/extraction-adherence-report.json`, modified
2026-09-08T17:31:57.005946+00:00, contains four empty maps:
`rejected_labels`, `rejected_property_names`,
`rejected_relationship_property_names`, and `rejected_relationship_types`.
It has no run identifier or processed-article total. It therefore cannot certify
adherence for all 98 graph articles or prove that the specified rebuild ran.

This inventory satisfies the request for current graph counts and identifies
usable and missing structures. It does not complete the parent rebuild task:
five stored Stories remain unprocessed, the rebuild history is unverified, and
the stored claim and identity limitations above require explicit handling.
