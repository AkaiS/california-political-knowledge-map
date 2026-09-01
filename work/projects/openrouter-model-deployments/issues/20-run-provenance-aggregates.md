# 20 — Aggregate Evaluation Run request provenance

**What to build:** The Evaluation Run report summarizes the request evidence it
already contains. It totals available token categories, charged and upstream
costs, attempts, and retries, and counts requests by the actual downstream
provider and BYOK status.

**Blocked by:** 17 — Record tokens and costs for each request; 18 — Record
attempts for each request; 19 — Keep concurrent Evaluation
Case requests isolated and ordered.

Labels: completed

- [x] Aggregate input, output, reasoning, cache, and total tokens equal the available per-request values.
- [x] Charged and upstream costs are summed separately without treating unavailable values as observed zero cost.
- [x] Attempts and retries equal the per-request evidence.
- [x] Request counts are grouped by downstream provider and BYOK status, including explicit unavailable groups.
- [x] Aggregation is deterministic regardless of concurrent case completion order.
- [x] Thin report tests cover mixed local, BYOK, funded-provider, and unavailable examples.
