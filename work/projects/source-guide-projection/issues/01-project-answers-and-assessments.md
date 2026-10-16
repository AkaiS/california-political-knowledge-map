# 01 Project Retrieval Answers and assessments through one outcome interface

Labels: ready-for-agent

## Parent

[Source Guide projection](../PRD.md)

## What to build

The Source Guide projection module offers one way to turn a Chat Session outcome
into a terminal Source Guide. This ticket covers:

- Retrieval Answers;
- evidence assembly failures;
- Declined and needs-edit assessments.

The projection reads article publications and original-section highlights from
a story document store that the caller names explicitly. Nothing falls back to a
location relative to the working directory.

Several callers use this one projection for these outcomes:

- the web application's successful execution path;
- the chat evaluation task;
- the retrieval evaluation task.

Rendering takes an already projected Source Guide, so it can never project a
second time against a different store. People asking questions see unchanged
Source Guides. Evaluation reviewers see highlights from the configured document
store.

## Acceptance criteria

- [ ] The projection accepts a typed Chat Session outcome. It covers a
      Retrieval Answer, an evidence assembly failure and a terminal assessment;
      the stage-failure and stopped variants are added by later tickets. It
      returns the terminal Source Guide.
- [ ] The projection requires the story document store whenever publication or
      highlight lookup is needed; there is no working-directory default.
- [ ] The web application projects successful outcomes through this interface
      with its configured store. The answer-prepared audit observation still
      renders from the saved guide.
- [ ] The chat and retrieval evaluation tasks project through this interface
      with the store resolved from the application's configuration. Rendered
      text for assessments keeps its current value.
- [ ] Rendering requires a projected Source Guide and no longer projects
      implicitly.
- [ ] New tests at the projection interface use a temporary story SQLite file.
      They cover completed, empty with irrelevant candidates, empty with no
      matches, partial, all branches failed, assembly failure, Declined, needs
      edit, Deferred, unmatched requests, publications and highlights.
- [ ] A chat evaluation task test shows highlights come from the configured
      document store without changing the working directory.
- [ ] Existing HTTP Source Guide tests and evaluation task tests pass unchanged.

## Blocked by

None (can start immediately).
