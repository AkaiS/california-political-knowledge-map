# Renewable and Fenced Evaluation Finalization Authority

Labels: completed

## Problem Statement

Evaluation Finalization is intended to let only one worker perform a run's missing report-evaluator work at a time, but its current claim is a fixed-duration lease. The runner verifies ownership immediately before invoking a report evaluator and then performs no renewal while that potentially long, nondeterministic operation runs. If the invocation outlives the lease, a second worker may recover the expired claim and invoke the same missing evaluator concurrently. The stale worker is fenced from saving a Report Evaluator Execution, but duplicate invocation still spends resources and may repeat external effects, violating the intended finalization exclusivity during healthy operation.

The durable fences are also incomplete around the rest of finalization. Report checkpoints require a matching live claim, while Evaluation Run completion checks only claim identity and can succeed after mere expiry when no successor has replaced the claim. Release Gates may run long enough to expose that gap. The fixed `now` value accepted by finalization also freezes time when supplied, which is unsuitable for a renewable authority lifecycle and makes realistic deterministic concurrency testing awkward.

The existing concurrency tests prove that a second worker cannot acquire a claim while the first worker's fixed lease remains live. They do not advance time beyond the original expiry while the first evaluator remains in flight, so they do not cover the reported race. Evaluation Finalization needs continuously renewed authority, consistent live-claim fencing, deterministic recovery diagnostics, and tests that exercise the full runner and ledger boundary.

## Solution

Protect each Evaluation Finalization Attempt with one continuously held, renewable, expiring authority claim. The Evaluation Ledger will own current time and atomically authorize acquisition, renewal, report checkpointing, completion, and recovery. The runner will maintain the claim with a heartbeat throughout report materialization, report-evaluator invocation, checkpointing, Release Gate evaluation, and completion. Callers continue to configure only the lease duration, which remains 300 seconds by default; heartbeat cadence is derived internally at approximately one-third of that duration.

A healthy worker therefore retains authority for an arbitrarily long report evaluator, and competing workers remain unable to begin the same missing work. Expiry irreversibly ends an attempt even if no successor has acquired the run. A stale in-flight evaluator may finish locally, but its output is discarded, no additional evaluator or gate work begins, and the ledger rejects stale checkpoints and completion. The same finalization call never reacquires authority. A later attempt resumes from terminal report evidence.

The guarantee is exactly one terminal Report Evaluator Execution per frozen evaluator identity, not exactly-once evaluator invocation across process suspension or failure. Report evaluator work must tolerate replay after genuine authority loss. Release Gates are deterministic, side-effect-free policy checks and may all be replayed by a recovering attempt; external release actions consume persisted outcomes only after finalization completes.

When a worker atomically replaces an expired claim, the ledger will append a factual Evaluation Run Issue describing the observed claim recovery without speculating about why the prior worker stopped renewing. Worker-local renewal history and causes remain telemetry. Narrow retries are allowed only for explicitly classified SQLite `busy` or `locked` persistence conflicts, only while the last confirmed lease remains live, and never by rerunning an evaluator.

## User Stories

1. As an evaluation operator, I want long-running report evaluators to retain finalization authority, so that normal evaluator duration cannot trigger competing work.
2. As an evaluation operator, I want a competing worker rejected while another healthy worker renews its claim, so that one run has one active finalizer during healthy operation.
3. As an evaluation operator, I want authority maintained across the whole Evaluation Finalization Attempt, so that report materialization, evaluators, checkpoints, gates, and completion share one safety boundary.
4. As an evaluation operator, I want the existing 300-second lease default retained, so that this correctness change does not unexpectedly alter recovery timing.
5. As an evaluation operator, I want heartbeat cadence derived from lease duration, so that I do not have to coordinate two related timing settings.
6. As an evaluation operator, I want multiple renewal opportunities before expiry, so that one brief persistence conflict does not forfeit authority.
7. As an evaluation operator, I want claim expiry to irreversibly end an attempt, so that stale authority cannot resurrect and race a recovery worker.
8. As an evaluation operator, I want a finalization call that lost authority to exit rather than reacquire automatically, so that ownership epochs remain explicit.
9. As an evaluation operator, I want a fresh finalization attempt to resume from terminal report evidence, so that expensive completed work is preserved.
10. As an evaluation operator, I want both successful and failed terminal Report Evaluator Executions skipped during recovery, so that already-accounted work is not rewritten.
11. As an evaluation operator, I want an uncheckpointed evaluator invocation eligible for replay after claim loss, so that a run cannot remain permanently incomplete.
12. As an evaluation investigator, I want exactly one terminal Report Evaluator Execution per frozen evaluator identity, so that run evidence remains unambiguous.
13. As an evaluation investigator, I want stale evaluator output rejected, so that evidence produced outside live authority cannot enter the ledger.
14. As an evaluation investigator, I want stale evaluator failures rejected as well as stale successes, so that a lost attempt cannot decide terminal evaluator status.
15. As an evaluation maintainer, I want no additional report evaluator to start after claim loss, so that a stale worker stops consuming resources once its in-flight invocation returns.
16. As an evaluation maintainer, I want no Release Gate to start after claim loss, so that stale policy work does not continue unnecessarily.
17. As an evaluation maintainer, I want claim loss represented by a typed operational error, so that orchestrators can distinguish lost authority from evaluator failure or controlled stopping.
18. As an orchestrator maintainer, I want claim-loss errors to carry run, claim, owner, expiry, and known renewal-failure context, so that operational logs are actionable.
19. As an orchestrator maintainer, I want worker-local claim-loss errors to bubble to the orchestrator, so that the orchestration layer remains responsible for logging and retry scheduling.
20. As an observability operator, I want renewal success and failure history emitted as telemetry, so that heartbeat behavior is diagnosable without expanding the durable claim model.
21. As an evaluation investigator, I want expired-claim recovery recorded as an Evaluation Run Issue, so that the durable run explains why a later finalization attempt took ownership.
22. As an evaluation investigator, I want recovery issues to state only ledger-proven facts, so that lifecycle diagnostics do not invent a crash, suspension, or network cause.
23. As an evaluation investigator, I want the prior claim identity, owner, acquisition, and expiry represented in recovery diagnostics, so that the recovered attempt is traceable.
24. As an evaluation operator, I want transient heartbeat persistence conflicts treated as temporarily unknown ownership, so that one SQLite contention event does not immediately stop a healthy attempt.
25. As an evaluation operator, I want new evaluator work paused while ownership cannot be reconfirmed, so that uncertainty does not expand the amount of potentially stale work.
26. As an evaluation operator, I want renewal retried only while the last confirmed lease remains live, so that retry cannot revive expired authority.
27. As an evaluation operator, I want report checkpoint persistence retried for narrowly classified SQLite contention, so that a completed nondeterministic evaluator need not be invoked again because of a brief lock.
28. As an evaluation operator, I want completion persistence retried for narrowly classified SQLite contention, so that fully accounted work can complete when a brief lock clears.
29. As an evaluation investigator, I want checkpoint retry to reuse the exact execution and observation identities, so that retries cannot duplicate evidence.
30. As a persistence maintainer, I want exact report-checkpoint replay to be idempotent, so that an ambiguous persistence acknowledgement is safe to repeat.
31. As a persistence maintainer, I want conflicting checkpoint content rejected, so that idempotency cannot conceal inconsistent evidence.
32. As a persistence maintainer, I want non-retryable database, validation, constraint, and programming errors to fail immediately, so that retry does not mask durable defects.
33. As a persistence maintainer, I want the Evaluation Ledger to own the clock used for authority decisions, so that callers cannot freeze or inconsistently supply transactional time.
34. As a test maintainer, I want a shared controllable ledger clock, so that expiry and recovery scenarios remain deterministic without wall-clock sleeps.
35. As a persistence maintainer, I want renewal to require the matching claim, a still-future expiry, and a finalization-pending run in one transaction, so that authority checks cannot race state changes.
36. As a persistence maintainer, I want report checkpointing to require the matching live claim in the checkpoint transaction, so that preflight ownership checks are not trusted as fences.
37. As a persistence maintainer, I want Evaluation Run completion to require the matching live claim in the completion transaction, so that a worker cannot complete after mere expiry.
38. As an evaluation operator, I want successful completion to atomically persist gate outcomes, transition the run, and clear authority, so that completion has one durable outcome.
39. As an evaluation operator, I want early claim release treated as best-effort cleanup, so that release failure cannot corrupt evidence or mask the attempt's original outcome.
40. As an evaluation operator, I want natural expiry to recover from unconfirmed early release, so that explicit cleanup is not a correctness dependency.
41. As an evaluation operator, I want a controlled finalization stop distinguished from Evaluation Run cancellation, so that pausing report work leaves the run resumable.
42. As an evaluation operator, I want a controlled stop to begin no further evaluator or gate work after an in-flight evaluator returns, so that stopping has a predictable boundary.
43. As an evaluation operator, I want a controlled stop to leave the run finalization-pending without a run issue, so that intentional pausing is not reported as a failure.
44. As a release owner, I want Release Gates to be deterministic and side-effect-free, so that recovery can replay them safely.
45. As a release owner, I want deployments, notifications, approvals, and other external actions kept outside Release Gates, so that replay cannot duplicate release effects.
46. As a release owner, I want gate outcomes persisted only with fenced completion, so that a stale worker cannot publish release policy results.
47. As an evaluator author, I want the concurrency contract to acknowledge possible replay after genuine worker failure, so that I can keep evaluator effects replay-safe.
48. As a maintainer, I want synchronous and asynchronous report evaluators protected by the same heartbeat semantics, so that execution style does not alter authority safety.
49. As a maintainer, I want renewal history kept out of the durable claim schema, so that current ownership and expiry remain the claim's only durable responsibility.
50. As a CI maintainer, I want the original lease-expiry race reproduced deterministically, so that the regression cannot return unnoticed.

## Implementation Decisions

- Preserve `EvaluationRunner.finalize()` as the public orchestration boundary and the Evaluation Ledger as the atomic authority boundary.
- Introduce a ledger-owned clock dependency that defaults to current timezone-aware UTC time. All authority transactions sample this clock after obtaining the transaction's write position. Remove the fixed current-time argument from Evaluation Finalization; tests inject one shared controllable clock into every ledger connection participating in a scenario.
- Keep the existing claim identity, owner, acquisition time, and expiry as the complete durable claim model. Do not add persisted heartbeat history or a last-renewed field.
- Add an atomic claim-renewal operation. Renewal succeeds only when the run remains finalization-pending, the exact claim identity is still current, and its expiry is strictly later than the ledger's sampled current time. Successful renewal moves expiry to current time plus the attempt's lease duration.
- Never renew an expired claim, even when no successor has acquired it. Never let the same Evaluation Finalization Attempt acquire a new claim after loss.
- Maintain authority with a runner-owned heartbeat independent of evaluator execution, so both synchronous calls and awaitable report evaluators remain protected. Start it immediately after acquisition and keep it active through report materialization, evaluator invocation, checkpoint persistence, Release Gate evaluation, and atomic completion.
- Derive heartbeat cadence internally at approximately one-third of the configured lease duration. Keep `lease_seconds` as the only public timing setting and retain its 300-second default.
- Represent definitive loss and temporarily unknown ownership separately. A conditional renewal that reports a non-current, expired, or ineligible claim is definitive loss. An explicitly classified transient persistence conflict is unknown ownership and may be retried while the last confirmed expiry remains in the future.
- Use a thread-safe claim-loss signal shared by the heartbeat and finalization loop. Check it before starting each evaluator, after an in-flight evaluator returns or raises, before starting each Release Gate, and before persistence transitions. Database-side live-claim predicates remain the authoritative fence.
- On claim loss, discard the in-flight evaluator's uncheckpointed success or failure, begin no further evaluator or gate work, stop renewal, and raise a typed `FinalizationClaimLostError`. Include run identity, claim identity, owner identity, last confirmed expiry, loss classification, and any known renewal exception.
- Emit heartbeat renewals, transient renewal failures, definitive claim loss, and best-effort release failures as operational telemetry. Let `FinalizationClaimLostError` bubble to the orchestrator for logging. Do not let a stale worker append worker-local details to the Evaluation Run.
- When claim acquisition replaces an expired claim, read the prior claim and append a `finalization_claim_recovered` Evaluation Run Issue in the same transaction that installs the successor claim. Record prior attempt identity, owner, acquisition, expiry, successor owner, and recovery time without inferring the cause of expiry.
- Keep an expired claim visible until release, completion, or atomic recovery replaces it. This permits diagnosis before recovery; no separate durable heartbeat-history record is introduced.
- Require the exact matching live claim inside report-checkpoint transactions and inside Evaluation Run completion. Completion must check expiry as well as identity, even when no successor has acquired the claim.
- Make successful completion atomically validate terminal evidence, persist issues and Release Gate outcomes, transition the Evaluation Run to completed, and clear finalization authority. A heartbeat response racing after confirmed completion must not convert success into claim loss.
- Treat explicit exact-token release as best-effort cleanup for controlled stops and exceptional exits. Stop the heartbeat before ending the attempt, attempt release without masking the original result or exception, emit telemetry on failure, and rely on expiry for eventual recovery. Successful completion already clears the claim atomically.
- Rename or replace the finalization-specific cancellation callback with `should_stop_finalization` so it cannot be confused with cancelling an Evaluation Run. A controlled stop waits for an in-flight evaluator to return, starts no further work, ends heartbeat renewal, attempts best-effort release, returns the partial result normally, and leaves the run finalization-pending without adding an issue.
- Preserve the existing rule that both successful and failed Report Evaluator Executions are terminal evidence and are skipped by later attempts. Claim loss is operational and produces no terminal evaluator evidence from the stale invocation.
- Permit at-least-once report-evaluator invocation only across genuine authority loss while maintaining exactly one terminal execution checkpoint per frozen evaluator identity. Report evaluators must tolerate replay; the framework does not forcibly terminate an in-flight evaluator or retract its external requests.
- Define Release Gates as deterministic, side-effect-free calculations over terminal run evidence and explicit gate configuration. Do not checkpoint individual gates. If an attempt loses authority before completion, its gate outcomes are discarded and the recovering attempt reruns all gates. External release actions consume persisted outcomes after completion.
- Retry only explicitly classified SQLite `busy` or `locked` conflicts for renewal, report checkpointing, and completion. Use bounded backoff within the last confirmed live lease, pause new evaluator or gate work until ownership is reconfirmed, and fail immediately for claim loss, constraint conflicts, invalid state, validation failures, disk exhaustion, corruption, and programming errors.
- Retry persistence with the exact same Report Evaluator Execution, observation, and issue payload. Make exact report-checkpoint replay idempotent as one atomic no-op success, including avoiding duplicated issues or observations. Reject a replay when any stored content conflicts.
- Use transaction modes and timestamp sampling order that prevent a writer from waiting past expiry and then succeeding with a stale pre-lock timestamp.
- Make heartbeat scheduling controllable behind an internal runner test seam without exposing heartbeat cadence as a production setting.
- Preserve the current explicit finalization model. Do not introduce implicit background workers; the caller or orchestrator initiates a new attempt after a typed claim-loss error or observes a finalization-pending run.
- Treat ADR 0012 and the project glossary definitions for Evaluation Finalization, Evaluation Finalization Attempt, Evaluation Run Issue, and Release Gate as governing terminology and behavior.

## Testing Decisions

- Prefer one highest-level behavioral seam: execute `EvaluationRunner.finalize()` against a temporary real SQLite Evaluation Ledger while coordinating two ledger connections and deterministic blocking report evaluators. Assert returned and persisted Evaluation Run behavior rather than heartbeat thread internals.
- Use the existing finalizer claim, expired-claim recovery, missing-report-work resumption, and competing-finalizer tests as prior art. Extend those scenarios instead of creating a parallel test-only finalizer.
- Provide a shared fake ledger clock and an internal controllable heartbeat scheduler so concurrency tests advance authority time deterministically without real sleeps. Continue using synchronization events only to establish evaluator entry and release ordering.
- Add the primary regression test: worker A enters a report evaluator, time advances beyond A's original expiry, A's heartbeat renews, worker B attempts finalization, B is rejected, A completes, and exactly one evaluator invocation and one terminal Report Evaluator Execution exist.
- Add a genuine-loss concurrency test: pause A's heartbeat while its evaluator is in flight, advance past expiry, let B recover and begin the same missing evaluator, resume A, and prove A discards its result, runs no later evaluator or gate, cannot checkpoint or complete, and raises `FinalizationClaimLostError`.
- In the genuine-loss test, prove B alone checkpoints terminal evidence and the final run contains one Report Evaluator Execution for the frozen identity.
- Test synchronous and asynchronous blocking report evaluators through the same finalization seam.
- Test atomic renewal directly at the ledger seam: a matching live claim extends expiry; acquisition time remains unchanged; a competing claim remains rejected; an expired, replaced, released, completed, or wrong-run claim cannot renew.
- Test that an expired claim cannot renew even when no successor exists.
- Test that the ledger clock, not a caller-supplied fixed timestamp, governs acquisition, renewal, checkpoint, completion, and recovery across multiple connections.
- Test timestamp sampling under write contention so a renewal or fenced write cannot wait past expiry and then succeed using a stale pre-contention time.
- Test report checkpoint fencing for both expiry without replacement and replacement by a successor claim.
- Test completion fencing for expiry without replacement, covering the current gap where identity still matches but authority is no longer live.
- Test claim loss during Release Gate evaluation: the stale attempt cannot complete, its gate outcomes are not persisted, and a recovery attempt reruns every gate before completing.
- Test that a healthy heartbeat remains active during long Release Gate evaluation and prevents takeover.
- Test controlled finalization stopping: no later evaluator or gate starts, the run remains finalization-pending, no cancellation or recovery issue is added, and confirmed release permits immediate resumption.
- Test failed best-effort release: the original controlled result or exception is not masked, release failure is emitted as telemetry, the stored claim remains until expiry, and recovery succeeds afterward.
- Test atomic recovery diagnostics: replacing an expired claim appends exactly one `finalization_claim_recovered` issue with factual prior and successor metadata; a rejected competing acquisition and a recovered transient renewal conflict append no issue.
- Test that worker-local renewal exceptions appear in telemetry and `FinalizationClaimLostError` but not in Evaluation Run Issues.
- Test narrow retry classification: SQLite `busy` or `locked` conflicts retry within the lease; unrelated operational, constraint, validation, state, and programming errors do not retry.
- Test that no new evaluator begins while ownership is unknown and that work resumes only after successful renewal.
- Test report-checkpoint retry without reevaluation: one evaluator invocation produces one execution payload, a retryable persistence conflict occurs, the same payload succeeds later, and the evaluator call count remains one.
- Test exact checkpoint replay after an ambiguous acknowledgement: identical execution, observations, and issues produce no duplicate rows or duplicated issue entries.
- Test conflicting checkpoint replay: changed execution or observation content under an existing identity is rejected atomically.
- Test bounded persistence retry expiry: when contention lasts beyond the confirmed lease, the attempt raises claim loss and does not persist or continue.
- Test idempotent completion retry when the first completion committed but its acknowledgement was ambiguous.
- Test the 300-second default and derived heartbeat cadence at the heartbeat policy seam without sleeping for those durations.
- Test successful completion stops the heartbeat and clears authority atomically without a late renewal response falsely reporting claim loss.
- Keep all tests deterministic and offline; no live model provider or nondeterministic evaluator is required to establish concurrency behavior.
- Avoid assertions about private thread names, exact SQL strings, incidental helper structure, or exact retry sleep sequences. Test observable ownership, invocation count, durable evidence, run status, issues, exceptions, and telemetry.

## Out of Scope

- Forcibly interrupting synchronous evaluators, cancelling arbitrary awaitables, terminating worker processes, or retracting external provider requests.
- Guaranteeing exactly-once report-evaluator invocation across process crash, machine suspension, or authority loss.
- Retrying a terminal successful or failed Report Evaluator Execution.
- Automatically rerunning an evaluator after a non-persistence evaluator exception; existing failed terminal evidence semantics remain unchanged.
- Resuming incomplete case execution within the same Evaluation Run or changing bounded case concurrency.
- Introducing implicit background finalization or an orchestrator implementation.
- Persisting heartbeat history, `last_renewed_at`, or a general Finalization Attempt audit log in the durable claim.
- Exposing heartbeat cadence as an independently configurable production setting.
- Changing the default 300-second lease duration.
- Checkpointing Release Gates individually or introducing versioned gate identities and configurations.
- Performing deployments, notifications, approvals, or other external release actions inside Release Gates.
- Broad retry of arbitrary SQLite operational errors, disk failures, corruption, invalid state, validation failures, or programming errors.
- Generalizing persistence retries across unrelated Evaluation Ledger operations.
- Changing Evaluation Metric Definitions, evaluator result semantics, Frozen Aggregate Manifest content, or report materialization semantics.
- Migrating historical production evaluation data; the change uses existing claim fields and the project has no production evaluation ledger compatibility requirement.

## Further Notes

- This specification closes the gap in the previously completed “Guard Evaluation Finalization against competing workers” ticket: the existing implementation fences stale durable evidence but does not renew authority during an unbounded evaluator invocation.
- ADR 0012, “Renew and fence Evaluation Finalization authority,” records the architectural tradeoff between automatic recovery and exactly-once invocation. The domain glossary separately defines Evaluation Finalization Attempt, Evaluation Run Issue, and Release Gate.
- The critical safety rule is continuous authority: a worker may renew only before expiry, and every durable write must independently fence on the matching live claim. Pre-call ownership checks and heartbeat state improve control flow but never replace transactional predicates.
- The critical liveness rule is resumability from terminal evidence: failure to save an invocation means the invocation may be replayed, while saved successful or failed executions are never rerun.
- Release is intentionally not a correctness boundary. Atomic completion clears authority; early release only shortens recovery latency when an attempt stops before completion.
- The test-seam choice follows existing repository practice: blocking report-evaluator doubles, temporary SQLite ledgers, multiple ledger connections, and runner-level lifecycle assertions already exercise the relevant behavior at the highest practical seam.
