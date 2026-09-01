# 13 — Adapt OpenRouter request admission after probes

**What to build:** The process-wide controller maintains a working OpenRouter
request-admission limit at or below the operator's ceiling. Successful requests
restore capacity gradually after a probe. Another `429` lowers working
concurrency and pauses admission again.

**Blocked by:** 12 — Resume a paused route with one probe.

Labels: completed

- [x] Successful requests increase working admission gradually and never above the configured ceiling.
- [x] A new `429` lowers working admission and closes the shared gate.
- [x] Repeated success can restore admission to the operator's ceiling.
- [x] The controller reacts only to observed request outcomes and performs no proactive token counting or fixed-quota scheduling.
- [x] Concurrent Agent tests demonstrate reduction and restoration using controlled coordination rather than wall-clock sleeps or private-state assertions.
