# 20 — Aggregate Evaluation Run request provenance

**What to build:** The Evaluation Run report summarizes the request evidence it
already contains. It totals available token categories, charged and upstream
costs, attempts, retries, and rate-limit wait time, and counts requests by the
actual downstream provider and BYOK status.

**Blocked by:** 17 — Record tokens and costs for each request; 18 — Record
attempts and rate-limit waits for each request; 19 — Keep concurrent Evaluation
Case requests isolated and ordered.

Labels: ready-for-agent

- [ ] Aggregate input, output, reasoning, cache, and total tokens equal the available per-request values.
- [ ] Charged and upstream costs are summed separately without treating unavailable values as observed zero cost.
- [ ] Attempts, retries, and rate-limit wait time equal the per-request evidence.
- [ ] Request counts are grouped by downstream provider and BYOK status, including explicit unavailable groups.
- [ ] Aggregation is deterministic regardless of concurrent case completion order.
- [ ] Thin report tests cover mixed local, BYOK, funded-provider, and unavailable examples.

