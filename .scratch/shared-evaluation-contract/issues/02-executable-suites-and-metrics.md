# 02. Define Executable Evaluation Suites and Metric Semantics

Status: completed

## Parent

[Shared Evaluation Contract and Record Model](../PRD.md)

## What to build

Evaluation maintainers can define a revisioned Evaluation Suite that binds a typed provider-neutral task contract to compatible Evaluation Gold Set cases, suite-local configured case evaluators, at least one configured report evaluator, exact Evaluation Rubric revisions, and declared Evaluation Metric Definitions. Provider and model selection remain Evaluation Run Configuration, not suite configuration.

The suite contract supports deterministic in-memory execution through `pydantic-evals`, including scalar and structured metric values with explicit, versioned comparison semantics. This makes a valid suite executable and invalid configurations rejectable before a run is created.

## Acceptance criteria

- [x] `pydantic-evals` is an explicit, locked project dependency used by the shared evaluation execution seam.
- [x] An Evaluation Suite revision validates its typed task contract, exact case schemas, suite-local evaluator names and configuration fingerprints, rubric references, and declared metrics.
- [x] A suite cannot be valid without at least one report evaluator, and it cannot select provider or model execution settings.
- [x] Metric Definitions have a namespaced name, evaluator revision, value type, semantic description, and versioned comparison operation; identity is `(namespaced name, evaluator revision)`.
- [x] Deterministic evaluators can produce number, integer, boolean, string, and exact-schema structured values; comparisons return better, equivalent, worse, or incomparable as appropriate.
- [x] Incompatible case/schema, rubric, or metric revisions are rejected before evaluation begins.

## Blocked by

- [Model Immutable Authored Evaluation Definitions](01-authored-evaluation-definitions.md)
