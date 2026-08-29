# 05 — Pass a Model Deployment through the Relevance Filter

**What to build:** The production Relevance Filter and its Evaluation Task use
an explicit Model Deployment from the shared factory. Changing inference
capacity does not change the authored Evaluation Cases, training-split
few-shots, prompt, or evaluators.

**Blocked by:** 02 — Build local chat models from a Model Deployment.

Labels: ready-for-agent

- [ ] Production relevance classification constructs its agent from a supplied Model Deployment.
- [ ] The Relevance Filter Evaluation Task binds the command-selected deployment explicitly.
- [ ] Training-split few-shot selection and scoring remain unchanged.
- [ ] A conflicting stage-specific environment value cannot replace the supplied deployment.
- [ ] Existing injected-agent tests run without model credentials or live calls.

