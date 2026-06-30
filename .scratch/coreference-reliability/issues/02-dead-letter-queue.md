Status: completed

## Parent

[.scratch/coreference-reliability/PRD.md](file:///Users/akaisenghor/Projects/california-political-knowledge-map/.scratch/coreference-reliability/PRD.md)

## What to build

Create a Dead Letter Queue (DLQ) using the adapter pattern to capture detailed information about coreference resolution failures.

- Define a `DeadLetterQueueAdapter` protocol with a `log_failure(self, url: str, title: str, original_text: str, annotated_text: str, validation_issues: list[str], failure_type: str, retry_count: int, metadata: dict)` method.
- Implement `LocalFileDLQAdapter` that implements this protocol, writing JSON files containing the failure payload to `.scratch/coreference_dlq/`.
- Ensure filename naming format uses the domain, a SHA256 hash of the URL, current timestamp, failure type, and retry count: `{domain}_{url_hash}_{timestamp}_{failure_type}_retry_{retry_count}.json`.
- Safeguard file writes by catching any filesystem operational errors, logging a warning, and propagating the error (which will transition state to `SYSTEM_ERROR` in the orchestrator).
- Hook up DLQ logging to the coreference resolution pipeline so that when coreference fails to resolve, a DLQ record is written.

## Acceptance criteria

- [x] `DeadLetterQueueAdapter` protocol is defined.
- [x] `LocalFileDLQAdapter` is implemented to write JSON documents to `.scratch/coreference_dlq/`.
- [x] Filenames are generated using `{domain}_{url_hash}_{timestamp}_{failure_type}_retry_{retry_count}.json` to avoid collision/length issues.
- [x] JSON payload schema matches all fields in the PRD (url, title, original_text, failed annotated_text, validation_issues, failure_type, timestamp, agent metadata).
- [x] Filesystem write errors are caught, a warning is logged, and the error is reraised to allow the pipeline to crash.
- [x] Unit tests verify successful DLQ file creation, formatting, naming conventions, and file-write failure behavior.

## Blocked by

- [.scratch/coreference-reliability/issues/01-structural-identity-check.md](file:///Users/akaisenghor/Projects/california-political-knowledge-map/.scratch/coreference-reliability/issues/01-structural-identity-check.md)
