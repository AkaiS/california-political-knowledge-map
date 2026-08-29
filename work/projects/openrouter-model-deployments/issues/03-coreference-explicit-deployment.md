# 03 — Pass a Model Deployment through Coreference Resolution

**What to build:** Coreference Resolution receives one explicit Model
Deployment and uses it for both the Coreference Annotator and Coreference
Critic. Production resolution and both coreference Evaluation Tasks stop
resolving stage-specific model names from ambient environment variables.

**Blocked by:** 02 — Build local chat models from a Model Deployment.

Labels: ready-for-agent

- [ ] The Coreference Annotator and Coreference Critic obtain their models through the shared factory from the same supplied deployment.
- [ ] The full Coreference Resolution Evaluation Task and annotator-only task bind their selected deployment explicitly.
- [ ] Agent injection and overrides used by deterministic tests still work without live model credentials.
- [ ] A conflicting stage-specific environment value cannot replace the supplied deployment.
- [ ] Existing Coreference Resolution behavior and focused tests remain green with a local deployment.

