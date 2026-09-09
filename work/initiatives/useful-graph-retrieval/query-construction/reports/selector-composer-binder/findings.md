# Keyed selector, composer, and binder findings

## Result

The full model-selected pipeline completed 2 of 25 questions: Q24 and Q25. This equals the latest compiler-assigned selection result of 2/25 and remains below the corrected composable-triples result of 11/25. The historical correct-supplied-pattern binding diagnostic remains 22/25; it is not a planning score.

The selector returned schema-valid key lists for all 25 questions, but only two lists were semantically sufficient for the question. Eight selections lacked a triple or output and failed the bounded enumerator immediately. Eight more produced no connected compiler-valid complete wiring. Q08 produced 331 valid wirings and stopped at the explicit 50-option composer limit. Eight cases had exactly one valid wiring, bypassed the composer model, reached the binder, and executed. Six returned rows and two were empty.

Three executions had the exact reference evidence set. Q14 is excluded from completion because the selector chose only `LOBBIED_FOR` for a question asking about a lobbying relationship. The current graph happened to return the same 27 evidence Chunks as the reference union, but the query would omit opposing relationships. Q24 and Q25 retained the requested referral scope, entity roles, and evidence.

| Measurement | Result |
| --- | ---: |
| Schema-valid selector responses | 25/25 |
| Semantically sufficient selections | 2/25 |
| Deterministic unique compositions | 8 |
| Composer-model calls in the primary batch | 0 |
| Composer option overflow | 1, Q08 with 331 candidates |
| Valid binder outputs | 8/8 reached |
| Executed queries | 8 |
| Executed empty | 2 |
| Exact reference evidence sets | 3 |
| Semantically complete retrievals | 2/25 |

The primary batch does not measure composer-model accuracy. No model-selected key list produced between 2 and 50 candidates. That absence matters: splitting the calls did not rescue selection, and the deterministic bypass cannot be treated as a composer success.

## What the contract actually tests

The selector sees an 89-entry catalog and emits a list whose item schema is an enum of those exact integer keys. Repeated integers create repeated occurrences. It cannot emit nodes, handles, joins, slot names, values, or prose.

The catalog is broader than the previous 29-triple catalog because it includes atomic filter, output, distinctness, and grouped-count pieces. It also excludes date equality and offers only the half-open date operators for `NewsArticle.published_date`. The earlier interface exposed a date equality choice and a broad optional aggregate field. These are coordinated contract changes, so the result does not isolate the effect of adding a composer stage or integer keys.

Code assigns typed endpoint ports to each selected triple occurrence, enumerates label-exact joins and operation attachments, and removes isomorphic duplicates. It checks the old compiler before calling a candidate valid. Enumeration and canonicalization have small explicit bounds, and the runner refuses to truncate a large set and call it unique. LaborUnion and PAC stay exact sub-labels rather than silently merging into Organization.

The composer sees the question, selected resolved pieces, and complete candidate records. Its output field is an enum containing only the offered candidate ids. It cannot add an unselected edge, predicate, node, filter, output, or evidence path. Uniqueness covers the complete semantic wiring. Shared topology alone does not qualify when the bound anchor and returned peer can swap roles.

The existing compiler generates direction, names, ids, slots, Cypher, and claim-specific evidence traversal. It adds `HAS_CHUNK` only as mechanical support for the grouped NewsArticle count. The unchanged binder receives the question and exact compiler-generated slots. No resolver or graph candidate lookup was added.

The no-model authored-piece check covers all 25 prior correct patterns. Twenty-three yield one candidate. Q16 and Q17 each yield two: C001 returns the Organization carrying the name filter, while C002 returns the other Organization joined through the same Bill. This diagnostic proves the representation can preserve the anchor-versus-peer decision.

## Three worked examples

### Q25, complete through a unique composition

Question: “Which committees is AB 2540 in the 2025-2026 session recorded as having been referred to?”

The selector returned `[1014, 1015, 1028, 1032, 1045]`:

- 1014: filter `Bill.name` with an unbound equality slot
- 1015: filter `Bill.session` with an unbound equality slot
- 1028: return Bill identity
- 1032: return Committee identity
- 1045: `Bill -REFERRED_TO-> Committee`

Code found one complete wiring, C001. It attached both filters to the Bill, returned the Bill and Committee, and assigned `slot_0` and `slot_1`. The binder supplied `AB 2540` and `2025-2026`. The read-only query returned both stored committees with the exact referral evidence. This is one of the two complete primary results.

### Q05, filter keys without the relation they need

Question: “Which stored articles discuss housing and community development in July 2026?”

The selector returned `[1020, 1021, 1025, 1036]`:

- 1020 and 1021: the lower and upper `NewsArticle.published_date` bounds
- 1025: filter `PolicyArea.name`
- 1036: return NewsArticle identity

It omitted key 1060, `NewsArticle -DISCUSSES_TOPIC-> PolicyArea`. Without a triple there are no handles or join to which those filter and output pieces can attach. Enumeration rejected the selection before composition, no slots were created, and the binder and graph were not called. The selector recognized the filter semantics but did not select a retrievable graph relation.

### Q16, primary selector failure and separate composer diagnostic

Question: “Which other organizations are recorded as lobbying for AB 186 alongside Walt Disney in the 2025-2026 session?”

In the primary batch the selector returned `[1009, 1015, 1023, 1068, 1009]`: Organization distinctness twice, a Bill-session filter, an Organization-name filter, and one `Organization -LOBBIED_FOR-> Bill` occurrence. It omitted the second lobbying occurrence, Bill-name filter, and outputs. Enumeration rejected it for having no output. No composer or binder call occurred.

The separate supplied-key diagnostic used the evaluator-authored keys `[1068, 1068, 1023, 1014, 1015, 1009, 1038, 1028]`. Code resolved two lobbying occurrences sharing one Bill and produced two complete candidates. C001 returns the named Organization. C002 returns the distinct peer. The composer model chose C002 for both Q16 and Q17. The binder then supplied:

```json
{"slot_0": "Walt Disney", "slot_1": "AB 186", "slot_2": "2025-2026"}
```

Q17 used `Creative Artists Agency` in `slot_0`. Both diagnostic queries returned three peers with the exact reference evidence sets. This is 2/2 composer-stage success under privileged correct keys. It bypasses the selector and is excluded from the 2/25 primary score.

## Per-case primary audit

| Case | Selected-piece outcome | Final outcome |
| --- | --- | --- |
| Q01 | Omitted Article-to-Chunk reporting connection | No valid wiring |
| Q02 | Omitted Article-to-Chunk reporting connection | No valid wiring |
| Q03 | Filters and output, no triple | Enumeration rejection |
| Q04 | Kept Prop mention, added an extra topic edge, omitted name filter/reporting output | 3 rows, wrong scope and evidence |
| Q05 | Date/topic filters, no topic triple | Enumeration rejection |
| Q06 | Date/topic filters, no topic triple | Enumeration rejection |
| Q07 | Count operation, no topic triple | Enumeration rejection |
| Q08 | Selected the relevant stance plus four extra relationships | 331 candidates, option overflow |
| Q09 | Omitted named Campaign filter | 15 broad rows |
| Q10 | Added anchor filter/distinctness, no output | Enumeration rejection |
| Q11 | Added anchor filter/distinctness, no output | Enumeration rejection |
| Q12 | Mixed Organization and PAC funding shapes | No valid wiring |
| Q13 | Filtered PAC instead of Campaign, returned Campaign | Empty |
| Q14 | Chose only `LOBBIED_FOR` instead of union | Exact current evidence, under-scoped |
| Q15 | Chose only `LOBBIED_FOR` instead of union | Empty |
| Q16 | One lobbying occurrence, duplicate distinctness, no output | Enumeration rejection |
| Q17 | One lobbying occurrence, duplicate distinctness, no output | Enumeration rejection |
| Q18 | Omitted the Steve Hilton filter | 295 broad rows |
| Q19 | Omitted Article-to-Chunk connection | No valid wiring |
| Q20 | Omitted Campaign-to-Politician target triple | No valid wiring |
| Q21 | Omitted Campaign-to-Prop target, added PAC funding | No valid wiring |
| Q22 | Omitted Event-to-Bill and Bill-name filter | No valid wiring |
| Q23 | Omitted Event-to-Bill and Bill-name filter | No valid wiring |
| Q24 | Sufficient referral pieces; Committee output unnecessary | Complete, exact evidence |
| Q25 | Complete referral pieces | Complete, exact evidence |

## Usage and integrity

The primary batch took 41.522 seconds. It captured 25 selector responses using 42,440 tokens and 31.818 HTTP seconds, plus eight binder responses using 27,833 tokens and 7.113 HTTP seconds. The total is 33 responses, 70,273 tokens, and 38.931 HTTP seconds. There were no primary composer responses.

The separate diagnostic took 8.329 seconds. Its two composer responses used 2,419 tokens and 5.682 HTTP seconds. Its two binder responses used 7,088 tokens and 2.269 HTTP seconds. Both diagnostic compositions and retrievals succeeded.

The coordinator rechecked all 25 live references before inference, including 533 resolved Article Chunks. Every saved field matched the prior reference except inspection time. The primary report records hashes for the cases, reference results, ontology, fresh verification, and every Python source file used by the run; all still match. Raw requests, responses, usage, prompts, schemas, selected pieces, candidates, bindings, queries, rows, and references are preserved. There was no retry after the batch to improve a selector result and no compiler replay.

The experiment answers a narrower question than hoped. Whole-candidate composition works cleanly when the selected pieces are sufficient, and the two-case privileged check shows the composer can distinguish anchor from peer. The full run offers no evidence that the composer helps end-to-end, because the selector rarely selected a complete set and never produced a manageable ambiguity. With this prompt and model run, flat selection from the 89-piece catalog did not improve planning.
