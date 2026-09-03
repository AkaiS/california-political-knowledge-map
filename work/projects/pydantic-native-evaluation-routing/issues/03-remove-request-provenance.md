# 03: Remove Request Provenance

**What to build:** Complete the contract change. New Evaluation Run reports keep
their Model Route Summaries and Pydantic Evals metrics but stop recording a
parallel request ledger. Remove the custom capture, aggregation, and failure
serialization machinery once no report behavior depends on it.

**Blocked by:** 02, Add Model Route Summaries to completed reports.

Labels: completed

- [x] New reports contain neither per-request provenance nor a run-level
  provenance aggregate.
- [x] The custom request provenance schema, capture context, request sequence,
  retry-state recorder, aggregate builder, and public exports are deleted.
- [x] Evaluation execution no longer opens a provenance capture scope or stores
  request records by case.
- [x] Failure objects are no longer mutated with request records, and report
  serialization no longer repairs those dynamic attributes.
- [x] Model Route Summaries remain limited to successful Evaluation Cases.
- [x] Pydantic Evals metrics, evaluator output, and the Evaluation Run's outer
  provenance remain unchanged.
- [x] Model-request telemetry and the structured OpenRouter completion event
  introduced or preserved by ticket 01 remain intact.
- [x] Failed, interrupted, and exhausted Evaluation Runs continue to write no
  report.
- [x] Historical reports and completed project records are not rewritten.
- [x] Tests of capture scopes, request sequencing, custom aggregation, failure
  mutation, and synthetic same-case parallel ordering are removed with the
  implementation they covered.
- [x] The completed-report tests prove the final public contract contains
  `model_routes` and no retired provenance fields.
