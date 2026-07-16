# Atomically create runs from frozen plans

Status: ready-for-agent
Labels: ready-for-agent

## Parent

[Case Evaluation Requirements and Resumable Evaluation Execution](../PRD.md)

## What to build

Create an Evaluation Run only from a successfully resolved plan, making the authoritative intended evaluation durable in the same transaction as its manifested population and pending result envelopes. Freeze bounded case concurrency as part of the run's reproducible configuration.

## Acceptance criteria

- [ ] The authoritative Resolved Evaluation Plan is stored as canonical compact JSON in the relational ledger and can be read back by run identity.
- [ ] The Evaluation Run, Resolved Evaluation Plan, Evaluation Case Manifest, and one pending Evaluation Case Result per manifested case commit in one transaction.
- [ ] Any failure in that transaction rolls back every run, plan, manifest, and pending-result write.
- [ ] A run cannot exist without a plan that matches its exact Suite revision and manifested Evaluation Case revisions.
- [ ] Evaluation Run Configuration defaults case concurrency to one and rejects non-positive bounds.
- [ ] The selected concurrency bound is included in canonical configuration serialization and its fingerprint.
- [ ] Atomicity and canonical round-trip behavior are verified against a temporary real SQLite evaluation ledger.

## Blocked by

- [Preflight selected cases into a Resolved Evaluation Plan](02-preflight-selected-cases-into-a-resolved-evaluation-plan.md)
- [Freeze typed component configuration in Evaluation Runs](../../evaluation-contract-hardening/issues/03-freeze-typed-component-configuration-in-evaluation-runs.md)
