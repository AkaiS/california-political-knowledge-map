# 09 Explain guide coverage, outcomes, and search limits

Labels: enhancement, ready-for-agent
Parent: [Source Guides spec](../PRD.md)

## What to build

Show searchable collections and dates near the input, complete source metadata
where available, and clear coverage/outcome explanations in the saved guide.
Provide collapsed Search details that help voters understand the result without
exposing internal evidence or infrastructure diagnostics.

## Acceptance criteria

- [ ] Available collections and date ranges appear near question entry and are
  retained with saved search limits. They do not imply a particular article
  exists or is absent.
- [ ] Articles show linked title, Publication, publication date, and reading
  direction when available. Missing metadata is omitted rather than generated
  or inferred from unrelated text.
- [ ] Typed disclosures identify unmatched portions of a request while retaining
  useful sources for supported portions. A failed retrieval branch is disclosed
  without discarding available sibling evidence.
- [ ] A successful empty search, rejection of irrelevant candidates, failed
  retrieval/guidance, and existing agent-owned Declined/Deferred outcomes have
  distinct reader explanations. Empty results do not claim real-world absence.
- [ ] Persist disclosures and restore them with the guide. Search details are
  collapsed initially and show collections, dates, completion/failure, and
  result limits; they expose no chunks, ranks, technical routes, graph metadata,
  or detailed infrastructure diagnostics.
- [ ] Outcome presentation uses typed values rather than keyword matching model
  prose. Source-supplied/model-supplied text retains safe rendering protections.
- [ ] Reuse existing agent eligibility and coverage semantics and coordinate
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
