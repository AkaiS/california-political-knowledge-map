# 07 — Build a native OpenRouter chat model

**What to build:** The shared factory can turn an OpenRouter Model Deployment
into Pydantic AI's native OpenRouter model and provider. A fixed requested model
and applicable shared request settings reach the provider without borrowing the
llama.cpp compatibility profile or null-content workaround.

**Blocked by:** 02 — Build local chat models from a Model Deployment.

Labels: completed

- [x] A real Pydantic AI Agent built from an OpenRouter deployment completes against an injected mock HTTP transport.
- [x] The configured API key reaches only the provider client and never enters the Model Deployment or cache identity.
- [x] The request carries exactly one requested model and no model fallback list.
- [x] Temperature, top-p, top-k, reasoning or thinking mode, and applicable output and request limits reach the request when supported.
- [x] OpenRouter uses its own model profile rather than llama.cpp schema or message workarounds.
- [x] Tests require no live OpenRouter credentials or network calls.
