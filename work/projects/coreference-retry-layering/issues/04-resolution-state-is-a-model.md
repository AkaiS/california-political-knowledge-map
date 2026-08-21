# 04 — Prefactor: the resolution loop's state becomes a model

**What to build:** No behavior change. The resolution loop's state moves out of
five local variables into one model that owns the rule they currently obey by
ordering: one final outcome per Mention Span identity, last write winning, so a
Mention Span rejected in one round and corrected in the next is recorded once
with the decision the run ended on.

This is the prefactor that makes 05 easy. Once the partial run is something the
state can hand over, narrowing the exception handler stops being surgery.

It also sweeps up three cleanups in the same file: a resolution helper with no
callers, structured output validated a second time at three call sites, and a
retry budget whose name does not say which retries it counts.

**Blocked by:** None — can start immediately. Note that 03 rewrites the same
resolver loop; working the two in parallel will conflict.

Labels: ready-for-agent

- [ ] One model holds the numbered sentence records, every observed Mention Span, the outcome map keyed by Mention Span identity, the accepted located spans, and the critic round count.
- [ ] That model exposes the recording operations and the conversion to a Coreference Resolution Run.
- [ ] The last-write-wins rule for a Mention Span corrected across rounds is enforced by the state rather than by loop ordering.
- [ ] A correction response containing a Mention Span that was not a retry target is still excluded from the outcome map and cannot reach the resolved text.
- [ ] The discard proportion is computed by the state that holds the outcomes.
- [ ] The redundant structured-output re-validation is removed at all three call sites.
- [ ] The text-only `resolve_coreferences` helper is deleted; the run-returning function is the only way to resolve a Source Article.
- [ ] The critic round budget is renamed for what it counts and moves into a coreference settings block, distinct from the agents' structured-output retry budget.
- [ ] Every behavioral test in the coreference suite passes without modification.
