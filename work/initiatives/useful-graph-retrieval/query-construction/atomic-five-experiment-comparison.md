# Five minimal atomic-retrieval experiments

Date: 2026-09-13

Baseline: `104d626`

## Decision

The Bill Designation binding experiment at `511eaeee` is the primary atomic
prototype shape. It is preserved by the annotated tag
`experiments/query-construction/primary-atomic-shape-2026-09-14`.

Keep that change. Reject the other four implementations.

The Bill experiment is the only clean causal result. It fixed its target failure,
changed no other case's classification or failure stage, reused the ingestion-side
Bill Designation parser, and improved combined micro and macro scores without an
extra model call.

The peer example and vote catalog explanation did not fix their targets. The
attached-reporting prompt fixed three reporting lookups, but its wording closely
matches the development questions and it caused unrelated regressions. The
NewsArticle boundary branch is too large, uses a phrase-shaped lexical gate, and
lost most of the baseline evidence.

None of these 25 questions is held out. The results measure repair behavior on a
known development set. They do not establish generalization to new political
questions.

## Experimental controls

Each branch started from `104d626` and retained:

- the same 25 question file, SHA-256
  `7abdd6c6f7fb389583aaf87925d8d9294b0731aa10d84e3fff7b5e545de934e0`;
- the same reference results, SHA-256
  `36229d9a5ca7d682dc169e9658f4f55806a14ab3d9cb311b1a42f221fd1ce73a`;
- the same populated graph and read-only execution path;
- local `gemma4:26b`, temperature 0, thinking disabled, 3,000 maximum output
  tokens, a 120-second timeout, and two transport attempts;
- reference loading only after all model and graph execution;
- oracle-free raw event logs.

One evaluator ran one batch at a time. The vote experiment's first batch aborted
during case 4 because deterministic fallback compilation raised an uncaught
`SemanticCompileError`. Its scored batch was a clean restart. The aborted attempt
is reported separately under cost.

## Implementations and verdicts

| Experiment | Commit | Behavioral change | Target result | Verdict |
| --- | --- | --- | --- | --- |
| NewsArticle boundary | `1f9a85c7` | Removes the selectable NewsArticle role, injects article roles in code, adds compiler routing and a lexical role-only gate | C-R1-01 recovered, but C-R3-01 and both vote cases returned nothing | Reject |
| Peer guidance | `0b360924` | Adds one generic peer-shape sentence to selector instructions | Both peer cases stopped in selection | Reject |
| Bill binding | `511eaeee` | Normalizes `Bill.name` with `parse_bill_designation` and includes specific validation feedback on retry | C-C1-02 recovered all expected nodes, evidence, and `REFERRED_TO` | Primary prototype shape |
| Attached reporting | `aad10407` | Adds the same reporting-lookup paragraph to schema filtering and selection | C-E1-01, C-E2-01, and C-E2-02 became exact; unrelated losses nearly canceled them | Reject this wording |
| Vote alternatives | `eba17ba` | Clarifies one predicate-alternative catalog description | Both vote cases still selected no relationships and missed `VOTED_NO` | Reject |

## Outcome, evidence, and cost

Evidence is reported as `returned/correct overlap` context IDs. The expected total
is 654 for every run. Lower payload or runtime is not an efficiency improvement
when it comes from stopping cases or returning less evidence.

| Run | Executed | Nonempty | Stopped | Exact combined sets | Evidence returned/correct | Payload bytes | Requests | Tokens | Elapsed | Case p50 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Baseline | 19 | 18 | 6 | 2 | 608/607 | 711,972 | 137 | 159,038 | 538.04s | 22.44s |
| NewsArticle boundary | 13 | 12 | 12 | 2 | 121/121 | 356,726 | 119 | 152,163 | 438.68s | 16.43s |
| Peer guidance | 17 | 15 | 8 | 2 | 579/578 | 669,600 | 123 | 139,266 | 489.28s | 20.15s |
| Bill binding | 20 | 19 | 5 | 2 | 609/608 | 715,744 | 137 | 159,728 | 531.94s | 21.79s |
| Attached reporting | 20 | 20 | 5 | 5 | 608/606 | 673,282 | 138 | 140,758 | 531.53s | 21.64s |
| Vote alternatives | 20 | 19 | 5 | 3 | 381/380 | 547,179 | 135 | 143,518 | 504.88s | 20.74s |

The vote experiment also consumed an aborted 74.5-second attempt. That attempt
completed three cases and part of case 4, made 21 recoverable requests, and used
at least 19,471 recorded tokens. Its five partial-case calls did not serialize
token counts. Total vote-experiment cost was therefore at least 156 requests,
162,989 tokens, and about 579.4 seconds.

## Combined node and evidence metrics

| Run | Scope | Precision | Recall | F1 | Jaccard |
| --- | --- | ---: | ---: | ---: | ---: |
| Baseline | Micro | 0.9715 | 0.9160 | 0.9429 | 0.8920 |
| Baseline | Macro | 0.5743 | 0.6667 | 0.6098 | 0.5543 |
| NewsArticle boundary | Micro | 0.9505 | 0.3139 | 0.4719 | 0.3088 |
| NewsArticle boundary | Macro | 0.3699 | 0.4267 | 0.3920 | 0.3499 |
| Peer guidance | Micro | 0.9766 | 0.8751 | 0.9231 | 0.8571 |
| Peer guidance | Macro | 0.4955 | 0.6000 | 0.5384 | 0.4955 |
| Bill binding | Micro | 0.9705 | 0.9207 | 0.9449 | 0.8956 |
| Bill binding | Macro | 0.6063 | 0.7067 | 0.6453 | 0.5863 |
| Attached reporting | Micro | 0.9704 | 0.9172 | 0.9430 | 0.8922 |
| Attached reporting | Macro | 0.6311 | 0.7267 | 0.6657 | 0.6031 |
| Vote alternatives | Micro | 0.9605 | 0.6534 | 0.7778 | 0.6364 |
| Vote alternatives | Macro | 0.6020 | 0.6589 | 0.6050 | 0.5433 |

Absolute combined deltas from baseline:

| Experiment | Micro precision | Micro recall | Micro F1 | Micro Jaccard | Macro precision | Macro recall | Macro F1 | Macro Jaccard |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| NewsArticle boundary | -0.0210 | -0.6021 | -0.4710 | -0.5832 | -0.2044 | -0.2400 | -0.2178 | -0.2044 |
| Peer guidance | +0.0050 | -0.0408 | -0.0199 | -0.0349 | -0.0788 | -0.0667 | -0.0714 | -0.0588 |
| Bill binding | -0.0011 | +0.0047 | +0.0020 | +0.0035 | +0.0320 | +0.0400 | +0.0356 | +0.0320 |
| Attached reporting | -0.0012 | +0.0012 | +0.0001 | +0.0001 | +0.0569 | +0.0600 | +0.0560 | +0.0489 |
| Vote alternatives | -0.0110 | -0.2625 | -0.1652 | -0.2557 | +0.0277 | -0.0078 | -0.0048 | -0.0110 |

The attached-reporting macro gain needs care. Three small cases became exact,
while three previously full-recall cases returned nothing. Micro overlap across
all 857 expected combined items increased by only one.

## Evidence metrics

| Run | Scope | Precision | Recall | F1 | Jaccard |
| --- | --- | ---: | ---: | ---: | ---: |
| Baseline | Micro | 0.9984 | 0.9281 | 0.9620 | 0.9267 |
| Baseline | Macro | 0.7000 | 0.6800 | 0.6800 | 0.6600 |
| NewsArticle boundary | Micro | 1.0000 | 0.1850 | 0.3123 | 0.1850 |
| NewsArticle boundary | Macro | 0.4800 | 0.4400 | 0.4533 | 0.4400 |
| Peer guidance | Micro | 0.9983 | 0.8838 | 0.9376 | 0.8824 |
| Peer guidance | Macro | 0.5800 | 0.6000 | 0.5867 | 0.5800 |
| Bill binding | Micro | 0.9984 | 0.9297 | 0.9628 | 0.9282 |
| Bill binding | Macro | 0.7400 | 0.7200 | 0.7200 | 0.7000 |
| Attached reporting | Micro | 0.9967 | 0.9266 | 0.9604 | 0.9238 |
| Attached reporting | Macro | 0.7600 | 0.7200 | 0.7200 | 0.6800 |
| Vote alternatives | Micro | 0.9974 | 0.5810 | 0.7343 | 0.5802 |
| Vote alternatives | Macro | 0.7400 | 0.6612 | 0.6689 | 0.6412 |

## Node metrics

| Run | Scope | Precision | Recall | F1 | Jaccard |
| --- | --- | ---: | ---: | ---: | ---: |
| Baseline | Micro | 0.8900 | 0.8768 | 0.8834 | 0.7911 |
| Baseline | Macro | 0.5059 | 0.6600 | 0.5648 | 0.4925 |
| NewsArticle boundary | Micro | 0.9136 | 0.7291 | 0.8110 | 0.6820 |
| NewsArticle boundary | Macro | 0.3252 | 0.4200 | 0.3615 | 0.3119 |
| Peer guidance | Micro | 0.9101 | 0.8473 | 0.8776 | 0.7818 |
| Peer guidance | Macro | 0.4472 | 0.6000 | 0.5064 | 0.4472 |
| Bill binding | Micro | 0.8873 | 0.8916 | 0.8894 | 0.8009 |
| Bill binding | Macro | 0.5359 | 0.7000 | 0.5991 | 0.5225 |
| Attached reporting | Micro | 0.8911 | 0.8867 | 0.8889 | 0.8000 |
| Attached reporting | Macro | 0.5813 | 0.7400 | 0.6388 | 0.5680 |
| Vote alternatives | Micro | 0.8911 | 0.8867 | 0.8889 | 0.8000 |
| Vote alternatives | Macro | 0.5439 | 0.7000 | 0.6036 | 0.5305 |

## Explicit relationship-value metrics

| Run | Scope | Precision | Recall | F1 | Jaccard |
| --- | --- | ---: | ---: | ---: | ---: |
| Baseline | Micro | 0.2632 | 0.5000 | 0.3448 | 0.2083 |
| Baseline | Macro | 0.4200 | 0.8000 | 0.4267 | 0.4200 |
| NewsArticle boundary | Micro | 0.4167 | 0.5000 | 0.4545 | 0.2941 |
| NewsArticle boundary | Macro | 0.6000 | 0.8000 | 0.6000 | 0.6000 |
| Peer guidance | Micro | 0.3333 | 0.5000 | 0.4000 | 0.2500 |
| Peer guidance | Macro | 0.5400 | 0.8000 | 0.5467 | 0.5400 |
| Bill binding | Micro | 0.3000 | 0.6000 | 0.4000 | 0.2500 |
| Bill binding | Macro | 0.4600 | 0.8400 | 0.4667 | 0.4600 |
| Attached reporting | Micro | 0.5000 | 0.5000 | 0.5000 | 0.3333 |
| Attached reporting | Macro | 0.6200 | 0.8000 | 0.6267 | 0.6200 |
| Vote alternatives | Micro | 0.3333 | 0.5000 | 0.4000 | 0.2500 |
| Vote alternatives | Macro | 0.5000 | 0.8000 | 0.5067 | 0.5000 |

Most apparent relationship precision gains came from returning fewer values.
Only Bill binding increased correct relationship overlap, from five to six.

## Target-case analysis

### NewsArticle boundary and relationship-free plans

`C-R1-01` advanced from a composer stop to full expected recall. It returned the
expected Bill, LaborUnion, evidence, and `DECLARED_STANCE`, plus one source
Article identity. `C-R3-01` and `C-R3-02` stopped during selection. Both vote cases
also stopped because the model kept emitting the now-forbidden article role.

The article path itself regressed. `C-E1-02`, `C-E3-01`, and `C-E3-02` stopped
during selection; `C-E2-01` executed empty; `C-E2-02` stopped during composition.
Only `C-E1-01` and the aggregate `C-E3-03` retained exact node-and-evidence sets.

This branch changed seven files, with 162 added and 30 removed behavioral lines.
It changed catalog IDs, typed contracts, compiler legality, article-role injection,
composer participation, model instructions, and question-dependent routing. It is
not a minimal experiment.

### Peer guidance

Both peer cases regressed from one-third combined recall to selector stops. On
`C-M2-01`, the first response chose the correct two Organization roles, two
relationships, and shared Bill, but placed the distinct-role key in
`aggregation_ids`. Later attempts misspelled an ID or chose another wrong group.
`C-M2-02` repeatedly misspelled the relationship ID and also misbucketed the
distinct-role key.

The semantic example taught the occurrence shape once. The typed output contract
still made the plan invalid. More examples are unlikely to fix that interface.

### Bill binding

`C-C1-02` changed from a binder stop to a two-row execution:

1. The first attempt returned `committee` for the `Bill.name` slot.
2. Code rejected it because it was not a Bill Designation.
3. Retry feedback listed the four accepted forms and pointed to the designation
   already present in the question.
4. The second attempt returned `AB 2540`.
5. The query recovered all three expected nodes, its evidence context, and
   `REFERRED_TO`.

The result is labeled over-broad only because compiler hydration adds the source
Article identity. No other case changed classification or failure stage.

The normalizer returns the first designation found in a string. Keep the current
change for one Bill-name slot. If a later query has several Bill-name slots, do
not assign the first question designation to each slot. That requires an explicit
multi-value assignment contract.

### Attached reporting

`C-E1-01`, `C-E2-01`, and `C-E2-02` became exact. The target `C-E2-02` returned all
three expected nodes and all 20 expected evidence contexts.

The prompt also caused unrelated changes. `C-M1-01`, `C-M1-02`, and `C-M5-01`
went from full recall to zero. Two M4 cases lost expected material. Gains and
losses left total combined overlap only one item above baseline and evidence
overlap one item below it.

### Vote alternatives

Both schema-filter responses identified `VOTED_AYE`, `VOTED_NO`, `ABSTAINED`, and
`ACTION_ON`. Both selectors still returned zero relationships. Relationship-free
co-occurrence recovered the expected nodes and one evidence context, but neither
case returned the expected `VOTED_NO` value.

The scored restart also lost 202 of 214 combined items on `C-E3-02`. The catalog
sentence did not fix vote semantics and caused broad selection drift.

## Contamination audit

| Experiment | Mechanical leakage | Phrase or decision leakage | Scope isolation | Confidence |
| --- | --- | --- | --- | --- |
| NewsArticle boundary | No case IDs, entities, stored values, or expected answers | High. The lexical gate keys on reporting, mention, attach, same, appear, and chunk forms used by the development questions | Poor. Several contracts and compiler paths changed | Low |
| Peer guidance | None found | Low. Abstract A/B roles and a shared-anchor shape | Good. One instruction sentence | High confidence in the negative result |
| Bill binding | None found | Low. `SB`, `AB`, `Senate Bill`, and `Assembly Bill` are domain grammar | Good. Only `Bill.name` slots change | High |
| Attached reporting | No full question or entity copied | High. `reporting attached to` appears verbatim and the prompt supplies the target decision | Medium. Six prompt lines affect every case | Low for the positive target result |
| Vote alternatives | No case ID, entity, Bill number, or expected answer | Medium. The catalog gives the known vote cases' intended piece choice | Good source size, but the sentence appears in every selector prompt | High confidence in the negative result |

The raw event logs contained 25 records for every completed batch and no expected
rows, overlap scores, classifications, missing sets, or other evaluator fields.
The vote aborted log was also pre-scoring. There is no evidence that reference
answers entered a model call.

The larger limitation is development-set awareness. Four changes were proposed
after inspecting named failures. Exact-literal guards cannot turn those cases into
a held-out benchmark. A positive result needs fresh paraphrases and negative
controls before it supports production behavior.

## Minimal next implementations

### 1. Article evidence and relationship-free legality

Do not remove NewsArticle globally and do not parse question wording in code.

Make two structural changes:

1. After piece selection, discard a NewsArticle role only when no selected
   article relationship, article filter, or aggregate consumes it. This removes
   orphan evidence roles while retaining article-as-answer semantics.
2. Reject a relationship-free piece selection when the preceding schema selection
   identified required semantic relationships. Permit the existing role-only
   compiler path when the schema stage selected none.

These rules use the two model outputs and ontology shape already present. They do
not match evaluation words or add a call.

### 2. Peer queries

Do not add more peer examples yet. Replace the five separately typed ID arrays
with one ordered `piece_ids` list whose values are constrained to catalog IDs.
Group valid IDs by `Piece.kind` in code. This removes the observed misbucketing
failure. Enum validation supplies precise feedback for misspelled IDs.

Repeated IDs remain legal, so peer queries can still request two role and
relationship occurrences. The compiler and composer do not change.

### 3. Bill names

Use the `511eaeee` implementation:

- run every compiled `Bill.name` value through `parse_bill_designation`;
- normalize the four accepted forms before graph resolution;
- include the rejected value and accepted forms in existing retry feedback;
- mention a question-derived designation only when there is one Bill-name slot.

No new regular expression or model call is needed.

### 4. Reporting attached to an entity

Do not ship the target-aware paragraph. First try one general sentence in the
schema filter only:

> Evidence is compiler-produced output. A request for evidence alone does not add
> a semantic entity or relationship to the query plan.

The selector already says reporting context is automatic. Keeping the new rule at
one stage reduces global prompt drift and avoids the words `attached`, `associated`,
and `mentions`. Test it on fresh paraphrases plus article-as-answer negative
controls. If the distinction remains unreliable, add a typed evidence-lookup flag
to the existing schema-filter output rather than a new agent.

### 5. Unknown vote outcomes

Do not rely on another catalog example. Use deterministic closure between the two
existing stages:

- when schema filtering selects a declared mutually exclusive predicate family,
  expose only its predicate-alternative piece to the selector;
- when schema filtering requires relationships but the selector returns none,
  reject and retry instead of compiling role-only co-occurrence;
- keep `ACTION_ON` as a separate required connection when the schema selected it
  and the plan contains LegislativeEvent and Bill roles.

This rule derives from ontology-declared alternative families and stage output. It
does not mention a person, Bill, case, or expected vote.

## Per-case runtime and terminal stage

`semantic` means graph execution completed but the returned set differed from the
reference. Times are wall-clock seconds for that case. The vote table covers the
successful restart; its aborted attempt is reported above.

| Case | Baseline | NewsArticle boundary | Peer guidance | Bill binding | Attached reporting | Vote alternatives |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| C-E1-01 | 12.41s selector | 17.79s ok | 20.15s selector | 13.26s selector | 19.59s ok | 18.38s ok |
| C-E1-02 | 20.34s ok | 11.36s selector | 21.33s ok | 20.59s ok | 19.51s ok | 15.56s ok |
| C-E2-01 | 11.63s selector | 19.39s empty | 24.21s empty | 11.78s selector | 16.81s ok | 21.22s empty |
| C-E2-02 | 23.95s empty | 40.66s composer | 21.62s empty | 23.39s empty | 14.14s ok | 20.74s composer |
| C-E3-01 | 21.55s semantic | 12.62s selector | 21.99s semantic | 21.79s semantic | 21.68s semantic | 21.44s semantic |
| C-E3-02 | 22.44s semantic | 12.60s selector | 21.29s semantic | 21.32s semantic | 22.66s semantic | 16.11s semantic |
| C-E3-03 | 12.19s ok | 10.24s ok | 11.96s ok | 12.31s ok | 11.67s ok | 11.72s ok |
| C-R1-01 | 28.94s composer | 19.58s semantic | 13.39s selector | 29.24s composer | 30.52s composer | 28.37s composer |
| C-R1-02 | 18.54s semantic | 18.00s semantic | 15.97s semantic | 18.28s semantic | 18.94s semantic | 15.56s semantic |
| C-R2-01 | 16.69s semantic | 16.07s semantic | 13.46s semantic | 16.23s semantic | 13.28s semantic | 13.26s semantic |
| C-R2-02 | 17.06s semantic | 16.03s semantic | 13.67s semantic | 16.25s semantic | 16.26s semantic | 16.19s semantic |
| C-R3-01 | 25.44s composer | 14.18s selector | 13.35s selector | 25.81s composer | 23.07s semantic | 12.31s selector |
| C-R3-02 | 24.60s semantic | 13.19s selector | 21.07s semantic | 22.84s semantic | 20.25s semantic | 22.94s semantic |
| C-M1-01 | 24.51s semantic | 9.03s composer | 24.59s composer | 23.48s semantic | 21.64s composer | 21.63s composer |
| C-M1-02 | 23.97s semantic | 21.05s semantic | 22.75s semantic | 23.32s semantic | 21.53s composer | 20.15s semantic |
| C-M2-01 | 24.59s semantic | 24.48s semantic | 15.41s selector | 24.38s semantic | 24.87s semantic | 23.85s semantic |
| C-M2-02 | 24.95s semantic | 24.85s semantic | 15.18s selector | 24.38s semantic | 27.31s semantic | 24.37s semantic |
| C-M3-01 | 20.76s semantic | 18.03s semantic | 21.65s semantic | 20.19s semantic | 18.56s semantic | 20.40s semantic |
| C-M3-02 | 24.09s semantic | 13.72s selector | 23.93s semantic | 23.96s semantic | 23.87s semantic | 24.11s semantic |
| C-M4-01 | 20.28s semantic | 21.41s composer | 20.02s semantic | 19.50s semantic | 21.70s semantic | 21.81s semantic |
| C-M4-02 | 14.28s semantic | 14.02s semantic | 13.95s semantic | 13.94s semantic | 22.61s semantic | 14.07s semantic |
| C-M5-01 | 31.82s semantic | 16.43s selector | 32.09s semantic | 31.39s semantic | 28.55s composer | 30.81s semantic |
| C-M5-02 | 36.61s composer | 15.77s selector | 29.14s composer | 34.95s composer | 31.41s semantic | 30.57s semantic |
| C-C1-01 | 13.62s semantic | 17.78s semantic | 17.16s semantic | 17.23s semantic | 17.56s semantic | 17.08s semantic |
| C-C1-02 | 22.68s binder | 20.31s binder | 19.89s binder | 22.03s semantic | 23.48s binder | 22.13s binder |

## Artifacts

The implementation commits are retained on these branches:

- `codex/exp-newsarticle-boundary` at `1f9a85c7`;
- `codex/exp-peer-guidance` at `0b360924`;
- `codex/exp-bill-binding` at `511eaeee`;
- `codex/exp-attached-reporting` at `aad10407`;
- `codex/exp-vote-alternatives` at `eba17ba`.

The annotated tag
`experiments/query-construction/primary-atomic-shape-2026-09-14` points to the
selected Bill binding commit, `511eaeee`.

Completed evaluator artifacts are currently in each worktree's ignored
`.scratch/evaluations/<experiment>/` directory. The vote aborted raw log is at
`/private/tmp/vote-alternatives-aborted-raw-stage-events.jsonl`.
