# Engineering log

Findings that the code cannot state about itself: behaviour of a dependency
we had to discover by experiment, and measurements taken against a corpus on
a date.

An entry is dated and never edited. That is the point of keeping them here
rather than in a docstring or an ADR — both of those describe what is
currently true and have to be maintained as the code moves, whereas an entry
below describes what was true on a day and does not become wrong when the
world changes. Every entry carries what would make its finding stale.

This is not a changelog and not a record of decisions. Architecture decisions
belong in [adr/](adr/); what a function does belongs in the function.

Newest first.

---

## 2026-09-08 — Pydantic AI spends the whole retry budget before diagnosing a truncated tool call

**Found while** capping the Coreference annotator's output.

A tool call cut off by `max_tokens` arrives with unparseable arguments.
Pydantic AI treats that as an ordinary bad-arguments retry and re-asks until
the output-retry budget is gone; only then does `consume_output_retry` call
`check_incomplete_tool_call`, notice `finish_reason == 'length'`, and raise
`IncompleteToolCall` instead of the generic retry-exhausted error. With
`retries=3` that is four generations at the same ceiling, and nothing about
the request changes between them, so all four truncate identically.

Measured against `pydantic-ai` as vendored on this date, with a `FunctionModel`
returning a truncated tool call: four model calls, then `IncompleteToolCall`.

This is why `fail_on_exhausted_budget` exists. Refusing the response in an
`after_model_request` hook ends the run on the first truncation. Without the
hook the cap made the failure slower than no cap at all: for the 1,644-word
runaway, 4 x 13,152 tokens is about 44 minutes at the ~20 tok/s the ingestion
run measured, against 23 minutes to fail with no cap.

**Stale when** Pydantic AI diagnoses truncation before consuming retries, or
stops surfacing `finish_reason` on the response. The hook is then redundant
rather than wrong. `tests/test_coreference.py` asserts the single call, so a
version that changes this fails there first.

---

## 2026-09-08 — Mention Span density is stable per 100 words; runaways are 4-6x outside it

**Found while** sizing the annotator's output budget.

104 annotator runs from the logs, joined to their article text in
`document_store.db`. Spans per 100 words: median 8.15, mean 8.30, sd 2.64,
p95 12.67, max 14.83. Density does not track article size — medians by size
bucket run 7.2 to 9.2 from under 600 words to over 1,800 — while the count
does, `r(words, spans) = 0.822`. The rate is what holds still, which is why
the budget is a rate.

Two runs in the same corpus returned ~1000 spans at 61 and 93 per 100 words,
four to six times any other article, ~99% of them failing validation. The gap
between 14.83 and 61 is wide enough that every rate from 18 to 30 per 100
words separated the two without clipping a single legitimate run. 25 was
chosen from the middle of that range: 1.7x the densest article observed.

**Stale when** the chat model, the annotator prompt, or the source mix
changes. The density figures describe local `gemma4:26b` on CalMatters
articles in September 2026 and nothing else. Re-derive before moving
`COREFERENCE_SPANS_PER_HUNDRED_WORDS` on the strength of them.

---

## 2026-09-08 — A client bound to a closed event loop reports as `Connection error.`

**Found while** reading five connectivity failures in an ingestion run.

Model clients cache an httpx connection pool whose synchronisation primitives
bind to the loop that first drove them. `asyncio.run` closes the loop it made
and clears the thread's current loop, so the next blocking call builds a fresh
one and reaches a pool bound to the loop that is gone. That raises
`RuntimeError: ... is bound to a different event loop`, which the OpenAI SDK
surfaces as the bare string `Connection error.` — indistinguishable from a
network failure.

Batch ingestion classifies connectivity errors as retryable and returns the
Story to the queue, so the defect presented as an unreliable network and
survived several runs unread. In the run of 2026-09-08 it cost five Stories
and 115 minutes.

Worth knowing because the symptom names the wrong layer. A bare
`Connection error.` from a provider SDK is worth checking against loop
lifetime before it is believed.

**Stale when** the pipeline goes async to the root, at which point
`knowledge_map.utils.event_loop` has nothing to do.
