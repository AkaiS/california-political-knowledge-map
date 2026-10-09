# Source Guides for California political questions

Labels: enhancement, ready-for-agent
Parent: [Source-first UI shaping](../../initiatives/chat-error-follow-up/issues/04-shape-source-first-chat-ui.md)

## Problem Statement

A voter investigating California politics needs help finding which Source
Articles to read and where to look within them. The current chat displays
Article Chunks before useful comparisons and requires approving a rewritten
question. That makes readers work through internal evidence, can change the
question's intended scope, and can encourage treating generated output as a
replacement for the reporting.

The current interaction also treats a question as a temporary browser
conversation. Readers cannot reliably return to a saved organization of sources,
update it, or leave several independent questions running while consulting
other results. Browser history is not a durable application record.

The desired product is a librarian for voters: organize relevant reading,
explain why each article matters, and direct readers to the actual sources.

## Solution

Provide a durable, updateable Source Guide for each explicit political question.
The reader submits their own wording, sees available collections and dates, and
receives relevant articles with brief reading directions. Each direction names
the part of the question the article helps investigate without recounting the
article's arguments or conclusions.

Present sources through views suited to the question: contrasting positions,
differing accounts, chronological reading, or another supported division of the
question. Article Groups organize sources rather than assign political positions
to articles. One article may belong to several groups, while its ordinary link
appears once with relevant reading directions and verified highlights listed
nearby. An ungrouped list remains
useful when group organization is unavailable, provided every article has a
defensible relevance reason.

Show article metadata and links, including links that highlight relevant
original wording on the article page when possible. Display no Article Chunks
in the voter interface. Ordinary article links remain the fallback.

Readers can browse saved guides, run several questions independently, update
the same guide, or edit a question to create another guide. Search execution
continues independently of the displayed page while the local service runs.
Saved content and the latest attempt's outcome remain distinct, so a failed
update preserves useful previous content without presenting it as newly retrieved.

This spec records revisable choices for this product iteration. It does not
create an architectural constraint or require an ADR.

## User Stories

1. As a voter, I want to submit a political question in my own words, so that the search preserves what I meant to investigate.
2. As a voter, I want submission to begin searching without rewrite approval, so that I can reach sources with fewer steps.
3. As a voter, I want dates, names, bounds, and requested order preserved, so that the search does not quietly broaden or change my request.
4. As a voter, I want available collections and date ranges visible near the input, so that I understand what material the tool can search.
5. As a voter, I want broad but meaningful questions accepted, so that I can begin investigating without knowing precise political terminology.
6. As a voter, I want an unresolved referent identified, so that I can edit the question to name the bill, actor, proposition, or period I meant.
7. As a voter, I want the complete question visible in its Source Guide, so that I know what the displayed sources were selected for.
8. As a voter, I want to start a new question with an empty input, so that another guide's context does not silently shape my search.
9. As a voter, I want every included article to have a reading direction, so that I know which part of my question it helps investigate.
10. As a voter, I want reading directions to tell me where to look rather than retell the article, so that I consult the actual reporting.
11. As a voter, I want no Article Chunks displayed, so that internal evidence processing does not become the reading experience.
12. As a voter, I want sources grouped by what matters to my question, so that I can choose a useful reading path.
13. As a voter, I want supporters' and detractors' arguments organized when the sources support those groups, so that I can find reporting on each position.
14. As a voter, I want developments over time distinguished from conflicting accounts, so that a changed proposal is not presented as a reporting disagreement.
15. As a voter, I want chronological reading when my question asks for it, so that I can consult the relevant reporting in order.
16. As a voter, I want publication dates distinguished from reported event dates, so that article ordering does not imply an unsupported event timeline.
17. As a voter, I want one article to appear in several relevant groups, so that an article covering multiple aspects remains discoverable in each.
18. As a voter, I want each group membership to have an appropriate reading direction, so that I understand why the same article appears more than once.
19. As a voter, I want group membership to describe relevance rather than an article's political position, so that organization does not mischaracterize the source.
20. As a voter, I want an ungrouped article list when groups cannot be supplied, so that useful reading remains available.
21. As a voter, I want articles without a defensible relevance reason omitted, so that unexplained retrieval hits do not distract from my question.
22. As a voter, I want all articles passing the final relevance gate displayed, so that presentation does not silently hide selected reading.
23. As a voter, I want articles ordered by relevance unless I request chronology, so that the most useful reading is easy to find.
24. As a voter, I want linked titles, Publications, and publication dates when available, so that I can judge which source to open.
25. As a voter, I want unavailable metadata omitted rather than invented, so that the guide accurately represents the stored source information.
26. As a voter, I want a link to a relevant article section when it can be verified, so that I can begin reading at the useful passage.
27. As a voter, I want relevant wording highlighted on the source page when supported, so that I can locate it without viewing chunks in the tool.
28. As a voter, I want ordinary article links to remain useful when highlighting fails, so that navigation does not depend on browser or publisher support.
29. As a voter, I want articles to open in a separate tab, so that I can return to my guide and compare reading options.
30. As a voter, I want useful sources for the supported parts of a question, so that incomplete coverage does not discard relevant material.
31. As a voter, I want unmatched parts of my request identified, so that I can see the limits of this search.
32. As a voter, I want empty results distinguished from claims that articles or arguments do not exist, so that I do not mistake search limits for real-world absence.
33. As a voter, I want a failed retrieval branch disclosed while useful sibling evidence remains available, so that I can still consult sources without mistaking an incomplete search for a complete one.
34. As a voter, I want guidance failure distinguished from a successful empty search, so that I know whether the system assessed the retrieved material.
35. As a voter, I want existing Declined and Deferred outcomes explained, so that I understand eligibility and unavailable data without encountering a second UI policy.
36. As a voter, I want collapsed Search details about collections, dates, completion, and result limits, so that I can inspect the search's scope without reading technical diagnostics.
37. As a voter, I want my question saved when I submit it, so that an unsuccessful attempt does not erase what I asked.
38. As a voter, I want to browse saved questions and their Source Guides, so that I can return to prior investigations.
39. As a voter, I want guides to survive reload and local service restart, so that they are durable resources rather than temporary page state.
40. As a voter, I want opening a guide to restore saved content without searching again, so that reviewing it does not incur another model request or change the result.
41. As a voter, I want completed, empty, Declined, Deferred, failed, cancelled, and interrupted outcomes retained, so that I can understand what happened to each submitted question.
42. As a voter, I want an explicit Update guide action, so that I decide when to retrieve fresh material for the same question.
43. As a voter, I want a successful update to replace the existing guide's content, so that the guide remains current without creating another guide for the same update.
44. As a voter, I want a successfully completed empty update reflected honestly, so that old articles are not presented as newly selected results.
45. As a voter, I want previous content retained during an update, so that I can continue consulting the guide while its search runs.
46. As a voter, I want failed updates to preserve previous content and show failed state, so that useful reading is not lost to a transient failure.
47. As a voter, I want last update/retrieved information on the guide, so that I can distinguish saved content from the latest attempt's outcome.
48. As a voter, I want to edit the complete question to create a separate guide, so that I can investigate another scope without changing the original guide.
49. As a voter, I want edited questions to work without a lineage view, so that independent investigations do not require managing a question tree.
50. As a voter, I want several independent searches to run, so that consulting one guide does not block work on another question.
51. As a voter, I want searches to continue when I switch guides or close the page, so that browser navigation does not cancel my investigation.
52. As a voter, I want to reopen a running guide and see its status, so that I can reconnect to work already underway.
53. As a voter, I want Cancel for a running search, so that I can stop that attempt without affecting other guides.
54. As a voter, I want cancellation to preserve previous guide content, so that stopping an update does not erase the last useful result.
55. As a voter, I want late results rejected after cancellation, so that stopped work cannot overwrite the guide later.
56. As a voter, I want interrupted work identified after the local service restarts, so that an unfinished search does not remain misleadingly marked running.
57. As a voter, I want Retry after interruption or failure, so that I can explicitly start another attempt for the same question.
58. As a voter, I want no automatic replay or refresh, so that opening a guide or restarting the service does not silently start searches.
59. As a local user, I want the rebuilt interface to preserve loopback security and safe source rendering, so that the new interaction retains the current local application's protections.
60. As a maintainer, I want existing retrieval and evidence facilities reused, so that this feature does not create a competing retrieval or answering system.
61. As a maintainer, I want typed source guidance and search outcomes, so that presentation does not infer state from model prose.
62. As a maintainer, I want independently verifiable durability, cancellation, and update behavior, so that the interface cannot misrepresent the content it saved.
63. As a maintainer, I want browser verification of the reader's interaction, so that the delivered view is checked through its actual controls and navigation.

## Implementation Decisions

### Feature boundary and interface

- Rebuild the whole voter interaction around a browsable collection of Source
  Guides and a detail view for an individual guide. This is not a message
  transcript, a temporary workspace, or an immutable artifact collection.
- Use the existing local FastAPI application as the composition boundary for
  the interface, guide operations, dependency lifetime, and background execution.
  Preserve the existing command, loopback binding, fixed Model Deployments,
  startup ownership, and safe rendering protections unless a change is required
  by this feature's explicitly revised interaction contract.
- Replace the stock chat interaction with a reader interface consuming typed
  guide values. Do not require a new frontend framework, an account system, a
  design system, or a generalized workspace abstraction. Select the smallest
  implementation that provides the agreed controls and views.
- The public application operations are submit question, list guides, read
  guide/status, update the same guide, submit an edited question as a new guide,
  and cancel an attempt. Submission/update returns the saved guide identity and
  attempt status without keeping execution dependent on a browser response.
- The list identifies each question and guide outcome; the detail view displays
  the explicit question, source organization, last retrieval/update information,
  latest attempt status, reading links, and applicable actions. Opening a guide
  only reads saved values.
- Reader controls are New question, Edit question, Update guide, Cancel when
  running, Retry when an attempt fails or is interrupted, and Search details.
  Edit restores the complete question into an editable input; submitting it
  creates a distinct guide. No lineage relation is required.

### Original question and existing assessment

- Change the rebuilt submission path to use the submitted question for both
  assessment and retrieval. Do not call the Query Rewriter or require separate
  approval. Do not hide a reformulation inside a refinement or an assessment.
- Preserve explicit entities, publication-date scope, result bounds, and order.
  Ordinary whitespace normalization must not change meaning. An edited question
  is explicit user input, not feedback for another rewrite proposal.
- Keep the existing Chat Agent responsible for question assessment and final
  source guidance, receiving the Evidence Assembler's package. Do not introduce
  a separate answering, sufficiency, relevance, or grouping agent by default.
- Ask for direct question editing when a missing referent prevents a meaningful
  search. Do not demand clarification for every broad question or implement a
  generic model-driven question-reformulation workflow.
- Preserve the saved question and request for editing when input is insufficient;
  do not leave it marked as actively retrieving while awaiting voter input.
  Submitting the edited complete question creates a separate guide and execution.
- Reuse existing Declined/Deferred semantics and typed explanations. Coordinate
  evidence-support timing with its existing workstream; do not invent a UI
  eligibility gate, silently substitute a related task, or interpret collection
  metadata as proof that a particular article is absent.
- Preserve the current Jev, sparse, and dense branch participation, fusion,
  context limits, and partial-failure handoff. Removing rewriting does not
  introduce a new routing classifier or change the reporting gate into whole-
  question eligibility.
- The rebuilt application and its shared chat-evaluation consumer must agree
  on submitted wording and source guidance. Preserve historical reports and
  prompt versions rather than relabeling past runs as the new behavior.

### Article selection, groups, and views

- Strengthen typed final guidance so every included article has a defensible
  reading direction tied to the submitted question. This is the final relevance
  gate over evidence already organized and bounded by retrieval and assembly.
  Omit articles without such a reason instead of exposing unexplained candidates.
- Reuse Source Article identity, selected citation metadata, and per-source
  relevance guidance. Reader-facing sources must refer to selected evidence;
  group membership and section targets must refer to included articles. Validate
  these references deterministically.
- Support optional Article Groups with descriptive headings and article
  references. Different groups may reference the same article with distinct
  reading directions. Distinct directions may also reference the same article
  within one group; this alone is not invalid guidance. Render each included
  article once as an ordinary, non-highlighted link, with its group-labeled
  directions and any verified highlights listed nearby. Selecting a reading
  view can reorder this single complete list. An ungrouped result is valid and
  retains per-article reasons.
- Support question-appropriate organization for opposing positions, differing
  accounts, timelines, and other parts of a question without forcing every
  question into two opposing groups or a fixed political taxonomy.
- A contrast view directs readers to the relevant accounts without adjudicating
  them. A timeline view organizes reading rather than narrating events as a
  substitute for the sources. Relevance notes describe what an article helps
  investigate; they do not supply its arguments or conclusions.
- Display all articles passing the final relevance gate. Retain relevance order
  by default; honor requested chronological organization without conflating
  publication dates and reported event dates or inventing missing dates.
- Distinguish a successful assessment rejecting irrelevant material from a
  model/provider/validation failure preventing assessment. A missing grouping
  arrangement is not itself proof that relevance guidance failed.
- Typed result data separates reading directions, optional groups, unmatched
  portions, eligibility/coverage explanations, and search failures. Do not derive
  outcomes by keyword matching generated prose.

### Article links and reader-safe presentation

- Wire title, Publication, publication date, article URL, and reading directions
  into guide presentation. Omit missing metadata; do not infer Publication names
  from unrelated source text or generate authors, dates, or scores.
- Article links open separately and preserve the displayed guide. Show each
  article once as an ordinary, non-highlighted link. List available verified
  relevant-section highlights close to that link. Ticket 07 provides nearby
  reading directions; ticket 08 supplies verified highlight links.
- Derive targeted links from verified original Story wording associated with
  the selected Source Article. Retrieved chunks may contain coreference
  substitutions; their text and resolved offsets are not reliable original
  location data.
- Best-effort text-fragment links can highlight verified original substrings.
  Use only a confidently identified original target, with sufficient context
  where necessary to avoid an ambiguous repeated match. If original wording or
  the location cannot be established, omit the targeted link and retain the
  ordinary article link. Do not fabricate DOM anchors or claim a live match.
- Browser support, publisher opt-outs, and changed pages may defeat scrolling
  or highlighting. The reader still reaches the article. Guaranteed live-page
  alignment, retention of complete DOM maps, and a new scraping pipeline are
  not required for this iteration.
- No Article Chunks appear anywhere in the voter interface, including Search
  details. Internal Grounding Evidence remains available to the existing
  retrieval and development facilities.
- Escape source-supplied and model-supplied display values and preserve existing
  safe-link rules. Source text cannot inject markup, script, or controls.
- Search details contain relevant collections/date ranges, completion or failure,
  and result limits. Technical routes, ranks, graph metadata, and detailed
  infrastructure diagnostics remain development information.

### Durable guides and attempt ownership

- Persist guides using the existing SQLite document-store infrastructure and
  transactional conventions. Add a focused guide persistence interface rather
  than another database, a telemetry-backed result store, or a generalized
  document/workspace platform.
- Save guide identity and explicit question before starting the first attempt.
  Persist the reader-facing content and its metadata independently of current
  graph hydration, so reopening a completed guide restores what was saved rather
  than silently retrieving or regenerating it.
- A guide has a stable identity, question, creation information, saved result
  and disclosures, last successful retrieval/update information, and the latest
  attempt's identity, timing, and outcome. Store enough context to explain saved
  search limits and distinguish them from a later attempt's result.
- Each new search/update has its own execution identity. A same-question update
  publishes content to the existing guide; an edited question starts a new guide.
  Historical Chat Session audit observations keep their execution meaning.
- The application owns running operations through its lifespan, not an HTTP
  response or displayed page. Reconnection reads persisted guide/status values.
  Several guides may run independently using existing provider admission and
  resource limits; this is not a request for unlimited model concurrency.
- Serialize conflicting updates of one guide rather than allow an older attempt
  to overwrite a later result. Accept completion only for that guide's still-
  active attempt. Cancellation and replacement invalidate late publication.
- Persist execution outcomes separately from saved content. Keep pending,
  completed/empty, failed, cancelled, and interrupted execution distinct from
  agent eligibility/coverage states such as Declined and Deferred. An eligible
  search failure is not an eligibility decision.
- Publish successful new content atomically with its retrieval/update metadata.
  A successfully completed empty update publishes that empty outcome. Failed
  or cancelled updates preserve prior content and its last successful retrieval
  information while recording the current attempt's failed/cancelled state.
- Cancel only the selected attempt and retain its question and any previous
  content. Cancellation need not undo an already issued provider request, but
  cancelled work cannot publish a result afterward.
- On startup, identify persisted attempts whose local execution stopped and
  mark them interrupted. Preserve guides and previous content. Retry is explicit;
  do not replay requests automatically or introduce checkpoint/resume machinery.
- Opening, page reload, new source ingestion, and service restart do not trigger
  updates. Use explicit Update guide or Retry actions only.
- Retain submitted questions and their outcomes durably, including completed,
  empty, Declined, Deferred, failed, cancelled, and interrupted attempts. No
  automatic expiry or result-revision browser is required by this spec.

### Change coordination

- Treat direct submission, durable guides, independently owned attempts, and
  source-only presentation as deliberate replacements for the old chat
  interaction. Update affected consumer expectations rather than preserve a
  second mandatory rewrite/approval path in the rebuilt interface.
- Reuse current SQLite, retrieval, model, evidence, and telemetry facilities.
  Logfire observations remain best-effort execution telemetry, not the durable
  user-facing guide or the source of truth for reading history.
- Author new immutable versions for changed instructions and message templates,
  select them explicitly, and preserve existing versions and historical data.
- These are feature implementation choices for this iteration. No new ADR is
  required merely to record Source Guide views or interactions.

## Testing Decisions

- A good automated test exercises the highest public boundary owning the
  behavior and asserts a reader-visible result or durable effect. Do not assert
  registry layout, private methods, prompt bytes, DOM snapshots, or the chosen
  frontend framework. Use deterministic synchronization rather than timing sleeps.
- The primary automated seam is the existing FastAPI application, exercised
  through HTTP/ASGI with temporary real SQLite storage and deterministic
  substitutes for retrieval/model activity and dependency startup. Prior art is
  the current web interaction, answer rendering, correction, and lifecycle suite.
  Change its expected interaction rather than duplicate the obsolete approval
  protocol in new tests.
- Exercise guide submission, list/read, same-guide updates, edited-question
  creation, retained failures, cancellation, and startup interruption at that
  application boundary. Use a new application instance over the same temporary
  store to prove durability. Observe published content and statuses rather than
  inspecting background-task containers or SQL row layouts.
- Script deterministic retrieval/model behavior through application dependency
  injection to verify preserved submitted wording, final relevance omission,
  reference validation, group overlap, group-free fallback, typed eligibility,
  partial branch results, and distinction between empty results and failed
  assessment. Existing source guidance and evidence fixtures supply prior art;
  do not add an independent Chat Session test seam or reuse its old approval
  tests as the feature's testing plan.
- Delay controlled executions with explicit events to prove two guides can
  progress independently, changing/disconnecting clients does not cancel work,
  cancellation rejects late completion, and a failed update cannot replace
  retained content or its retrieval date. Cover conflicting updates through
  externally observable outcomes.
- Use adversarial display values and a distinctive stored-chunk sentinel to
  prove the public guide/detail responses and rendered reader view expose no
  chunk bodies or unsafe markup. Verify that omitted articles do not remain
  reachable through group membership or reader-facing section metadata.
- Verify section links against original-text fixtures, including a coreference-
  changed chunk, an unchanged match, repeated ambiguous text, absent original
  text, missing metadata, and ordinary-link fallback. Do not claim a generated
  text fragment proves today's live publisher page matches stored content.
- Browser verification is explicitly authorized by the maintainer and is the
  additional seam for the actual reader interaction. Verify the implemented
  local interface with controlled outcomes: submission without approval,
  browsing saved guides, contrast/timeline organization, editing, explicit
  update, multiple running questions, reconnecting, cancellation, retained
  content after failure, visible timestamps, and reopening after restart.
- In the browser, check actual article/section navigation, separate-tab behavior,
  useful fallback when highlighting is unavailable, collapsed details, safe
  rendering, and absence of chunks. Use controlled source pages where needed
  to make target matching reproducible. Do not depend on real model responses
  or changing publisher content for deterministic acceptance.
- Keep final relevance and librarian behavior in the existing evaluation
  workflow using controlled examples. Deterministic tests prove filtering and
  output contracts; they do not establish the semantic accuracy of model
  relevance judgments. Reuse the existing RAG and evidence-support workstreams
  rather than create another evaluator, prevalence claim, or unreviewed floor.
- Run implementation checks with uv and the repository's required CI suite.
  There is no application implementation to test during spec publication.

## Out of Scope

- Public hosting, non-loopback exposure, authentication, accounts, multi-tenant
  isolation, and cross-device synchronization.
- Standalone reporting, summaries that replace article reading, adjudication
  of reported positions, or displaying Article Chunks to voters.
- Mandatory query rewriting, another approval step, implicit conversational
  context, automatic reformulation, or a general clarification framework.
- A question lineage view, a workspace hierarchy, immutable guide artifacts,
  an event-sourced guide history, or a version-comparison product.
- Automatic refresh, ingestion-triggered updates, scheduled guide monitoring,
  automatic replay after restart, and resumable model-call checkpoints.
- Retrieval score tuning, new retrieval branches, corpus expansion, a new
  answering/sufficiency/classification agent, or a competing coverage policy.
- Guaranteed scrolling/highlighting on every live article, rebuilding ingestion
  to preserve full DOM location maps, or scraping live pages whenever a guide opens.
- A required new frontend framework, generalized artifact platform, new database,
  model/tool picker, or streaming partial model prose into unfinished guides.
- Independent Chat Session tests as a new feature-testing seam. Browser
  verification is in scope; it is not restricted by the earlier repository
  default because the maintainer explicitly authorized it for implementation.

## Further Notes

This spec supersedes the temporary workspace/history and immutable-artifact
suggestions raised during the interview. A Source Guide is durable and updateable;
its source views and controls remain revisable product choices. No feature ADRs
are created. Two mistakenly written ADRs were removed at the maintainer's request.

The existing source-first shaping record contains the Q1-Q32 conversation history
and controlled acceptance examples. The maintainer requested this spec and the
implementation tickets below.

Existing code already has typed selected evidence, source citations, optional
per-article relevance notes, partial-failure disclosures, and a secured local web
composition boundary. It lacks durable application guides, independently owned
browser-detached work, required per-article notes, question-specific group data,
and targeted original-text links. Stored chunks can contain replacements, and
original Story text has no reliable persisted DOM anchors. These are concrete
implementation gaps, not a reason to introduce another retrieval system.

Coordinate implementation with the [original-question baseline](../../initiatives/chat-error-follow-up/issues/01-original-question-retrieval-baseline.md)
and [evidence-support work](../../initiatives/chat-error-follow-up/issues/03-assess-evidence-support-after-retrieval.md).
The guide UI renders agent-owned states; the existing controlled evaluation owns
changes to coverage-assessment semantics. Preserve the shared retrieval contract
in [ADR 0023](../../../docs/adr/0023-jev-constructs-cypher-in-the-shared-chat-retrieval-path.md),
prompt-version rules in [ADR 0022](../../../docs/adr/0022-prompts-are-immutable-versioned-text-resources.md),
and evaluation record semantics in [ADR 0017](../../../docs/adr/0017-git-is-the-evaluation-versioning-system.md).

The maintainer approved the primary application seam and explicitly replaced
reuse of Chat Session tests with browser verification. This is recorded in the
testing plan so implementation does not reopen that authorization.

### Implementation tickets

Each ticket links directly to this spec. Start a ticket when its listed blockers
are complete; ticket 01 is the initial frontier.

| Ticket | Blocked by |
| --- | --- |
| [01 Submit an original question and read relevant articles](issues/01-submit-original-questions.md) | None |
| [02 Save, browse, and reopen Source Guides](issues/02-save-and-reopen-guides.md) | 01 |
| [03 Keep independent searches running across navigation](issues/03-continue-independent-searches.md) | 02 |
| [04 Update a guide or edit its question](issues/04-update-and-edit-guides.md) | 03 |
| [05 Cancel searches without losing saved content](issues/05-cancel-searches.md) | 04 |
| [06 Recover interrupted searches with explicit Retry](issues/06-retry-interrupted-searches.md) | 03 |
| [07 Organize reading through contrast and timeline views](issues/07-organize-reading-views.md) | 02 |
| [08 Direct readers to relevant article sections](issues/08-link-relevant-sections.md) | 02 |
| [09 Explain guide coverage, outcomes, and search limits](issues/09-explain-search-coverage.md) | 02 |

## Maintainer clarification, 2026-10-09

The maintainer clarified article presentation during ticket 07 implementation:
"An article should always appear once as a non-highlighted link and if we have
them, a list of relevant highlights should appear in close proximity." This
clarification supersedes repeated article-link rendering across groups. Group
membership remains useful organization; the reader consolidates its directions
near each article. Repeated memberships with distinct directions are accepted.
Ticket 08 remains responsible for verified highlights.
