# Renew and fence Evaluation Finalization authority

Superseded by ADR 0017. Its use of "Gold Set" is retired too: four of the five sets were model-labeled and are now Silver Sets under `evals/silver/` — see the amendment to ADR 0017. The Evaluation Ledger and every mechanism this decision specifies for persisting, versioning, or finalizing evaluation records are removed; Gold Sets are YAML files and run reports are JSON files, both versioned by git.

This decision refines the execution-lease portion of ADR 0005. Each Evaluation Finalization Attempt must continuously hold one renewable, expiring authority claim. The Evaluation Ledger owns time and atomically permits renewal, report checkpointing, and completion only for the matching, still-live claim. Expiry irreversibly ends an attempt; it cannot reacquire authority, while a new attempt may replace the expired claim and resume from terminal evidence.

A heartbeat preserves authority throughout report materialization, evaluator invocation, checkpointing, release-gate evaluation, and completion. Successful completion atomically clears the claim; early release is best-effort cleanup because expiry remains the recovery boundary. Recovery records a factual Evaluation Run lifecycle issue, while worker-local renewal failures remain operational telemetry.

This provides exclusive execution during healthy operation but deliberately does not promise exactly-once invocation across process suspension or failure. An already-started evaluator may return after authority is lost, but its evidence is rejected and no further evaluator or gate work starts. Report evaluator work must tolerate replay, and Release Gates must be deterministic, side-effect-free policy checks; the ledger preserves exactly one terminal checkpoint for each report evaluator identity.

## Considered options

A longer fixed lease still fails when evaluator duration exceeds its estimate. A non-expiring lock prevents automatic crash recovery. Renewing after expiry permits stale authority to race recovery, while automatically reacquiring within the same attempt risks accepting stale work across ownership epochs. Forcibly terminating evaluators adds substantial complexity and cannot retract external requests already made.

## Consequences

Healthy long-running evaluators retain authority through renewal. Recovery may replay an uncheckpointed report evaluator or every Release Gate, but stale workers cannot checkpoint or complete. Recovery latency is bounded by the configured lease duration, which remains 300 seconds by default. Heartbeat cadence, renewal telemetry, and narrowly classified persistence retries remain implementation concerns rather than architectural commitments.
