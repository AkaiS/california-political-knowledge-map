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

- [ ] An exhausted transport retry reaching the Story Pipeline surfaces as `PipelineRateLimitError` when the final response was a 429 and as `PipelineConnectivityError` otherwise, carrying the failing component.
- [ ] An article whose transport retries are exhausted returns to `UNPROCESSED`.
- [ ] `_execute_with_retry` no longer exists in the Story Pipeline.
- [ ] `classify_api_error` and `get_retry_after` are deleted, along with the tests asserting on them.
- [ ] `classify_exception`, which routes Dead Letter Queue-worthy errors, is unchanged.
- [ ] The embedding stage still retries, since it does not pass through the model factory.
- [ ] The four backoff tests that patch `time.sleep` and assert delay sequences and call counts are deleted, replaced by assertions on the resulting pipeline error, component, and Article Status.
- [ ] Batch ingestion's consecutive-failure locking behaves exactly as before and its existing test passes unchanged.
- [ ] A coreference failure still reaches the Dead Letter Queue and still leaves the article `FAILED_DLQ`.
