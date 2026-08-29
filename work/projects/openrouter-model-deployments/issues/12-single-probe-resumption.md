# 12 — Resume a paused route with one probe

**What to build:** When the shared OpenRouter pause expires, exactly one waiting
caller receives permission to probe the route. Other callers remain held until
that probe succeeds or another rate limit establishes a new pause.

**Blocked by:** 11 — Pause every OpenRouter caller after a 429.

Labels: ready-for-agent

- [ ] A controlled-clock concurrency test shows that only one request begins at the pause deadline.
- [ ] Other waiting callers remain blocked while the probe is pending.
- [ ] A successful probe permits waiting work to resume under the current working limit.
- [ ] A probe that receives another `429` closes the gate again without releasing the waiting burst.
- [ ] Probe behavior is observed through real Agent calls and mock transports, not private controller fields.

