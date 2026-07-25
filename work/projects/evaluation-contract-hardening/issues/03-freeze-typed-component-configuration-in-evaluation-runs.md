# Freeze typed component configuration in Evaluation Runs

Labels: completed

## Parent

[Evaluation Contract and Ledger Hardening](../PRD.md)

## What to build

Freeze the Validated Component Configuration used to construct the evaluated component as a schema-identified, secret-free Pydantic snapshot inside each Evaluation Run Configuration. Keep provider identity, model identity, model parameters, execution mode, random seed, and bounded case concurrency as normalized shared execution dimensions rather than an untyped `model_settings` or component-options mapping.

The persisted snapshot must reproduce what constructed the evaluated component while remaining safe to serialize, fingerprint, query, and read back from the Evaluation Ledger.

## Acceptance criteria

- [x] Evaluation Run Configuration requires a Validated Component Configuration produced by the component's Pydantic configuration model rather than an arbitrary mapping.
- [x] The component configuration snapshot records its exact schema identity, revision, and fingerprint alongside canonical secret-free content.
- [x] Provider, model, model parameters, execution mode, random seed, and bounded case concurrency use normalized shared fields with unambiguous vocabulary.
- [x] Case concurrency defaults to one, rejects non-positive bounds, and participates in canonical serialization and fingerprinting.
- [x] Credentials and secret values are excluded from persisted content and from the configuration fingerprint.
- [x] Materially equivalent configurations produce the same fingerprint, while any material shared or component setting changes it.
- [x] A temporary-ledger contract test creates and reads back a run with a typed component configuration without losing its canonical meaning.

## Blocked by

- [Persist a complete run through a decomposed Evaluation Ledger](01-persist-a-complete-run-through-a-decomposed-evaluation-ledger.md)
