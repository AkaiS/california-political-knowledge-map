# Ticket 01 independent review and resolution

Reviewed on 2026-10-09 UTC with the repository code-review skill. Standards and
Spec reviewers ran in parallel, inherited the review agent's model, and did not
edit the implementation. The owner evaluated the finding, fixed it, and ran the
required checks.

- Fixed point: `d512b7153f0fac441be5e34a84800ef1148aa8b5`.
- Diff command: `git diff d512b7153f0fac441be5e34a84800ef1148aa8b5...HEAD`.
- Reviewed implementation: `d1ffb1e5182cff6819a4bd2aabfc12b82a6590d3`,
  Replace rewrite approval with direct Source Guides.
- Bounded spec: [ticket 01](../issues/01-submit-original-questions.md), with the
  [parent PRD](../PRD.md). Later-ticket requirements were excluded.

## Standards

Hard violations: none found against the supplied repository instructions,
domain conventions, or relevant ADRs. Prompt resources preserve previous
versions and consumers select new versions explicitly.

Judgment call:

- P3, Duplicated Code / Shotgun Surgery. `web.py:107` and
  `evaluation/tasks/chat.py:242` independently project terminal Question
  Assessments into Source Guides. The added hunks repeat `question`,
  `status: result.status`, `assessment: result`, and
  `message: result.explanation`. Changes to Declined or needs_edit presentation
  require editing both consumers, while retrieval results already use the
  shared `source_guide` projection. Consider putting terminal assessment
  projection beside the existing shared projection. This is a maintainability
  suggestion, not a documented-standard violation.

Disposition: accepted and fixed. `assessment_guide` now owns terminal assessment
projection in `chat_presentation.py`; both consumers call it. The existing shared
evaluation test now covers both Declined and needs_edit, retained question and
message, and absence of retrieval. The Standards reviewer inspected the fix and
confirmed resolution with no new issue.

Standards findings: 1 fixed, 0 invalid, 0 duplicate, 0 out of scope, 0 unresolved.

## Spec

No Spec findings for ticket 01. The reviewer found no missing or partial
requirements, unrequested scope expansion, or concrete behavior contradicting
the bounded acceptance criteria.

The diff preserves submitted wording through assessment and retrieval, filters
public articles through validated reading directions, keeps typed outcomes and
source-safe presentation, and aligns the application with the shared
chat-evaluation consumer. Historical prompts and records retain their original
interpretation.

The reviewer inspected implementation evidence, application tests, the shared
evaluation path, and the packaged reader interface. The reviewer did not rerun
browser verification or the full suite. Persistence, detached execution,
grouping, targeted section links, and complete Publication metadata belong to
later tickets and were not treated as omissions.

Spec findings: 0. No disposition or unresolved question remains.

## Checks and ticket reconciliation

All Python and Node commands used `uv` with
`UV_CACHE_DIR=/tmp/source-guides-uv`. Type tooling also used
`UV_TOOL_DIR=/tmp/source-guides-tools` and cached offline execution.

- Before the fix, `uv run --no-sync pytest -q tests/test_chat_web.py
  tests/test_chat_eval_task.py tests/test_chat_startup.py
  tests/test_prompt_resources.py`: 60 passed, one existing pydantic-evals
  event-loop deprecation warning.
- After the fix, `uv run --no-sync pytest -q tests/test_chat_web.py
  tests/test_chat_eval_task.py`: 35 passed with the same warning.
- `uv run --no-sync ruff check` on the three modified application modules and
  `tests/test_chat_eval_task.py`: passed after formatting the new imports.
- `uv tool run --offline --from ty ty check` on all eight changed application
  modules: passed.
- `uv run --no-sync node --test tests/chat_eval_review_editing.test.mjs
  tests/rag_eval_review.test.mjs tests/chunk_eval_review.test.mjs`: 29 passed.
- One final `uv run --no-sync pytest -q tests`, with approved loopback binding
  for existing local HTTP tests: 1,494 passed, 61 skipped, one existing
  OpenRouter reasoning/temperature warning, 42.43 seconds.
- `git diff --check`: passed.

The [implementation record](ticket-01.md) provides controlled real-model and
browser evidence for all seven acceptance criteria. The owner inspected the
final five-case report and reran the affected application and shared-consumer
checks. This review fixes presentation duplication without changing prompts,
article selection, or browser controls, so those semantic and browser checks
were not repeated. Their stated limits still apply.

All ticket 01 acceptance checkboxes are checked and its single triage label is
`completed`. The parent project remains `ready-for-agent`; ticket 02 is now
takeable. No valid finding or unresolved question remains.
