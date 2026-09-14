# Experiment 3: Bill Designation binding

## Hypothesis

The positional binder can avoid a class of Bill-name misses if code applies the
repository's Bill Designation contract before generic entity resolution. When
the model binds an answer-type phrase instead of the bill, a retry that names
the accepted forms and points out the designation already present in the
question should be more useful than the generic `no canonical entity match`
message.

## Exact delta

The atomic deterministic hydration binder now inspects only slots whose label
is `Bill` and whose property is `name`. It passes each such value to
`parse_bill_designation` from `knowledge_map.core.bill_sessions`. Accepted
values are normalized to `SB N` or `AB N` before the existing entity resolver
runs.

An invalid value stops that attempt before graph candidate lookup. Its
validation record states the four accepted forms and preserves the rejected
value. If the same parser finds a Bill Designation in the question, the error
also tells the binder to use that designation instead of another question
phrase. The existing retry loop includes the specific errors in the next
prompt. This adds no agent or graph call.

Focused offline tests cover `SB N`, `AB N`, `Senate Bill N`, and
`Assembly Bill N`; reject ordinary nouns, a generic bill reference, and bare
digits; and verify that the retry receives both the rejected phrase and the
normalized designation found in the question.

## Generality and contamination audit

The change keys off the compiled slot's ontology label and property, not a case
identifier, question text, bill number, answer, or expected result. It applies
to every `Bill.name` equality slot produced by this prototype. All matching and
normalization come from the ingestion-side Bill Designation parser, so the
experiment does not introduce a second regular expression or a competing
vocabulary.

The question-derived hint contains only a value already visible to the binder.
It does not inspect reference queries, graph rows, saved reports, oracle values,
or evidence. Other entity names, sessions, and dates retain their prior
binding and resolution behavior.

## Tradeoffs

`parse_bill_designation` returns the first supported designation in a string.
That matches the existing repository contract and is enough for questions with
one Bill-name slot. A question that names several bills needs a separate rule
for assigning designations to slots; this experiment does not invent one.

Invalid Bill values now spend an existing retry before generic graph lookup.
That is intentional because a stored entity named like an ordinary question
phrase cannot satisfy the Bill Designation contract. The final failure record
is more specific. The commit-level experiment did not run the 25-case model
evaluation. The later
[five-experiment comparison](atomic-five-experiment-comparison.md) did: the
retry recovered `C-C1-02` without changing any other case's classification or
failure stage.
