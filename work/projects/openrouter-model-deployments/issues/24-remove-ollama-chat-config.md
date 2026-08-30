# 24 — Remove obsolete Ollama chat configuration

**What to build:** Runtime configuration names the two chat Model Deployments
that now exist: one local llama.cpp model and one OpenRouter model with its
approved providers. Obsolete global and stage-specific Ollama chat names leave
runtime code, examples, tests, messages, and operational instructions without a
compatibility fallback.

**Blocked by:** 03 — Pass a Model Deployment through Coreference Resolution;
04 — Pass a Model Deployment through Entity Extraction; 05 — Pass a Model
Deployment through the Relevance Filter; 06 — Pass a Model Deployment through
Selector Healing; 14 — Select and record an Evaluation Run Model Deployment;
22 — Select one Story Pipeline chat deployment.

Labels: completed

- [x] Configuration supplies one local chat model and one OpenRouter chat model plus its API key and non-empty ordered provider list.
- [x] No runtime path reads the obsolete global or stage-specific Ollama chat model names.
- [x] Example environment values, tests, error messages, and operator instructions use the new deployment vocabulary.
- [x] No compatibility fallback silently reactivates an obsolete chat name.
- [x] Embedding configuration remains local and is changed only where an obsolete name still contradicts the current llama.cpp embedding deployment.
- [x] A repository search and the deterministic suite confirm the contraction is complete.
