# Decide which subgraph is retrievable now and which is deferred

Labels: wayfinder:grilling, completed
Parent: [Useful Graph Retrieval](../MAP.md)
Inputs: [Target question set](02-target-question-set.md), [Current graph inventory](../research/04-graph-inventory-2026-09-08.md)

## Question

Given what extraction actually populated and which questions matter, which slice
of the ontology is retrievable today, and which is deferred until the
legislative and campaign-finance layers land?

The ontology is the design target in full. The News Ontology already admits
`Bill`, `LegislativeEvent`, `Committee`, `Prop`, `Campaign`, `FUNDED`, and
`LOBBIED_FOR`. Their presence permits reported claims; it does not establish
complete legislative or campaign-finance coverage. This ticket names the first
buildable slice, the questions it can honestly serve, and how retrieval handles
requests whose required coverage exceeds the available evidence.

That behaviour is contract surface, so this decision feeds the contract as well
as the build order.

## Blocking

- Blocks: Decide the retrieval modes and the index inventory they require.

## Answer

Accepted during grilling on 2026-09-08. The subsequent read-only inventory
establishes the current graph contents; the observations below qualify the
intended scope without changing the accepted answer policy.

### Partial evidence is returned with the unmet requirement stated

When a legitimate question needs coverage we lack, return the supported portion
automatically and state what remains unavailable. If a question asks how every
senator voted and reporting names three senators, present the reporting on those
three and say that the complete roll call is unavailable. Do not present the
three as the full result or treat missing reporting as a non-vote.

The answering agent must receive context that communicates the relevant coverage
limits alongside the evidence; a lack of retrieved results does not itself
establish why information is missing. A succinct Coverage Description is supplied to the
orchestration agent, analogous to directory instructions that establish the
context for its work. Relevant coverage limits must also reach the answering
agent. Its concrete representation feeds ticket 08.

Use the existing **Deferred** coverage state from
[ticket 02](02-target-question-set.md). Do not introduce a second name for the
same gap. Finding no matching evidence is a separate retrieval outcome, not
proof that a question is Deferred or that the reported event did not happen.
A Deferred question can still return useful sources, as established by the
partial-evidence policy. Ticket 08 chooses how to represent coverage and search
outcomes together without conflating them.

### Incomplete graph elements remain useful for discovery

`needs_review` does not exclude a node or relationship from retrieval. Eligibility
depends on the claim being made. A funding claim without an amount can lead to
reporting that funding occurred, but cannot by itself support a spending total.
A Bill with an unresolved session can lead to relevant reporting with the
ambiguity stated, but cannot justify combining claims as though its identity
were settled.

The connected Article Chunks may contain information absent from graph
properties. Inspect that Grounding Evidence before deciding that the requested
information is unavailable; an incomplete graph record is not proof of an
incomplete source. Reading the evidence does not silently resolve graph identity.

### Coverage is described per collection

A Coverage Description has one entry per Publication or distinct public-record
collection. Bill text and roll calls from the same provider have separate
entries because they support different questions.

What each collection provides is authored when the source is configured.
Ingestion updates measured availability; it does not infer a new capability
description from the records it encounters. Finding a reported vote in a news
article does not turn the Publication into a complete roll-call collection.

Coverage percentages require a known, bounded set of expected records.
Otherwise report observed counts and leave completeness unknown. A fraction
such as 90 of 100 discovered articles ingested describes progress through that
discovered set, not 90% of a Publication's output. Discovery must account for
what it finds so that those observed counts have a basis; this is a requirement
for the implementation handoff, not a new counting subsystem specified here.

For a Publication, dates describe the publication dates of its Stories. News
does not claim temporal coverage of the events those Stories discuss. Event-time
coverage belongs to sources that explicitly claim it, such as a legislative
portal. Broader temporal reasoning remains deferred; this ticket does not
specify event-time completeness or historical as-of semantics.

The description reflects verified material currently available, including
material added by a partially successful refresh. It does not include refresh
status, retry information, or an incomplete-refresh warning in the orchestrator
context. Those are operational concerns. The orchestrator needs overall corpus
coverage and, when relevant, coverage for the question's time period. Where no
denominator is known, completeness remains unknown rather than being converted
into a refresh-status signal.

The primary description contains collection totals. The initial retrieval
contract also provides access to a separate monthly breakdown, loaded when the
question needs it rather than included in every orchestrator prompt. Each
month's percentage uses that month's expected total, where known, rather than
the Publication's overall total. Without a known denominator, it reports that
month's verified available count and leaves completeness unknown. News uses
publication dates; this does not reopen event-time reasoning.

### Existing discovery measurements

The archive already persists a candidate URL list and its current position in
Discovery State, and logs discovery counters. Its position advances over failed
fetches too, so reaching the end means it visited the saved candidate list, not
that all articles were fetched or ingested. See
[discovery.py](../../../../src/knowledge_map/core/discovery.py:589) and
[the counter logging](../../../../src/knowledge_map/core/discovery.py:691).

Per-URL cache records link to a Publication and carry fetch, relevance, and
validation status. They provide a basis for observed counts alongside Story
records. Neither those records nor the archive cursor establish an exhaustive
Publication total. Implementation should reuse this information before adding
new counting machinery.

### The Retrieval Answer directs the reader to sources

The answering agent acts as a librarian. Its main output finds and presents
relevant sources for the user to read. A brief lead-in or explanation of how a
source relates to the question is appropriate; summarization must not replace
the sources.

Each source selection carries its title, publication date when available, link,
a short supporting passage verified against the original extracted wording,
and a brief relevance note where useful. Graph chunks contain
coreference-resolved text with overlap and are not guaranteed verbatim source
wording. Quoted passages must therefore be checked against the original body
retained in SQLite rather than copied unverified from a graph chunk.

### A missing graph relationship does not exclude a source

The graph establishes connections, and Article Chunk embeddings provide another
route to relevant information. A passage describing opposition to a Bill remains
eligible for selection even if Entity Extraction missed the stance relationship.
Retrieval need not repair the graph before presenting that source.

Ticket 06 chooses the modes and how their results combine. The comparative
quality of retrieval methods is an evaluation question; this decision does not
declare one method best for every query.

### Disagreements remain visible

The librarian presents conflicting sources and highlights what they disagree
about. It does not adjudicate disputes or silently choose one account as the
truth. Where the evidence establishes that two reports concern different periods
or scopes, the relevance notes can explain that distinction without treating it
as a verdict on either source.

## Handoff and follow-up

- The current graph inventory is recorded below. The parent population task
  remains open: five stored Stories are unprocessed and the required rebuild's
  history is unverified. That work is separate from this completed decision and
  does not prevent prototyping against the observed graph.
- Carry the observed claim and identity limitations into query construction and
  retrieval modes. Source discovery remains useful, while unsupported typed
  comparisons and aggregates cannot be treated as available capabilities.
- The coverage and presentation policies above are settled; their concrete
  contract representation belongs to ticket 08.

## Observed availability, 2026-09-08

The [current inventory](../research/04-graph-inventory-2026-09-08.md) contains
98 CalMatters Source Articles, 2,407 embedded Article Chunks, 3,668 nodes, and
6,061 relationships. Every News Ontology base label is present. All articles
have chunks, all extracted entities reach chunks, and no dangling claim
references were found. These observations establish source access, not answer
quality or complete coverage.

- Entity and measure lookup, article-level Policy Area discovery, reported
  lobbying, actor-to-policy connections, and co-reporting paths are populated.
- All 174 `DECLARED_STANCE` edges lack alignment. Shared-Bill stance paths
  exist, but zero can establish the same side from graph properties. The
  librarian must inspect the reporting rather than equate shared topology with
  matching positions.
- All 12 `FUNDED` edges lack amount and date. Their sources remain eligible;
  monetary totals and funding dates cannot come from graph properties.
- The complete M4 funding-to-candidate-to-Bill path is empty. The component
  relationship types exist separately, which is insufficient for this query.
- Seven reported vote-to-event-to-Bill paths exist. Two Bill-to-Committee
  referrals exist, but no Bill-to-event-to-Committee path joins `ACTION_ON` and
  `HELD_BY`. Complete roll calls and committee history remain unavailable.
- `VICE_CHAIRS` and the `IE_Committee` sub-label are included but empty.
  `District`, `ExternalIdentifier`, `LegislativeTenure`, and
  `RedistrictingCycle` are excluded and absent.
- Thirty-four Organization IDs occur on multiple nodes, affecting 70 nodes;
  22 Bills lack sessions. Stored-node counts are not counts of distinct real
  actors, and cross-article joins must respect identity uncertainty.

The chunk vector index is online. This inventory did not evaluate vector
relevance, repair the graph, or verify that any named target question is
answered by the retrieved passages.

## Application to the target questions

This table applies the accepted policy to the authored target families. The
observed availability above qualifies that intended scope. Every selection
remains subject to the evidence available for that question; the existence of
a generic path is not proof that a named target question can be answered.

| Target families | Eligible news evidence | What remains unavailable without further coverage |
| --- | --- | --- |
| E1 entity dossier, E2 measure lookup | Reporting about the named actor, Bill, or Prop, with unresolved identity made explicit | Claims that require an identity or session the evidence cannot settle |
| E3 Policy Area sweep | Reporting attached to a Policy Area, scoped by publication date when requested; corpus distributions with supporting sources | Event-time coverage inferred from publication dates |
| R1 stated position, R2 lobbying | Sources reporting stances, endorsements, and lobbying | An exhaustive account of all actors or activity without completeness evidence |
| M1 policy footprint, M2 same side, M3 reported alongside | Reported connections and corpus-scoped lists or intersections, grounded per contributing element | Claims of exhaustive participation, or an inferred alliance from co-mention |
| R3 funding, M4 influence chain | Reported funding and connected activity, with each link supported and gaps stated | Complete donor rankings, spending totals, or complete chains unsupported by the available records |
| M5 roll calls | Sources reporting particular votes | Complete roll calls, population-wide voting rankings, and non-votes inferred from missing reporting |
| Committee activity, added by the question set's closing note | Reporting on hearings, committee actions, and referrals | Complete committee activity without corresponding coverage |
| Deferred district history | Relevant reporting found through available retrieval routes | Structured district and tenure history, including redistricting comparisons |

The primary ontology admits district and tenure structures that the News
Ontology excludes. Other Deferred requirements above concern the completeness
of coverage, not wholesale exclusion of votes, funding, or committees from news.
Permanently Declined questions retain ticket 02's policy.

Two stale path descriptions in the target documents must not shape the build:
E3's news topic path now runs through `NewsArticle` and `HAS_CHUNK`, per
[ADR 0020](../../../../docs/adr/0020-a-topic-edge-hangs-off-the-source-article-not-the-article-chunk.md),
and committee activity has `HELD_BY` and `REFERRED_TO`, per the question set's
closing correction. The target questions themselves are unchanged.

## Comments

### 2026-09-08 — Grilling, first round

The maintainer accepted automatic partial evidence with an explicit limitation
and claim-dependent use of incomplete graph elements. They emphasized that
connected source text may supply missing information and that the answering
agent should be a librarian whose selections direct users to the information
sources. They raised an unresolved design question: how the answering agent
gets context describing the data's incompleteness relative to the question.

### 2026-09-08 — Grilling, second round

The maintainer pointed back to ticket 02's Deferred coverage state and identified
no matching stories as a separate state to manage. They accepted the source
presentation with original supporting passages and confirmed that the librarian
highlights disputes without resolving them.

### 2026-09-08 — Grilling, third round

The maintainer proposed supplying a succinct Coverage Description to the
orchestration agent, analogous to AGENTS.md for a directory. Their initial
proposal is to update it on each reingestion with source, dates, percent covered,
and a short account of what the source provides. The unit of coverage, meaning
of those measurements, and update rules remain proposals to sharpen.

They accepted retrieving relevant sources without a matching graph relationship
and identified Article Chunk embeddings as another route. Retrieval methods
will be evaluated for the answers they support relative to a query.

### 2026-09-08 — Grilling, fourth round

The maintainer accepted one coverage entry per Publication or distinct
public-record collection, including separate bill-text and roll-call entries
from one provider. They chose an authored description of what each collection
provides, with ingestion updating the measured facts.

### 2026-09-08 — Grilling, fifth round

The maintainer accepted percentages only against a known, bounded expected set
and noted that archive discovery or another function will need to count what
scraping finds. They clarified that news coverage uses Publication-supplied
publication dates, with no claim of temporal coverage of events. Event coverage
belongs to sources that claim it. The wider temporal problem is deferred.

### 2026-09-08 — Grilling, sixth round

The maintainer chose to update the description from verified available material
and explicitly excluded incomplete-refresh status from the orchestrator context.
The orchestrator needs overall coverage and coverage of relevant periods, not
ingestion operations. They proposed collection totals in the primary description
and an additional monthly breakdown available on demand, measured against the
expected total for each month rather than the Publication total.

### 2026-09-08 — Grilling, seventh round

The maintainer accepted on-demand monthly coverage detail in the initial
retrieval contract. It is loaded when the question needs it, with a verified
available count and unknown completeness where no monthly denominator exists.

### 2026-09-08 — Closed after inventory and handoff

The coverage and presentation decisions are accepted and the current inventory
establishes the available slice and its limits. Issue 05 receives those limits
as prototype conditions. Issues 06 and 08 carry the mode and contract handoffs.
The unfinished population task does not keep this decision open.
