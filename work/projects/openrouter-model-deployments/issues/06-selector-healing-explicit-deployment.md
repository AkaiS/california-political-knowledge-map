# 06 — Pass a Model Deployment through Selector Healing

**What to build:** Selector Healing receives one explicit Model Deployment and
uses it for both its Generator and Critic. Its prompts, review workflow, and
stored proposals remain unchanged.

**Blocked by:** 02 — Build local chat models from a Model Deployment.

Labels: ready-for-agent

- [ ] The Selector Healing Generator and Critic obtain models through the shared factory from the same supplied deployment.
- [ ] A conflicting stage-specific environment value cannot replace the supplied deployment.
- [ ] Existing agent injection and deterministic Selector Healing tests continue to avoid live inference.
- [ ] Selector proposal and review behavior is unchanged with a local deployment.

