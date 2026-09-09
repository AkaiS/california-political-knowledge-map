# Compiler-assigned pattern-selection findings

## What we were extending

We extended the previous composable ontology triples prototype. Here, a
**pattern** means the graph structure needed to answer a question: which kinds
of nodes participate, which relationships connect them, which nodes are shared
between triples, which filters apply, and which values should be returned.
Selecting that structure was already the first model stage in the previous
two-stage prototype.

For example, `Organization -LOBBIED_FOR-> Bill` is one allowed ontology triple.
Two Organizations lobbying for the same Bill require two such triples joined
at one shared Bill. Choosing that join is a semantic decision. Naming the
nodes `anchor`, `peer`, and `bill` is bookkeeping.

Previously, the model did both. It wrote the triples and invented node names,
claim names, binding-slot names, and descriptions. This experiment moved those
names into code while keeping semantic choices with the model.

There are two different kinds of identifier in the new interface:

| Identifier | What it identifies | Who supplies it |
| --- | --- | --- |
| `Organization__LOBBIED_FOR__Bill` | An allowed kind of ontology triple | Code generates the catalog; the model selects an entry |
| `n0`, `n1`, `claim_0`, `slot_0` | A particular node, claim, or value slot in this query | Code assigns names from list positions |

There is no identifier for an entire ready-made query such as "find fellow
lobbyists." The model still composes the query from individual triples, in one
structured response. It references node positions such as 0 and 1, so it still
has to get the cross-references right. We did not implement an incremental
interaction that offers only the valid next choices.

The actual implementation path is:

```text
Question
  -> model selects triples, node positions, filters, and outputs
  -> new adapter assigns names and creates the previous PatternPlan
  -> previous triples compiler generates Cypher and evidence retrieval
  -> previous binder supplies names, sessions, and dates
  -> execute against the graph
```

`compiler.py:materialize` performs that conversion; `compile_selection` calls
the previous `compile_pattern`. The supplied-pattern control bypasses the first
model decision by giving code an authored correct structure, then uses the same
conversion, compiler, and binder. Its 22/25 result measures binding with correct
structure supplied, not successful model planning.

## Which earlier result is the baseline?

The earlier composable ontology triples prototype had separate arms. Its
22/25 result and its 11/25 result did not measure the same task.

| What the model had to do | Previous composable triples | This identifier extension |
| --- | ---: | ---: |
| Fill values for an authored correct pattern supplied by the evaluator | 22/25 | 22/25 |
| Choose the triples, joins, filters, and outputs, then fill values | 8/25 frozen; 11/25 after a compiler-only replay | 2/25 |

The first row is the successful 22-case result. This experiment retained it as
a control and reproduced every previous control output after renaming generated
fields. The second row is the planning task we extended and scored as 2 versus
11. The previous 11 includes the documented compiler correction; it was not the
untouched frozen result.

Thus, **we did not take 22 successful supplied-pattern cases and turn them into
2 successes**. The supplied-pattern cases stayed at 22. We tested a changed
model-facing planning interface as well. These arms use the same composable
ontology triple representation underneath, but supply different amounts of
structure to the model.

A clearer description of the requested work would have separated "rename and
compile the 22/25 supplied-pattern path" from "test whether the model can select
those structures more reliably." The first was preserved; the second performed
poorly. The reports previously led with scores before explaining that distinction.

## Three concrete examples

The intended structures below explain the task. The paragraphs labeled
"Observed" describe the saved model outputs, not those intended structures.

### 1. Find reporting that mentions Steve Hilton, Q01

The question was "What stored reporting mentions Steve Hilton?"

The essential triple is:

```text
Politician -MENTIONED_IN-> Chunk
Filter the Politician by name.
Return the matching reporting Chunks.
```

Previously, the model would invent names such as `politician`, `chunk`,
`politician_mention`, and `politician_name`, and repeat those names in the
appropriate fields. With this extension, it selects node labels
`[Politician, Chunk]`, chooses catalog entry
`Politician__MENTIONED_IN__Chunk` between positions 0 and 1, and requests a name
filter on position 0.

Code turns those choices into:

```text
(n0:Politician) -[claim_0:MENTIONED_IN]-> (n1:Chunk)
n0.name = $slot_0
```

The binder supplies `slot_0 = "Steve Hilton"`. The selected triple tells the
compiler how to retrieve Grounding Evidence. **Observed:** this is the structure
the model selected, and it retrieved the two expected Chunks.

### 2. Find organizations lobbying alongside Walt Disney, Q16

The question asked which other organizations lobbied for AB 186 alongside Walt
Disney in the 2025-2026 session. The intended composition is:

```text
n0:Organization -LOBBIED_FOR-> n1:Bill <-LOBBIED_FOR- n2:Organization
n0.name = "Walt Disney"
n1.name = "AB 186"; n1.session = "2025-2026"
n0.id must differ from n2.id
Return n2, with evidence for both lobbying claims.
```

The same catalog triple, `Organization__LOBBIED_FOR__Bill`, is selected twice.
Both occurrences must reference Bill position 1. Code can assign the two claim
names and three binding slots. The model must still choose two Organization
positions and share the Bill position. Actual names and session values are
filled later by the binder.

**Observed:** the model created only one Organization and one Bill. It selected
one lobbying triple, constrained that Organization to Walt Disney, and required
position 0 to differ from itself. It also requested an unnecessary aggregate,
which caused rejection before execution. Assigning names did not supply the
missing peer or the shared-Bill join.

### 3. Find housing articles published in July 2026, Q05

The intended structure is:

```text
n0:NewsArticle -DISCUSSES_TOPIC-> n1:PolicyArea
n1.name = $slot_0
n0 publication date >= $slot_1
n0 publication date <  $slot_2
Return articles and their supporting Chunks.
```

The model should select `NewsArticle__DISCUSSES_TOPIC__PolicyArea`, a name
equality filter, and two date-bound filters. Code assigns the slots. The binder
then supplies `Housing & Community Development`, `2026-07-01`, and
`2026-08-01`. The existing compiler obtains the article's Chunks through
`HAS_CHUNK`.

**Observed:** the model selected the right triple but chose one date equality
filter. The binder filled it with `2026-07`, and the query returned nothing.
The identifier assignment worked; the selected date operation was wrong.

## What this experiment can establish

This was an extension of the existing triples approach, but it changed more
than names. It replaced the full-ontology prompt with a 29-entry triple catalog
and shorter instructions, and changed the response fields for nodes, joins,
filters, outputs, and aggregation. The binder instructions and underlying
Cypher/evidence compiler were reused.

Consequently, the 2/25 result says this particular revised interface performed
poorly. It does not establish that compiler-assigned identifiers are a bad idea,
or isolate their effect from the other interface changes. Describing the run
only as "pattern selection failed" hid that distinction.

## Question and fixed gate

This throwaway experiment asks whether a smaller model-facing contract, with
compiler-assigned node handles, claim ids, binding slots, slot descriptions, and
projection aliases, reduces malformed semantic plans without weakening scope or
Grounding Evidence. The gate was recorded before inference: reduce malformed
plans and improve correctly scoped retrieval over the corrected composable-
triples baseline of 11/25. Structure, meaning, and binding are scored separately.

The gate failed. The new selected arm completed 2/25 correctly scoped
retrievals, down from 11/25, and compiler rejection rose to 18/25 from 13/25.
There is no case for combining this interface with entity resolution.

## What changed

The model selected an ordered list of node labels, positional node handles,
stable ontology-derived relationship ids, filters, distinct-node requirements,
projections, and one optional aggregate. Code assigned all repeated names and
derived relationship direction, provenance, binding descriptions, and aliases.
The catalog contained 29 representable triples generated from the supported
News Ontology subset. A reversed-endpoint smoke confirmed that code retained
direction ownership.

This was an interface experiment with coordinated changes. The prompt replaced
the full ontology and prior rules with the 29-choice catalog and shorter storage
notes, while the contract changed identifiers and field shapes. The result does
not isolate compiler-assigned identifiers as the cause. The original binder
instructions stayed fixed, although it received the newly derived slot names and
descriptions by design.

## Frozen outcome

The selection arm produced seven compiler-valid plans and eighteen rejected
plans. The seven valid plans all produced schema-valid bindings and executed.
Q01 and Q25 returned the exact reference evidence sets with correct scope. Q03,
Q05, Q06, Q09, and Q13 returned no rows because their plans or bindings were
wrong.

The dominant failure was optional aggregate selection. The model supplied a
non-null aggregate in 16/25 cases even though only Q07 asks for a grouped count.
Fifteen plans failed an aggregate compiler rule; Q22 also selected an aggregate
but first failed an unsupported projection. The reduced contract removed alias
and claim-name failures but left the model with another broadly optional field
that it treated as routine structure.

| Case | Outcome | Semantic audit |
| --- | --- | --- |
| Q01 | complete | Direct Politician mention retrieval; exact requested evidence with a chunk-only row layout. |
| Q02 | rejected | Correct mention edge, plus a self-inequality and unsupported aggregate. |
| Q03 | empty | Chose LegislativeEvent reporting instead of the Bill's direct mention path. |
| Q04 | rejected | Correct mention edge, plus a self-inequality and unsupported aggregate. |
| Q05 | empty | Used date equality with `2026-07` instead of a half-open July range. |
| Q06 | empty | Used date equality with `2026-07` instead of a half-open July range. |
| Q07 | rejected | Requested grouping but omitted `HAS_CHUNK` evidence and added a disallowed article projection. |
| Q08 | rejected | Kept LaborUnion, Bill, session, stance, and its claim evidence, but added a Bill-mention join, an unrelated inequality, and an invalid aggregate. |
| Q09 | empty | Chose endorsement and Campaign scope, then required Organization id to differ from itself; binder also dropped `campaign`. |
| Q10 | rejected | Chose the right claim and Bill scope, then added a self-inequality and unsupported aggregate. |
| Q11 | rejected | Chose the right claim and Bill scope, then added a self-inequality and unsupported aggregate. |
| Q12 | rejected | Retained funding-claim evidence but overconstrained both Prop and Campaign names, added a Campaign-mention join, and misused distinctness and aggregation. |
| Q13 | empty | Retained funding-claim evidence but used Organization instead of PAC, added an Organization name filter, self-inequality, and mention join; binder dropped `campaign`. |
| Q14 | rejected | Kept the lobbying union and shared Bill-to-topic join, then added a self-inequality and unsupported aggregate. |
| Q15 | rejected | Kept the lobbying union and shared Bill-to-topic join, then added a self-inequality and unsupported aggregate. |
| Q16 | rejected | Used one Organization handle, so anchor and peer cannot be distinct while sharing one Bill. |
| Q17 | rejected | Used one Organization handle, so anchor and peer cannot be distinct while sharing one Bill. |
| Q18 | rejected | Kept the shared Chunk join but added a cross-label inequality and unsupported aggregate. |
| Q19 | rejected | Omitted NewsArticle/`HAS_CHUNK` and applied the article title to unsupported `Chunk.title`. |
| Q20 | rejected | Kept the funding-to-candidate chain and target label, then added a cross-label inequality and unsupported aggregate. |
| Q21 | rejected | Kept the funding-to-Prop chain and target label, then added a cross-label inequality and unsupported aggregate. |
| Q22 | rejected | Omitted `ABSTAINED`, asked unsupported names from LegislativeEvent and Chunk, and added mention/aggregate structure. |
| Q23 | rejected | Omitted `ABSTAINED`, asked unsupported names from LegislativeEvent and Chunk, and added a mention edge. |
| Q24 | rejected | Kept referral and both scope filters, then added a cross-label inequality and unsupported aggregate. |
| Q25 | complete | Correct referral, Bill designation/session scope, Committee projection, and claim evidence. |

The vote cases demonstrate a material semantic regression even before execution:
both omitted `ABSTAINED`, so a successful query could have silently guessed the
allowed outcomes. The same-side cases did not create separate anchor and peer
handles. Q13 dropped the PAC sub-label. Q05 and Q06 lost the date-range meaning.
These cannot count as progress merely because parts of their selected paths were
recognizable.

## Supplied-pattern diagnostic

All 25 supplied patterns compiled and executed. After normalizing `n#`,
`claim_#`, and projection aliases, every result equals the prior oracle-arm
output, including relationship-type projections, per-claim evidence groups, and
all 26 Policy Area counts and source-id sets. Twenty-two are complete
retrievals. The three known Campaign cases remain empty because the unchanged
binder returns `Steve Hilton`, `Yes on Proposition 38`, and `Ed Musgrove`
without the stored `campaign` suffix. This preserves the failure that the
separate resolver experiment is intended to measure.

## Usage and integrity

| Stage | Responses | Tokens | HTTP time |
| --- | ---: | ---: | ---: |
| Pattern selection | 25 | 34,690 | 176.8871 s |
| Selected-pattern binding | 7 | 24,540 | 6.4486 s |
| Supplied-pattern binding | 25 | 87,881 | 20.8388 s |
| Total | 57 | 147,111 | 204.1745 s |

The batch took 208.075639 seconds wall time. Every provider response has usage,
request, response, and transport timing in the frozen report. No retry occurred.
The fresh pre-inference verifier passed all 25 references with 533 resolved
Article Chunks. References entered the report only after all model calls.

The frozen report is `results/full-report.json`. The offline audit is
`results/assessment.json`; it makes no model or graph calls. No fix, replay, or
rescue inference was run.
