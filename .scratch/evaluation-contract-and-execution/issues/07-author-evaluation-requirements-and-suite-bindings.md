# Author Evaluation Requirements and Suite bindings

Labels: ready-for-agent

## Parent

[Evaluation Contract and Resumable Execution](../PRD.md)

## What to build

Allow an Evaluation Case to declare the stable semantic Evaluation Requirements it needs from its component's closed Evaluation Requirement Catalog, while keeping all judging machinery owned by the Evaluation Suite. A Suite can apply Case Evaluators Suite-wide and can bind each supported requirement to one or more declared case Configured Evaluators.

## Acceptance criteria

- [ ] A component can define a closed Evaluation Requirement Catalog whose keys have non-empty, immutable semantic descriptions.
- [ ] An Evaluation Case accepts zero or multiple distinct catalog keys and rejects duplicate or unknown requirements.
- [ ] Requirements participate in authored case content hashing, so changing the requirement set requires a new Evaluation Case revision.
- [ ] Evaluation Requirements cannot carry evaluator names or revisions, rubrics, metrics, providers, models, or evaluator configuration.
- [ ] An Evaluation Suite keeps case and report Configured Evaluators in separate typed collections while enforcing name uniqueness across both collections.
- [ ] Suite-wide Case Evaluator references and Evaluation Requirement Bindings resolve only to declared case Configured Evaluators; bindings are non-empty and reject duplicate references.
- [ ] Every configured case evaluator is referenced Suite-wide or by at least one binding, while a valid binding may remain dormant for a particular selection.
- [ ] At least one report Configured Evaluator remains required and exact Evaluation Task Contract validation remains intact.
- [ ] Contract tests demonstrate that changing Suite-owned judging machinery does not revise a case or Gold Set, while changing case requirements revises the case without requiring a Suite revision when an existing binding supports it.

## Blocked by

- [Bind every Evaluation Gold Set to one Task Contract](02-bind-every-evaluation-gold-set-to-one-task-contract.md)
