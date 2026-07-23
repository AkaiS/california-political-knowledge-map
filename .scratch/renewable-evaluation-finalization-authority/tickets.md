# Tickets: Renewable Evaluation Finalization Authority

Labels: ready-for-agent

These tickets implement the [Renewable and Fenced Evaluation Finalization Authority PRD](PRD.md) as dependency-ordered, independently verifiable slices.

Work the **frontier**: any ticket whose blockers are all done. Tickets 2 and 4 can proceed independently after Ticket 1; Tickets 5, 6, and 8 can proceed independently after Ticket 3.

## Move finalization authority onto ledger-owned time

**What to build:** Make the Evaluation Ledger the sole authority for transactional time, so every claim-sensitive write uses a fresh, correctly ordered time sample and expired workers cannot mutate or complete an Evaluation Run.

**Blocked by:** None — can start immediately

- [x] The ledger accepts an injectable timezone-aware UTC clock, defaulting to the real current UTC time.
- [x] Claim acquisition, expiry recovery, checkpointing, renewal eligibility, release, and completion no longer depend on a caller-supplied fixed current time.
- [x] Finalization callers cannot freeze the authority lifecycle by passing one timestamp for the whole attempt.
- [x] Report checkpoints require the exact matching claim to remain live inside the checkpoint transaction.
- [x] Evaluation Run completion requires the exact matching claim to remain live inside the completion transaction, including when no successor has replaced an expired claim.
- [x] Transaction ordering prevents a writer that waited beyond expiry from succeeding with a time sampled before it obtained the write position.
- [x] Deterministic multiple-connection tests use one shared controllable clock and no wall-clock sleeps.

## Renew authority during long-running evaluators

**What to build:** Keep a healthy Evaluation Finalization Attempt authoritative while a long synchronous or asynchronous report evaluator is running, preventing a competing worker from starting the same missing work after the original expiry.

**Blocked by:** Move finalization authority onto ledger-owned time

- [x] A matching claim can be atomically renewed only while the run is finalization-pending and the claim remains unexpired.
- [x] Renewal extends expiry from the ledger's current time without changing the claim identity or original acquisition time.
- [x] A wrong, released, replaced, completed, or expired claim cannot renew, even when no successor exists.
- [x] The runner starts an independent heartbeat immediately after acquisition and keeps it active while report evidence is materialized and an evaluator is invoked and checkpointed.
- [x] Heartbeat behavior is identical for synchronous and asynchronous report evaluators.
- [x] Heartbeat cadence is derived internally at approximately one-third of `lease_seconds`; the 300-second default remains unchanged and no public cadence setting is added.
- [x] In the primary regression scenario, worker A remains healthy beyond its original expiry, worker B is rejected, and exactly one evaluator invocation and one terminal Report Evaluator Execution result.

## Fence and stop an attempt that loses authority

**What to build:** End an Evaluation Finalization Attempt definitively when its authority expires or is replaced, without forcibly interrupting an evaluator that is already running and without allowing the stale attempt to create evidence or continue work.

**Blocked by:** Renew authority during long-running evaluators

- [x] Claim expiry is irreversible for the current attempt, and the same finalization call never reacquires authority.
- [x] A thread-safe loss signal communicates definitive heartbeat loss to the finalization loop.
- [x] If an in-flight evaluator returns or raises after authority loss, its success or failure is discarded and creates no terminal evaluator evidence.
- [x] A stale attempt starts no later evaluator or Release Gate and cannot checkpoint or complete the run.
- [x] The stale attempt raises `FinalizationClaimLostError` with the run, claim, owner, last confirmed expiry, loss classification, and any known renewal-failure context.
- [x] Claim loss and renewal history are emitted as operational telemetry and are not appended by the stale worker to Evaluation Run Issues.
- [x] A deterministic two-worker test proves that the recovery worker alone persists one terminal execution while the stale worker exits with the typed error.

## Record factual expired-claim recovery

**What to build:** Give a recovered Evaluation Run durable, factual evidence that a successor replaced an expired finalization claim, without guessing why the original worker stopped renewing.

**Blocked by:** Move finalization authority onto ledger-owned time

- [x] Replacing an expired claim and appending its `finalization_claim_recovered` Evaluation Run Issue occur in the same transaction.
- [x] The issue records the prior claim identity, owner, acquisition time, expiry, successor owner, and recovery time.
- [x] The issue contains no inferred crash, suspension, database, process, or network cause.
- [x] One successful recovery appends exactly one recovery issue.
- [x] Rejected competing acquisition, ordinary acquisition, and recovered transient contention append no recovery issue.
- [x] An expired claim remains inspectable until release, completion, or atomic replacement; no durable heartbeat-history or last-renewed field is added.

## Handle transient renewal contention without expanding stale work

**What to build:** Let a healthy finalizer survive brief SQLite contention while treating ownership as unknown, pausing new work until the ledger reconfirms authority and refusing to retry beyond the last confirmed lease.

**Blocked by:** Fence and stop an attempt that loses authority

- [ ] Only explicitly classified SQLite `busy` or `locked` renewal conflicts are retryable.
- [ ] A retryable renewal conflict marks authority as temporarily unknown rather than definitively lost.
- [ ] No new evaluator or Release Gate begins while authority is unknown.
- [ ] Renewal uses bounded backoff and retries only while the last confirmed expiry remains in the future.
- [ ] Work may resume only after a successful renewal reconfirms ownership.
- [ ] Contention lasting beyond the confirmed lease becomes definitive claim loss and cannot revive the expired claim.
- [ ] Constraint, state, validation, disk, corruption, unrelated operational, and programming failures do not retry.
- [ ] Renewal successes, transient failures, and definitive loss are observable through telemetry without creating a recovery issue.

## Retry finalization persistence without reevaluating

**What to build:** Preserve completed nondeterministic evaluator work across brief checkpoint or completion contention by retrying the same durable operation safely, never by invoking the evaluator again.

**Blocked by:** Fence and stop an attempt that loses authority

- [ ] Only explicitly classified SQLite `busy` or `locked` conflicts are retryable for report checkpointing and completion.
- [ ] A checkpoint retry reuses the exact Report Evaluator Execution, observation, and issue identities and payloads.
- [ ] Exact checkpoint replay is one atomic idempotent success and duplicates no executions, observations, or issues.
- [ ] Replay with conflicting execution or observation content is rejected atomically.
- [ ] A retryable checkpoint conflict can clear within the live lease with one evaluator invocation and one terminal execution.
- [ ] Completion retry safely handles both a pre-commit contention failure and an ambiguous acknowledgement after a committed completion.
- [ ] Checkpoint and completion retries stop at claim expiry, preserve the live-claim fence, and never mask non-retryable defects.
- [ ] Retry behavior is deterministic and does not depend on exact sleep timing in tests.

## Protect Release Gates through completion

**What to build:** Extend continuous authority through deterministic Release Gate evaluation and atomic completion, so stale gate results never decide release policy and a recovery attempt can safely replay every gate.

**Blocked by:** Handle transient renewal contention without expanding stale work; Retry finalization persistence without reevaluating

- [ ] The heartbeat remains active throughout long Release Gate evaluation and prevents takeover by a competing worker.
- [ ] Authority is checked before starting each Release Gate and before the completion transition.
- [ ] If authority is lost during gate evaluation, the stale attempt cannot persist gate outcomes or complete the run.
- [ ] A recovery attempt reruns all gates from terminal run evidence rather than relying on partial gate checkpoints.
- [ ] Release Gates remain deterministic and side-effect-free; deployments, notifications, approvals, and other external release actions remain outside them.
- [ ] Successful completion atomically validates terminal evidence, persists issues and gate outcomes, transitions the run, and clears finalization authority.
- [ ] A heartbeat response racing after confirmed completion cannot turn a successful result into claim loss.

## Stop finalization cleanly without cancelling the run

**What to build:** Allow an operator-requested stop to end only the current Evaluation Finalization Attempt, leaving the Evaluation Run resumable and treating early claim release as cleanup rather than a correctness boundary.

**Blocked by:** Fence and stop an attempt that loses authority

- [ ] The finalization-specific callback is named `should_stop_finalization` and is not represented as Evaluation Run cancellation.
- [ ] A controlled stop waits for an already-running evaluator to return and then starts no later evaluator or Release Gate.
- [ ] The runner stops heartbeat renewal before ending the attempt.
- [ ] The run remains finalization-pending, the partial result returns normally, and no cancellation, failure, or recovery issue is added.
- [ ] Exact-token release is attempted as best-effort cleanup and confirmed release permits immediate resumption.
- [ ] Release failure does not mask the controlled result or an existing exception and is emitted as telemetry.
- [ ] When release cannot be confirmed, the stored claim remains until natural expiry and a later attempt can recover it.
- [ ] Successful completion relies on its atomic claim clearing and does not require a separate release for correctness.
