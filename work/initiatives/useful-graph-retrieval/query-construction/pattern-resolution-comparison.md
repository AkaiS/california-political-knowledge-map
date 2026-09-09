# Pattern selection and candidate resolution experiments

Follow-up to the [composable-triples experiment](composable-triples-comparison.md)
for [issue 05](../issues/05-prototype-query-construction-and-validation.md).

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

## What the two experiments changed

A graph pattern is the composition of ontology triples, shared nodes, filters,
and requested outputs needed for a question. Pattern selection already existed
in the previous two-stage composable-triples arm. We extended that stage with
an ontology-derived triple catalog and compiler-assigned names. The new adapter
converts the model's selections into the previous `PatternPlan` and calls the
existing compiler. It does not select an identifier for a whole authored query.

The model still chooses the triples and their joins in one response, referring
to node-list positions. Code assigns names such as `n0`, `claim_0`, and
`slot_0`. It also derives slot descriptions. The prompt and response structure
changed alongside these names, so this was not an identifier-only comparison.

Three examples make the intended extension concrete:

| Question | Intended composable pattern and identifier assignment | Observed selected result |
| --- | --- | --- |
| Q01: reporting mentioning Steve Hilton | Select `Politician -MENTIONED_IN-> Chunk`; code names the nodes `n0/n1` and the name filter `slot_0`; binder supplies Steve Hilton | Correct structure and two expected Chunks |
| Q16: other organizations lobbying alongside Walt Disney for AB 186 | Use `Organization -LOBBIED_FOR-> Bill` twice, sharing one Bill handle and keeping separate anchor/peer handles; code names both claims and the value slots | Model created only one Organization, required it to differ from itself, and added an invalid aggregate |
| Q05: housing articles in July 2026 | Select `NewsArticle -DISCUSSES_TOPIC-> PolicyArea`; code names slots for the topic and two date bounds; binder supplies July 1 and August 1 | Model chose date equality instead of two bounds; binding `2026-07` retrieved nothing |

The separate resolver experiment extended binding with correct patterns
supplied. It kept the old slot names and reused each initial binder response
across both arms. Code discovered stored candidates under the bound node's
label and scope; a model selected project ids. It did not select graph patterns
or use the new identifier interface.

| Question | Binding change tested | Observed result |
| --- | --- | --- |
| Q09: organizations endorsing the Steve Hilton campaign | Keep `Organization -ENDORSED-> Campaign`; replace name `Steve Hilton` with offered Campaign id `Campaign:steve-hilton-campaign` | Recovered Reform California and its endorsement evidence |
| Q03: reporting about SB 9 in session 2025-2026 | Keep Bill mention triples; select `Bill:2025-2026:sb-9` among session-restricted Bill candidates and retain the session filter | Same 19 reporting Chunks in both arms |
| Q13: PACs funding the Ed Musgrove campaign | Keep PAC funding triples; replace shortened name with `Campaign:ed-musgrove-campaign` | Correct id selected, but returned under `target` instead of required `target_name`; rejected before execution |

The individual findings reports below include expanded examples separating
intended structure, compiler work, binding values, and actual saved outputs.

## Experiment plan, recorded before inference

On 2026-09-09 the maintainer requested two Sol agents at medium reasoning in
separate worktrees. One tests compiler-assigned identifiers and a smaller
pattern-selection contract. The other tests graph-backed candidate resolution
with supplied correct patterns, isolating binding from planning. A third
experiment will combine the approaches only if both independent results support
doing so.

Both start from the composable-triples prototype at `2da6872`. The agents build
in parallel and run local model inference sequentially. Prototype code remains
on throwaway branches. Existing coordinator changes are preserved.

The coordinator rechecked all 25 reference queries before implementation.
Every field except inspection time matches the saved reference, including 533
supporting Article Chunks. The fresh report is
`.scratch/query-construction/pattern-resolution-reference-20260909.json`.

The combination gate asks whether each change improves its targeted failure
without a material regression in meaning:

- Pattern selection must reduce malformed plans and improve correctly scoped
  model-selected retrieval over the prior corrected two-stage result of 11/25.
  Valid structure, semantic correctness, and final binding success are assessed
  separately. A gain caused by dropping filters, joins, requested outputs, or
  evidence requirements does not pass.
- Candidate resolution must recover the three known Campaign binding misses
  while preserving the 22 successful supplied-pattern retrievals. Candidate
  choice must respect labels and explicit scope, bind stored project ids, and
  expose ambiguity or no match. Equivalent alias retrieval requires an evidence
  audit instead of blind exact-reference scoring.
- Inconclusive results or an unresolved material defect keep the gate closed.
  Passing this gate authorizes a combined experiment, not a production decision.

References remain evaluator-only. The supplied-pattern arm has privileged
structure and is a diagnostic control. Prompts stay fixed within each batch,
failed attempts and complete usage are retained, and later repairs or replays
stay separate from frozen inference. These are development examples, not a
held-out benchmark or a formal Gold Set.

## Pattern-selection result

The pattern-selection gate fails. The frozen model-selected arm retrieves two
complete answers, Q01 and Q25, compared with 11 in the prior two-stage experiment
after its compiler correction. Eighteen plans are rejected before binding;
seven execute, of which five return no rows. The supplied-pattern control
retrieves the same 22 complete answers as before and retains the three Campaign
name misses.

| Frozen outcome | Model-selected pattern | Supplied-pattern control |
| --- | ---: | ---: |
| Complete retrievals in coordinator audit | 2 | 22 |
| Executed empty query | 5 | 3 |
| Pattern rejected before binding | 18 | 0 |
| Model transport or output-validation failure | 0 | 0 |

The interface derives 29 allowed triples from the supported News Ontology
subset. The model selects ordered node labels, positional handles, catalog
relationships, filters, projections, inequalities, and an optional aggregate.
Code assigns node names, claim names, binding slots, descriptions, output aliases,
and direction. All 25 supplied patterns compile through this interface, and a
separate reversed-endpoint smoke confirms ontology-derived direction.

Fifteen rejections concern invalid aggregates. The model requests an aggregate
in 16 cases although only Q07 asks for a count. The other rejections concern
unsupported properties or projections. The five executable failures also expose
semantic mistakes:

- Q03 follows Legislative Events instead of direct Bill mentions.
- Q05 and Q06 compare the stored publication date to `2026-07` rather than
  applying the required half-open July date range.
- Q09 and Q13 add a self-inequality, requiring one Organization to have an id
  different from itself. Both also shorten the Campaign name. Q13 uses an
  Organization name filter for `PAC` instead of the PAC sub-label.

Compiler-assigned names remove some bookkeeping opportunities but this contract
does not improve planning. The new catalog and instructions also differ from
the prior full-ontology prompt, so this is evidence about the tested interface,
not an isolated estimate of identifier assignment's effect.

The coordinator independently checked all nonempty evidence sets, both successful
selected query scopes, and all 26 Policy Area counts and Source Article sets.
All 25 control outputs exactly match the prior supplied-pattern outputs after
mechanically normalizing node and claim aliases, including relationship types
and per-claim evidence groups. There was no post-batch rescue inference or
compiler replay.

| Captured stage | Responses | Input plus output tokens | HTTP seconds |
| --- | ---: | ---: | ---: |
| Pattern selection | 25 | 34,690 | 176.89 |
| Binding selected patterns | 7 | 24,540 | 6.45 |
| Binding supplied patterns | 25 | 87,881 | 20.84 |

The batch took 208.08 seconds, with 147,111 tokens across 57 captured responses.

## Candidate-resolution result

The resolver gate also fails. It recovers Q09 and Q12, two of the three Campaign
misses, but loses four previously complete retrievals. Its final result is 20/25
against 22/25 for the paired literal-binding control.

| Frozen outcome | Literal-binding control | Candidate resolution |
| --- | ---: | ---: |
| Complete retrievals in coordinator audit | 22 | 20 |
| Executed empty query | 3 | 0 |
| Rejected resolution slot mapping | 0 | 3 |
| Explicitly unresolved | 0 | 2 |

Both arms share each question's supplied pattern and original binder output.
Candidate discovery reads the chosen node label and applies same-node equality
scope, including Bill session. Code merges graph rows by project id, ranks stored
names lexically, and offers up to eight candidates with names, labels, sessions,
and Campaign target metadata. The model selects an offered project id or returns
ambiguity or no match. Successful resolution changes only the relevant name
constraint to an id constraint; the query retains its other filters, joins,
labels, projections, and evidence rules.

The failures separate candidate discovery from the model-facing contract:

- Q13 chooses the correct Ed Musgrove Campaign id but returns `target` instead
  of the required `target_name` slot. Q24 similarly selects the correct Committee
  under `committee` instead of `seed_name`. Both are rejected.
- Q05 returns the wrong slot and confuses the Policy Area being bound with the
  articles requested as output. Q18 makes the same distinction incorrectly,
  declining to resolve Steve Hilton because the answer should contain
  Organizations.
- Q19 declares Gavin Newsom ambiguous because both `Gavin Newsom` and `Newsom`
  exist as separate project identities. This avoids an arbitrary choice but
  loses a retrieval the exact-name control completed. The prototype does not
  resolve alias sets.

The three known Campaign cases all have their intended identity in the candidate
list. Q13 therefore exposes a slot-contract failure rather than a discovery
failure. The generic list of slot strings gives up the exact required-field
guarantees of the original pattern-specific binder. Runtime checks reject bad
slot mappings after the model call, without feeding that check back into output
correction.

The separate unknown-Campaign model challenge returns `no_match`; the challenge
with two plausible Campaign identities returns `ambiguous`. A deterministic
wrong-session check returns no Bill candidates without relaxing its session.
These bounded checks pass, but do not offset the regressions in the 25 cases.
Top-eight lexical candidate recall remains a limitation. Truncation and hidden
top-score ties are recorded; absence of such a tie does not establish semantic
uniqueness.

The coordinator confirmed that all 20 successful resolver outputs have the exact
reference evidence sets. The 18 cases completed by both arms have identical
normalized outputs, including per-claim evidence. The two recovered cases have
the correct subjects, Campaign identities, relationships, and supporting Chunks.
All 22 control results match the earlier supplied-pattern baseline. No extra
alias evidence was returned in this batch.

| Captured stage | Responses | Input plus output tokens | HTTP seconds |
| --- | ---: | ---: | ---: |
| Shared initial binding | 25 | 87,451 | 21.81 |
| Candidate resolution for the 25 cases | 37 | 51,039 | 120.89 |
| Separate model challenges | 2 | 2,627 | 7.22 |

The paired 25-case batch took 147.97 seconds, excluding the later challenges.
All 64 responses, including correction attempts and challenges, total 141,117
tokens. The report preserves failed outputs; no rescue inference or replay was
performed.

## Combination decision

Do not combine these implementations. Both fail the prospectively recorded
gates, and no combined experiment was launched.

These results leave useful, narrower questions. For pattern selection, optional
aggregation and constraints still admit semantically invalid choices even after
identifier bookkeeping moves into code. For candidate resolution, the intended
stored identities are available, but slot naming, input-versus-output roles, and
alias ambiguity need a better contract. These are findings for the next design
discussion, not settled architectural decisions.

## Preserved artifacts

Pattern selection lives on `codex/prototype-pattern-selection`, commit
`034ba5e`, in `/private/tmp/ca-map-prototype-pattern-selection-20260909`.

- [Pattern findings](reports/pattern-selection/findings.md)
- [Frozen pattern report](reports/pattern-selection/results/full-report.json)
- [Pattern run instructions](reports/pattern-selection/README.md)

Candidate resolution lives on `codex/prototype-entity-resolution`, commit
`08602d1`, in
`/private/tmp/ca-map-prototype-entity-resolution-20260909`.

- [Resolver findings](reports/entity-resolution/findings.md)
- [Frozen resolver report](reports/entity-resolution/results/fresh-report.json)
- [Resolver run instructions](reports/entity-resolution/README.md)

Both agents checked Ruff, formatting, Python compilation, whitespace, and report
integrity. Pattern selection passed supplied-structure conversion and direction
smokes. Candidate resolution passed the read-only graph and separate model
challenges described above. The coordinator independently audited both frozen
reports. No browser verification was used.

This checkout contains the comparison and issue updates. Prototype code and
captured runs remain in their own worktrees and branches; no production code
was integrated.
