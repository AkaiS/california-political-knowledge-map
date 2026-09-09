# Findings from graph-backed entity resolution

## What we were extending

This experiment extended the **binding stage** of the previous composable
ontology triples prototype. The graph pattern was supplied correctly for every
question, using the earlier authored patterns. The model did not choose triples
or joins in this experiment.

A pattern says, for example, "find Organizations that ENDORSED a Campaign."
A binding identifies which Campaign the question names. The old binder
extracted a name string; the new step looked up stored candidates and asked the
model to choose a project id. This is read-only query binding. It does not merge
or change graph entities.

The actual paired comparison was:

```text
Question + supplied correct triples
  -> previous binder extracts names, sessions, and dates
       -> control: execute with those literal names
       -> treatment: discover candidates under each bound node's label/scope
                     -> model selects stored project ids
                     -> execute the same triples with id bindings
```

The two arms shared the initial binder response. The treatment retained the old
pattern's node and slot names; it did not include the separate compiler-assigned
identifier extension. Candidate lookup was performed by code before the
resolution call, rather than through a model-invoked search tool.

The relevant previous result for this experiment is the **22/25 supplied-pattern
arm**. This run reproduced that control and compared it with 20/25 after adding
candidate resolution. The separate identifier experiment's 2/25 versus 11/25
compares model-selected structures; it is a different measurement task within
the same composable-triples approach.

## Three concrete examples

These show the supplied structure, the binding change being tested, and the
actual saved result.

### 1. Find organizations endorsing the Steve Hilton campaign, Q09

The supplied pattern was:

```text
Organization -ENDORSED-> Campaign
Filter the Campaign.
Return the Organizations and evidence for each endorsement.
```

The old binder produced `target_name = "Steve Hilton"`. The graph stores the
Campaign as `Steve Hilton campaign`, so the control's name equality returned
nothing.

The treatment searched only Campaign candidates. Among the offered candidates
was the stored name `Steve Hilton campaign` with project id
`Campaign:steve-hilton-campaign`. The resolver selected that id, and code
changed the filter:

```text
Before: Campaign.name = "Steve Hilton"
After:  Campaign.id = "Campaign:steve-hilton-campaign"
```

The `ENDORSED` triple and its evidence retrieval stayed the same.
**Observed:** the treatment retrieved Reform California and the expected
endorsement evidence. It did not bind the Politician Steve Hilton in place of
the Campaign.

### 2. Find reporting about SB 9 in the 2025-2026 session, Q03

The supplied pattern connected a Bill to its reporting Chunks and those Chunks
to their Source Articles:

```text
Bill -MENTIONED_IN-> Chunk <-HAS_CHUNK- NewsArticle
Bill.name = "SB 9"
Bill.session = "2025-2026"
```

The old binder already supplied both values correctly. Candidate discovery
searched Bill nodes restricted to session `2025-2026`. The resolver selected
`Bill:2025-2026:sb-9`, so the treatment used:

```text
Bill.id = "Bill:2025-2026:sb-9"
Bill.session = "2025-2026"
```

**Observed:** both arms retrieved the same 19 reporting Chunks. This was a
preservation check, not a newly recovered answer. A separate deterministic
check supplied session `1900-1901` and found no candidates; code did not drop
the session to find a match.

### 3. Find PACs funding the Ed Musgrove campaign, Q13

The supplied pattern was:

```text
Organization with PAC sub-label -FUNDED-> Campaign
Filter the Campaign.
Return PACs and evidence for their funding claims.
```

The old binder shortened the Campaign name to `Ed Musgrove`, producing an empty
control result. Candidate discovery offered the correct stored identity,
`Campaign:ed-musgrove-campaign`, and the resolver selected it.

**Observed:** the response nevertheless failed. The required slot was
`target_name`, but the model returned:

```json
{"slot": "target", "outcome": "selected", "project_id": "Campaign:ed-musgrove-campaign"}
```

This excerpt omits the response's reason field. Code rejected the wrong slot
name and did not execute the treatment query. The candidate was found and
chosen correctly, but the interface could not attach that choice to the
required binding. This failure explains why finding good candidates alone did
not make the resolver experiment pass.

## What this experiment can establish

This tests literal name binding against an added candidate-selection step with
correct triples supplied. Its 20/25 result is not a score for selecting graph
patterns. It also does not test the resolver combined with compiler-assigned
identifiers. The run shows two recovered Campaign answers and four regressions
under this particular candidate and output contract.

The resolver used a generic list of slot names and decisions, whereas the
original binder had a separate required output field for every actual slot.
That change matters: it allowed the wrong-slot failure above. The report's
failure verdict applies to this implementation, not to graph-backed candidate
lookup in general.

## Question and result

Can a read-only graph candidate resolver recover the three known Campaign binding misses while preserving all 22 successful supplied-pattern controls?

No. The frozen run recovers two of the three Campaign misses, but the resolver finishes 20 of 25 cases compared with 22 of 25 for the literal-binding control. Four previously complete cases stop at resolution. This fails the combination gate.

Both arms use the same evaluator-authored semantic pattern and the same first binder response for each question. The control binds that response as a stored name. The resolver queries the graph under the exact node label and same-node scope declared by that pattern, deduplicates graph rows by project id, presents at most eight identities with stored names and disambiguating metadata, and requires an explicit `selected`, `ambiguous`, or `no_match` decision. A selected identity changes only the corresponding name constraint to an id constraint. The resolver never sees reference queries, values, rows, or evidence during inference.

The fresh read-only reference recheck verified all 25 cases and 533 distinct supporting Article Chunks immediately before inference.

## Frozen results

| Outcome | Literal control | Resolver |
| --- | ---: | ---: |
| Complete reference retrieval | 22 | 20 |
| Executed empty query | 3 | 0 |
| Resolver slot validation failure | 0 | 3 |
| Explicit ambiguity | 0 | 2 |
| Cases with no identity slot | 1 | 1 |

The resolver recovers Q09 and Q12 by selecting `Campaign:steve-hilton-campaign` and `Campaign:yes-on-proposition-38-campaign`. Q13 identifies `Campaign:ed-musgrove-campaign`, but calls its decision slot `target` instead of the required `target_name`; deterministic validation rejects it. Thus the known Campaign recovery is 2 of 3. Every selected Campaign identity is a Campaign project id. The candidate or ballot-measure ids appear only as disambiguating metadata.

The resolver loses four controls:

- Q05 returns slot `area` instead of `area_name` and treats the requested articles as evidence that the exact Policy Area seed is ambiguous.
- Q18 marks exact `Politician:steve-hilton` ambiguous because the question asks for Organizations, confusing the anchor identity with the answer type.
- Q19 marks exact `Politician:gavin-newsom` ambiguous because a separate `Politician:newsom` node exists.
- Q24 selects the exact Committee project id but returns slot `committee` instead of `seed_name`.

All 20 executed resolver cases exactly match the reference project and source ids, grouped counts, and evidence-id union. The 18 cases that execute nonempty in both arms have canonically identical result rows. Q04 selects the exact `Prop:proposition-38` reference identity, so this run adds no alias evidence beyond the reference. No nonempty result is being promoted on row count alone.

| Question | Control | Resolver | Resolution note |
| --- | --- | --- | --- |
| Q01 | complete | complete | Exact Politician id |
| Q02 | complete | complete | Exact Politician id |
| Q03 | complete | complete | Exact Bill id under session `2025-2026` |
| Q04 | complete | complete | Exact Proposition 38 id |
| Q05 | complete | failed | Wrong slot and anchor/answer confusion |
| Q06 | complete | complete | Exact Policy Area id |
| Q07 | complete | complete | No identity slot; same execution |
| Q08 | complete | complete | Exact Bill id under session |
| Q09 | empty | complete | Recovered Steve Hilton Campaign id |
| Q10 | complete | complete | Exact Bill id under session |
| Q11 | complete | complete | Exact Bill id under session |
| Q12 | empty | complete | Recovered Yes on Proposition 38 Campaign id |
| Q13 | empty | failed | Correct Campaign id, wrong slot |
| Q14 | complete | complete | Exact Organization id |
| Q15 | complete | complete | Exact Organization id |
| Q16 | complete | complete | Exact Organization and Bill ids under session |
| Q17 | complete | complete | Exact Organization and Bill ids under session |
| Q18 | complete | ambiguous | Confused anchor with requested answer type |
| Q19 | complete | ambiguous | Exact name plus a shorter alias node |
| Q20 | complete | complete | Exact funding Organization id |
| Q21 | complete | complete | Exact funding Organization id |
| Q22 | complete | complete | Exact Politician and Bill ids under session |
| Q23 | complete | complete | Exact Politician and Bill ids under session |
| Q24 | complete | failed | Correct Committee id, wrong slot |
| Q25 | complete | complete | Exact Bill id under session |

The generic list of `ResolutionDecision` objects reintroduces a problem the pattern-derived binder had removed. The output schema requires a string `slot`, but it cannot require the actual slot names for that case. Two correct candidate choices are discarded because the model substitutes semantic variable names. Q05 does the same while also making the wrong ambiguity decision. A useful follow-up would derive the resolution output fields from the compiled identity slots, as the original binder already does. This run does not test that alternative, and no rescue inference was performed.

## Negative and ambiguity checks

The wrong-session smoke asks for `SB 9` in session `1900-1901`. Label-locked and session-locked candidate discovery returns zero identities and does not relax the scope.

The separate unknown-name model challenge sees eight Campaign candidates from a 41-identity Campaign inventory and returns `no_match` for `Entity That Is Not Stored 9f02e`.

The separate ambiguity challenge presents two distinct Campaign project ids, `Campaign:yes-on-proposition-38-campaign` and `Campaign:yes-on-38-campaign`. Both point to `Prop:proposition-38`. The resolver returns `ambiguous`, which is the safe result because the graph does not establish that the two Campaign identities should be merged.

## Inference usage and failures

| Stage | Provider responses | Input plus output tokens | Summed HTTP time |
| --- | ---: | ---: | ---: |
| Shared literal binder | 25 | 87,451 | 21.8103 seconds |
| Resolver over the 25 cases | 37 | 51,039 | 120.8917 seconds |
| Separate model challenges | 2 | 2,627 | 7.2162 seconds |

All 64 provider attempts returned HTTP 200 and remain in the frozen report, including 13 structured-output correction responses from the resolver batch. The paired 25-case wall time is 147.96931 seconds. The runner captured that timestamp before running the deterministic and model challenges, so the duration excludes the challenge time even though the transport totals include their two responses. The report's top-level model field is null because `LLAMA_CPP_MODEL` was absent from the environment; every captured request and response identifies the configured local model as `gemma4:26b`, served at the verified `localhost:8080` endpoint.

## Limits

The candidate ranker is lexical and exposes at most eight project identities. It records the total identity count, truncation, cutoff ties, and whether a top-score tie crosses the cutoff. The correct identity ranked first in every identity-bearing development case; Q07 has no identity slot. That does not establish semantic recall or uniqueness on new questions. An identity below the lexical cutoff cannot be selected.

Candidate discovery merges duplicate graph nodes by project id and unions their stored names, labels, and sessions. Campaign targets are deduplicated by target project id. Conflicting target names or labels for one target project id are not exposed by this prototype. Project-id merging avoids arbitrary selection among duplicate candidate rows, but it does not decide whether different project ids such as `Politician:gavin-newsom` and `Politician:newsom` are aliases. The graph contains extraction errors and unresolved aliases, so exact reference agreement measures retrieval against this graph rather than truth of the political claims.

These 25 questions are development examples with supplied correct patterns, not a formal Gold Set or an end-to-end planning evaluation. The pattern-selection experiment failed its own gate separately, so there is no combined run. The entity resolver also fails its independent gate and should not be combined in its current form.
