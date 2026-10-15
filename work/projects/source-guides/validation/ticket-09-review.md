# Ticket 09 independent review

Reviewed on 2026-10-09 UTC against fixed point
`887110ec4e9d3aeff7aefc473f0037e08dcccafc` with
`git diff 887110ec4e9d3aeff7aefc473f0037e08dcccafc...HEAD`.
Implementation commit: `c3f96cccfe20b2d916597a256be3b1ad2aba427f`.
Separate parallel Standards and Spec reviewers used the repository code-review
skill. Neither reviewer authored the implementation.

The review read AGENTS.md, GLOSSARY.md, tracker/domain conventions, ADRs 0017,
0022 and 0023, ticket 09, the parent PRD, the
[implementation evidence](ticket-09.md), and every changed code/test hunk.
Immutable report bodies were checked for provenance and metadata consistency.
The maintainer's clarification remains authoritative: each article appears once
as an ordinary non-highlighted link with relevant verified highlights nearby.

## Standards

No documented-standard breaches. One baseline judgement call:

- P3 possible Duplicated Code in `web.py:80` and `chat_presentation.py:209`.
  Both repeated `GuideCollection.model_validate(entry.model_dump(include={"name",
  "date_basis", "earliest_date", "latest_date"}))` for the reader-facing coverage
  projection. Future field changes could make entry/latest-attempt details and
  successful saved reading diverge. The reviewer recommended a shared projection.

Immutable prompt adoption, domain terminology, recorded Publication provenance,
shared evaluation rendering, and report metadata comply with the reviewed rules.
Existing ordinary article links and nearby verified highlights remain intact.
The remaining hunks produced no standards finding. Tooling-enforced checks were
excluded from the report.

## Spec

No findings.

The implementation covers typed disclosures, distinct outcome explanations,
saved collection/date limits, recorded Publication metadata, and initially
collapsed reader-safe Search details. Saved content remains separate from failed
latest attempts. Existing assessment timing and eligibility policy are preserved;
prompt v12 adds guidance rules without changing assessment instructions.
No independent Chat Session testing seam was added. The controlled reports are
unlabeled training observations and make no accuracy claim.

The Spec reviewer independently ran the coverage, group, and section suites:
47 passed using uv.

## Dispositions and acceptance

The P3 finding was accepted and fixed. `guide_collections` now supplies both
the question-entry/latest-attempt scope and successful saved-reading projection.
The original fields and reader behavior are unchanged. The Standards reviewer
rechecked the working correction and confirmed it addressed the finding with no
remaining issue. Existing public HTTP and shared-evaluation tests verify the
same saved scope without adding a test of the helper itself.

There are no rejected, duplicate, out-of-scope, or unresolved findings and no
maintainer question. All seven ticket criteria are checked with evidence in the
implementation record and the independently verified checks below. Ticket 09
has exactly one triage-state label, `completed`.

All nine project issues now have checked criteria and `completed` labels. The
parent PRD and authoritative work README reflect that completion. The README
retains the conductor's whole-sequence review as current attention. That separate
review and remote pull-request CI remain forthcoming; this record makes no claim
that they passed.

## Browser evidence

The review visually inspected the original reader and failed-update screenshots.
They show literal adversarial names and disclosures, omitted metadata for the
undated source, two ordinary article links, a nearby verified highlight, and
separate Saved reading and Latest attempt details after guidance failure.
The implementation record retains the actual cached Chromium interactions for
all seven terminal scenarios, initial collapse, reload, and failed update.

The review correction changes only the shared Python coverage projection.
Post-fix public HTTP checks verify that its fields remain identical. No new
browser acquisition was needed or attempted.

## Final checks

All commands use uv and `UV_CACHE_DIR=/tmp/source-guides-uv`; cached type tooling
also uses `UV_TOOL_DIR=/tmp/source-guides-tools`.

- Before the correction, focused HTTP, groups, sections, and shared evaluation:
  118 passed, one existing Pydantic Evals event-loop deprecation warning.
- After the correction, `uv run --no-sync pytest -q
  tests/test_source_guide_coverage.py tests/test_chat_web.py
  tests/test_chat_eval_task.py tests/test_retrieval_eval_task.py`: 82 passed,
  the same existing event-loop warning.
- Final `uv run --no-sync pytest -q tests`: 1574 passed, 61 skipped, one existing
  OpenRouter reasoning/temperature warning, 52.38 seconds. Existing temporary
  HTTP-server checks ran with approved loopback permission.
- `uv run --no-sync node --test tests/chat_eval_review_editing.test.mjs
  tests/rag_eval_review.test.mjs tests/chunk_eval_review.test.mjs`: 29 passed.
- Cached `uv tool run --offline --from ty ty check` on presentation, web, chat,
  guide store, and guide/retrieval schemas: passed.
- Ruff on those modules and `tests/test_source_guide_coverage.py`: passed.
- JavaScript syntax, tracker consistency, and `git diff --check`: passed.

The implementation's unchanged `sqlite_db.py` baseline remains two existing
`lastrowid` type diagnostics and 79 Ruff diagnostics, recorded in its evidence.
No whole-module SQLite cleanliness is claimed.

Standards: one P3 finding, accepted, fixed, and confirmed. Spec: zero findings.
No valid finding remains unresolved.
