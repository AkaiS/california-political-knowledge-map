# 02 — The Story Pipeline stops retrying stage calls

**What to build:** The Story Pipeline goes back to being orchestration. Reading
it tells you the stage order, the Article Status transitions, and the Dead
Letter Queue routing, with no backoff arithmetic in the middle.

An exhausted transport retry still surfaces as the pipeline error categories
that batch ingestion locks on, raised at one seam that maps the final HTTP
status rather than by walking exception chains and substring-matching error
text.

This is the contract half of 01: the old path is deleted now that the new one
carries the load.

**Blocked by:** 01 — A retrying HTTP client behind every Ollama model.

Labels: ready-for-agent

- [x] An exhausted transport retry reaching the Story Pipeline surfaces as `PipelineRateLimitError` when the final response was a 429 and as `PipelineConnectivityError` otherwise, carrying the failing component.
- [x] An article whose transport retries are exhausted returns to `UNPROCESSED`.
- [x] `_execute_with_retry` no longer exists in the Story Pipeline.
- [x] `classify_api_error` and `get_retry_after` are deleted, along with the tests asserting on them.
- [x] `classify_exception`, which routes Dead Letter Queue-worthy errors, is unchanged.
- [x] The embedding stage still retries, since it does not pass through the model factory.
  It retries at the failed request rather than by re-running the stage: the
  embedding adapter builds the same retrying HTTP client the model factory
  uses, which is what the wrapper the PRD describes is for. Asserted in
  `tests/test_embedding.py` through a real embedding call against an
  `httpx.MockTransport` — a rate limit honoured from the `Retry-After`
  header, an exhausted attempt count, and the exhaustion surfacing as
  `PipelineConnectivityError` for the `embedding` component.
- [x] The four backoff tests that patch `time.sleep` and assert delay sequences and call counts are deleted, replaced by assertions on the resulting pipeline error, component, and Article Status.
- [x] Batch ingestion's consecutive-failure locking behaves exactly as before and its existing test passes unchanged.
- [x] A coreference failure still reaches the Dead Letter Queue and still leaves the article `FAILED_DLQ`.
