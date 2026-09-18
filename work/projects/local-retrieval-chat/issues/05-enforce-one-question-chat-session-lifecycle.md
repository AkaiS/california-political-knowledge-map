# 05 — Enforce the one-question Chat Session lifecycle

Labels: completed

## Parent

[Local Retrieval Chat](../PRD.md)

## What to build

Finish the local interaction by enforcing one political question per Chat
Session across success, rejection, failure, and restart. Browser conversations
remain isolated while the process is running, terminal Chat Session objects are
released, and frontend history never becomes an accidental persistence layer.

A maintainer may read completed history in the stock frontend. Continuing that
history after an answer or process restart produces deterministic guidance to
start a new chat and never invokes a model.

## Acceptance criteria

- [x] Different browser conversation IDs use isolated Chat Sessions and cannot
      approve, correct, or receive the answer belonging to another conversation.
- [x] A Chat Session object is removed from the active registry after an answer,
      a Declined outcome, an unavailable rewrite, or another unrecoverable
      terminal failure.
- [x] A rejected proposal remains active while it awaits the next correction
      message.
- [x] A later message in a terminal browser conversation receives deterministic
      guidance to start a new chat without invoking the Query Rewriter, Chat
      Agent, or retrieval.
- [x] A later message carrying browser history to a restarted application cannot
      reconstruct or continue the old Chat Session and receives the same
      deterministic new-chat guidance.
- [x] A genuinely new browser conversation may still create a new Chat Session
      after another conversation has completed or after the application restarts.
- [x] Process exit invalidates every pending proposal and awaiting-correction
      state while leaving browser-managed history outside the server's concern.
- [x] The implementation adds no durable session store, server-side transcript,
      expiry timer, time-to-live setting, recovery mechanism, or background
      cleanup worker.
- [x] ASGI-level tests cover conversation isolation, every terminal cleanup path,
      rejected-session retention, attempted second questions, and restart
      behavior without asserting the private registry representation.

## Blocked by

- [03 — Approve and inspect a Retrieval Answer](03-approve-and-inspect-retrieval-answer.md).
- [04 — Reject and revise a Query Rewrite Proposal](04-reject-and-revise-query-rewrite.md).

## Comments

2026-09-18: Implemented one-question lifecycle enforcement at the ASGI and
application-lifespan boundaries. Browser conversations have isolated Chat
Sessions, rejected proposals remain available for correction, and every
terminal or interrupted path releases its Chat Session. Later messages to a
terminal conversation and browser history submitted after restart receive the
same deterministic new-chat guidance. State remains process-local with no
transcript, persistence, expiry, recovery, or cleanup worker.

The independent Spec review found no missing, incorrect, or out-of-scope
behavior. The Standards review found two valid issues. The lifecycle helper's
name implied that the Chat Session had finished even when approval was about to
start, so the review fix renamed it to describe retiring the browser
conversation. The ticket, project, and authoritative tracker also still marked
the completed work as ready; reconciliation completed the acceptance checklist,
closed ticket 05 and its parent PRD, and moved Local Retrieval Chat to the
completed project list.

Review verification passed 77 focused chat tests, changed-feature-file Ruff,
formatting, and type checks, `git diff --check`, and the full deterministic
suite: 1,264 passed, 47 skipped, with one existing Pydantic AI sampling warning.
No browser, live model, Neo4j, CDN, or retrieval-quality check was run, as this
ticket's deterministic ASGI boundary requires.
