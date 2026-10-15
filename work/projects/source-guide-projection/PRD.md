# Source Guide projection

Labels: ready-for-agent

## Problem Statement

A person asking a political question sees the terminal Source Guide that the
web application saves. A maintainer reviewing a chat Evaluation Run sees a
Source Guide that the chat evaluation task builds separately. The two should
describe the same Chat Session outcome in the same way. Today they can differ,
because the rules that turn a Chat Session outcome into a Source Guide are split
across several modules, each holding part of the rules.

- **Retrieval Answers and evidence assembly failures.** These go through the
  presentation module. It decides the guide status, the reader disclosures, the
  partial flag and a search completion value.
- **Failures inside the Chat Session.** When the session fails during
  assessment, retrieval or guidance, the web application's execution code
  decides the failed status, the reader message and the disclosures. It does
  this from the session's current stage, and the evaluation task never applies
  these rules. The evaluation task instead records its own failure stages
  ("startup", "retrieval_and_guidance", "rendering", "cleanup") and saves no
  Source Guide for a failed session.
- **Persisting the outcome.** The Source Guide store recomputes search
  completion with its own rule, overwriting the presentation module's value.
  It also derives the attempt state and decides whether the outcome replaces
  the saved reading.
- **Cancelled and interrupted outcomes.** The cancel route, the execution
  deadline, task cancellation and startup recovery each build these by hand.
  The interrupted message is duplicated between the web application and the
  store.
- **Article publication and original-section highlights.** These come from the
  story document store. The web application passes its configured store
  location. The evaluation tasks rely on a default location relative to the
  working directory, so an evaluation run from another directory, or against a
  configured document store, can render different publications and highlight
  links than the application. Rendering a Retrieval Answer without a guide
  quietly projects one against that default.

Together these mean a maintainer must read four modules to know which status,
completion and disclosures a reader will see. A change to one rule can make the
web application and the evaluation disagree without any test failing. Projection
behaviour can be tested only through the HTTP application or the evaluation task,
each needing fake models, fake sessions and fake dependencies.

## Solution

One deep Source Guide projection module decides how every Chat Session outcome
becomes a terminal Source Guide. It covers:

- a Retrieval Answer;
- an evidence assembly failure;
- a Declined or needs-edit assessment;
- a failure at a named Chat Session stage;
- a cancelled, interrupted or time-limited attempt.

The module decides the status, message, disclosures, partial flag and search
completion once. It reads publication and highlight information from a story
document store that the caller names explicitly.

Several callers use this one module:

- the web application, during execution, cancellation and startup recovery;
- the chat evaluation task;
- the retrieval evaluation task.

The Source Guide store persists the projected guide and stops computing
reader-facing values of its own.

People asking questions see the same Source Guides as today. Maintainers
reviewing chat Evaluation Runs see the guide a reader would have seen, including
for failed sessions, rendered against the same document store the application
uses. Maintainers change a projection rule in one place and test it through one
interface.

## User Stories

1. As a person asking a political question, I want this change to preserve the status, message, disclosures and articles of my Source Guide, so that maintenance does not change what I read.
2. As a person asking a political question, I want a Declined question to show the same explanation and disclosure as before, so that I understand why it was not searched.
3. As a person asking a political question, I want a question that needs editing to show the same explanation and disclosure as before, so that I know what to change.
4. As a person asking a political question, I want a Deferred explanation to stay visible whether the search completes, returns nothing or fails, so that I know coverage is still expanding.
5. As a person asking a political question, I want a failed assessment to tell me the question could not be assessed and offer Retry, so that I can try again.
6. As a person asking a political question, I want a failed retrieval to tell me the search could not be completed and offer Retry, so that I do not mistake failure for no results.
7. As a person asking a political question, I want a guidance failure to tell me reading directions could not be prepared and that retrieved articles have not passed the relevance check, so that I do not trust unchecked articles.
8. As a person asking a political question, I want an evidence assembly failure to tell me retrieved material could not be prepared, so that I can retry.
9. As a person asking a political question, I want a search where every branch failed to be reported as failed rather than empty, so that I do not conclude nothing was reported.
10. As a person asking a political question, I want a partially failed search to keep its available reading with a partial-search disclosure, so that I can use what was found while knowing it is incomplete.
11. As a person asking a political question, I want an empty search to tell me whether candidates were found but irrelevant or none were available, so that I understand the limits of the result.
12. As a person asking a political question, I want unmatched parts of my question disclosed with the portion I asked about, so that I know which part the reading does not cover.
13. As a person asking a political question, I want a cancelled search to say it was cancelled, so that I know my request was honoured.
14. As a person asking a political question, I want a search that exceeded its time limit to say so and offer Retry, so that I can try again later.
15. As a person asking a political question, I want a search interrupted by shutdown or restart to say it was interrupted, so that I know it did not finish.
16. As a person asking a political question, I want search completion to read the same in the saved guide and the latest attempt, so that the completion notice is consistent.
17. As a person asking a political question, I want a failed or interrupted update to keep my previously saved reading, so that an update never loses reading I already had.
18. As a person asking a political question, I want article publications and original-section highlights to come from the configured document store, so that my links point to the article I am reading.
19. As a person asking a political question, I want the search scope I saw at submission to remain on a failed or stopped attempt, so that I know what the search covered.
20. As a maintainer, I want every Chat Session outcome projected by one module, so that changing a status, completion or disclosure rule takes one edit.
21. As a maintainer, I want the projection module to be the only place that decides search completion, so that the store cannot silently overwrite it with a different rule.
22. As a maintainer, I want the attempt state and saved-reading promotion derived from the projected guide's status by one rule that the projection module owns, so that the store only persists.
23. As a maintainer, I want the interrupted message defined once, so that startup recovery and live interruption cannot drift apart.
24. As a maintainer, I want the projection to require an explicit story document store, so that no caller depends on its working directory.
25. As a maintainer, I want rendering to require an already projected Source Guide, so that rendering can never project a second time against a different store.
26. As a maintainer, I want to test every projection outcome by calling one interface with a temporary story store, so that I need no HTTP application, fake models or fake sessions.
27. As a maintainer, I want the web application's execution code to hand the Chat Session's outcome to the projection and persist the result, so that HTTP code contains no reader-facing rules.
28. As a chat evaluation reviewer, I want each case to record the Source Guide the application would have saved for that outcome, so that I review what a reader would see.
29. As a chat evaluation reviewer, I want a session that failed at assessment, retrieval or guidance to carry the same failed Source Guide the application would show, so that failures are classified the same way in both places.
30. As a chat evaluation reviewer, I want the existing evaluation failure record kept for failures outside the Chat Session, such as startup and rendering, so that operational diagnostics remain available.
31. As a chat evaluation reviewer, I want evaluation guides rendered against the configured document store, so that highlights in review match the application.
32. As a retrieval evaluation reviewer, I want rendered answers projected with the configured document store, so that retrieval reviews show the application's links.
33. As a maintainer reading historical Evaluation Runs, I want existing report fields to keep their meaning, so that older reports remain comparable.
34. As a maintainer, I want the answer-prepared audit observation to keep rendering from the same projected guide that is saved, so that the Chat Session Audit Trail matches the reader's guide.

## Implementation Decisions

- **One deep module.** The existing presentation module becomes the Source
  Guide projection module. Its interface is a single projection of a Chat
  Session outcome into a terminal Source Guide, plus rendering of an already
  projected guide.
  - Helpers that exist only because callers assembled guides by hand become
    internal, or are deleted. These are the assessment-guide builder, the
    Deferred-disclosure helper and the guide-collection projection.
  - Publication-order projection for saved guides stays in this module.
- **Chat Session outcome.** The projection accepts one typed outcome value,
  which is one of:
  - a Retrieval Answer;
  - an evidence assembly failure;
  - a terminal assessment (Declined or needs edit);
  - a stage failure, which names the Chat Session stage (assessment,
    retrieval or guidance) and carries the assessment if one exists;
  - a stopped attempt: cancelled, interrupted, or exceeded its time limit.

  The caller also supplies the submitted question and the attempt's search
  scope (the collections recorded when the attempt started), so failed and
  stopped guides keep the scope the reader saw.
- **Explicit story document store.** The projection requires the story document
  store location whenever an outcome needs publication or highlight lookup. It
  has no working-directory default.
  - The web application passes the configured store it already uses.
  - Both evaluation tasks resolve the store from the same configuration the
    application uses.

  No new reader abstraction is introduced: there is one production store, and
  tests use a temporary SQLite file.
- **Completion decided once.** The projection sets search completion for every
  terminal outcome. The store's current effective rule becomes the single rule:
  - every failed status gives "failed";
  - cancelled and interrupted keep their names;
  - Declined and needs edit give "not_searched";
  - a partial search gives "partial";
  - otherwise "completed".

  The store no longer recomputes completion.
- **Attempt state and promotion.** The projection module owns the mapping from a
  terminal guide status to the persisted attempt state, and the rule for which
  statuses replace the saved reading (completed and empty).
  - The store applies that mapping inside its existing conditional update.
  - The store keeps its guarantee that only the latest running attempt can
    finish.
- **Stopped outcomes.** These are built through the projection:
  - cancellation by the reader;
  - exceeding the public time limit;
  - task cancellation during shutdown;
  - startup recovery of unfinished attempts.

  Each message is defined once.
- **Web application.** Execution passes the session's result, or the stage
  failure named by the Chat Session, to the projection and persists the
  returned guide. The answer-prepared audit observation keeps its fields and
  renders from that same guide. The HTTP code holds no status, message or
  disclosure rules.
- **Chat evaluation task.**
  - It records the projected guide for every Chat Session outcome, including
    stage failures.
  - The existing evaluation failure record keeps its current fields and stage
    names, so historical reports keep their meaning (ADR 0024 preserves the
    population and progress of runs).
  - Rendered text for assessments keeps its current value.
- **Retrieval evaluation task.** It projects with the configured story document
  store before rendering.
- **Rendering.** Rendering requires a projected guide and no longer projects
  implicitly.
- **No schema changes.** The Source Guide, its disclosures and the
  attempt-summary schema keep their vocabularies. The stored guide and attempt
  tables are unchanged.

## Testing Decisions

- **What a good test is.** A good test supplies a Chat Session outcome and
  asserts the observable terminal Source Guide: status, message, disclosure
  kinds and text, partial flag, completion, articles, groups, publications and
  highlight links. Tests do not assert which helper produced a value, and do not
  reach into the store's tables to check projection decisions.
- **New tests at the projection interface.** Each outcome is a call with a
  temporary story SQLite file:
  - Retrieval Answer: completed, empty with irrelevant candidates, empty with
    no matches, partial, all branches failed;
  - evidence assembly failure;
  - Declined and needs edit;
  - Deferred with success, empty result and each stage failure;
  - failure at each stage;
  - cancelled, interrupted and time-limited outcomes;
  - completion for every terminal status;
  - attempt-state and promotion mapping for every terminal status;
  - publications and highlights read from the named store.
- **Existing regression tests stay unchanged.** The HTTP Source Guide tests
  (coverage, groups, publication bounds, sections, cancellation, recovery,
  updates, execution and public deployment) keep the current behaviour seen by
  readers, including persistence and restart.
- **New chat evaluation task assertions:**
  - a stage failure records the same Source Guide the projection produces for
    that outcome;
  - the existing evaluation failure record is kept;
  - highlights come from the configured document store without changing the
    working directory.
- **Prior art:**
  - the HTTP Source Guide test modules, for the reader-facing assertions to
    preserve;
  - the chat evaluation task tests, for evaluation output assertions;
  - the sections tests, for temporary story stores with saved stories.

## Out of Scope

- Moving the Source Guide attempt lifecycle out of the web application:
  admission, task registry, cancellation race, deadline and injected clock.
  That is a separate architecture candidate.
- Changing how the Chat Session reports its stage. Callers still name the stage
  from the session; returning failures from the session instead of raising is a
  separate change.
- Changing the evaluation report format, reviewer projections or case-outcome
  classification in evaluation summaries.
- Changing reader-facing wording, disclosure kinds, completion values or browser
  presentation.
- Linking Chat Session IDs to saved guides or attempts in the Chat Session
  Audit Trail.
- Removing the legacy Query Rewrite path.

## Further Notes

- This spec comes from the 2026-10-14 architecture review (candidate 1). The
  review found completion computed with two rules, the same session failure
  classified differently by the web application and the chat evaluation, and
  evaluation highlights depending on the working directory.
- The deepened module supplies the terminal Source Guide that a later deepening
  of the attempt lifecycle would rely on.
