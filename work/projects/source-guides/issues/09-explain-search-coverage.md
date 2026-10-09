# 09 Explain guide coverage, outcomes, and search limits

Labels: enhancement, completed
Parent: [Source Guides spec](../PRD.md)

## What to build

Show searchable collections and dates near the input, complete source metadata
where available, and clear coverage/outcome explanations in the saved guide.
Provide collapsed Search details that help voters understand the result without
exposing internal evidence or infrastructure diagnostics.

## Acceptance criteria

- [x] Available collections and date ranges appear near question entry and are
  retained with saved search limits. They do not imply a particular article
  exists or is absent.
- [x] Articles show linked title, Publication, publication date, and reading
  direction when available. Missing metadata is omitted rather than generated
  or inferred from unrelated text.
- [x] Typed disclosures identify unmatched portions of a request while retaining
  useful sources for supported portions. A failed retrieval branch is disclosed
  without discarding available sibling evidence.
- [x] A successful empty search, rejection of irrelevant candidates, failed
  retrieval/guidance, and existing agent-owned Declined/Deferred outcomes have
  distinct reader explanations. Empty results do not claim real-world absence.
- [x] Persist disclosures and restore them with the guide. Search details are
  collapsed initially and show collections, dates, completion/failure, and
  result limits; they expose no chunks, ranks, technical routes, graph metadata,
  or detailed infrastructure diagnostics.
- [x] Outcome presentation uses typed values rather than keyword matching model
  prose. Source-supplied/model-supplied text retains safe rendering protections.
- [x] Reuse existing agent eligibility and coverage semantics and coordinate
  controlled assessment changes with the evidence-support workstream. Do not
  add a UI relevance classifier, a second policy gate, or substitute tasks.

## Blocked by

- [02 Save, browse, and reopen Source Guides](02-save-and-reopen-guides.md)

## Validation

At the application boundary using real temporary SQLite and deterministic
retrieval/model substitutes, exercise partial branch failure, unmatched requests,
empty/rejected/failed/Declined/Deferred states, absent metadata, persistence,
and safe display values. Verify near-input scope, source metadata, explanations,
collapsed Search details, and absence of chunks in the browser. Use existing
controlled evaluation work for assessment semantics. Run required checks with
uv, without independent Chat Session tests.

## Comments

Independent Standards and Spec review completed on 2026-10-09 UTC. The Standards
review found one P3 maintenance issue, repeated coverage projection, which is
fixed by a shared reader projection. The Spec review found no gaps. All seven
criteria have application-boundary, persisted-read, browser, and shared controlled
evaluation evidence. Existing assessment timing and eligibility remain unchanged.
The maintainer's one ordinary article link with nearby verified highlights rule
remains authoritative. See the [implementation evidence](../validation/ticket-09.md)
and [independent review and checks](../validation/ticket-09-review.md).
