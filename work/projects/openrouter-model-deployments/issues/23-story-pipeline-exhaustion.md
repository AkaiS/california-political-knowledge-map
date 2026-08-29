# 23 — Preserve Story Pipeline failure handling after exhaustion

**What to build:** When an OpenRouter request exhausts its bounded attempts, the
failure re-enters the Story Pipeline's existing failure path. A later batch may
retry the Story, and model-output failures retain their established Dead Letter
Queue behavior. Remote deployment support does not silently lose or complete a
failed Story.

**Blocked by:** 13 — Adapt OpenRouter request admission after probes; 22 —
Select one Story Pipeline chat deployment.

Labels: ready-for-agent

- [ ] Exhausted retryable transport and rate-limit failures retain the existing retry-later Article Status behavior.
- [ ] Non-retryable provider failures surface immediately through the established pipeline error translation.
- [ ] Existing Coreference Resolution and Entity Extraction validation failures retain their Dead Letter Queue behavior.
- [ ] A failed Story is never marked completed and may be selected by a later batch according to existing rules.
- [ ] Focused Story Pipeline tests use injected adapters or mock transports and make no live provider calls.

