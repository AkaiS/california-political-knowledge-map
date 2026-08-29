# 11 — Pause every OpenRouter caller after a 429

**What to build:** A rate limit observed by any OpenRouter request closes one
process-wide admission gate. Requests already admitted may finish, but new
requests from every OpenRouter model instance wait. Concurrent `429` responses
may extend the pause and can never shorten it. Local llama.cpp requests remain
outside the gate.

**Blocked by:** 10 — Honor OpenRouter rate-limit timing for one request.

Labels: ready-for-agent

- [ ] Concurrent real Agent calls through mock transports show one `429` preventing every new OpenRouter request from starting.
- [ ] OpenRouter models with different non-secret identities still share the same process-wide gate.
- [ ] A later deadline replaces an earlier deadline, while an earlier deadline cannot shorten an active pause.
- [ ] Requests admitted before the gate closes may complete.
- [ ] Local Model Deployment requests continue while OpenRouter admission is paused.
- [ ] Tests use controlled clocks and coordination hooks rather than inspecting private gate state.

