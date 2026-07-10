# 01. Model Immutable Authored Evaluation Definitions

Status: ready-for-agent
Labels: ready-for-agent

## Parent

[Shared Evaluation Contract and Record Model](../PRD.md)

## What to build

Evaluation authors can create typed, immutable Evaluation Case revisions, Evaluation Gold Set versions, and Evaluation Rubric revisions in version-controlled code or files. Each authored revision carries a stable business identity, revision, canonical content hash, exact Pydantic schema identity and revision, human-facing metadata, and declared artifact references.

The contract makes semantic changes produce a new revision, keeps split assignment in Evaluation Gold Set membership, excludes evaluator configuration from Evaluation Cases, and rejects compatibility based on merely similar structures. It also provides secret-free canonical serialization and UUIDv7 identity generation for shared evaluation records.

## Acceptance criteria

- [ ] Authored Evaluation Cases, Evaluation Gold Sets, Evaluation Rubrics, schema references, and revision identities serialize and deserialize without losing their canonical meaning.
- [ ] Changing authored content while reusing a business identity and revision is detectable by its content hash; semantic changes require a new revision.
- [ ] Evaluation Gold Set membership names exact Evaluation Case revisions and owns split assignment without changing case identity.
- [ ] Evaluation Case task input, expected output, and metadata are strongly typed; exact schema identity and revision are required for compatibility.
- [ ] Evaluation Cases contain no evaluator configuration, and canonical configuration utilities remove credentials before serialization or fingerprinting.

## Blocked by

None — can start immediately.
