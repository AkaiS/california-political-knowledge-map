# 08 — Deterministic Evidence Assembly

Labels: ready-for-agent

## Parent

[Graph-Prioritized Retrieval](../PRD.md)

## What to build

Turn ranked Grounding Evidence into the typed package returned to the Chat
Agent. The Evidence Assembler hydrates provenance, verifies displayed wording,
groups passages by Source Article, attaches relevant coverage limits, and
applies the context budget without introducing another model decision.

## Acceptance criteria

- [ ] Every selected passage is tied to its Source Article and retains the
      retrieval routes and graph claims that led to it.
- [ ] Any wording presented as a quotation is verified against the original
      Story body.
- [ ] Transformed Article Chunk text cannot be silently presented as verbatim
      original wording.
- [ ] Selected passages are grouped by Source Article while useful passages from
      different parts of one article remain available.
- [ ] The package includes the relevant Coverage Description entries and omits
      unrelated collection detail.
- [ ] Context limiting is deterministic and follows the accepted contract.
- [ ] Assembly failure remains distinct from retrieval branch failure.
- [ ] The assembler does not summarize evidence, decide sufficiency, adjudicate
      disagreements, or request another retrieval.
- [ ] Behavioral tests cover original-wording verification, source grouping,
      route retention, coverage attachment, deterministic context limiting, and
      assembly failure.

## Blocked by

- [02 — Retrieval execution and evidence contracts](02-retrieval-execution-and-evidence-contracts.md).
