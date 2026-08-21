# 05 — Only model-output failures are recorded as validation failures

**What to build:** A socket timeout that outlives its retries reaches the Story
Pipeline as a system error instead of being archived in the Dead Letter Queue as
a coreference validation failure.

The resolver currently wraps its whole body in a broad exception handler that
labels anything escaping it a `coreference_validation_failure`, so an
infrastructure problem is filed as a prompt-quality problem and pollutes the
corpus that prompt work is done against.

A resolution also gains a ceiling that is not a round count, so an annotator
returning hundreds of Mention Spans is stopped by a limit rather than by
patience.

**Blocked by:** 04 — Prefactor: the resolution loop's state becomes a model.

Labels: ready-for-agent

- [x] The escaping exception handler catches only Pydantic validation errors and pydantic-ai's unexpected-behavior error.
- [x] Anything else propagates and is handled by the Story Pipeline as a system error, leaving the article `SYSTEM_ERROR` rather than `FAILED_DLQ`.
  As written this criterion names one of two correct outcomes, and the
  socket timeout this issue opens with is the other one. What holds in
  every case is that the failure is not archived as a
  `coreference_validation_failure`. Where it goes instead depends on what
  fixes it: a transport failure that outlived its retries is translated by
  the pipeline's transport seam into `PipelineConnectivityError` or
  `PipelineRateLimitError` and returns the article to `UNPROCESSED`, per
  PRD user story 9, because the next batch run may well succeed. Anything
  that is neither a model-output failure nor a transport failure — a
  programming error, an exhausted usage limit — leaves the article
  `SYSTEM_ERROR`, because neither re-running the batch nor rewriting a
  prompt is what fixes it. Both paths are implemented and asserted in
  `tests/test_batch.py`.
- [x] A model-output failure still produces a Dead Letter Queue record carrying the partial Coreference Resolution Run.
- [x] Each resolution runs under a request limit and a total token limit.
- [x] A resolution that exceeds either limit fails rather than continuing.
- [x] The limits are configured in the coreference settings block alongside the critic round budget.
- [x] Every behavioral test in the coreference suite passes without modification.
