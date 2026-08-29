# 22 — Select one Story Pipeline chat deployment

**What to build:** A Story Pipeline command selects one Model Deployment for
all of its chat-backed stages. Local remains the default. An explicit
OpenRouter selection applies to Coreference Resolution and Entity Extraction,
while the Embedding Adapter and its Neo4j vector space remain local. Incomplete
OpenRouter configuration fails before a Story changes status.

**Blocked by:** 03 — Pass a Model Deployment through Coreference Resolution;
04 — Pass a Model Deployment through Entity Extraction; 08 — Constrain every
OpenRouter route.

Labels: ready-for-agent

- [ ] Story Pipeline command assembly accepts local and OpenRouter deployment selections and defaults to local.
- [ ] One selected deployment is passed explicitly to both Coreference Resolution and Entity Extraction.
- [ ] The Embedding Adapter still uses the configured local embedding server and model under either chat selection.
- [ ] Missing OpenRouter API key, requested model, or provider list fails before a Story enters processing.
- [ ] An explicit OpenRouter selection is visible in mock requests from both chat stages.
- [ ] Existing injected-adapter Story Pipeline tests remain deterministic and require no model credentials.

