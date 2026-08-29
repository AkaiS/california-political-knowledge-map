# 04 — Pass a Model Deployment through Entity Extraction

**What to build:** Entity Extraction receives one explicit Model Deployment and
uses the shared factory to construct its agent. The adapter keeps its existing
structured-output, validation, and News Ontology conformance behavior while
dropping stage-specific model lookup.

**Blocked by:** 02 — Build local chat models from a Model Deployment.

Labels: ready-for-agent

- [ ] The Entity Extraction agent is constructed from the supplied Model Deployment through the shared factory.
- [ ] The concrete adapter can receive an agent or deployment without consulting a stage-specific model variable.
- [ ] A conflicting stage-specific environment value cannot replace the supplied deployment.
- [ ] Deterministic adapter injection continues to avoid live inference.
- [ ] Existing extraction and conformance tests remain green with a local deployment.

