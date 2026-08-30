# 25 — Reconcile Model Deployment documentation

**What to build:** The project documentation describes the two chat Model
Deployments that actually run. It explains command defaults and overrides,
OpenRouter BYOK and approved fallback routing, reactive rate control, report
provenance, and why an OpenRouter Evaluation Run is directional evidence rather
than proof that the local deployment behaves identically.

**Blocked by:** 20 — Aggregate Evaluation Run request provenance; 21 — Write no
report after exhausted inference; 23 — Preserve Story Pipeline failure handling
after exhaustion; 24 — Remove obsolete Ollama chat configuration.

Labels: completed

- [x] The domain glossary retains Model Deployment as the canonical term and describes the local and OpenRouter distinction accurately.
- [x] ADR 0017 records structured Model Deployment and request provenance without adding a ledger, remote run identity, or resumption.
- [x] ADR 0019 retains the local llama.cpp structured-output decision and explains the removal of obsolete Ollama chat names.
- [x] Operator guidance covers both command defaults, overrides, required environment values, provider order, BYOK behavior, funded fallbacks, and reactive rate limits.
- [x] Report guidance explains route, BYOK, token, cost, attempt, wait, and unavailable fields without claiming deployment equivalence.
- [x] Documentation states that embeddings remain local and that no fixed quotas, token scheduler, or application spending ceiling were added.
