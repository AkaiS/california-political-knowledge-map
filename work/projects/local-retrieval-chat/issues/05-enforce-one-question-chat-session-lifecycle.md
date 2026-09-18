# 05 — Enforce the one-question Chat Session lifecycle

Labels: ready-for-agent

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

- [ ] Different browser conversation IDs use isolated Chat Sessions and cannot
      approve, correct, or receive the answer belonging to another conversation.
- [ ] A Chat Session object is removed from the active registry after an answer,
      a Declined outcome, an unavailable rewrite, or another unrecoverable
      terminal failure.
- [ ] A rejected proposal remains active while it awaits the next correction
      message.
- [ ] A later message in a terminal browser conversation receives deterministic
      guidance to start a new chat without invoking the Query Rewriter, Chat
      Agent, or retrieval.
- [ ] A later message carrying browser history to a restarted application cannot
      reconstruct or continue the old Chat Session and receives the same
      deterministic new-chat guidance.
- [ ] A genuinely new browser conversation may still create a new Chat Session
      after another conversation has completed or after the application restarts.
- [ ] Process exit invalidates every pending proposal and awaiting-correction
      state while leaving browser-managed history outside the server's concern.
- [ ] The implementation adds no durable session store, server-side transcript,
      expiry timer, time-to-live setting, recovery mechanism, or background
      cleanup worker.
- [ ] ASGI-level tests cover conversation isolation, every terminal cleanup path,
      rejected-session retention, attempted second questions, and restart
      behavior without asserting the private registry representation.

## Blocked by

- [03 — Approve and inspect a Retrieval Answer](03-approve-and-inspect-retrieval-answer.md).
- [04 — Reject and revise a Query Rewrite Proposal](04-reject-and-revise-query-rewrite.md).
