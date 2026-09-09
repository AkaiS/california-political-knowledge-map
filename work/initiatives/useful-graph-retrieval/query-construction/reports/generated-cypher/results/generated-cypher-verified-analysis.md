# Generated Cypher on the 25 verified-answerable cases

This frozen throwaway run asks whether `gemma4:26b` can construct read-only
Cypher against the persisted News Ontology, and whether a same-model critic plus
one repair earns its cost. All 25 questions have verified graph retrievals, so
every case was instructed to attempt construction. Reference queries,
parameters, rows, evidence, family labels, and source ids were evaluator-only.

## Result

Manual comparison of requested entities, article sets, counts, and relevant
evidence found 10 complete final retrievals: Q01, Q02, Q04, Q05, Q06, Q07, Q09,
Q10, Q18, and Q25. Q17 retrieved the three expected peer organizations but did
not establish the named seed's participation and returned Neo4j internal ids
instead of stored evidence ids, so it is partial. The other 14 failed.

The 25 final outcomes divide into 11 cases with rows, six executed queries that
returned no rows, four repaired plans stopped by final validation, and four
queries that failed during execution. Q03, Q08, Q16, Q19, Q22, and Q23 are the
six true empty executions. Q12, Q13, Q20, and Q24 are the validation stops:
each has `repair.deterministic_errors` populated and no final execution latency.
Q11, Q14, Q15, and Q21 are the execution errors. These categories are disjoint.

The frozen JSON's summary value `empty_results: 10` is an instrumentation
mistake: its expression counts a final plan with no rows whenever no execution
or model-stage error was recorded, including the four plans validation prevented
from executing. The per-case records remain valid, so this audit corrects the
aggregate without changing or rerunning the raw report.

Q04 matched Proposition number `38` rather than the canonical name. It returned
the 20 reference chunks plus five chunks attached to an alias node named
`Prop. 38`; the extra chunks come from the same two source articles and also
explicitly discuss the current measure. This is useful alias expansion, with
duplicate graph identity still visible as a data-quality limitation.

The JSON's scalar and evidence overlap fields are inspection aids, not an
accuracy score. They compare alias-independent scalar sets, so they penalize
valid text-bearing output that does not use the reference aliases, cannot judge
whether prose supports a claim, and cannot safely classify Q04's alias
expansion. Full initial and final result rows are retained for independent
semantic review.

| Case | Final audit | Main observation |
| --- | --- | --- |
| Q01–Q02 | Complete | Entity reporting and evidence chunks match. |
| Q03 | Failed | Reversed `MENTIONED_IN`; critic accepted the empty query. |
| Q04 | Complete with alias caveat | Reference chunks plus five valid alias-node chunks from the same articles. |
| Q05 | Complete after repair | Critic caught invalid syntax and single-day scope; repair retrieved the July article set and chunks. |
| Q06 | Complete | Article and chunk set matches. |
| Q07 | Complete | All 26 per-area counts and article-id sets match. |
| Q08 | Failed | Used `industry_sector='LaborUnion'` instead of the `LaborUnion` sub-label; critic accepted it. |
| Q09–Q10 | Complete | Requested organizations and relationship evidence match; Q09 duplicates one claim row. |
| Q11 | Failed at execution | Treated string ids in `r.chunks` as objects; critic accepted it. |
| Q12–Q13 | Failed | Repairs kept missing or wrong seeds and invented relationship-to-node evidence traversal. |
| Q14–Q15 | Failed at execution | Repairs treated string provenance ids as objects and omitted topic-hop evidence. |
| Q16 | Failed | Did not anchor the named seed and filtered on nonexistent relationship properties. |
| Q17 | Partial | Expected peers, but no seed proof and no stored evidence ids. |
| Q18 | Complete | Co-mentioned organizations and shared Chunk ids match. |
| Q19 | Failed | Reversed `HAS_CHUNK`; critic accepted the empty query. |
| Q20 | Failed | Repair tried to traverse from a relationship as a node. |
| Q21 | Failed at execution | Treated string provenance ids as objects; critic accepted it. |
| Q22–Q23 | Failed | Matched unpopulated `last_name`; Q23 also returned event type instead of vote relationship type. |
| Q24 | Failed | Validator regex falsely parsed a list comprehension as relationships; critic followed that false premise and repair invented relationship-to-node traversal. The initial query still had its own string-as-object error. |
| Q25 | Complete | Committee entities and referral evidence ids match. |

## Critic and deterministic validation

The critic made 33 calls: 25 initial reviews and eight post-repair reviews. Every
initial critic rejection coincided with a deterministic rejection, so this run
contains no critic-only repair trigger. Of the eight repairs, Q05 is the only
complete rescue. Q12, Q13, Q20, and Q24 remained rejected at `EXPLAIN`; the
other repairs did not produce complete answers, and several invented edges from
relationship objects to Chunk nodes.

The critic missed clear errors in Q03, Q08, Q11, Q19, Q21, Q22, and Q23. These
include wrong edge direction, sub-label/property confusion, unpopulated
properties, and treating stored string ids as objects. It did not provide enough
independent checking to justify execution on its verdict alone.

Deterministic checks usefully caught missing parameters and obvious absence of
an evidence path, and Neo4j `EXPLAIN` caught syntax and relationship-as-node
errors. Their current regex also produced the Q24 false positive, cannot verify
edge direction or persisted property presence, and cannot catch string-as-object
errors that arise only when rows exist. Execution errors currently occur after
the bounded repair decision, so four such cases had no opportunity to repair.

## Cost and limits

The batch took 638.12 seconds. Initial generation used 91,609 tokens and 287.55
seconds; eight repairs added 32,440 tokens and 49.54 seconds. Initial criticism
used 90,518 tokens and 217.55 seconds; repaired-plan criticism added 30,803
tokens and 81.21 seconds. The critic therefore used 121,321 tokens and about
298.76 seconds for one complete rescue, close to the generator's 124,049 tokens
and 337.09 seconds.

This is evidence about one deterministic local-model run on a small populated
graph. The references are verified graph retrievals rather than independently
adjudicated political facts or a formal Gold Set. The generator and critic use
the same deployment, so their errors are correlated. The result supports
strengthening deterministic schema, property, and direction checks and
executing a safe baseline before choosing repair; it does not settle the
production retrieval architecture by itself.
