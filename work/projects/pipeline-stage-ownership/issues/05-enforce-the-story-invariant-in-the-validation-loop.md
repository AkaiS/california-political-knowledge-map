# Enforce the story invariant in the validation loop

Labels: ready-for-agent

## Parent

[Pipeline Stage Ownership: Validation, Relevance, and Raw HTML Lifecycle](../PRD.md)

## What to build

Validation state answers exactly one question — do we hold extracted content for
this article? After this ticket the answer is never ambiguous:

> `validation = 'VALIDATED'` if and only if a Story row exists for that URL.

The loop stops running relevance unconditionally. Classification runs only when
`relevance_status` is `'PENDING'`, so no decision — human or automated — is ever
recomputed, and an article carrying a settled decision reaches neither the model
weights, the embedding adapter, nor the LLM agent. On success the loop ensures
headline, description, and embedding are populated regardless of whether
classification ran.

Each branch then resolves cleanly. A relevant article gets a Story with its links
at `UNPROCESSED`, is marked `'VALIDATED'`, and immediately loses its raw HTML —
the database should not retain content it has already extracted. An irrelevant or
inconclusive article gets no Story and returns to null validation. Keeping
inconclusive articles at null rather than validated is deliberate: they hold no
content, so claiming validation would break the invariant, and a later human
decision must be able to queue them for extraction.

Because irrelevant articles no longer produce Story rows, `'IRRELEVANT'` leaves
the Story status vocabulary here, where its writer is removed.

The loop also stops selecting articles with no cached HTML. Ground-truth
extraction raises on absent markup, the loop's outer handler swallows it, no
status is written, and the row re-enters the queue on every subsequent run — a
silent, permanent retry that this selection change ends.

## Acceptance criteria

- [ ] Relevance classification is not invoked at all — not the weight loader, the embedding adapter, or the LLM agent — for an article whose `relevance_status` is not `'PENDING'`.
- [ ] An article whose relevance is `'PENDING'` is classified and the decision persisted through the guarded relevance writer.
- [ ] A relevant article ends at `'VALIDATED'` with a Story row and its links, and with no raw HTML remaining.
- [ ] An irrelevant article ends with null validation, no Story row, and its classification recorded.
- [ ] An inconclusive article ends with null validation and no Story row.
- [ ] The invariant holds after every branch: a Story row exists exactly when validation is `'VALIDATED'`.
- [ ] Extraction failure still yields `VALIDATION_FAILED` and accrues failure points as today, and absent JSON-LD ground truth still yields `UNVALIDATABLE`.
- [ ] An article with no cached raw HTML is not selected by the validation loop.
- [ ] `'IRRELEVANT'` is rejected by the Story status constraint and no code path attempts to write it.
- [ ] Headline, description, and embedding are populated after successful extraction even when classification was skipped.
- [ ] The full deterministic test suite passes.

## Blocked by

- 03 — Default relevance to PENDING and record fetch status.
- 04 — Give relevance and validation disjoint writers.
