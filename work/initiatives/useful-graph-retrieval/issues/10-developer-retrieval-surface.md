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
