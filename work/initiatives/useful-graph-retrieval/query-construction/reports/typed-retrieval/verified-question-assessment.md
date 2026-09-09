# Verified-question assessment

This is the assessment of the first complete 25-case follow-up batch in
`verified-question-report.json`. The catalog and prompt were frozen before the
batch. No model calls were rerun or tuned after inspecting results.

## Result

Eleven cases produced a fully scoped selection whose entities, article sets,
counts, and Grounding Evidence match the evaluator-only reference. `C-R2-02`
also produced the exact two reference rows and evidence, but its selection
omitted the question's `2025-2026` session. That current-graph match does not
make the query properly scoped. The two M1 result arrays differ from their
references only in ordering within evidence groups.

Five executed selections returned no rows because their meaning or literal
parameters were wrong. Eight more did not reach the graph because bounded
structured-output correction crossed the per-case token limit.

| Cases | Count | Assessment |
| --- | ---: | --- |
| C-E1-01, C-E1-02, C-E2-01, C-E2-02, C-E3-03, C-M1-01, C-M1-02, C-M3-01, C-M3-02, C-M4-01, C-M4-02 | 11 | Fully scoped and reference-equivalent |
| C-R2-02 | 1 | Reference-equivalent rows, but session constraint omitted |
| C-E3-01, C-E3-02 | 2 | Correct template; `housing` and `labor` did not match the persisted Policy Area names |
| C-R1-01 | 1 | Chose lobbying instead of the recorded-position query and omitted the LaborUnion and session constraints |
| C-R1-02 | 1 | Chose campaign funding instead of endorsement and shortened the Campaign name |
| C-R3-01 | 1 | Chose funded Campaign targets instead of Campaign funders and invented `Organization` as the funder |
| C-R2-01, C-R3-02, C-M2-01, C-M2-02, C-M5-01, C-M5-02, C-C1-01, C-C1-02 | 8 | Token limit during correction; no graph query |

Ten cases invoked correction. Two produced a structurally valid selection
within the limit: `C-R1-01`, whose repaired selection was semantically wrong,
and `C-R2-02`, whose rows matched but whose session scope was incomplete. The
other eight did not establish correction exhaustion. They stopped because
their cumulative token count exceeded 12,000 after a provider response.

The retained responses show distinct problems. `C-R2-01` and `C-M2-02`
generated long, repetitive relationship values and truncated JSON. `C-R3-02`
confused a PAC sub-label and candidate name with a funder and target label. The
M2 pair omitted the measure and session while returning invalid relationship
values. The M5 pair omitted measure and session. The C1 pair omitted session
and supplied invalid target labels.

## Usage and capture limit

The report retains 35 model responses with 137,247 input tokens and 8,883
output tokens, for a retained input-plus-output lower bound of 146,130 tokens.
The eight budget exceptions record each failed run's cumulative total. Combining
those totals with successful-run usage reconstructs 184,933 input-plus-output
tokens across 43 provider responses, assuming no hidden transport attempts.

Pydantic AI increments run usage and checks the token limit before appending the
budget-triggering response to captured history. Those eight response bodies are
therefore absent. Their combined 38,803 tokens cannot be split into input,
output, or cache categories, and their validity cannot be inspected. The report
supports a reconstructed total, not a complete per-category cost comparison.

## Comparison limits

The typed catalog was adapted to these 25 questions. This was a construction
batch over known examples, not a held-out evaluation. Its instruction also gave
the exact half-open bounds for July 2026. The generated-Cypher experiment did
not receive that date example. Both experiments received the same persisted
News Ontology and the same four persisted-store notes, though prompt order
differed. These differences prevent treating the result gap as a causal effect
of typed templates alone.

The semantic assessment compares exact requested values and evidence groups
where output shapes agree, and treats ordering as irrelevant. It is not an
independently adjudicated political-fact score. The reference itself measures
the current extracted graph and may contain extraction errors.
