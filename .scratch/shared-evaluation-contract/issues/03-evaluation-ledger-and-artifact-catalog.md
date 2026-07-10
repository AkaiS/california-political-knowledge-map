# 03. Persist Imported Definitions and the Evaluation Artifact Catalog

Status: ready-for-agent
Labels: ready-for-agent

## Parent

[Shared Evaluation Contract and Record Model](../PRD.md)

## What to build

The relational Evaluation Ledger can import the immutable identity, revision, content hash, schema references, and queryable metadata for every referenced authored definition before execution. Its SQLite implementation keeps authored material authoritative outside the database while preventing an imported business revision from being reused for different bytes.

It also gives evaluation evidence a content-addressed Evaluation Artifact catalog: immutable artifact metadata, multiple replaceable Artifact Locations, and redacted derivatives that retain their source relationship rather than overwriting it.

## Acceptance criteria

- [ ] Importing an authored definition revision creates one immutable, UUIDv7-identified ledger record with its business identity, revision, canonical hash, schema references, and queryable metadata.
- [ ] Re-importing the same authored bytes is idempotent; attempting to reuse a business identity and revision with a different hash is rejected.
- [ ] The ledger uses relational constraints for Gold Set membership and preserves authored definitions as externally authored records rather than editable SQLite content.
- [ ] An Evaluation Artifact is deduplicated by content hash and records its kind, media type, byte size, retention class, and sensitivity/redaction classification.
- [ ] One artifact can have multiple replaceable Artifact Locations, and a redacted derivative is a distinct artifact linked to its source.

## Blocked by

- [Define Executable Evaluation Suites and Metric Semantics](02-executable-suites-and-metrics.md)
