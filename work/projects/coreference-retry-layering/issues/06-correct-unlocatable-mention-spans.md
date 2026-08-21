# 06 — An annotator whose Mention Spans cannot be located is asked again

**What to build:** When every Mention Span the annotator returned fails
deterministic validation, the annotator is told why and asked to correct itself
before the Coreference Resolution Run becomes a Dead Letter Queue record.

An unknown sentence label, or a mention text that does not occur where it was
claimed, is exactly the mistake an annotator can fix when told. Today it is
archived as `all_mentions_discarded` without the annotator ever hearing about
it.

This lands last because it changes which runs reach the Dead Letter Queue.
Measure it against the existing `all_mentions_discarded` and
`coreference-validation-failure` records under `.scratch/dlq/coreference/`.

**Blocked by:** 03 — Coreference agents take dependencies. The validator reads
the Source Article out of the agent's dependencies. Recommended after 05 so the
Dead Letter Queue corpus it is measured against is already clean of transport
failures, though 05 does not gate it.

Labels: ready-for-agent

- [ ] The annotator has an output validator that runs deterministic Mention Span validation against the Source Article in its dependencies.
- [ ] When the annotator returned Mention Spans and none can be located, the validator asks the model to try again, carrying the discard reasons.
- [ ] That correction is bounded by the agent's structured-output retry budget.
- [ ] A response with at least one locatable Mention Span passes the validator, and its unlocatable Mention Spans remain recorded discards.
- [ ] An empty Mention Span list is not a retry; `no_mentions_returned` remains a distinct failure type.
- [ ] `all_mentions_discarded` remains a failure type, reached only once the correction budget is exhausted.
- [ ] The Coreference Resolution Run's round count reflects the correction attempts, so an exhausted run is distinguishable from a first-response failure in the Dead Letter Queue payload.
- [ ] A test shows an annotator citing an unknown sentence label being corrected on its second response and producing resolved text.
- [ ] A test shows a persistently unlocatable annotator reaching the Dead Letter Queue as `all_mentions_discarded`.
- [ ] Every behavioral test in the coreference suite passes without modification.
