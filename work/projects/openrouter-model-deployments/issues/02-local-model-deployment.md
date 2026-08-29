# 02 — Build local chat models from a Model Deployment

**What to build:** The shared model factory accepts a local Model Deployment and
produces the same working llama.cpp-backed Pydantic AI model used today. The
local compatibility profile, inlined schemas, native structured output,
thinking switch, and null-content workaround remain intact and do not become
defaults for another deployment kind.

**Blocked by:** 01 — Define the Model Deployment contract.

Labels: ready-for-agent

- [ ] A real Pydantic AI Agent built from a local Model Deployment completes against an injected mock HTTP transport.
- [ ] The request uses the configured llama.cpp endpoint, requested model, and applicable explicit request settings.
- [ ] Schema inlining, native structured output, and the llama.cpp profile still reach local requests.
- [ ] The null-content workaround applies to local requests only.
- [ ] Repeated construction shares a model and connection pool only when the complete local deployment identity agrees.
- [ ] Local transport retries retain their existing bounded behavior.

