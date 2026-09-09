# Findings from composable semantic triples

The frozen batch ran all three arms over 25 questions in 663.95 seconds. After replaying five otherwise unchanged plans through the deterministic duplicate-projection fix, the oracle structure arm retrieved 22 complete answers, the two-stage arm retrieved 11, and the single-call arm retrieved 8. Every nonempty result across the frozen run and replay had exactly the reference union of evidence Chunk ids. The article-count case also matched all 26 reference counts and each Policy Area's source Article id set.

| Arm | Model responses | Tokens | Compiler-valid patterns | Valid bindings | Executed after replay | Nonempty and complete |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Oracle structure and binder | 25 | 87,451 | 25 | 25 | 25 | 22 |
| Two-stage pattern and binder | 37 | 143,578 | 12 | 12 | 12 | 11 |
| Single call | 28 | 127,999 | 14 | 11 | 11 | 8 |
| Total | 90 | 359,028 | 51 | 48 | 48 | 41 |

The two-stage response count combines 25 pattern responses with 12 binding responses. HTTP time was 21.75 seconds for oracle binding, 254.59 for pattern selection, 12.56 for two-stage binding, and 368.95 for the single call. All 90 local responses returned HTTP 200. The single Q04 run exhausted the 18,000-token run limit after three captured responses; those responses and their usage remain in the report.

`C` means a complete graph-backed retrieval. `R` marks the deterministic offline projection replay. `E` means the query executed but returned no rows because the model shortened a campaign name. `I` means the compiler rejected an invalid generated pattern. `B` means the single-call generic bindings did not exactly fit the slots derived from its pattern. `M` is a model-run token-limit failure.

| Question | Oracle | Two-stage | Single |
| --- | --- | --- | --- |
| Q01 | C | C/R | C/R |
| Q02 | C | C/R | C/R |
| Q03 | C | I | I |
| Q04 | C | C/R | M |
| Q05 | C | I | C |
| Q06 | C | I | C |
| Q07 | C | I | I |
| Q08 | C | I | I |
| Q09 | E | E | E |
| Q10 | C | C | C |
| Q11 | C | C | C |
| Q12 | E | I | E |
| Q13 | E | I | E |
| Q14 | C | C | B |
| Q15 | C | C | B |
| Q16 | C | I | I |
| Q17 | C | I | I |
| Q18 | C | I | I |
| Q19 | C | C | I |
| Q20 | C | I | B |
| Q21 | C | C | I |
| Q22 | C | I | I |
| Q23 | C | I | I |
| Q24 | C | C | C |
| Q25 | C | C | C |

The oracle failures are useful because they isolate value binding. The binder copied `Steve Hilton`, `Yes on Proposition 38`, and `Ed Musgrove` instead of the stored campaign names `Steve Hilton campaign`, `Yes on Proposition 38 campaign`, and `Ed Musgrove campaign`. All three compiled and executed safely but returned no rows. Supplying the right graph shape did not solve entity naming.

The model chose strong, scoped patterns for direct lobbying, actor-to-policy paths, the article-title co-mention, one funded campaign target, and both referral directions. The compiler rejected 13 two-stage and 10 single-call patterns before execution. These records mostly contain malformed plans rather than missing compiler features: undeclared variables, duplicate claim names, wrong endpoint labels, invalid return fields, and bogus id constraints in place of a variable inequality. They remain `compiler_unsupported` in the frozen JSON because that was the runner's stage label. The more accurate interpretation is "generated pattern rejected by compiler."

The five execution errors revealed one compiler defect. Repeated Return Targets produced duplicate Cypher result columns. The compiler now deduplicates identical projections. The replay uses only each frozen raw pattern and frozen binding object, and all five then execute with the exact reference evidence sets. No model response was regenerated.

The single call's generic binding list caused three failures that the derived binder schema avoided. Q14 and Q15 added an undeclared `policy.name` binding. Q20 added node-name bindings that were not constraint slots. This is evidence for the value of a pattern-specific binding contract, though one run cannot isolate that cause from ordinary sampling variation.

The two-stage boundary was also porous. Pattern responses sometimes embedded concrete question values in slot descriptions despite the instruction to omit binding values. These values came from the question, not the hidden references, but they let pattern selection influence binding. The shortened campaign name in Q09 propagated through that overlap. A stricter representation would make slot descriptions compiler-authored from variable label, property, and operator.

The compiler can canonicalize endpoint order from the ontology only when one direction is possible. The pre-freeze interface smoke exercised this by converting the model's Bill-to-Organization `LOBBIED_FOR` endpoints to the stored Organization-to-Bill direction. No compiler-valid pattern in the frozen full batch needed reversal after the prompt explained this rule, so the main batch does not measure its practical recovery rate.

The experiment supports the basic split: once a valid pattern and exact bindings exist, the compiler produces read-only, evidence-bearing queries without freeform Cypher errors. Pattern construction is now the main failure point. The current model-facing structure is still too permissive around variable references, claim names, aggregates, and inequalities. Turning this prototype into a general graph query language would be the wrong next move. A narrower next test should constrain those fields with compiler-generated identifiers and add read-only candidate resolution for stored entity names.

This remains a graph-backed construction batch, not a formal Gold Set. Exact reference agreement measures retrieval against the current graph. It does not establish that every extracted political claim is true. The graph has known duplicate identities and extraction errors, and equivalent row grouping was accepted.
