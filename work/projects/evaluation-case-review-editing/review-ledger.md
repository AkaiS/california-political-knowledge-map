# Evaluation Case review editing review ledger

Recorded 2026-10-02 as project completion evidence. The [PRD](PRD.md) and
ordered tickets define the scope. Browser workflows were retained and not
executed.

## Fixed points and commits

| Stage | Fixed point | Implementation | Review, fixes, and reconciliation |
| --- | --- | --- | --- |
| Sequence | `b7dc72476a52ae40c4acc5ea912d0ea6dba33de1` | Both tickets below | Final evidence commit contains this file and its PRD link |
| [Ticket 01](issues/01-concentrate-review-editing.md) | `b7dc72476a52ae40c4acc5ea912d0ea6dba33de1` | `bfa00d680ad8ff6983e528eb240985b489497c6c` | `4dec0b6a92819a64bc11f1a04652346967d35c51` |
| [Ticket 02](issues/02-enforce-review-editing-checks.md) | `4dec0b6a92819a64bc11f1a04652346967d35c51` | `75c90528c5b1ebb42a2b4f7eeeca4a7b4c17300c` | `85733092521b250ca036ef607c0ce72fa56ca32e` |

Each review used `git diff <fixed-point>...HEAD` with independent Standards and
Spec agents. The final whole-sequence review covered the PRD and both tickets
through `85733092521b250ca036ef607c0ce72fa56ca32e`, including cross-ticket
integration, initialization, copy isolation, recovery, save interleavings,
filter movement, Undo, exact asset delivery, and required CI commands.

## Findings and dispositions

| Review | Standards | Spec | Disposition |
| --- | --- | --- | --- |
| Ticket 01 | 0 documented violations; 1 P3 Duplicated Code judgement | 0 | Accepted and fixed: `canNavigate` shares the module's destination calculation with navigation, removing the page's repeated rule. Standards confirmed closure. |
| Ticket 02, including reconciliation | 0 documented violations; 0 smells | 0 | No fixes required. Completion evidence and project state reconciled. |
| Whole sequence | 0 documented violations; 0 smells | 0 | Both reports accepted. Closure checked against every finding; no valid finding remains unresolved. |

The final Standards report confirms repository conventions, domain vocabulary,
ADR 0017, prompt immutability, copied state, and module/page ownership. The final
Spec report confirms the editing durability and ordering contract, retained
page behavior by adapter inspection, exact route validation, CI enforcement,
and documentation. No implementation fix was needed in the final pass.

## Verification

All commands used `UV_CACHE_DIR=/private/tmp/ca-map-review-uv-cache`. Node was
v22.23.1. Python commands used uv; no dependencies or browsers were installed.

| Check | Ticket 01 review | Ticket 02 final review | Whole-sequence final review |
| --- | --- | --- | --- |
| `uv run --no-sync node --test tests/chat_eval_review_editing.test.mjs` | 22 passed | 22 passed | 22 passed |
| `uv run --no-sync pytest -q tests/test_chat_eval_review.py tests/test_chat_eval_task.py` | 29 passed; 1 existing warning | 29 passed; 1 existing warning | 29 passed; 1 existing warning |
| `uv run --no-sync pytest -q tests` | 1409 passed; 61 skipped; 1 existing warning | 1409 passed; 61 skipped; 1 existing warning | 1409 passed; 61 skipped; 1 existing warning |

The final Python runs explicitly set `RUN_REVIEW_BROWSER_TESTS=0` and
`RUN_NEO4J_INTEGRATION=0`. The full deterministic suite ran once after final
review. The focused run's initial restricted-sandbox attempt had seven
socket-bind permission failures and 22 passes; its approved loopback rerun
passed all 29 checks. Both successful Python runs used approved socket
permission for temporary HTTP servers.

The focused warning is Pydantic Evals' existing event-loop deprecation. The
full-suite warning is Pydantic AI's existing unsupported OpenRouter sampling
parameter warning. Final workflow parsing and assertions verified explicit
Node 22, disabled package-manager caching, the unconditional required Node
command, and the retained pytest command. `git diff --check` passed.

No Python type checker is configured, and no type-check result is claimed.
Deterministic checks and adapter inspection do not establish browser focus,
caret, keyboard, filter-control, DOM, trace, or visual behavior. Those browser
workflows remain opt-in and unexecuted. Actual pull-request CI evidence belongs
to the conductor's handoff after PR creation; these local passes do not claim a
remote CI result. There are no unresolved review findings or local blockers.
