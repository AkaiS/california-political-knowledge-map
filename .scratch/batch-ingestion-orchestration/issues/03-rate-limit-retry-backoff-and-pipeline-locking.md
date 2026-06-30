Status: completed

## Parent

[.scratch/batch-ingestion-orchestration/PRD.md](file:///Users/akaisenghor/Projects/california-political-knowledge-map/.scratch/batch-ingestion-orchestration/PRD.md)

## What to build

Build a comprehensive retry and backoff system for adapters, and implement consecutive error tracking with a pipeline locking mechanism.

- **Exception Classification:** Identify `RATE_LIMIT` (e.g., HTTP 429) and `CONNECTIVITY` (e.g., timeouts, sockets) error types.
- **Connectivity Retries:** Retry connectivity errors up to 3 times with progressive backoff before failing.
- **Rate Limit Handlers:**
  - Parse the `Retry-After` header. If the delay is within our configured wait cap (e.g., 120 seconds), sleep and retry.
  - If the delay exceeds the cap, skip the current article, increment the consecutive rate limit failures counter, and move to the next article.
  - If the header is missing, fall back to a longer exponential backoff schedule (final retry waits at least 60 seconds).
- **Consecutive Error Locking:**
  - Track consecutive rate limit failures across different articles. A successful article resets this counter.
  - If consecutive rate limit failures reach 3, halt ingestion and write a JSON lock file to `.scratch/pipeline.lock`.
  - The lock file must specify the locked `component`, the `timestamp` of the lock, and the last `error_message`.
- **Fail-Fast Startup:** Check for the existence of `.scratch/pipeline.lock` at startup and abort execution if it is present.

## Acceptance criteria

- [x] Exception classification helper identifies `RATE_LIMIT` and `CONNECTIVITY` error types.
- [x] Connectivity errors trigger up to 3 retries using progressive backoff.
- [x] Rate limits parse the `Retry-After` header to dynamically sleep.
- [x] Ingestion service skips the current article and proceeds if `Retry-After` exceeds the wait cap.
- [x] Rate limits without `Retry-After` headers trigger exponential backoff reaching at least 1 minute on the final attempt.
- [x] Ingestion service tracks consecutive rate limit failures and resets the count on successful article ingestion.
- [x] Ingestion halts and writes `.scratch/pipeline.lock` if consecutive rate limit failures reach 3.
- [x] Lock file contains JSON schema specifying: `timestamp`, `component`, and `error_message`.
- [x] Ingestion service checks for `.scratch/pipeline.lock` at startup and aborts execution if it exists.
- [x] Mock-driven unit tests verify progressive retries, backoff, skipping, consecutive error counting, lock file writing, and fail-fast behavior.

## Blocked by

- [.scratch/batch-ingestion-orchestration/issues/02-non-breaking-failures-dlq.md](file:///Users/akaisenghor/Projects/california-political-knowledge-map/.scratch/batch-ingestion-orchestration/issues/02-non-breaking-failures-dlq.md)
