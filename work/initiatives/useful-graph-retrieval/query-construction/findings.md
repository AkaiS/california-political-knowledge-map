# Query-construction findings across six experiments

**The 22/25 result measured filling values into a correct, supplied structure.
It did not measure selecting triples and then filling them.** The original
two-stage composable approach completed 8/25 in its frozen run and 11/25 after
a compiler-only replay. Generated Cypher with a critic completed 10/25.
These development results do not establish a winning production architecture.

All scores below concern the same 25 known-answerable development questions.
“Complete” requires the requested meaning, constraints, and Grounding Evidence;
a nonempty result or valid output schema is insufficient. The earlier
42-question exploratory runs remain in the [archive](reports/README.md), but
are not mixed into this comparison. These cases are not a held-out Gold Set,
and their graph facts were not independently verified as political truth.

## End-to-end question-to-answer attempts

| Approach | Complete answers | What the model had to decide |
| --- | --- | --- |
| Generated Cypher + critic | 10/25 after repair; 9/25 before repair | Write the query, then review and repair it |
| Fixed typed queries | 11/25 | Select supported query types and their arguments; one additional nonempty but underconstrained result is excluded |
| Composable triples, two stages | 8/25 frozen; 11/25 after compiler-only replay | Choose triples, joins, filters, and outputs; then bind values |
| Composable triples, one stage | 6/25 frozen; 8/25 after compiler-only replay | Produce structure and bindings together |
| Compiler-assigned pattern identifiers | 2/25 | Select catalog triples and compose their structure in one stage, then bind values |
| Separate selector, composer, binder | 2/25 | Select keyed pieces; compose deterministically when unique, otherwise use a model; then bind values |

The compiler replay reused saved model outputs; it was not another inference
run. See the [original verified comparison](comparison.md),
[composable comparison](composable-triples-comparison.md),
[identifier and resolution comparison](pattern-resolution-comparison.md), and
[selector/composer/binder comparison](selector-composer-binder-comparison.md).

## Controls and diagnostics: different tasks

| Condition | Result | What it establishes |
| --- | --- | --- |
| Original correct composable structure supplied; model fills values | 22/25 | Binding works well when planning is already correct |
| Identifier compiler supplied correct patterns | Same results as the 22/25 control across all 25 cases | The new compiler can represent the successful supplied structures |
| Correct structure supplied; literal binding versus entity resolution | 22/25 literal; 20/25 resolved | Candidate resolution recovered two Campaign cases but introduced four losses |
| Correct piece keys supplied to the separate composer diagnostic | 2/2 | The composer and binder handled these two ambiguous peer-query examples when selection was bypassed |
| Authored keyed-piece coverage check | 25/25 representable: 23 unique, 2 ambiguous | The interface can express the authored cases; this is not model selection accuracy |

The primary selector/composer/binder run made **zero composer model calls**.
Eight cases had a unique composition, sixteen failed selection or had no valid
composition, and one exceeded the composer option limit. Thus its 2/25 score
does not test model composition on correctly selected ambiguous inputs. The
separate 2/2 diagnostic must not be added to that score.

## What “pattern” meant, with three examples

A composable pattern is a graph structure: which typed relationships to use,
which endpoints are shared, which node to return, and which properties to
filter. Bindings supply names, dates, sessions, and other values afterward.
A catalog key identifies a reusable piece; it does not by itself identify a
complete question or decide how multiple pieces connect.

1. **Articles about a topic during a period.** The intended structure connects
   a NewsArticle to a Chunk, then through `DISCUSSES_TOPIC` to the Topic. Date
   filters constrain the article and a name filter constrains the Topic; the
   binder supplies the period and topic name. In the later keyed experiment,
   Q05/Q06 selected date/topic filters but omitted `DISCUSSES_TOPIC`. Valid keys
   alone could not produce the intended connected structure.
2. **Organizations on the same side of a Bill.** The pattern needs two lobbying
   relationship occurrences sharing one Bill, with separate anchor and peer
   Organizations, the named anchor filtered, and the peer returned. Values
   include the organization name, Bill name, and session. In the latest primary
   run, Q16/Q17 omitted necessary pieces. With correct keys supplied separately,
   the composer chose the peer-returning arrangement and both diagnostic cases
   returned the expected three peers with supporting evidence.
3. **Funding a named Campaign.** Structure identifies the Campaign being
   funded and the funding entity to return; binding identifies the particular
   Campaign. The resolver recovered Q09 by resolving a shortened Steve Hilton
   Campaign name to its stored identifier. In the separate keyed experiment,
   Q09 omitted the Campaign filter entirely and returned overbroad results.
   Resolving a name cannot repair a missing structural constraint.

Each later experiment's archived findings contains three worked examples:
[identifiers](reports/pattern-selection/findings.md),
[resolution](reports/entity-resolution/findings.md), and
[selector/composer/binder](reports/selector-composer-binder/findings.md).

## Findings by stage

**Selection and composition remain the main unresolved problem.** Original
plans invented references, repeated claim identifiers, and requested invalid
projections. Moving identifiers into the compiler addressed bookkeeping but
did not make the model choose the right relationships, output targets, or
constraints. The identifier experiment rejected eighteen plans; fifteen had
aggregate errors. Of seven executed queries, only two were complete.

**Separating stages did not yet improve selection.** All 25 keyed selector
outputs were schema-valid, but valid pieces were often incomplete or wrong.
Eight cases reached binding and execution; six were nonempty and only two
were complete. A unique composition of the wrong pieces is still wrong.
The supplied-key diagnostic is encouraging evidence about two downstream
cases, not evidence that the entire approach succeeds.

**Binding and resolution have their own failures.** The original supplied
patterns missed three Campaign names. Candidate lookup recovered two, but the
resolver's 20/25 result also included new failures involving wrong binding
slots, anchor/output confusion, and ambiguity. Bookkeeping belongs to both
interfaces: repeated structural node/claim identifiers arose in composition;
wrong binding-slot references arose during value filling or resolution.
Compiler-owned structural identifiers do not automatically fix the latter.

**These are not isolated causal comparisons.** The identifier experiment
changed the presentation from the full ontology to a shorter 29-triple catalog.
The later selector used 89 atomic pieces, including filters, outputs, and
operations, and changed date and composition constraints. Differences cannot
be attributed solely to assigning IDs or adding a third model stage. The
resolver comparison did share the initial binder response between its paired
arms and supplied correct structure to both.

## Disposition and preserved evidence

The independent identifier and resolver experiments both missed their
predeclared gates, so no combined identifier-plus-resolver experiment ran.
The subsequently requested selector/composer/binder experiment is a separate
attempt. No prototype is adopted into production by this aggregation.

The [archive index](reports/README.md) links all six implementations' source
commits, archived assessments, raw reports, and input snapshots. Its
[manifest](reports/manifest.json) records exact source blobs and checksums.
Prototype code remains on experiment branches and annotated tags. Active
comparison links point into this repository; absolute temporary paths inside
unchanged source snapshots are historical run metadata.
