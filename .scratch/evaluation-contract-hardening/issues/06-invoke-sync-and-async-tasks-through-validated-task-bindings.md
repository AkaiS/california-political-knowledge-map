# Invoke sync and async tasks through validated Task Bindings

Status: ready-for-agent
Labels: ready-for-agent

## Parent

[Evaluation Contract and Ledger Hardening](../PRD.md)

## What to build

Introduce an Evaluation Task Binding as the sole runtime boundary between one evaluated component operation and its exact Evaluation Task Contract. The Binding invokes synchronous or asynchronous components, validates every returned value once, and produces a complete Evaluation Task Outcome containing either typed success plus output-artifact references or normalized failure plus failure-artifact references.

The evaluation engine trusts the Binding's outcome and does not repeat output validation. Task Bindings and evaluators remain persistence-free; checkpoint sinks persist their evidence. Consolidate the common timing, success/failure normalization, and recording behavior used by synchronous and asynchronous evaluator paths while retaining the invocation-specific call or await step.

## Acceptance criteria

- [ ] An Evaluation Task Binding associates one component operation and its input, output, and metadata Pydantic models with one exact Evaluation Task Contract.
- [ ] Binding creation rejects model schemas that do not exactly match the authored contract.
- [ ] Every synchronous and asynchronous invocation validates its returned value once at the Binding boundary.
- [ ] A valid return produces a typed success outcome with any output-artifact references; an output contract violation produces a terminal, non-retryable `output_validation` task failure.
- [ ] Component exceptions and failure evidence become provider-neutral failure outcomes without leaking provider SDK objects.
- [ ] Task Bindings describe artifact evidence but perform no ledger or artifact-catalog writes.
- [ ] The evaluation engine and Pydantic Evals projection consume the validated success output without performing duplicate validation.
- [ ] Synchronous and asynchronous evaluator adapters share timing and evidence-recording logic while preserving their distinct call and await behavior.
- [ ] Deterministic tests cover synchronous success, asynchronous success, output mismatch, component failure, artifact references, evaluator success, and evaluator failure.

## Blocked by

- [Bind every Evaluation Gold Set to one Task Contract](02-bind-every-evaluation-gold-set-to-one-task-contract.md)
- [Freeze typed component configuration in Evaluation Runs](03-freeze-typed-component-configuration-in-evaluation-runs.md)
