# Bound transient renewal contention by confirmed authority

Labels: ready-for-agent

This follow-up closes the renewal-contention boundary gap in the [Renewable and Fenced Evaluation Finalization Authority PRD](../PRD.md).

## What to build

Ensure an Evaluation Finalization Attempt retries transient SQLite renewal contention only while its last ledger-confirmed authority lease remains live. The heartbeat must be able to decide that the confirmed lease has expired even when contention prevents the Evaluation Ledger from answering renewal or ownership queries.

Production ledger and heartbeat clocks may independently use timezone-aware UTC, but they must occupy the same time domain. Deterministic scenarios must be able to inject one shared controllable clock into both components so authority expiry advances consistently without wall-clock sleeps.

## Acceptance criteria

- [ ] The heartbeat compares its current time with the last confirmed claim expiry before treating authority as potentially live.
- [ ] A claim is live only while its expiry is strictly later than the current time; equality is treated as expiry.
- [ ] The heartbeat checks the confirmed expiry before an ownership query and again after a retryable contention failure, so time spent blocked cannot extend authority.
- [ ] Retryable SQLite `busy` or `locked` failures may keep authority temporarily unknown only while the last confirmed lease remains live.
- [ ] Reaching the confirmed expiry records definitive claim loss and causes the attempt to raise `FinalizationClaimLostError`; it does not retry, reacquire authority, or resume evaluator or Release Gate work.
- [ ] Non-retryable ownership-query failures retain their existing immediate claim-loss behavior.
- [ ] Production clocks default to current timezone-aware UTC.
- [ ] The Evaluation Ledger and heartbeat accept the same controllable clock for deterministic tests, without requiring production to share the same callable instance.
- [ ] A deterministic regression test keeps both renewal and ownership queries contended through the confirmed expiry and proves that retries terminate without wall-clock sleeps.
- [ ] Existing healthy-renewal, recovered-contention, completion-race, and finalization test scenarios continue to pass.

## Blocked by

None — can start immediately.

