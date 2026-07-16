# Execute frozen plans through one shared multi-case engine

Labels: ready-for-agent

## Parent

[Evaluation Contract and Resumable Execution](../PRD.md)

## What to build

Make in-memory and durable evaluation consume a Resolved Evaluation Plan through one shared two-phase execution engine. The case phase builds one multi-case Pydantic Evals Dataset, projects case-evaluator scopes from the frozen plan, and produces the complete aggregate report input. The report phase accepts that immutable aggregate report and the exact Suite revision resolved from frozen identity. In-memory execution runs both phases consecutively through a no-op checkpoint sink; durable report-phase resumption is completed by the finalization ticket.

## Acceptance criteria

- [ ] The shared engine accepts a frozen Resolved Evaluation Plan rather than independently deriving evaluator assignments during execution.
- [ ] The engine exposes explicit case and report phases with the aggregate Pydantic Evaluation Report as the immutable boundary between them.
- [ ] One Pydantic Evals Dataset contains every selected case in the plan.
- [ ] Suite-wide Case Evaluators are attached at Dataset scope and run for every selected case.
- [ ] Requirement-selected evaluators are attached only to matching Cases, with evaluators already applied Suite-wide omitted at Case scope.
- [ ] Each effective Configured Evaluator executes at most once for a case even when multiple requirements selected it.
- [ ] Report evaluators run only in the report phase and receive the complete multi-case Pydantic Evaluation Report.
- [ ] A planned case evaluator that requires typed task output receives a terminal `skipped` execution with reason `task_output_unavailable` when output validation fails; no planned application silently disappears.
- [ ] In-memory execution uses a no-op checkpoint sink and requires no ledger.
- [ ] Task failures, evaluator failures, evaluator skips, observations, and aggregate report semantics remain distinguishable through the shared result contract.
- [ ] A highest-level deterministic test resolves and executes a typed Suite and Gold Set and asserts observable report behavior without coupling to private engine structure.

## Blocked by

- [Preflight selected cases into a Resolved Evaluation Plan](08-preflight-selected-cases-into-a-resolved-evaluation-plan.md)
- [Invoke sync and async tasks through validated Task Bindings](06-invoke-sync-and-async-tasks-through-validated-task-bindings.md)
