# Source Guides whole-sequence review

Reviewed on 2026-10-09 UTC with the repository's code-review skill. Separate
parallel Standards and Spec reviewers inherited the review owner's model and
reasoning settings without overrides. They reviewed read-only; the owner made
the corrections and requested independent confirmation.

- Fixed point: `d512b7153f0fac441be5e34a84800ef1148aa8b5`.
- Prefinal implementation: `64bfb2e46479cb9321a79d0d1686f2955535bb03`.
- Diff command: `git diff d512b7153f0fac441be5e34a84800ef1148aa8b5...HEAD`.
- Commit command: `git log d512b7153f0fac441be5e34a84800ef1148aa8b5..HEAD --oneline`.
- Spec: [PRD](../PRD.md), all nine tickets, and the latest maintainer
  clarification: each article appears once as an ordinary non-highlighted link,
  with any verified highlights nearby. Distinct membership directions remain
  valid; identical entries consolidate. A view reorders the complete list.
- Standards sources: AGENTS.md, CONTEXT.md, tracker/domain conventions, relevant
  ADRs 0017, 0019, 0022, and 0023, plus the skill's Fowler smell baseline.

Both reviewers and the owner read all nine implementation and review records.
This pass checked integrated behavior and prior-finding closure, beyond each
ticket's bounded review.

## Standards report

No documented-standard breaches found.

S1, P3 judgment call, possible Duplicated Code. `chat_presentation.py` and
`web.py` both conditionally constructed the same Deferred disclosure:

```python
GuideDisclosure(
    kind="deferred",
    message=f"{assessment.explanation}\n\n{assessment.recoverable_portion}",
)
```

The web path used `guide.assessment`. Ordinary result projection and exceptional
execution handling required synchronized formatting and condition changes.
A shared assessment-disclosure projection would keep both paths consistent.
This was a baseline heuristic, not a hard repository-rule violation.

Disposition: accepted and fixed. `deferred_disclosures` owns the status/None
guard and message construction. The normal result and assembly-failure projection
extends that tuple; the exceptional web path expands it after its failure
disclosure. Conditions, text, ordering, persistence, and eligibility remain
unchanged. The Standards reviewer independently inspected the correction and
confirmed resolution without a new concern.

Standards: 1 fixed, 0 invalid, 0 duplicate, 0 out of scope, 0 unresolved.
Worst original finding: P3 disclosure duplication.

## Spec report

R1, P3 integration documentation issue. The main README still described
request-owned execution with no saved guides, reload recovery, or detached work,
and claimed SQLite was read-only. This contradicted the PRD's "Persist guides
using the existing SQLite document-store infrastructure" and "The application
owns running operations through its lifespan, not an HTTP response" requirements.

Disposition: accepted and fixed. The README now describes persistence,
independent searches, update/edit/cancel/retry, complete reading views, nearby
verified highlights, saved limits, and separate content/attempt times. It records
focused guide-table writes and read-only Story/Publication lookups while preparing
new reading. It no longer claims startup checks Story tables or reads SQLite for
retrieval. The Spec reviewer independently confirmed closure.

No functional omissions, partial requirements, or scope creep found across
tickets 01 through 09. One ordinary article link, nearby directions/highlights,
complete reading lists, durable outcomes, attempt publication guards, and shared
application/evaluation guidance remain implemented. The Deferred helper preserves
the required behavior.

Spec: 1 fixed, 0 invalid, 0 duplicate, 0 out of scope, 0 unresolved.
Worst original finding: P3 stale user documentation.

## Prior review closure ledger

The table uses verified, unambiguous short Git object names. Each record links
the full SHA, criterion mapping, browser evidence, findings, and final checks.
The sequence order is 01 through 09. Each row's review commit becomes the next
ticket's fixed point.

| Ticket and evidence | Fixed point | Implementation | Review | Final Python / Node checks | Prior findings and current closure |
| --- | --- | --- | --- | --- | --- |
| [01](ticket-01.md), [review](ticket-01-review.md) | `d512b71` | `d1ffb1e` | `945bfb2` | 1494 passed, 61 skipped / 29 passed | Standards 1 fixed: shared `assessment_guide` still serves web and evaluation. Spec 0. |
| [02](ticket-02.md), [review](ticket-02-review.md) | `945bfb2` | `92d76f4` | `f66eccf` | 1505 passed, 61 skipped / 29 passed | Standards 1 fixed: terminal persistence remains shared. Spec 1 fixed: selection generations reject delayed reads after New question or another guide. |
| [03](ticket-03.md), [review](ticket-03-review.md) | `f66eccf` | `bf33bdb` | `487712e` | 1509 passed, 61 skipped / 29 passed | Standards 1 fixed: `readSavedGuide` remains shared while caller guards stay distinct. Spec 0. Pre-coroutine shutdown candidate was deferred to 06 and is now covered by its startup regression. |
| [04](ticket-04.md), [review](ticket-04-review.md) | `487712e` | `65d70ff` | `c71ccb2` | 1514 passed, 61 skipped / 29 passed | Standards 1 fixed: shared JSON and shutdown guards cover submission/update/cancel. Spec 0. |
| [05](ticket-05.md), [review](ticket-05-review.md) | `c71ccb2` | `18d3570` | `6a1040c` | 1521 passed, 61 skipped / 29 passed | Standards 0, Spec 0. Cancellation remains bound to the selected attempt and guarded completion. |
| [06](ticket-06.md), [review](ticket-06-review.md) | `6a1040c` | `4a309c2` | `9d6fa3c` | 1524 passed, 61 skipped / 29 passed | Standards 0. Spec 1 fixed: checked criteria and completed state remain reconciled. Startup interrupts all persisted running attempts without replay. |
| [07](ticket-07.md), [review](ticket-07-review.md) | `9d6fa3c` | `561eb88` | `0ab6cfe` | 1537 passed, 61 skipped / 29 passed | Standards 1 fixed: shared `ReadingOrder`. Spec 1 fixed: selected publication timelines sort the complete article list, including nonmembers and undated articles. |
| [08](ticket-08.md), [review](ticket-08-review.md) | `0ab6cfe` | `246f02f` | `887110e` | 1562 passed, 61 skipped / 29 passed | Standards 0. Spec 2 fixed: accent-equivalent ambiguity falls back and suffix endpoints require a word boundary. Original Story wording and conservative Unicode fallback remain in use. |
| [09](ticket-09.md), [review](ticket-09-review.md) | `887110e` | `c3f96cc` | `64bfb2e` | 1574 passed, 61 skipped / 29 passed | Standards 1 fixed: shared `guide_collections` serves entry/attempt and saved-reading scope. Spec 0. |

All 6 earlier Standards findings and 5 earlier Spec findings remain closed.
Their historical per-ticket observations and reports retain their original
meaning. Every one of the 57 acceptance criteria remains checked, and each
issue and the parent PRD retains exactly one `completed` triage-state label.
The authoritative work README no longer lists this review as pending attention.

## Integration closure

The owner inspected the application lifecycle, SQLite guide store, shared reader
projection, typed guidance validation, startup, shared evaluation consumer, and
packaged reader. Public tests prove these integrated outcomes:

- Submitted wording reaches assessment and all existing retrieval branches.
  Final typed reading directions govern inclusion; rejected references cannot
  survive through groups or highlights.
- A successful update publishes content and retrieval time together. Running,
  failed, cancelled, and interrupted updates retain prior articles, groups,
  highlights, disclosures, and retrieval time. Latest-attempt scope/outcomes
  remain separate. Empty success replaces old reading.
- Cancellation and retired completions cannot overwrite a newer attempt. Other
  guides progress independently. Restart identifies unfinished work, and only
  explicit Retry starts another attempt.
- Reopening reads the saved projection without graph hydration, Story reload,
  or model execution. All reading views retain every included article exactly
  once, with consolidated directions and verified highlights nearby.
- Reader-safe responses retain metadata and limits while excluding chunk
  bodies, ranks, branch diagnostics, and unsafe markup. Shared evaluation uses
  the same guidance projection. Existing assessment timing and eligibility are
  unchanged.

The owner visually inspected the final partial-publication screenshot, the
six-article highlight-correction screenshot, and the failed-update coverage
screenshot. They show complete chronological reading, one ordinary link with
nearby highlights/directions, conservative fallback articles, and separate saved
and latest-attempt details. No frontend behavior changed in this final review,
so the recorded browser interactions were inspected rather than repeated.
No unavailable CUA/native-browser acquisition was retried.

An additional observation about projection work occurring outside the executor's
exception handler was evaluated, but no valid typed input or concrete required
behavior failure was reproduced. Story/Publication lookup errors already use
ordinary fallback. It was not promoted to a finding or a speculative change.
There is no unresolved input question.

## Final checks and limits

All implementation checks use uv with `UV_CACHE_DIR=/tmp/source-guides-uv`.
Cached type tooling also uses `UV_TOOL_DIR=/tmp/source-guides-tools`.

- Before corrections, integrated HTTP/shared evaluation suite: 138 passed.
- After the Deferred helper correction, coverage/web/chat-evaluation/retrieval-
  evaluation suite: 82 passed, one existing Pydantic Evals event-loop warning.
- Independent Spec verification: 116 public application/shared-consumer tests
  passed in 7.02 seconds.
- `uv run --no-sync pytest -q tests`: 1574 passed, 61 skipped, one existing
  OpenRouter reasoning/temperature warning, 53.58 seconds after the helper fix.
  Existing local HTTP tests ran with approved loopback access.
- `uv run --no-sync node --test tests/chat_eval_review_editing.test.mjs
  tests/rag_eval_review.test.mjs tests/chunk_eval_review.test.mjs`: 29 passed.
- `uv tool run --offline --from ty ty check` on all nine changed application
  modules apart from baseline `sqlite_db.py`: passed.
- `uv run --no-sync ruff check` on those nine modules: passed.
- `uv run --no-sync node --check src/knowledge_map/resources/source-guides/guide.js`:
  passed.
- The format check exposed one existing sequence line in `web.py`; Ruff formatted
  that line without a behavior change. Final
  `uv run --no-sync ruff format --check src/knowledge_map/chat_presentation.py
  src/knowledge_map/web.py`: 2 files already formatted.
- Final `uv run --no-sync pytest -q tests` after that last code change:
  1574 passed, 61 skipped, one existing OpenRouter reasoning/temperature warning,
  53.86 seconds, with approved loopback access.
- Final tracker consistency and `git diff --check`: passed. Both reviewers also
  independently confirmed this ledger, reconciliation, correction integration,
  all prior dispositions, and absence of new or reopened findings.

Whole-module SQLite type/lint cleanliness is not claimed. Its two existing
`lastrowid` type diagnostics and 79 Ruff diagnostics match the prior fixed-point
baseline recorded in ticket 08 evidence. No unrelated SQLite cleanup was added.

The controlled semantic reports are fixed fictional training observations,
preserved with their prompt versions and provenance. They establish no held-out
accuracy score, failure prevalence, or production-corpus completeness. Browser
targets are best effort against stored original wording; live publisher matches
are not guaranteed. Remote pull-request CI has not run. No PR creation or push
is part of this local review.

Standards: 1 sequence finding fixed, no unresolved finding. Spec: 1 sequence
finding fixed, no unresolved finding. All prior findings remain closed. This
file and the corrections are committed together in the final local review commit.
