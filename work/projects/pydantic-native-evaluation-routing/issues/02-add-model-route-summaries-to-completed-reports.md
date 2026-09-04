# 02: Add Model Route Summaries to completed reports

**What to build:** Add a compact `model_routes` attribute to every successful
Evaluation Case. Derive it from the task execution span tree already owned by
Pydantic Evals. The summary counts effective response-model and observed
downstream-provider pairs, making route changes visible in a committed report
without copying request telemetry into it.

Request Provenance remains in the report for this expansion ticket. Ticket 03
removes it after the replacement has end-to-end coverage.

**Blocked by:** 01, Separate model telemetry from Request Provenance.

Labels: completed

- [x] Every successful Evaluation Case serializes a deterministic
  `model_routes` collection containing response model, downstream provider or
  null, and request count.
- [x] Repeated responses with the same route pair collapse into one count, and
  different pairs remain separate in stable order.
- [x] The effective response model follows Pydantic AI telemetry, including its
  fallback to the requested model when the provider omits a response model.
- [x] Local responses and OpenRouter responses without an observed downstream
  provider serialize a null provider; configuration is never substituted.
- [x] Only completed task-model responses beneath the case task contribute.
  Evaluator model calls and requests without a response do not contribute.
- [x] Sequential multi-round Coreference Resolution contributes each completed
  task response without introducing a request-order contract.
- [x] Concurrent Evaluation Cases receive only their own route counts.
- [x] The completed report retains Pydantic Evals request, token, and
  calculated-cost metrics and the existing commit, dirty-worktree, Data Set,
  split, and Model Deployment fields.
- [x] Historical reports are not rewritten, and failed, interrupted, or
  exhausted Evaluation Runs still write no report.
- [x] End-to-end report tests use deterministic mock transports and cover
  grouping, mixed routes, response-model fallback, missing providers,
  sequential task calls, concurrent cases, evaluator exclusion, and requests
  without responses.
