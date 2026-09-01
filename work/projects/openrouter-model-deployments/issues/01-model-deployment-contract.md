# 01 — Define the Model Deployment contract

**What to build:** A Model Deployment is a typed, serializable description of
the concrete chat deployment an Evaluation Run or Story Pipeline command will
use. It names the deployment kind, requested model, effective request settings,
and deployment-specific route without carrying either API key.

The contract is narrow. It describes only local llama.cpp and OpenRouter chat.
It does not add remote embeddings, model fallback, quota estimates, or a
spending limit.

**Blocked by:** None — can start immediately.

Labels: completed

- [x] Local and OpenRouter are the only accepted deployment kinds.
- [x] A deployment carries the requested model and explicit sampling, reasoning, output, and request-limit settings that the factory needs.
- [x] Local identity can carry its endpoint, and OpenRouter identity can carry its ordered provider policy.
- [x] Validation rejects incomplete or internally inconsistent deployment values before a model request can start.
- [x] Serialization, equality, and hashing exclude API keys and authorization headers.
- [x] Focused tests show that two deployments sharing an upstream model remain distinct values.
