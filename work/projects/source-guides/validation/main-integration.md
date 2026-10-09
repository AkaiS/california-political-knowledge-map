# Source Guides integration with main

The merge joins Source Guides at
`78c7e23f715c4fea9fa69c589de829952c7631d9` with main at
`efd70bde167536382d3ee1ff1cb9bb19eae7833f`. Their merge base is
`3ccdb030bf139a6464710c23e9611dae7c90f5a1`.

Direct submission still assesses and searches the exact submitted question.
Each attempt now receives main's fixed UTC `as_of` and `current_date` in both
assessment and guidance. An explicit update creates a new Chat Session with a
new reference time. Chat evaluation retains direct-question outputs and records
the supplied or resolved timestamp. Main's evaluation population accounting,
progressive persistence, reviewer changes, and shared fusion ranking are retained.

The merge preserves the nine completed Source Guides tickets and the subsequent
event chronology, publication bounds, and saved-guide navigation corrections.
The five UI/UX entries in `work/inbox.md` remain feedback awaiting triage.

## Prompt collision and preserved history

Both branches independently added `chat/instructions/v2.txt` and `v3.txt`.
Main's names remain canonical because its historical date-context evaluation
reports already identify those versions. Source Guides' conflicting texts remain
available byte-for-byte as explicit versions 14 and 15. Existing Git revisions
still resolve the original branch paths and content.

All paths below are relative to
`src/knowledge_map/resources/prompts/chat/instructions/`.

| Original revision and file | Integrated file | SHA-256 |
| --- | --- | --- |
| Main `efd70bd`, `v2.txt` | `v2.txt` | `77bc10b279920b877c820c5a373fca009ad90358139ece86820f4f7f788eb5e1` |
| Main `efd70bd`, `v3.txt` | `v3.txt` | `2233c7624e9941dd4c0a900fd74b698d7b9b3d68f6aa6f03dddb8ac87ae74877` |
| Source Guides `78c7e23`, `v2.txt` | `v14.txt` | `c9b0001ce2b862b869c4c7046c3688a32d484b08336e0b3e6ac68f891a80f549` |
| Source Guides `78c7e23`, `v3.txt` | `v15.txt` | `bdde131d657eea35891ca2576ee04b798db74754ddddce292091c006e81a8d7d` |
| Source Guides `78c7e23`, `v13.txt` | `v13.txt` | `d204438d9628e272aea0b668ea2bcc0684c626a90941ad2333f0e6f6efdb3fe3` |
| New combined instructions | `v16.txt` | `13a19dad456271de744ef106e41ba64ded60e31dbf15405ae5b6adac61490ac4` |

Version 16 is exactly Source Guides v13 plus the two unchanged date-context
paragraphs from main v3, inserted after the introduction. No other policy text
changes. Runtime selects v16 explicitly and keeps Source Guides question-policy
v2. Historical Source Guides instructions v1 and v4 through v13 retain their
existing filenames and bytes. No current consumer selects either relocated
historical prompt.

The prompt-resource regression retains main's fixed hashes for v2/v3 and adds
hashes for v4 through v16. The rendered-prompt expectation adopts v16 without
altering either v1 baseline fixture. Runtime evaluation digests still derive from
the selected instructions. A byte comparison verified all 45 historical
evaluation report files against both merge parents without changing any report.

## Integration checks

The automatically merged files edited by both branches were inspected, including
startup, chat and retrieval evaluation tests, domain language, and user and audit
documentation. The work index retains both completion records.

- Focused date, evaluation, prompt, startup, and fusion tests passed, 101 tests.
- `uv sync --locked --dev` passed. The final deterministic suite passed with
  1,702 tests, 71 opt-in skips, and the existing OpenRouter sampling warning.
- The added HTTP/SQLite test verifies a guide's fixed date across midnight, a
  fresh date on explicit update, unchanged wording in both model stages and all
  retrieval branches, and preserved guide identity with a new attempt identity.
- The fixed-date evaluation regression also verifies direct-question mode and
  absence of a Query Rewriter exchange.
- All 31 Node reviewer tests passed.
- All 10 opt-in Source Guides browser regressions passed at desktop and mobile
  sizes against controlled local requests and temporary storage.
- Changed Python files pass Ruff lint. The manually resolved production modules,
  the new application regression, and the changed prompt/evaluation tests pass
  formatting. The manually resolved production modules and new application
  regression pass `ty check`.

The initial full deterministic run had 32 failures and eight errors from denied
loopback binds in the sandbox. It also exposed one old Source Guides assertion
that expected the question before the new date-context message. That assertion
now checks the question in its new position. The suite was rerun with local
loopback permission and passed. `git diff --check` also passed.

At merge commit `feb9eff`, broader type checking reported 48 diagnostics in three
unchanged main files,
`scripts/review_chat_eval.py`, `src/knowledge_map/evaluation/persistence.py`, and
`src/knowledge_map/evaluation/rag_review.py`. Their contents matched the main merge
parent byte-for-byte at that commit. Broad formatting also reported one unchanged
main assertion in `tests/test_chat_eval_review.py`. The six existing prompt-resource test type
diagnostics and two existing chat-evaluation test type diagnostics remain; the
latter were reproduced against the premerge HEAD file. These were not introduced
by integration. An inherited type diagnostic in the changed chat module was
resolved by naming the two telemetry date attributes explicitly, with identical
values.

These deterministic and controlled-browser checks verify contracts and reader
behavior. They do not measure model relevance quality. No live model evaluation
or public deployment was performed during integration.

## Independent review correction

Independent Spec review found a P2 mismatch between Source Guides outputs and
main's report consumers. Direct submissions record `assessment.status` and
`assessment.explanation`, while the RAG projection and summary still read only
historical `preparation` fields. Declined and Needs Edit cases appeared as
`no_answer`; Deferred explanations and direct decline counts were lost.

Regression tests reproduced all three direct assessment projection failures and
a mixed current/historical report summary that counted one decline instead of
two. The consumers now prefer the current assessment and fall back to historical
preparation. Legacy `needs_clarification` remains supported. Failure and unresolved
outcomes keep precedence, and Deferred guidance retains its context and generation
judgment inputs. The CLI regression also verifies that summarizing a report leaves
its saved bytes unchanged.

The focused evaluation/report suite passed 87 tests, and the 31 Node reviewer
tests passed. The final deterministic suite passed with 1,709 tests, 71 opt-in
skips, and the existing OpenRouter sampling warning. Changed files pass Ruff lint,
formatting, and whitespace checks.
The type check reproduces the same 36 existing RAG projection diagnostics and
three existing import-loader diagnostics in the summary tests, with no new
diagnostics. No prompt, historical report, inbox feedback, or browser code changed.
