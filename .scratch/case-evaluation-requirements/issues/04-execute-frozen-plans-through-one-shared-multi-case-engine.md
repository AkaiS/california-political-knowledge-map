# Execute frozen plans through one shared multi-case engine

Status: ready-for-agent
Labels: ready-for-agent

## Parent

[Case Evaluation Requirements and Resumable Evaluation Execution](../PRD.md)

## What to build

Make in-memory evaluation consume a Resolved Evaluation Plan through the shared execution engine. The engine builds one multi-case Pydantic Evals Dataset, projects evaluator scopes from the frozen plan, and exercises the same checkpoint boundary without requiring persistence.

## Acceptance criteria

- [ ] The shared engine accepts a frozen Resolved Evaluation Plan rather than independently deriving evaluator assignments during execution.
- [ ] One Pydantic Evals Dataset contains every selected case in the plan.
- [ ] Suite-wide Case Evaluators are attached at Dataset scope and run for every selected case.
- [ ] Requirement-selected evaluators are attached only to matching Cases, with evaluators already applied Suite-wide omitted at Case scope.
- [ ] Each effective Configured Evaluator executes at most once for a case even when multiple requirements selected it.
- [ ] Report evaluators receive the complete multi-case Pydantic Evaluation Report.
- [ ] In-memory execution uses a no-op checkpoint sink and requires no ledger.
- [ ] Task failures, evaluator failures, observations, and aggregate report semantics remain distinguishable through the shared result contract.
- [ ] A highest-level deterministic test resolves and executes a typed Suite and Gold Set and asserts observable report behavior without coupling to private engine structure.

## Blocked by

- [Preflight selected cases into a Resolved Evaluation Plan](02-preflight-selected-cases-into-a-resolved-evaluation-plan.md)
- [Invoke sync and async tasks through validated Task Bindings](../../evaluation-contract-hardening/issues/06-invoke-sync-and-async-tasks-through-validated-task-bindings.md)
