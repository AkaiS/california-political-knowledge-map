# Findings: Jev as a query-construction classifier

The latest experiment is the [preserved staged Jev implementation and aggregate
evaluation](../query-construction/experiments/jev-staged/README.md), completed on
2026-10-06. Removing the peer wording examples and replacing the reporting
keyword gate with a Jev intent Noul matched the dev control at schema .8 and
reached 15 of 25 exact held-out evidence sets, 80.94% evidence F1, and 71.02%
evidence recall. The comparison uses one run per configuration and a historical
control. Held-out review remained limited to aggregate metrics.

The chronology below records the earlier selector-only phase. The preserved
experiment now includes Jev schema narrowing and staged subtype/property
selection. It remains an experiment, with production retrieval unchanged.

Research supporting a possible follow-up to issue
[05](../issues/05-prototype-query-construction-and-validation.md). This note
compares TypeSafe AI's Jev API with the atomic semantic query-construction
prototype at commit `104d626`. It does not propose a production dependency.

The external claims below come from TypeSafe's documentation, source repository,
and launch material. The selector-only proposal was then tested against the
repository's frozen 25-question development set on 2026-09-15.

## Conclusion

Jev is now promising enough to justify a held-out and repeatability phase, but
not a production integration. The successful boundary keeps article hydration
in the compiler, asks peer-independent questions for concrete filters, and asks
Jev only about complete fragments that survive the local schema filter. The
fixed 0.52 cutoff was not retuned.

That design executed 24 of 25 development questions. Twenty-three cases had an
exact evidence set, semantic selection was exact for 22, and combined
node-and-evidence micro F1 reached 98.3%. The local-model baseline executed 19
cases and reached 94.3% combined F1. The gain cost more tokens and time: the new
run used 226,044 model tokens and 841.54 seconds, compared with 159,038 and
538.04 seconds for the baseline. Most of the added time came from the local
schema filter, not Jev.

The first two Jev formulations failed. Seventy-four independent occurrence
Choices executed only 3 of 25 cases because their individually valid answers
did not form one consistent plan. Unfiltered complete-fragment Nouls improved
structural validity but selected too many unrelated fragments. The chronological
experiments below preserve those negative results and show how schema pruning,
compiler-owned reporting context, and peer-independent filters changed the
outcome.

Before promotion, test fresh questions and repeated identical calls, reconcile
the output and reference contracts, prune the candidate long tail, and diagnose
schema-filter retries. Do not translate `PieceSelection`, `SemanticWiring`, or
`PositionalBindings` directly into Jev output contracts. They still require
variable-length lists, repeated occurrences, cross-field consistency, or open
strings that Jev does not return.

## What Jev is

Jev is TypeSafe AI's first "System One" model. A request supplies one `state`
and a map of typed questions. The service returns typed decisions rather than
generated text. TypeSafe positions it for classification, routing, scoring, and
other bounded decisions inside ordinary software
([introduction](https://docs.typesafe.ai/introduction),
[launch post](https://typesafe.ai/blog/introducing-system-one-models-and-jev)).

The HTTP interface is one endpoint:

```text
POST https://api.typesafe.ai/v1/systemone
Authorization: Bearer <API_KEY>
```

The request has three required fields:

- `state`: a string, JSON object, or array;
- `model`: currently `jev-latest`;
- `questions`: a map of caller-named questions.

The API has three output primitives:

| Primitive | Use | Returned decision |
| --- | --- | --- |
| `Choice` | One option from a caller-supplied set | winning option, probability for every option, confidence |
| `Score` | A position on an ordered rubric | probability-weighted score, level probabilities, confidence |
| `Noul` | A yes/no judgment | probability of yes from 0 to 1 |

All questions in one request see the same state. TypeSafe says it evaluates
them independently and in parallel. A caller may mix all three types in one
request. `Choice` accepts at most 255 options
([API reference](https://docs.typesafe.ai/api),
[Choice documentation](https://docs.typesafe.ai/primitives/choice),
[state documentation](https://docs.typesafe.ai/concepts/state)).

The question-map key is only a response correlation key. The model does not see
it. It does see Choice option names and descriptions. Semantic meaning therefore
belongs in the instructions and criteria, not in a terse question id.

The official Python package is `typesafe-sdk`. Its current source declares
version 0.6.0, Python 3.10 or newer, and an MIT license. The synchronous client
calls `client.system_one(...)` and reads `TYPESAFE_API_KEY` by default
([SDK README](https://github.com/typesafe-ai/typesafe-sdk-python),
[package metadata](https://github.com/typesafe-ai/typesafe-sdk-python/blob/main/pyproject.toml)).
Python 3.13 therefore falls within the declared range.

## Guarantees and limits

### What the type guarantee covers

Jev can only return one of the output shapes and options supplied by the caller.
That removes malformed JSON, invented enum values, and arbitrary prose from the
decision boundary. TypeSafe's launch material calls this "zero hallucinations,"
but its concrete technical claim is narrower: schema matching has zero type
errors. A valid option can still be the wrong option
([launch post](https://typesafe.ai/blog/introducing-system-one-models-and-jev)).

`Choice` and `Score` return full probability distributions. Their `confidence`
is computed from how concentrated that distribution is. It is not an observed
accuracy rate for this repository. TypeSafe explicitly recommends testing
confidence thresholds against application data
([confidence documentation](https://docs.typesafe.ai/confidence)). `Noul` has
no separate confidence field; its yes probability is the usable signal.

### What Jev cannot return

The published API has no primitive for:

- arbitrary generated text;
- an arbitrary scalar copied from the question;
- a variable-length list of selected values;
- a multiset in which the same option appears twice;
- a nested object such as a graph wiring plan;
- a dependency in which one question's answer controls another question in the
  same call.

The last point follows from the documented independent evaluation of questions.
Code may compose several answers after the call, or make another call, but one
Jev question cannot consume a sibling answer as hidden context.

These limits are a good match for TypeSafe's own design guidance: keep control
flow and deterministic rules in code, ask narrow atomic questions, and combine
answers in code
([building guide](https://docs.typesafe.ai/concepts/how-to-build-with-system-one)).

### Service boundary

This repository can run its current query-construction experiment against a
local llama.cpp deployment. Jev is a hosted bearer-token API, so adding it
creates a new provider and network dependency. The API documents `429` and
`529` responses and recommends exponential backoff; the official SDK handles
those responses with its default retry policy
([API errors](https://docs.typesafe.ai/api#errors)).

The SDK defaults to a 10-second timeout for each HTTP operation. Its default
retry policy makes two retries after the initial attempt, covers `408`, `429`,
all `5xx` responses, connection errors, and timeouts, and limits the whole SDK
call to a 30-second retry budget
([client defaults](https://github.com/typesafe-ai/typesafe-sdk-python/blob/main/src/typesafe_sdk/constants.py),
[retry policy](https://github.com/typesafe-ai/typesafe-sdk-python/blob/main/src/typesafe_sdk/_core/retry.py)).
Debug logging includes request and response bodies even though it redacts secret
headers, so a prototype must not enable it for user questions
([client source](https://github.com/typesafe-ai/typesafe-sdk-python/blob/main/src/typesafe_sdk/_core/client/sync/client.py)).

TypeSafe's privacy policy says it collects prompts, data, instructions, and
other input, does not train or fine-tune models on that input, and may disclose
input to service providers. It says the services are hosted in the United
States and retains personal data as long as reasonably necessary for service or
business purposes
([privacy policy](https://typesafe.ai/legal/privacy-policy)). A prototype should
send only the natural-language question and authored ontology descriptions, not
retrieved article text or user-identifying records.

TypeSafe launched Jev in early access on 2026-09-15. The vendor reports
$0.042 per million input tokens and 70 to 500 ms end-to-end latency from West
Coast tests. Treat those numbers as hypotheses for our benchmark, not planning
facts. The launch post says its workflow comparisons were authored by its model
capabilities team and may contain bias
([launch post](https://typesafe.ai/blog/introducing-system-one-models-and-jev)).

## Fit against `104d626` and the accepted `511eaeee` shape

Commit `104d626` separates query construction into four model stages, followed
by deterministic validation and execution:

1. semantic schema filtering;
2. semantic piece selection from a 74-entry catalog;
3. numeric wiring of the selected occurrences;
4. positional value binding.

Code then generates parameter names and Cypher, derives Grounding Evidence and
Source Articles, validates the query, executes it read-only, and hydrates the
result. That code-owned half should remain unchanged.

The frozen run made 137 model requests and used 159,038 tokens across 25 cases.
It executed 19 cases, returned nonempty results for 18, and stopped six before a
successful execution. Its findings identify semantic selection, repeated
occurrences, stray Article roles, wiring, and one value-binding failure as the
remaining problems. Those failures matter more than output syntax, which the
typed Pydantic contracts already control.

The accepted follow-up at `511eaeee` changes only Bill-name binding. It runs
every `Bill.name` value through the ingestion-side `parse_bill_designation`,
returns specific validation feedback, and retries the generative binder. It does
not change schema filtering, piece selection, composition, Cypher compilation,
or hydration. A Jev selector experiment should start from that accepted commit
so it retains the Bill Designation fix.

### Stage 1: semantic schema filter

Fit: possible, but not the first useful experiment.

The existing `SemanticSchemaSelection` returns lists of labels and
relationships plus a property map. Jev cannot return those lists directly.
It can answer many atomic questions in one request instead:

- one `Noul` per semantic relationship: "Does answering this question require
  traversing a recorded `LOBBIED_FOR` relationship?";
- one bounded `Choice` per entity label for required occurrence count:
  `none`, `one`, `two`, `three_or_more`;
- one `Noul` per filterable label/property pair.

This preserves the useful property of the current filter, which narrows the
later search space, while exposing probabilities for thresholding. The answers
are independent, so code must reject impossible combinations or use them as a
candidate set rather than an accepted plan.

More importantly, `104d626` does not enforce this stage's result. The selector
prompt includes the schema selection as context and then includes the complete
74-piece catalog. `_resolve_selection` validates the selector's ids and piece
kinds, but it never checks them against `SemanticSchemaSelection`. Replacing the
filter first would therefore optimize advisory prompt context rather than the
decision that reaches the compiler. Keep this stage unchanged in the first Jev
arm.

### Stage 2: semantic piece selector

Fit: strongest first experiment, with a different output contract.

The current selector returns five variable-length lists and may repeat a role or
relationship id. A single Jev `Choice` would select only one of the 74 pieces.
Seventy-four `Noul` questions could score membership of every piece in parallel,
but they cannot express that a peer query needs two occurrences of the same
Organization role and two occurrences of the same lobbying relationship. That
was already a named failure in the frozen run.

A direct list-for-list translation is a poor fit, but Jev can express the same
decision as 74 parallel occurrence-count classifications. Give every role,
relationship, and filter piece a `Choice` with `zero`, `one`, `two`, and
`three_or_more`. Distinct-role and aggregation pieces only need `zero` or `one`.
The state contains the natural-language question and the current schema-filter
output. Each Choice instruction must repeat the piece id and its full
description because Jev does not show the model the question-map key.

Normalize each winning count by repeating the piece id in the matching
`PieceSelection` list. Treat `three_or_more` as an explicit unsupported result
for the current development set rather than guessing a count. The existing
`_resolve_selection`, `validate_wiring`, compiler, and CyVer checks remain the
authority after normalization.

Keep the full probability vector for each piece. An ungated result measures raw
selector quality. A second analysis can abstain or fall back to the current
Pydantic AI selector when any required decision has low separation. That yields
a coverage-versus-accuracy curve instead of hiding uncertain selections behind
a valid object.

### Stage 3: semantic wiring composer

Fit: useful later, after code enumerates complete legal candidates.

Jev cannot emit the current arbitrary `SemanticWiring`, which contains lists of
indexed triples, filters, distinct-role constraints, and an optional aggregate.
It can choose one compiler-enumerated complete plan id from a bounded list. Each
option description should spell out the whole semantic plan because Jev sees the
option name and description but not the question-map key.

This is a cleaner boundary than asking any model to invent indexes. It also has
a hard ceiling: one Choice accepts 255 options. Code must prune by schema and
piece scores, split the choice hierarchically, or refuse cases above that limit.
Always include an explicit `none_of_these` option. A high-confidence selection
among incomplete candidates is still incomplete.

### Stage 4: positional binder

Fit: not a selector-arm change. It still needs generation unless code supplies
bounded candidates.

The current binder copies Bill names, organization names, sessions, titles, and
date boundaries from the question. Jev cannot return an arbitrary string. It
can select among graph-backed candidates when code supplies at most 255 options,
for example several full-text matches for "California Chamber of Commerce" plus
`none` and `ambiguous`. This could replace the model's entity resolution choice,
not its open extraction step.

Retain the `511eaeee` Bill Designation parser. Keep the existing model binder for
other open values until code can pre-extract or retrieve candidate values. Jev
could then select among graph-backed candidates, but that is a separate entity
resolution experiment.

## Executed selector-only experiment

The throwaway adapter is under `.scratch/jev-selector/` in the main checkout.
It starts from the `511eaeee` source so the accepted Bill Designation binding
fix is present. The durable result is this note; the complete report and raw
events remain disposable runtime artifacts:

- `.scratch/jev-selector/results/jev-selector-full-report.json`
- `.scratch/jev-selector/results/jev-selector-full-events.jsonl`

The adapter made one Jev request per case with 74 independent questions. Roles,
relationships, and filters used `zero`, `one`, `two`, or `three_or_more`.
Role constraints and aggregation pieces used `zero` or `one`. The adapter
expanded the winning counts into the existing `PieceSelection`, after which the
unchanged resolver and downstream stages remained authoritative.

A synthetic credential request succeeded against `jev-1.13.0`. A real
single-case smoke test also succeeded: C-E1-01 produced the two expected roles
and politician-name filter in 391 ms, compiled and executed, and returned the
exact expected nodes and evidence.

The full run rejected the approach:

| Outcome | Frozen `104d626` run | Jev selector arm |
| --- | ---: | ---: |
| Executed | 19/25 | 3/25 |
| Nonempty | 18/25 | 3/25 |
| Stopped before execution | 6/25 | 22/25 |
| Exact node/evidence sets | 2/25 | 3/25 |
| Selector failures | 2/25 | 16/25 |
| Composer/prebinding failures | 3/25 | 5/25 |
| Binder failures | 1/25 | 1/25 |
| Total runtime | 538.04 s | 270.91 s |
| Total model requests | 137 | 81 |
| Total model tokens | 159,038 | 673,767 |

The shorter total runtime is not an efficiency win. Most Jev cases stopped
before reaching the slower composer and binder.

At the selector stage alone, Jev made 25 requests instead of 42 correction-loop
requests and used 8.76 seconds of service latency instead of 179.29 seconds of
local-model latency. Its per-case latency was 230-683 ms, with 382 ms p50 and
435 ms p90. It used 532,151 input and 95,810 output tokens, 627,961 total. The
frozen selector used 91,954 total tokens. The 74-question formulation was 20
times faster in reported selector latency but consumed 6.8 times as many
selector tokens.

### Failure analysis

Jev returned all 74 typed answers for every case. There were no missing
question responses, unknown choice values, or malformed payloads. The problem
was semantic consistency:

- Thirteen selector failures contained a selected relationship or filter whose
  required role was absent. Common examples were a Prop-name filter for a
  named politician, a PAC relationship for a generic Organization question,
  and a LegislativeEvent-name filter when only a Bill session was named.
- Three selector failures chose `three_or_more` for a relationship occurrence.
  The questions ask for plural result rows, but the query pattern still needs
  one or two relationship occurrences. The independent classifier interpreted
  result cardinality as query-pattern cardinality.
- Five internally valid selections were still overcomplete. They reached the
  composer, then failed because extra roles or mutually redundant relationship
  alternatives could not form one connected plan using every selected piece.
- C-E2-01 reached binding but contained a spurious LegislativeEvent-name
  filter. The binder correctly failed because no LegislativeEvent value exists
  in the question.

The central mismatch is independence. A question about an Organization can
make the Organization, PAC, and LaborUnion variants each look individually
plausible. A direct relationship and its predicate-alternative relationship
can also each look plausible. Since sibling Jev questions do not compete or
observe each other's answers, type correctness does not produce a valid
multiset.

Confidence thresholding does not rescue the formulation. Wrong selected pieces
reached confidence 0.80-0.87, while required pieces in successful or otherwise
correct selections fell as low as 0.45. A threshold high enough to remove the
former would remove the latter. The distributions remain useful for diagnosis,
but they are not an integrity constraint.

### Revised integration boundary

Do not add the 74-question adapter to production or to the repository's general
model abstraction. If another Jev experiment is justified, move the boundary
one level up:

1. Code uses the ontology and schema-filter result to enumerate complete legal
   query plans or stable query families.
2. Code rejects disconnected or otherwise invalid candidates before inference.
3. One Jev `Choice` selects among the mutually exclusive complete candidates,
   including an explicit `none_of_these` option.
4. Code instantiates the selected plan, retains deterministic compilation and
   hydration, and keeps the existing binder for open values.

This makes the options compete and ensures every returned option is already a
valid shape. It also matches the product hypothesis more directly: the model
classifies what kind of Cypher code should generate. The 255-option limit must
remain an explicit refusal or pruning boundary, never silent truncation.

## Experiment design

The test used a throwaway Jev adapter next to the preserved prototype. It did
not put the TypeSafe SDK behind the repository's general chat-model abstraction.
Jev is a decision service with different contracts, so the adapter returns local
domain types and keeps `Choice`, `Noul`, and vendor response objects at the edge.

The first arm ran against the same 25 questions and frozen references used by
`104d626`, starting from the accepted `511eaeee` code.

### First arm: selector only (executed)

The arm kept the current schema-filter call and replaced the Pydantic AI
selector call with one Jev request containing one occurrence-count Choice for
each catalog piece. It normalized the 74 answers into `PieceSelection`, then ran
the current composer, deterministic unique-wiring fallback, positional binder,
compiler, validators, execution, and scorer without semantic changes.

This arm made one provider call per case instead of the selector's one to three
correction calls. It left later generative stages in place, so any changed
retrieval outcome can be traced first to the normalized selection and then to
how the unchanged composer handled it.

### Later arm: enumerated plan choice

If more work is justified, make code enumerate complete valid plans from the
ontology and narrowed schema, then give Jev one Choice over those complete
plans. This may replace both independent piece selection and numeric composition;
do not ask Jev to reproduce `SemanticWiring` fields. Keep binding unchanged
again. The 255-option limit must cause explicit pruning, hierarchical choice, or
failure rather than silent truncation.

### Evaluation

Preserve the existing contamination boundary: reference queries and expected
results load only after inference and execution. Report at least:

- end-to-end node, relationship, and Grounding Evidence recall and precision;
- full-recall and exact-set case counts;
- exact selection rate, required-piece recall, and unnecessary-piece rate;
- candidate-plan count before and after deterministic pruning;
- failure stage, including `unsupported_or_ambiguous` and more than 255 plans;
- selective accuracy as the confidence threshold rises, with coverage shown
  alongside it;
- input tokens, API calls, latency, retries, and cost;
- drift across repeated identical calls;
- local-model fallback behavior for network, authorization, rate-limit, and
  overload failures.

The 25 questions are development examples. A positive result should be checked
on fresh paraphrases and negative controls before changing the architecture.

### Access and authorization

The API key was read from the macOS keychain entry with service `jev_api` and
account `test_key`; it was not written to the repository or report. The user
explicitly authorized sending the experiment questions, schema-filter outputs,
and semantic-piece catalog to the Jev API. No retrieved article text, graph
rows, or reference answers were sent.

## Decision boundary

The selector prototype was worth running because occurrence counting looked
like a closed semantic decision. The result shows that 74 separately closed
decisions do not make one coherent query plan. Jev's probabilities make the
failure visible, but they did not provide a usable abstention boundary on this
development set.

It does not change the accepted architecture from issue 05. The model should
still never write Cypher. Code should continue to own legal graph shapes,
Grounding Evidence traversal, Source Article lookup, result hydration, and
validation. Jev should earn a narrower role by beating the current classifier
stages on retrieval quality at useful coverage, not by meeting its output type.
The next credible test is competitive selection among complete legal plans,
not another independent per-piece membership pass.

## Scored-Noul constrained-selection follow-up

A second throwaway prototype now exists under `.scratch/jev-noul-selector/`.
It tests the alternative proposed after the first run:

- request state has only `question` and one general selection rule;
- each of the 74 catalog pieces has one `Noul` with the piece's complete public
  structure, description, and kind-specific decision rules;
- code reads the yes probabilities as scores rather than accepting every yes;
- a deterministic search chooses a sparse legal pattern with zero, one, or two
  semantic hops, or a shared-reporting-context role set;
- relationship endpoints and filters require their roles, semantic edges must
  connect, and overlapping direct and predicate-alternative relationships
  cannot coexist;
- a distinct-role score can select a repeated one-hop pattern. Code then emits
  the repeated role and relationship occurrences required by `PieceSelection`.

The local checks passed. They verify all 74 descriptions are present, the
state has no schema-filter labels or relationships, the lobbying predicate
union beats its overlapping direct variants, and an "other organizations"
shape expands to two Organization roles and two occurrences of the selected
relationship. The resulting selections pass the catalog's endpoint, filter,
date-range, aggregation, connectivity, and competing-variant checks.

The first attempt to run the live subset was blocked before process creation
because the external execution approval did not accept the ontology catalog as
authorized data. After the user explicitly authorized sending the 74 internal
component descriptions, the six planned cases ran against `jev-1.13.0`:

| Metric | Six-case subset |
| --- | ---: |
| Jev requests | 6 |
| Questions per request | 74 `Noul`s |
| Structurally valid after constrained selection | 6/6 |
| Structurally valid at raw 0.5 threshold | 2/6 |
| Semantically exact selections | 2/6 |
| Required-piece recall | 85.3% |
| Selected-piece precision | 80.6% |
| Piece F1 | 82.9% |
| Input tokens | 85,583 |
| Output tokens | 11,718 |
| Total tokens | 97,301 |
| Summed API latency | 1,401.7 ms |
| Per-request latency | 168.5-447.5 ms, 188.3 ms median |

The semantic audit counted repeated occurrences and compared each result with
the minimal catalog selection implied by its question. Q14, the two-hop
lobbying-to-policy-area case, and Q19, the shared-reporting-context case, were
exact. Four failures remained:

- Q01 selected only NewsArticle. It omitted the Steve Hilton Politician role
  and name filter. Jev scored the Politician role at 0.17 even though it scored
  that role's name filter at 0.61.
- Q07 selected all required counting pieces, then added a Prop role and
  `Prop -ABOUT_TOPIC-> PolicyArea`. Jev scored the unrelated relationship at
  0.88.
- Q16 missed the two Organization occurrences, two lobbying-relationship
  occurrences, and distinct-role constraint required by "other organizations."
  It instead added a LegislativeEvent path and name filter. The distinct-role
  score was 0.74, but the nonexistent LegislativeEvent name filter scored 0.86.
- Q22 selected every required piece and added a LegislativeEvent name filter
  even though the question names no event. That filter scored 0.89.

The sparsity preference is not a clean repair. Testing the saved scores from
0.0 through 2.0 raised the best exact count only to 3/6. At sparsity 1.0 the
piece F1 reached 89.2%, but Q01 still lost the named politician, Q16 still lost
the repeated peer pattern, and Q22 retained the invented event filter. Tuning
the penalty on six development cases would also overfit the gate.

Verdict: using probabilities plus code-owned constraints fixes structural
integrity, not semantic selection. It is better than independently accepting
the 74 answers, but 2/6 exact is not promising enough to spend another 19 API
calls or run the downstream local-model and Neo4j stages. Stop this arm. A
future test needs dependencies inside the model decision, or a smaller staged
candidate set, rather than more post-hoc score tuning.

## Complete semantic-fragment follow-up

The next throwaway prototype is under
`.scratch/jev-semantic-fragment-selector/`. It removes the catalog's internal
`kind` and `piece_id` fields from Jev's input. Each relationship `Noul` instead
shows its source entity, predicate meaning, and target entity as one graph
fragment. Code supplies those endpoint roles when the fragment is selected.
Filter fragments include their entity role. The count fragment includes the
`NewsArticle -DISCUSSES_TOPIC-> PolicyArea` graph that it aggregates.
Entity-only fragments cover roles joined through automatic reporting context.

The catalog has 137 fragments because every relationship also has general
source-peer and target-peer variants. Those variants describe both repeated
relationship occurrences and the distinct-entity constraint. This keeps the
Q16 "other organizations alongside" choice inside one model decision instead
of asking independently for roles, a relationship, and distinctness. The state
still has only the question and general selection guidance. Deterministic
checks passed for the request boundary, absence of internal catalog fields,
endpoint implication, peer occurrence expansion, and complete aggregation.

The same six-case live subset produced:

| Metric | Complete fragments | Prior scored pieces |
| --- | ---: | ---: |
| Questions per request | 137 `Noul`s | 74 `Noul`s |
| Semantically exact selections | 1/6 | 2/6 |
| Occurrence precision | 37.5% | 80.6% |
| Occurrence recall | 85.7% | 85.3% |
| Occurrence F1 | 52.2% | 82.9% |
| Input tokens | 169,829 | 85,583 |
| Output tokens | 16,464 | 11,718 |
| Total tokens | 186,293 | 97,301 |
| Summed API latency | 1,930.8 ms | 1,401.7 ms |
| Median API latency | 286.0 ms | 188.3 ms |

These metrics cover the complete scored run. An earlier runner attempt made
four additional requests through Q16, then hit the old `PieceSelection` size
cap while recording Q16's over-selection. That attempt did not retain usage
data, so its tokens and latency are not included above. The corrected runner
records each response before continuing and scores over-sized selections as
failures instead of crashing.

Q14 was exact. Complete relationship fragments plus local competition chose
the predicate-alternative lobbying path and the Bill-to-PolicyArea path. The
other five cases failed:

- Q01 again selected only NewsArticle. The complete Politician name-anchor
  fragment scored 0.25 despite "Steve Hilton" in the question.
- Q07 again added `Prop -ABOUT_TOPIC-> PolicyArea`; that unrelated complete
  fragment scored 0.81.
- Q16 recognized the peer shape. Both the correct LOBBIED_FOR peer fragment and
  its broader predicate-alternative version scored 0.91. It also selected 12
  unrelated fragments, including Campaign, PAC, Prop, and LegislativeEvent
  peer patterns, while the Walt Disney Organization name anchor scored 0.47.
- Q19 contained every required occurrence but added a Prop name anchor and a
  repeated `Prop -ABOUT_TOPIC-> PolicyArea` fragment. The prior arm was exact
  on this case.
- Q22 contained every required occurrence but retained the invented
  LegislativeEvent name filter and added two Politician stance paths.

Sweeping fixed thresholds from 0.00 through 0.95 never exceeded 1/6 exact.
The best micro F1 was 59.8% at thresholds 0.54 through 0.60, with 46.8%
precision and 82.9% recall. Threshold tuning cannot repair the failure mode.

Verdict: complete fragments solve the dependency objection in the request
shape, and they let Jev recognize Q16's repeated peer structure. They do not
make independent `Noul` membership judgments selective. False complete
patterns now expand into several false piece occurrences, which cuts precision
and nearly doubles token use. Do not run the remaining 19 cases or the
downstream local-model and Neo4j pipeline. If this direction continues, first
reduce the candidate set with a separate retrieval or staged decision and then
compare a few complete legal plans, rather than asking 137 independent
membership questions.

## Schema-filtered complete-fragment follow-up

The staged version is under `.scratch/jev-filtered-fragment-selector/`. It
reuses the frozen `SemanticSchemaSelection` outputs from the accepted atomic
report for Q01, Q07, Q14, Q16, Q19, and Q22. It does not rerun the local filter
model. Code normalizes each result into a query-specific semantic subgraph and
then generates only compatible complete fragments.

Pruning follows three rules. Relationship fragments need both selected endpoint
labels and every predicate in the fragment. A predicate-family union survives
only when the schema filter selected the whole family, while the family members
remain competing alternatives. `NewsArticle` permits entity-only reporting
context without inventing an ontology relationship to the article. Every
surviving relationship keeps single, repeated-source, and repeated-target
variants, so Q16's peer option still implies two Organization roles, two
relationship occurrences, and distinctness.

The resulting candidate counts were 6 for Q01, 10 for Q07, 19 for Q14, 8 for
Q16, 8 for Q19, and 26 for Q22. The deterministic checks cover those counts,
the frozen-output boundary, absence of internal `kind` and `piece_id` fields,
endpoint compatibility, and Q16 peer expansion.

At the untuned 0.50 cutoff, the live six-case subset produced:

| Metric | Filtered fragments | 74 scored pieces | 137 unfiltered fragments |
| --- | ---: | ---: | ---: |
| Semantically exact | 3/6 | 2/6 | 1/6 |
| Occurrence precision | 94.3% | 80.6% | 37.5% |
| Occurrence recall | 94.3% | 85.3% | 85.7% |
| Occurrence F1 | 94.3% | 82.9% | 52.2% |
| Total tokens | 19,655 | 97,301 | 186,293 |
| Median API latency | 122.8 ms | 188.3 ms | 286.0 ms |

Q07, Q14, and Q19 were exact. Q01 missed only the NewsArticle role, scored
0.46. Q16 selected the complete repeated-peer pattern but missed Walt Disney's
Organization name anchor, scored 0.44. Q22 had every required occurrence and
added the NewsArticle context and a nonexistent LegislativeEvent name anchor,
both scored 0.51.

A fixed-threshold replay over the saved scores reaches 4/6 exact at 0.52. It
removes both Q22 extras without losing any required occurrence, yielding 100%
precision, 94.3% recall, and 97.1% F1. Q01 and Q16 still miss the two low-scored
occurrences above. This clears the development gate, but the one-hundredth
margin is fragile and comes from the same six cases.

Verdict: schema filtering changed this from a rejected arm into a promising
selector experiment. It cut tokens by 80% versus the 74-piece arm and 89%
versus unfiltered fragments while improving exactness and occurrence quality.
Do not claim a win yet. The attempted 25-case run was blocked before execution
because the larger external payload needs explicit authorization. No additional
Jev requests, local-model calls, or Neo4j executions occurred. Freeze 0.52 and
run all 25 only after that authorization, then judge the threshold on the full
set rather than retuning it.

### Authorized 25-case check

The user later authorized all 25 questions, frozen schema-filter outputs, and
pruned fragment descriptions. The full selector-only run used the frozen 0.52
cutoff without retuning:

| Metric | Full filtered run |
| --- | ---: |
| Semantically exact | 15/25 |
| Occurrence precision | 96.9% |
| Occurrence recall | 92.5% |
| Occurrence F1 | 94.6% |
| Candidate fragments | 267 total, 10.68 mean, 8 median, 2-26 range |
| Input tokens | 63,472 |
| Output tokens | 5,440 |
| Total tokens | 68,912 |
| Summed API latency | 3,370.1 ms |
| Median API latency | 131.5 ms |
| API latency range | 92.2-339.7 ms |

The full run averaged 2,756 tokens per case. The prior 74-piece subset averaged
16,217, and the 137-fragment subset averaged 31,049. The comparison is not a
same-size full-run comparison, but the per-case gap matches the candidate
reduction. The earlier 74-question full selector used 627,961 tokens across 25
cases and stopped 16 cases at selection. The filtered arm used 89% fewer
selector tokens and always returned a structurally complete normalized
selection.

The six gate cases inside the new run reached 3/6 exact, 97.1% precision, 94.3%
recall, and 95.7% F1 with the same 19,655 tokens. This did not reproduce the
4/6 saved-score replay. Q22's nonexistent LegislativeEvent name anchor moved
from 0.51 in the first call to 0.53 in the full run and crossed the frozen 0.52
cutoff. The cutoff remains fixed; this is call-to-call drift, not a reason to
retune it.

The ten non-exact cases fall into five concrete patterns:

- Q01 and Q03 scored an available NewsArticle reporting-context role below the
  cutoff. Q04 and Q18 could not recover that role because the frozen schema
  filter omitted NewsArticle, so hard pruning made the correct selection
  unreachable.
- Q05 and Q06 selected the PolicyArea relationship and name anchor but missed
  both July date-bound filters. The lower-bound scores were 0.33 and 0.32; both
  upper-bound scores were 0.09.
- Q16 and Q17 selected the complete repeated-Organization peer pattern, Bill
  name, and session, but missed the named anchor Organization at 0.44 and 0.43.
- Q13 added a Campaign-to-Politician path and Politician name anchor for "Ed
  Musgrove campaign." The path is plausible but unnecessary because the
  Campaign name anchor alone identifies the requested campaign.
- Q22 added a LegislativeEvent name anchor even though the question gives no
  event name. Q23, its paired question with the same shape, was exact.

Fifteen cases were exact: Q02, Q07-Q12, Q14-Q15, Q19-Q21, and Q23-Q25. The
small candidate set eliminated the broad unrelated-pattern failures from the
137-fragment arm. What remains is narrower: reporting context, temporal-bound
recognition, named peer anchors, one redundant semantic path, and one invented
filter.

Verdict: schema-filtered complete fragments are the first Jev arm worth
continuing, but 15/25 exact is not ready to replace the selector. Hard pruning
also makes upstream schema omissions unrecoverable. Before any downstream or
Neo4j run, test deterministic inclusion for required reporting context and
date-bound fragment packaging, then check repeatability around the decision
cutoff. Keep the 0.52 result as reported and do not tune it on these 25 cases.

### Anchor-specific peer-filter wording

Q16 and Q17 originally scored their named Organization filters at 0.44 and
0.43. The generic filter fragment said only that "one Organization" had a name
condition, so it did not identify that role as the fixed anchor while returned
peer Organizations remained unrestricted.

The prototype now specializes a name-filter prompt whenever its entity is the
repeated side of an available peer relationship. It asks whether the query
fixes the anchor entity by name, says that the named entity is the reference
point, and explicitly leaves peer entities unrestricted. The rule derives from
the peer fragment's repeated endpoint; it does not mention either case or name.

In the authorized two-case rerun, the Organization-name scores rose to 0.93 for
Q16 and 0.94 for Q17, and both filters crossed the frozen 0.52 cutoff. The peer
relationship scores remained 0.92 and 0.93. However, the Bill-name scores moved
from 0.92 and 0.91 in the prior run to 0.38 and 0.42. Both cases therefore
remained one required occurrence short, now missing the Bill-name filter rather
than the Organization-name filter. Each retained 100% precision, 88.9% recall,
and 94.1% F1.

This supports the role-ambiguity diagnosis for the Organization anchor, but it
does not establish an end-to-end improvement. The unrelated Bill-name movement
also reinforces the observed call-to-call instability. A controlled follow-up
would include generic and anchor-specific Organization questions in the same
request rather than comparing scores from different calls.

That controlled paired test then ran for Q16 and Q17. Each case used one state
and one Jev request containing exactly two `Noul`s: the original generic
Organization-name fragment and the anchor-specific version. No Bill-name or
other fragment question was present. Q16 scored the generic wording at 0.48 and
the anchor-specific wording at 0.94, a +0.46 change. Q17 scored 0.38 and 0.93,
a +0.55 change. The same-call comparison confirms that explicitly assigning the
name condition to the fixed anchor while leaving peers unrestricted materially
improves this decision. The separate Bill-name score movement from the earlier
end-to-end rerun is not evidence about this wording change.

## Full end-to-end evaluation

The full 25-question evaluation used the live local schema filter, not the
frozen outputs from the selector experiments. It then generated the pruned
complete-fragment set, applied the anchor-specific peer wording, fixed the
cutoff at 0.52, and ran the existing composer, compiler, CyVer checks, binder,
Neo4j query, deterministic hydration, and reference scorer. References remained
unavailable until after every query executed.

Twenty-three questions reached Neo4j and returned rows. Q05 and Q06 stopped at
the binder. Five questions matched the complete expected node and evidence
sets: Q01, Q02, Q03, Q04, and Q07. The other 18 executed questions all
over-returned. None under-returned.

| Returned set | Expected | Returned | Overlap | Micro precision | Micro recall | Micro F1 | Micro Jaccard | Macro precision | Macro recall | Macro F1 | Macro Jaccard |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Nodes | 203 | 404 | 188 | 46.5% | 92.6% | 61.9% | 44.9% | 46.7% | 92.0% | 55.3% | 46.7% |
| Evidence chunks | 654 | 455 | 204 | 44.8% | 31.2% | 36.8% | 22.5% | 58.4% | 92.0% | 63.5% | 58.4% |
| Nodes and evidence | 857 | 859 | 392 | 45.6% | 45.7% | 45.7% | 29.6% | 49.5% | 92.0% | 57.4% | 49.5% |
| Explicit relationship values | 10 | 30 | 10 | 33.3% | 100.0% | 50.0% | 33.3% | 64.0% | 100.0% | 65.9% | 64.0% |

The evidence count needs one qualification. Q05 and Q06 account for all 450
missing evidence chunks because neither query executed. Across the remaining
23 questions, the pipeline retrieved all 204 expected chunks, plus 251 extra
chunks. Executed-case evidence recall was therefore 100%, while precision was
44.8%. Twelve of 25 questions had an exact evidence set: Q01-Q04, Q07,
Q16-Q19, Q21, Q24, and Q25.

The primary failure is missing question-value filters, not relationship-family
selection. Q08-Q15 and Q20-Q25 usually selected the right path but omitted the
named Bill, campaign, organization, politician, or committee filter. Typical
required name-filter scores were 0.13 to 0.21, far below 0.52. For example, the
Bill-name score was 0.13 on Q10, the Campaign-name score was 0.17 on Q12, the
Organization-name score was 0.21 on Q14, and both the Bill and Politician names
were below 0.20 on Q22. The resulting queries matched the intended path across
many unrelated entities.

Q05 and Q06 show the same problem more sharply. Jev selected the
`NewsArticle -DISCUSSES_TOPIC-> PolicyArea` fragment but omitted the PolicyArea
name and both July date bounds. The compiler correctly produced a zero-slot
binding contract, while the binder kept returning values from the question and
failed validation three times. Q16 and Q17 did select the anchor Organization
after the wording change and retrieved the exact evidence chunks, but the
deterministic output includes the anchor Organization and its article. Those
values are extra under the current references. Q18 and Q19 have the same output
shape issue for the anchor Politician.

The live candidate count remained 267 total, with a median of 8 and a range of
2 to 26. Jev used 69,948 selector tokens across 25 requests. Selector latency
was 5.76 seconds summed, 224.9 ms median, and 181.1 to 326.4 ms per request.
The whole pipeline used 124 requests, 124,254 tokens, and 355.65 seconds. The
prior local-model selector report used 137 requests, 159,038 tokens, and 538.04
seconds, but achieved much stronger combined micro precision and F1 at 97.2%
and 94.3%. Jev made this run cheaper and more likely to execute, but the current
filter decision design made retrieval substantially less precise.

Verdict: the complete-fragment relationship decisions are good enough to keep
testing, and the peer-anchor wording worked. Independent generic condition
Nouls are not. The next experiment should make explicit question values and
their owning entity roles part of the fragment meaning, or derive those filters
deterministically before Jev selects relationship structure. Lowering the
global cutoff would add many unrelated condition fragments and does not address
the role ambiguity.

## Peer-independent filter experiment

The next six-case experiment removed anchor and peer language from every filter
question. Each Noul now asks only whether the question constrains a concrete
`Label.property`. A calendar window asks separately for the inclusive lower
and exclusive upper publication-date bounds. Filter-to-role attachment happens
after fragment selection. A unique label attaches directly; a repeated-label
identity filter attaches to the anchor while peers remain unrestricted.

The cases were Q05, Q10, Q12, Q14, Q22, and Q24. None was exact in the prior
end-to-end run. The revised selector chose the exact expected filter set and the
exact expected relationship set on all six:

| Case | Recovered filters | Revised scores |
| --- | --- | --- |
| Q05 | PolicyArea name, publication lower bound, publication upper bound | 0.88, 0.96, 0.94 |
| Q10 | Bill name, Bill session | 0.97, 0.97 |
| Q12 | Campaign name | 0.97 |
| Q14 | Organization name | 0.98 |
| Q22 | Bill name, Bill session, Politician name | 0.98, 0.96, 0.98 |
| Q24 | Bill session, Committee name | 0.98, 0.97 |

Five cases reached Neo4j. Each retrieved its full expected evidence set with no
extra chunks, 273 of 273 in total. Each also returned one extra node because
the deterministic output includes a filter anchor or source article omitted by
the current reference. Q22 stopped during composition because the independent
NewsArticle context fragment scored 0.54 and added a disconnected NewsArticle
role. Its filters and two semantic relationships were nevertheless exact. That
failure is separate from the filter change.

Across all six, combined micro precision, recall, F1, and Jaccard improved from
20.4%, 16.1%, 18.0%, and 9.9% to 98.3%, 98.7%, 98.5%, and 97.0%. The aggregate
still counts Q22 as a total miss. Evidence exactness improved from 1/6 to 5/6.

Verdict: this is the right filter formulation. It recovered every expected
condition in the six cases without adding a false condition. The next separate
problem is entity-only reporting context. It should not become a disconnected
semantic role when deterministic reporting hydration already supplies it.

## Compiler-owned article integration

The scratch end-to-end harness now combines three changes that had previously
lived on separate experiment branches: the Bill designation binder fix, the
peer-independent filter questions, and the compiler-owned article boundary.
`NewsArticle` is no longer a schema-filter label or selectable role. Article
topic relationships, title and date filters, and article counts retain
article-named operation IDs. Resolving any of those operations inserts one
internal article role before composition. The complete-fragment generator does
not emit `CONTEXT__NEWSARTICLE`, and article operations do not imply a
model-selected article role.

Reporting-only lookups remain legal through the compiler's shared-context
hydration. Other relationship-free plans fail closed. The reporting gate only
accepts explicit mention or attachment wording and explicit same-reporting-
chunk co-occurrence wording. This keeps a missed claim relationship from
silently becoming a weaker co-occurrence query.

The harness also records semantic-selection exactness after execution. It loads
the semantic oracle at the same post-execution boundary as retrieval
references. Jev telemetry now includes the returned model, per-case and total
candidate counts, requests, tokens, latency, retry availability, and every
decision within 0.05 of the fixed 0.52 threshold. The raw JSONL remains
oracle-free because each event is written before either scorer loads its
references.

The focused suite uses invented entities and wording. It covers a two-hop claim
shape with no selectable article context, reporting-only lookup, article
title/date/topic/count role insertion, rejection of an unrelated
relationship-free plan, peer-independent filter attachment, and a scan for
evaluation-specific hooks. The implementation contains no case IDs, named
evaluation entities, or reference answers.

Local verification passed:

```console
UV_CACHE_DIR=.scratch/uv-cache uv run --with typesafe-sdk --with keyring \
  --with cyver==2.0.2 pytest -q \
  .scratch/jev-selector/test_compiler_owned_article_boundary.py
# 8 passed

uv run ruff check \
  .scratch/jev-filtered-fragment-selector/filtered_fragments.py \
  .scratch/jev-semantic-fragment-selector/fragment_selector.py \
  .scratch/jev-selector/test_compiler_owned_article_boundary.py \
  .scratch/jev-selector/src/knowledge_map/prototypes/atomic_deterministic_hydration/catalog.py \
  .scratch/jev-selector/src/knowledge_map/prototypes/atomic_deterministic_hydration/contracts.py \
  .scratch/jev-selector/src/knowledge_map/prototypes/atomic_deterministic_hydration/compiler.py \
  .scratch/jev-selector/src/knowledge_map/prototypes/atomic_deterministic_hydration/runner.py
# All checks passed

UV_CACHE_DIR=.scratch/uv-cache uv run --offline --with typesafe-sdk \
  --with keyring python .scratch/jev-filtered-fragment-selector/run.py --synthetic
# synthetic checks passed
```

The live TypeSafe documentation was checked before the hosted calls. The Python
SDK exposes System One through `TypeSafeClient.system_one`; a Noul result's
`noul` field is the probability of yes, so the prototype continues to compare
that field directly with the frozen cutoff. The local llama.cpp endpoint and
Neo4j both passed reachability checks.

After explicit approval to transmit the questions, live schema-filter outputs,
and pruned fragment descriptions, the three-case smoke ran through the full
pipeline. No article text, graph rows, reference answers, or credentials were
sent to TypeSafe. All three cases executed and returned rows. Semantic
selection was exact on all three (15 of 15 required occurrences, no extras),
and all 245 expected evidence chunks were returned with no extras. The combined
node-and-evidence score was 99.2% precision, 100% recall, and 99.6% F1. The
remaining two extra nodes were deterministic output/reference-shape
differences. In particular, Q22 selected the two connected relationship
fragments and three filters without a standalone article role, executed, and
returned its one expected evidence chunk exactly.

```console
PYTHONPATH=.scratch/jev-selector/src:.scratch/jev-semantic-fragment-selector:\
.scratch/jev-filtered-fragment-selector UV_CACHE_DIR=.scratch/uv-cache \
uv run --with typesafe-sdk --with keyring --with cyver==2.0.2 \
  python .scratch/jev-selector/run_jev.py --selector jev-filtered \
  --case Q22 --case Q01 --case Q05 \
  --output .scratch/jev-selector/results/jev-compiler-owned-smoke-report.json \
  --raw-events .scratch/jev-selector/results/jev-compiler-owned-smoke-events.jsonl
```

The preflight therefore passed and the fresh 25-case run proceeded. Twenty-four
questions reached Neo4j and returned rows. One stopped during composition after
Jev added a disconnected Proposition path to an otherwise complete Campaign
plan. Five questions exactly matched the complete expected node and evidence
sets. Twenty-three had exact evidence sets. Across all 24 executed questions,
evidence recall was 100%; the only evidence errors in the aggregate were the
one expected chunk for the stopped question and one extra chunk from an
over-selected path on Q13.

```console
PYTHONPATH=.scratch/jev-selector/src:.scratch/jev-semantic-fragment-selector:\
.scratch/jev-filtered-fragment-selector UV_CACHE_DIR=.scratch/uv-cache \
uv run --with typesafe-sdk --with keyring --with cyver==2.0.2 \
  python .scratch/jev-selector/run_jev.py --selector jev-filtered \
  --output .scratch/jev-selector/results/jev-compiler-owned-full-report.json \
  --raw-events .scratch/jev-selector/results/jev-compiler-owned-full-events.jsonl
```

| Returned set | Expected | Returned | Overlap | Micro precision | Micro recall | Micro F1 | Micro Jaccard | Macro precision | Macro recall | Macro F1 | Macro Jaccard |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Nodes | 203 | 227 | 201 | 88.5% | 99.0% | 93.5% | 87.8% | 73.5% | 96.0% | 82.3% | 73.5% |
| Evidence chunks | 654 | 654 | 653 | 99.8% | 99.8% | 99.8% | 99.7% | 94.0% | 96.0% | 94.7% | 94.0% |
| Nodes and evidence | 857 | 881 | 854 | 96.9% | 99.6% | 98.3% | 96.6% | 80.5% | 96.0% | 86.9% | 80.5% |
| Explicit relationship values | 10 | 25 | 9 | 36.0% | 90.0% | 51.4% | 34.6% | 54.0% | 96.0% | 56.0% | 54.0% |

Semantic selection was exact for 22 of 25 questions. It selected 132
occurrences, of which 123 of the 124 required occurrences overlapped: 93.2%
precision, 99.2% recall, and 96.1% F1. The three misses were localized:

- Q12 added a disconnected PAC/Proposition path and stopped during composition.
- Q13 added an unnecessary Organization-to-Campaign-to-Politician path. It
  still returned the expected chunk plus one extra.
- Q16 missed the Organization-name condition at 0.50, just below the fixed
  0.52 threshold. Q17's paired condition landed exactly at 0.52.

Sixteen of the 26 extra nodes were source articles automatically returned for
grounding. The other ten were filter anchors or intermediate path nodes. This
explains most `over_broad` classifications without weakening the evidence
result, but it also shows that the current reference contract and deterministic
output contract disagree about whether source and anchor nodes belong in the
scored result. Explicit relationship scoring has the same contract issue: the
query returns connecting relationships such as `ACTION_ON`, while several
references score only the relationship named by the question.

Jev returned model `jev-1.13.0`. The selector made 25 requests over 457
candidates, with a median of 9 and a range of 2 to 136. It used 112,999 tokens.
Summed Jev latency was 6.94 seconds, with a 266.0 ms median and a 191.0 to
515.9 ms range. The SDK response did not expose retry counts. Nine decisions
were within 0.05 of the threshold; only Q16's 0.50 Organization-name decision
caused a required miss. The largest candidate sets were Q19 at 136 and Q12 at
59, so pruning still has a material long-tail problem.

The whole run made 121 model requests, used 226,044 tokens, and took 841.54
seconds. The live schema filter was the bottleneck: 32 requests, 66,429 tokens,
and 557.16 seconds, including retries after the article contract change. The
fresh artifacts are:

- `.scratch/jev-selector/results/jev-compiler-owned-full-report.json`
  (`cd4c1d573f8f66245244dc3a6f9a2bc21b9e5a3b42f052d9b55fa196961ede3e`)
- `.scratch/jev-selector/results/jev-compiler-owned-full-events.jsonl`
  (`25858b0264ea8a301941ae8b14b03fbf3cd231f04080fb447747b3ecee789328`)
- `.scratch/jev-selector/results/jev-compiler-owned-smoke-report.json`
  (`374320ad91399a08a205b23922a065af36c6b59a3f379aa98d4586c44467f19e`)
- `.scratch/jev-selector/results/jev-compiler-owned-smoke-events.jsonl`
  (`159241b6e1305708b6e935f33aa0c252963d317983fb6308e2a5c9ae4858a6be`)

The full JSONL contains 25 events and the smoke JSONL contains three. Events
were written before post-execution semantic and retrieval scoring. The report
records both oracle types as loaded only after execution, and the catalog has
no `CONTEXT__NEWSARTICLE` entry.

Compared with the local selector baseline, this run improved executions from
19 to 24 and combined micro recall/F1 from 91.6%/94.3% to 99.6%/98.3%, while
precision moved from 97.2% to 96.9%. It used fewer model requests, 121 versus
137, but more tokens, 226,044 versus 159,038, and more wall time, 841.54 versus
538.04 seconds. Compared with the prior full Jev run, it improved executions
from 23 to 24 and combined micro F1 from 45.7% to 98.3%. That gain came with
more candidates, selector tokens, total tokens, and elapsed time: 457 versus
267 candidates, 112,999 versus 69,948 selector tokens, 226,044 versus 124,254
total tokens, and 841.54 versus 355.65 seconds.

Verdict: the compiler-owned article boundary and peer-independent filters fix
the two dominant failures in the previous Jev run. On this development set,
the result is strong enough to justify a held-out and repeatability phase, but
not a production integration yet. Before promotion, resolve the result/reference
contract for source articles, anchor nodes, and connecting relationships; cap
or further prune the candidate long tail; investigate schema-filter retries;
and measure repeatability for decisions near 0.52. Do not retune the threshold
on these 25 cases.
