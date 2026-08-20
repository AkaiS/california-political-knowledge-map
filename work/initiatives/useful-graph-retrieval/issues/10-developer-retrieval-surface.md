# Decide the developer retrieval surface

Labels: wayfinder:grilling, needs-triage
Parent: [Useful Graph Retrieval](../MAP.md)
Blocked by: [Define the retrieval and answer contract](08-retrieval-and-answer-contract.md)

## Question

How does the first consumer — a developer investigating California politics —
actually ask questions and read answers?

Decide the shape: a `ca-map` subcommand alongside the existing CLI, an
interactive session in the manner of the Influence Graph Playground, or a
notebook-facing API. Settle how evidence and citations are presented in a
terminal, and how a developer inspects why a given answer was supported the way
it was, since a discovery layer is only useful if its support can be checked.

The constraint is that the surface stays a thin rendering of the retrieval and
answer contract. Any behaviour it needs that the contract does not express is a
gap in the contract, not something the surface should implement for itself —
otherwise the chat UI that replaces it later cannot inherit the same behaviour.

## Comments

### Previously discussed — 2026-08-19 grilling session

- **The surface is a web page, not a CLI.** One query box, one results list.
- **The graph is not browsable.** Query in, ranked sources out with relevance
  statements. No graph exploration view.
- **Built on FastAPI serving one server-rendered HTML page**, no JavaScript build
  step. `fastapi>=0.110.0` and `uvicorn>=0.28.0` are already declared in
  [pyproject.toml](../../../../pyproject.toml) and currently unused. Keep the
  underlying response shape clean so a later chat UI is a rendering job.
- **Acceptance is a fixed question list, written before building.**
  Ten to fifteen concrete questions drawn from the E and R families, answerable
  from the actual corpus, each with the Source Articles known to be correct.
  [question-set.md](../question-set.md) deliberately authored no expected answers;
  this list supplies them. It is a hand-run checklist, explicitly **not** an
  Evaluation Gold Set, and does not unfreeze the evaluation framework.
