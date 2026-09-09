# Select keyed pieces, compose them, then bind values

Follow-up to [issue 05](../issues/05-prototype-query-construction-and-validation.md)
and the [identifier and resolver experiments](pattern-resolution-comparison.md).

## Requested experiment

The maintainer requested a Sol agent at medium reasoning in a separate
throwaway worktree. The intended separation is:

1. A selector receives the question and a catalog of keyed composable pieces.
   It selects keys instead of writing a complete graph pattern.
2. Code resolves the keys. A composer connects the selected pieces and settles
   the query structure. Composition is deterministic when there is only one
   valid outcome; remaining semantic ambiguity goes to a separate model call.
3. A binder fills the required values in the resulting structure.

Evidence retrieval, identifier assignment, and Cypher generation belong to code.
The composer must not invent unselected relationships, nonexistent node handles,
or evidence paths. A unique topology alone does not prove that filters, anchor
roles, and outputs are uniquely determined. The experiment must report the
actual basis for bypassing the composer model.

The primary outcome is complete retrieval with model-selected pieces. The
previous comparable composable-triples result is **11/25 after a compiler-only
replay**, or 8/25 in its untouched frozen run. The 22/25 result used supplied
correct structures and is only a binding control. The more recent bundled
identifier interface achieved 2/25 at model selection plus binding.

## Evaluation boundaries

The coordinator rechecked all 25 questions before implementation. Every saved
reference field except inspection time is unchanged, including 533 supporting
Article Chunks. The fresh inspection is
`.scratch/query-construction/selector-composer-binder-reference-20260909.json`.

References and authored answer patterns remain evaluator-only. Report selection,
composition, binding, and final retrieval separately, including whether code or
the model composed each case. Supplied-input diagnostic controls must be labeled
separately from end-to-end results. Save full failed responses and usage, freeze
prompts within a batch, and preserve any subsequent repairs or replays separately.
These remain development examples rather than a held-out benchmark.

## Results

The primary model-selected batch completed **2/25** correctly scoped retrievals,
Q24 and Q25. It did not improve on the earlier two-stage composable-triples
result of 11/25 after its compiler replay. Both successful cases concern Bill
referrals to Committees.

**The primary batch made zero composer model calls.** Eight selections had one
compilable arrangement and used deterministic composition. Sixteen could not
be composed, and one produced 331 alternatives, exceeding the explicit limit
of 50 offered composer choices. This result measures the selected-piece
pipeline but does not measure the model composer's effectiveness.

| Primary stage outcome | Cases |
| --- | ---: |
| Missing any triple, or missing an output/count piece | 8 |
| No valid complete arrangement of the selected pieces | 8 |
| Too many composer alternatives, recorded without truncation | 1 |
| Unique arrangement, composed deterministically and executed | 8 |
| Composer model invoked | 0 |

The eight executed queries break down further:

| Retrieval outcome | Cases |
| --- | ---: |
| Complete, correctly scoped answers | 2 |
| Exact current evidence but missing a required predicate alternative | 1 |
| Nonempty results with incorrect scope | 3 |
| Empty results | 2 |

Q14 retrieves the exact 27 reference evidence Chunks but uses only
`LOBBIED_FOR`, where the question asks for a lobbying relationship and requires
the `LOBBIED_FOR`/`LOBBIED_AGAINST` alternative. It does not count as complete.
Q04 returns 34 evidence Chunks and none of its 20 expected Chunks. Q09 and Q18
include the requested evidence along with seven and 222 extra Chunks,
respectively, because the named Campaign or Politician filter was absent.

All 25 selector responses satisfied the key-enumeration output schema. All eight
binding responses satisfied their required-slot schemas. Neither fact guarantees
that the selected operations express the question. A unique arrangement of
incorrect pieces can still produce an incorrect query.

The coordinator independently checked every selection, the executed query
structures, evidence differences, successful answer identities, and captured
usage. No primary query failed in graph execution, and no primary output
correction or transport failure occurred. No rescue inference or replay changed
the primary result.

| Primary model stage | Responses | Input plus output tokens | HTTP seconds |
| --- | ---: | ---: | ---: |
| Selector | 25 | 42,440 | 31.82 |
| Composer | 0 | 0 | 0 |
| Binder | 8 | 27,833 | 7.11 |

The primary batch took 41.52 seconds and captured all 33 responses, totaling
70,273 tokens. The separate composer diagnostic described below is excluded.

## Contract chosen before implementation

The selector returns an ordered multiset of stable piece keys. The catalog
contains ontology triples and atomic filter, projection, distinctness, and
grouped-count pieces. This expands beyond triple-only keys: it lets selection
state which operations are needed without assigning their attachment nodes.
The selector emits no node handles, joins, values, aliases, or free-text plan.

Code resolves selected keys to typed occurrences, then enumerates complete,
connected, type-valid ways to connect and attach those occurrences. Generated
identifiers, relationship direction, and evidence traversal belong to code.
Neither question text nor reference data is used in enumeration.

Exactly one complete arrangement permits deterministic composition. More than
one requires a composer model call choosing an offered arrangement identifier.
No arrangement is a construction failure. Enumeration limits must produce an
explicit failure rather than hiding alternatives and declaring uniqueness.
Arrangements differing in which node is filtered or returned are distinct even
if their underlying triples have the same shape.

The binder fills only the required value slots derived from the chosen
arrangement. It reuses the original literal-binding approach; this experiment
does not add candidate resolution. Depending on composition ambiguity, a
successful run therefore uses two or three primary model calls, plus any bounded
output-correction attempts reported separately.

For shared lobbying, the selector can choose two occurrences of the same
Organization-to-Bill triple, a named Organization filter, Bill name/session
filters, distinct Organizations, and an Organization output. Returning the
named anchor and returning the other Organization remain different choices;
code must not silently choose the peer based on the question.

The initial catalog contains 89 pieces. Before any inference, the coordinator
independently checked three intended selections:

| Supplied pieces for a check | Compilable arrangements | Routing |
| --- | ---: | --- |
| Politician mention, Politician name filter, Chunk output | 1 | Deterministic composition |
| Article topic, Policy Area name filter, two article date bounds, article output | 1 | Deterministic composition |
| Two lobbying triples, named Organization, Bill name/session, distinct Organizations, Organization output | 2 | Model chooses bound anchor versus other Organization |

These are deterministic interface checks using supplied selections, not scored
model outcomes. The enumerator checks complete materialized plans with the
existing compiler before determining uniqueness. It rejects incompatible
aggregate outputs rather than discarding them, and applies explicit bounds
before expensive enumeration rather than truncating candidate lists.

## Three worked examples

### 1. Successful selection and deterministic composition, Q24

Question: "Which Bills from the 2025-2026 session are recorded as referred to
the Senate Appropriations Committee?"

The selector returned these actual catalog keys:

| Key | Resolved piece |
| --- | --- |
| 1015 | Bill session equality filter with an unbound value |
| 1017 | Committee name equality filter with an unbound value |
| 1045 | `Bill -REFERRED_TO-> Committee` |
| 1028 | Return Bill identity |

Only one complete arrangement exists: both filters and the output attach to
their matching node types. Code generates `n0` for the Bill, `n1` for the
Committee, `claim_0` for the referral, and two binding slots. The binder fills
`slot_0 = "2025-2026"` and `slot_1 = "Senate Appropriations Committee"`.
The query returns AB 2540 with the expected referral evidence. This is a real
end-to-end success with two model calls and deterministic composition.

### 2. A unique arrangement with a missing filter, Q09

Question: "Which organizations are reported to have endorsed the Steve Hilton
campaign?"

The selector returned `1030`, `1064`, and `1038`: return Campaign identity,
`Organization -ENDORSED-> Campaign`, and return Organization identity.
It omitted the Campaign name filter.

Code can compose those three pieces in exactly one way, but that arrangement
asks for all recorded Organization-to-Campaign endorsements. There are no
required binding slots, so the binder returns an empty object. The query
returns 15 rows instead of the requested endorsement alone. The compiler cannot
restore the missing filter by interpreting the question. This is a selector
failure despite deterministic composition and successful execution.

### 3. Missing pieces prevent the intended model-composer call, Q16

Question: "Which other organizations are recorded as lobbying for AB 186
alongside Walt Disney in the 2025-2026 session?"

The selector returned `[1009, 1015, 1023, 1068, 1009]`: Organization
distinctness, a Bill session filter, an Organization name filter, one
`Organization -LOBBIED_FOR-> Bill` triple, and repeated distinctness.
It omitted the second lobbying triple, the Bill name filter, and an output.
The selection was rejected before composition.

The intended selected pieces contain the lobbying key `1068` twice, Bill
name/session filters, the Organization name filter, distinct Organizations,
and an Organization output. Those supplied pieces produce two arrangements:
return the named Organization or return its peer. This is where the model
composer is needed. A separately recorded diagnostic supplies those correct
pieces for Q16 and Q17 to exercise that stage; it cannot improve the primary
selector's score.

## Separate composer diagnostic

The primary run did not reach the model composer, so a bounded diagnostic was
requested afterward for Q16 and Q17. It supplies the correct keys, runs the
unchanged composer and binder, and saves a separate report. These are
supplied-selection results, not end-to-end successes or repairs to the frozen
primary batch.

Both diagnostic cases succeeded. Each offered `C001`, which returns the named
anchor, and `C002`, which returns its distinct peer. The composer selected
`C002` for both Walt Disney and Creative Artists Agency. The binder supplied
the correct anchor name, AB 186, and session 2025-2026. Both queries returned
three peers. The coordinator confirmed the peer identities, shared Bill and
session, inequality, and evidence attached separately to each lobbying claim.

| Diagnostic stage | Responses | Input plus output tokens | HTTP seconds |
| --- | ---: | ---: | ---: |
| Composer with supplied correct keys | 2 | 2,419 | 5.68 |
| Binder | 2 | 7,088 | 2.27 |

The diagnostic took 8.33 seconds and used 9,507 tokens across four responses.
It shows the composer handling the two offered anchor-versus-peer choices.
It does not establish general composition accuracy or recover either primary
selector failure.

## Interpretation

The implementation prevents arbitrary composition references by enumerating
complete arrangements and restricting the composer to offered identifiers.
It also keeps evidence traversal in code. The new failure point is selecting
a sufficient and correctly scoped set of pieces from the 89-entry catalog.

This catalog includes filters, outputs, distinctness, and aggregation as well
as triples. That expansion makes full deterministic composition possible, but
it also means the selector still decides which semantic operations are needed.
The experiment changes the task division, catalog, and output contracts
together. It does not isolate the effect of a third model call, and the primary
run provides no model-composer evidence because selection never reached that
stage within its configured limits.

## Artifacts and checks

Worktree: `/private/tmp/ca-map-prototype-selector-composer-binder-20260909`.
Branch: `codex/prototype-selector-composer-binder`, commit `86c52fe`.

- [Findings with worked examples](reports/selector-composer-binder/findings.md)
- [Frozen primary report](reports/selector-composer-binder/results/full-report.json)
- [Separate supplied-key diagnostic](reports/selector-composer-binder/results/supplied-key-composer-diagnostic.json)
- [Authored-piece coverage and interface checks](reports/selector-composer-binder/results/interface-smoke.json)
- [Run instructions](reports/selector-composer-binder/README.md)

The coordinator verified the frozen report's recorded code and input hashes,
the correct baselines, primary scope and evidence outcomes, diagnostic
compositions and evidence, and both sets of usage totals. Reports and code are
preserved on the throwaway branch. This checkout receives documentation only.
Ruff, formatting, Python compilation, whitespace checks, and the all-25
authored-piece coverage check passed. No browser verification was used.
