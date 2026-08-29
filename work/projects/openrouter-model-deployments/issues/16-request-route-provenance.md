# 16 — Record the actual OpenRouter route for each request

**What to build:** Each model request in an Evaluation Run reports the actual
route returned by OpenRouter. The record identifies its Evaluation Case and
captures the returned model, selected downstream provider, generation identity,
and BYOK status. Missing route fields remain explicitly unavailable rather than
being guessed.

**Blocked by:** 08 — Constrain every OpenRouter route; 14 — Select and record an
Evaluation Run Model Deployment.

Labels: ready-for-agent

- [ ] A one-request Evaluation Case produces one request record associated with the authored case id.
- [ ] Returned model, downstream provider, generation identity, and BYOK status are normalized from response metadata when present.
- [ ] Missing response fields serialize as explicit unknown or unavailable values.
- [ ] A local request identifies llama.cpp and leaves remote route and BYOK facts unavailable.
- [ ] API keys, authorization headers, and direct Google credentials cannot enter the normalized record, report, log, or exception.
- [ ] A real Agent call through a mock OpenRouter response proves the complete route-to-report path.

