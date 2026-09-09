# Target Question Set

Authored by [Decide the target question set](issues/02-target-question-set.md).
The decisions this set embodies live in that ticket; this document holds the
targets themselves.

For issue 05's construction experiment, use the
[questions grounded in the populated graph](query-construction/README.md).
Authored on 2026-09-08 at the maintainer's request, that set retains these
families with concrete, retrievable subjects and executed reference Cypher.
This document retains the broader targets and the Declined and Deferred controls.

Additions may be made by anyone, including an agent. **Removals and rewordings
are the maintainer's alone** — a retrieval mode that cannot answer a question is
not fixed by editing the question.

## How to read an entry

Every question records six things.

**Orientation** — derived from the shape of the path's *entity segment*, which
is the path with its terminal grounding hop removed:

| Entity segment | Orientation |
| --- | --- |
| one node | entity lookup |
| one edge between two nodes | relationship lookup |
| two or more edges | multi-hop traversal |

Orientation is a function of the path, never an independent claim. It is
recorded only so coverage is checkable at a glance; where the two disagree, the
path is right.

**Grounding** — `evidence-grounded` where an Article Chunk states the answer and
the graph is what reaches it, or `structure-derived` where the answer is a
property of the graph's shape (a count, a list, an intersection) that no Chunk
states. Structure-derived answers are second-class: they are never delivered as
a bare result, always with the Grounding Evidence behind each element counted.

**Path** — the traversal in the ontology's own vocabulary, terminating in the
`(:Chunk)` grounding hop. Not Cypher: the executable form is
[ticket 05](issues/05-prototype-query-construction-and-validation.md)'s output,
and this set is authored before a graph exists to run it against.

**Layer** — `news-populated` where the News Ontology can produce the structure
today, or `outcome-5` where it depends on legislative or campaign-finance
ingestion.

**Tags** — zero or more of:

- `ambiguous seed` — the question names a subject that resolves to more than one
  node. A plausible-looking traversal lands on the wrong one and grounds the
  answer in the wrong Chunks.
- `temporal scope` — the answer depends on an as-of date the question leaves
  implicit. Bill numbers recycle across sessions; district identity changes
  across a `RedistrictingCycle`.
- `negation` — the question asks what did *not* happen over a universe that is
  enumerable and whose non-events are recorded. Answerable in principle; see
  [Deferred](#deferred).

**Questions** — natural language, as a developer would type them. Rewriting a
question into a parameterized form is a retrieval-layer concern, not a property
of the target.

Subjects are real wherever the gathered Source Articles support them, so a
family that is unanswerable in practice is discovered early. Questions on
`outcome-5` layers use placeholder subjects, because inventing a plausible FPPC
donation would create a target that can never be verified.

---

## Entity lookup

### E1 — Entity dossier

- **Orientation**: entity lookup
- **Grounding**: evidence-grounded
- **Layer**: news-populated
- **Path**: `(:Politician)-[:MENTIONED_IN]->(:Chunk)`

Questions:

- What has been reported about Gavin Newsom's position on the climate deal?
- Who is Steve Hilton?
- What has been reported about Tom Steyer's brother and California AI policy?

### E2 — Measure lookup

- **Orientation**: entity lookup
- **Grounding**: evidence-grounded
- **Layer**: news-populated
- **Path**: `(:Bill)-[:MENTIONED_IN]->(:Chunk)`, `(:Prop)-[:MENTIONED_IN]->(:Chunk)`

Questions:

- What has been reported about SB 9? `[temporal scope]` — SB 9 exists in more
  than one session and the question names none.
- What is Proposition 38?
- What does the HOA fee cap bill do? `[ambiguous seed]` — named by description
  rather than number.

### E3 — Policy area sweep

- **Orientation**: entity lookup
- **Grounding**: evidence-grounded
- **Layer**: news-populated
- **Path**: `(:PolicyArea)<-[:DISCUSSES_TOPIC]-(:Chunk)`

Questions:

- What has been reported on housing and community development?
- What has been reported on labor and employment in the last three months?
  `[temporal scope]`
- Which policy areas has coverage concentrated on? `structure-derived` — a
  distribution over hubs, delivered with the Chunks behind each count.

---

## Relationship lookup

### R1 — Stated position on a measure

- **Orientation**: relationship lookup
- **Grounding**: evidence-grounded
- **Layer**: news-populated
- **Path**:
  `(:Organization)-[:DECLARED_STANCE]->(:Bill)-[:MENTIONED_IN]->(:Chunk)`,
  and the same shape for `:Politician` sources and `ENDORSED` / `DENOUNCED`
  against `:Prop` / `:Campaign` targets.

Questions:

- Which organizations opposed the $28 construction minimum wage bill, and what
  did they say?
- Which lawmakers spoke against the HOA fee cap bill?
- Who endorsed Proposition 38?
- Which unions opposed the housing bill that would raise wages to $28?
  `[ambiguous seed]`

### R2 — Lobbying on a measure

- **Orientation**: relationship lookup
- **Grounding**: evidence-grounded
- **Layer**: news-populated
- **Path**: `(:Organization)-[:LOBBIED_FOR|:LOBBIED_AGAINST]->(:Bill)-[:MENTIONED_IN]->(:Chunk)`

Questions:

- Which organizations lobbied on the Uber insurance law?
- What did tribes argue in the cardroom blackjack dispute?

### R3 — Money into a campaign

- **Orientation**: relationship lookup
- **Grounding**: evidence-grounded
- **Layer**: outcome-5 (news supplies the edge only where an article names a
  figure; the corpus carries few)
- **Path**: `(:Organization)-[:FUNDED]->(:Campaign)-[:MENTIONED_IN]->(:Chunk)`

Questions:

- Which organizations funded the campaign for Proposition 38?
- How much did the construction trades spend opposing the wage bill?
- Which organizations funded a given ballot-measure campaign, and on what dates?

---

## Multi-hop traversal

### M1 — An actor's policy footprint

- **Orientation**: multi-hop traversal
- **Grounding**: structure-derived, delivered with Grounding Evidence per edge
- **Layer**: news-populated
- **Path**: `(:Organization)-[:LOBBIED_FOR|:LOBBIED_AGAINST|:DECLARED_STANCE]->(:Bill)-[:ABOUT_TOPIC]->(:PolicyArea)`,
  grounded through `(:Bill)-[:MENTIONED_IN]->(:Chunk)`

Questions:

- Which policy areas has Uber engaged with in California?
- Which policy areas do the construction trade unions appear in?

### M2 — Who took the same side

- **Orientation**: multi-hop traversal
- **Grounding**: structure-derived, delivered with Grounding Evidence per edge
- **Layer**: news-populated
- **Path**: `(:Organization)-[:DECLARED_STANCE]->(:Bill)<-[:DECLARED_STANCE]-(:Organization|:Politician)`,
  grounded through the `(:Chunk)` list on each edge

Questions:

- Which organizations took the same side as the construction unions on the wage
  bill?
- Which lawmakers have opposed the same bills as Uber?
- Which organizations have opposed the same measures more than once?

### M3 — Reported alongside

- **Orientation**: multi-hop traversal
- **Grounding**: evidence-grounded
- **Layer**: news-populated
- **Path**: `(:Politician)-[:MENTIONED_IN]->(:Chunk)<-[:MENTIONED_IN]-(:Organization)`

Questions:

- Which organizations are reported alongside Gavin Newsom in coverage of the
  climate deal?
- Who else appears in reporting on the Bay Area city project?

This is the family that works when the ontology declares no typed edge between
two entities but the reporting connects them anyway.

### M4 — Influence chain

- **Orientation**: multi-hop traversal
- **Grounding**: structure-derived, delivered with Grounding Evidence per edge
- **Layer**: outcome-5
- **Path**: `(:Organization)-[:FUNDED]->(:Campaign)-[:CAMPAIGN_FOR]->(:Politician)-[:DECLARED_STANCE]->(:Bill)`,
  grounded through the `(:Chunk)` list on each edge

Questions:

- Which bills has a given candidate taken a position on, among those whose
  campaign a given industry funded?
- Which funders of a given campaign also lobbied on bills that campaign's
  candidate voted on? `[temporal scope]`

### M5 — Roll call around a measure

- **Orientation**: multi-hop traversal
- **Grounding**: structure-derived, delivered with Grounding Evidence per edge
- **Layer**: outcome-5
- **Path**: `(:Politician)-[:VOTED_AYE|:VOTED_NO|:ABSTAINED]->(:LegislativeEvent)-[:ACTION_ON]->(:Bill)`,
  grounded through `(:LegislativeEvent)-[:MENTIONED_IN]->(:Chunk)`

Questions:

- How did each senator vote on the ADA lawsuit bill that died?
- Which lawmakers most often vote against their own party? `[temporal scope]`
- Which senators did not vote on the ADA lawsuit bill? `[negation]`

---

## Declined

Permanently outside what this layer will answer, regardless of coverage. These
are a stance, not a gap — the graph is a discovery layer that directs readers to
original reporting, and each of these would substitute for it, invent beyond the
evidence, or return a useless answer set.

| Kind | Example |
| --- | --- |
| Out of domain | What did the Texas legislature do about housing this year? |
| Narrative or motive | Why did Newsom *really* sign the Uber ballot-measure deal? |
| Normative | Should I vote yes on Proposition 38? |
| Predictive | Will the HOA fee cap bill pass? |
| Beyond-evidence inference | Which California legislators are bought by tech money? |
| Private individuals | Who are the family members of a given legislator? |
| Absence over an open universe | Which organizations did *not* fund the campaign against Proposition 38? |

The last row is the one to keep distinct from `negation`. Absence asks for the
complement of a set whose universe is unbounded — every organization in
California that stayed silent. The answer is enormous, unverifiable, and would
be an artifact of what our Publications happened to cover rather than a fact
about California politics. No amount of ingestion closes it.

## Deferred

Legitimate questions this layer is meant to answer and cannot yet.
[Ticket 04](issues/04-retrievable-subgraph-now.md) decides how the layer behaves
when a question reaches one of these — decline, partial answer with a stated gap,
or degrade to news evidence alone.

| Kind | Example | What closes it |
| --- | --- | --- |
| Roll-call votes | How did each senator vote on the ADA lawsuit bill? | Open States ingestion (outcome 5) |
| Campaign finance | Who were the largest donors to the 2026 governor's race? | CAL-ACCESS ingestion (outcome 5) |
| District history | Who represented Assembly District 52 before and after the 2021 redistricting? | `District`, `RedistrictingCycle`, and `LegislativeTenure`, none of which the News Ontology produces |
| Negation over a closed universe | Which Assembly members did not vote on AB 1165? | The roll-call layer. Every member is enumerable and every non-vote is recorded, so the complement is finite and meaningful — which is exactly what distinguishes this from absence above. |
### One structural gap, since closed

Committee activity — "which bills did the Assembly Appropriations Committee
hear?" — was listed above as unanswerable, and it was not an ingestion gap:
`ontology.md` declared no relationship from `:Committee` to `:Bill` or to
`:LegislativeEvent`, so a Committee connected only to `:LegislativeTenure`
through `SERVES_ON`, `CHAIRS`, and `VICE_CHAIRS` and no amount of outcome-5
data supplied a path.

The primary ontology has since been corrected under
[ADR 0014](../../../docs/adr/0014-the-primary-ontology-is-authored-not-frozen.md)
with `:LegislativeEvent` -`HELD_BY`→ `:Committee` and `:Bill` -`REFERRED_TO`→
`:Committee`. The question now has a path, and news supplies both edges, so
[ticket 04](issues/04-retrievable-subgraph-now.md) and
[ticket 06](issues/06-retrieval-modes-and-index-inventory.md) should treat
committee activity as in scope rather than as a declared gap.
