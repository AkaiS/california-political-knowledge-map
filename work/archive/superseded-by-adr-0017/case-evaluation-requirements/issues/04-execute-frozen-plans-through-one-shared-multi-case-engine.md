# Execute frozen plans through one shared multi-case engine

Labels: completed

## Parent

[Case Evaluation Requirements and Resumable Evaluation Execution](../PRD.md)

## What to build

Make in-memory evaluation consume a Resolved Evaluation Plan through the shared execution engine. The engine builds one multi-case Pydantic Evals Dataset, projects evaluator scopes from the frozen plan, and exercises the same checkpoint boundary without requiring persistence.

## Acceptance criteria

- [x] The shared engine accepts a frozen Resolved Evaluation Plan rather than independently deriving evaluator assignments during execution.
- [x] One Pydantic Evals Dataset contains every selected case in the plan.
- [x] Suite-wide Case Evaluators are attached at Dataset scope and run for every selected case.
- [x] Requirement-selected evaluators are attached only to matching Cases, with evaluators already applied Suite-wide omitted at Case scope.
- [x] Each effective Configured Evaluator executes at most once for a case even when multiple requirements selected it.
- [x] Report evaluators receive the complete multi-case Pydantic Evaluation Report.
- [x] In-memory execution uses a no-op checkpoint sink and requires no ledger.
- [x] Task failures, evaluator failures, observations, and aggregate report semantics remain distinguishable through the shared result contract.
- [x] A highest-level deterministic test resolves and executes a typed Suite and Gold Set and asserts observable report behavior without coupling to private engine structure.

## Blocked by

- [Preflight selected cases into a Resolved Evaluation Plan](02-preflight-selected-cases-into-a-resolved-evaluation-plan.md)
- [Invoke sync and async tasks through validated Task Bindings](../../evaluation-contract-hardening/issues/06-invoke-sync-and-async-tasks-through-validated-task-bindings.md)
