# 06 — Pass a Model Deployment through Selector Healing

**What to build:** Selector Healing receives one explicit Model Deployment and
uses it for both its Generator and Critic. Its prompts, review workflow, and
stored proposals remain unchanged.

**Blocked by:** 02 — Build local chat models from a Model Deployment.

Labels: completed

- [x] The Selector Healing Generator and Critic obtain models through the shared factory from the same supplied deployment.
- [x] A conflicting stage-specific environment value cannot replace the supplied deployment.
- [x] Existing agent injection and deterministic Selector Healing tests continue to avoid live inference.
- [x] Selector proposal and review behavior is unchanged with a local deployment.
