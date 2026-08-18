# 04 — Per-Mention-Span Critic verdicts and targeted retry

**What to build:** The Coreference Critic judges each reference individually
instead of passing or failing the article as a whole, so one misread pronoun
stops costing its correct neighbours.

The Critic receives the numbered sentences once and the list of validated Mention
Spans, and returns a verdict per Mention Span: which one it refers to, accept or
reject, and a short reason when rejecting. Its context drops from roughly two
copies of the article — the original and the annotated text it receives today —
to one copy plus a compact list.

Rejected Mention Spans are discarded individually. When the retry budget allows,
the annotator is re-asked for the rejected Mention Spans only, given the Critic's
reasons; accepted ones are not re-derived. The article-level pass or fail
response shape is replaced, not extended.

Two model calls per article remain the accepted cost. Each call now makes a
narrower judgement than before.

**Blocked by:** 03 — Annotator returns Mention Spans, wired end to end.

Labels: completed

- [x] The Coreference Critic receives the numbered sentences once and the validated Mention Spans, and does not receive a second copy of the article text.
- [x] The Critic returns one verdict per Mention Span, each identifying the Mention Span it judges, an accept or reject decision, and a reason when it rejects.
- [x] The article-level pass or fail response shape is removed rather than kept alongside the per-Mention-Span verdicts.
- [x] A rejected Mention Span is discarded while accepted Mention Spans in the same article are applied.
- [x] A verdict naming a Mention Span that was not sent to the Critic is ignored and cannot alter the resolved text.
- [x] A Mention Span that receives no verdict is discarded rather than applied.
- [x] A retry re-asks the annotator only for the rejected Mention Spans, supplying the Critic's reasons, and leaves accepted Mention Spans untouched.
- [x] Retries remain bounded by the existing retry budget.
- [x] A retry that corrects a rejected Mention Span produces resolved text containing both the corrected reference and the originally accepted ones.
