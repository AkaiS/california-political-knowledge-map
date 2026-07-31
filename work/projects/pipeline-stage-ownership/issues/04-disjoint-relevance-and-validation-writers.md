# Give relevance and validation disjoint writers

Labels: ready-for-agent

## Parent

[Pipeline Stage Ownership: Validation, Relevance, and Raw HTML Lifecycle](../PRD.md)

## What to build

Relevance code can no longer express a validation write, because the parameter
does not exist. Today the relevance writer takes a validation value as a required
positional argument and always includes it in its `UPDATE`, so every relevance
caller is forced to name one — the boundary violation is not an oversight, it is
what the signature demands. Removing the parameter is what makes the boundary
unbreakable; a convention would not survive the next caller.

The relevance writer takes a URL, a status, and a label source, and nothing else.
The one deliberate coupled transition — deciding an article irrelevant discards
its content, so validation state must clear — moves to the call site, where it is
visible, rather than living inside the writer.

A separate metadata writer owns `headline`, `description`, and `embedding`. It is
idempotent and populates them whenever they are missing and either raw HTML or
stored metadata is available, independent of whether classification runs.
Coupling these to the classifier is what currently starves human-labeled articles
of the representation the trainer needs: skipping classification for a human
label also skips the only code that would ever write them.

## Acceptance criteria

- [ ] The relevance writer accepts no validation parameter, and no relevance call site passes one.
- [ ] Writing a relevance decision leaves the validation column unchanged unless the calling stage sets it explicitly.
- [ ] The human-label guard and the effective-value return from ticket 01 still hold after the signature change.
- [ ] The metadata writer populates `headline`, `description`, and `embedding` for an article that has raw HTML or stored metadata and lacks them, without consulting relevance state.
- [ ] Running the metadata writer twice over the same article changes nothing the second time.
- [ ] An article with a `HUMAN` label and no classification run still receives its headline, description, and embedding.
- [ ] The full deterministic test suite passes.

## Blocked by

- 01 — Guard human relevance labels against automated overwrites.
