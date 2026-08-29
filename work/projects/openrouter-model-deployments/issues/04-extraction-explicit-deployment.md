# 04 — Pass a Model Deployment through Entity Extraction

**What to build:** Entity Extraction receives one explicit Model Deployment and
uses the shared factory to construct its agent. The adapter keeps its existing
structured-output, validation, and News Ontology conformance behavior while
dropping stage-specific model lookup.

**Blocked by:** 02 — Build local chat models from a Model Deployment.

Labels: completed

- [x] The Entity Extraction agent is constructed from the supplied Model Deployment through the shared factory.
- [x] The concrete adapter can receive an agent or deployment without consulting a stage-specific model variable.
- [x] A conflicting stage-specific environment value cannot replace the supplied deployment.
- [x] Deterministic adapter injection continues to avoid live inference.
- [x] Existing extraction and conformance tests remain green with a local deployment.
