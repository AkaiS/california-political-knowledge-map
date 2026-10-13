# Control a search attempt

Update guide and Retry search again for a saved question. Cancel targets its selected running attempt. Existing successful reading remains available during an update and after failure or cancellation.

## Sub-features

- `attempt-update` creates another attempt using the same saved question.
- `attempt-retry` explicitly retries a failed or interrupted guide.
- `attempt-cancel` stops the selected running attempt.
- `attempt-interrupt` marks unfinished work Interrupted after shutdown or restart.
- `attempt-retain` keeps previous reading until a successful update replaces it, including an empty result.

## How to get to it (user POV)

- Open a saved guide and choose `Update guide` when it is idle.
- Open a failed or interrupted guide and choose `Retry`, the alternate label of `#update`.
- Open a running guide and choose `Cancel`.
- Stop and restart the local application while its selected attempt is running, then reopen that guide.

## Driving it with HTTP and authorized browser controls

Preconditions:

- Hold an owned instance with `--pause-after-doctor`. Set `VERIFY_GUIDE` to an idle saved guide ID.
- Retention requires a prior successful guide with nonempty articles. Retry requires a genuine failed or interrupted attempt. The default missing-reference fixture supplies neither precondition.

- Update or retry. Run `curl --fail-with-body -sS -D update.headers -H 'Content-Type: application/json' -d '{}' "$VERIFY_URL/api/guides/$VERIFY_GUIDE/update" > update.json`. Require HTTP 202, unchanged guide ID and question, and a new latest attempt ID. Save the prior successful response for retention checks. In the browser, click `Update guide` or `Retry` and require the corresponding running state in `#guide-attempt`.
- Guard concurrent updates. While the attempt is running, repeat the same POST into `duplicate-update.json` and record the HTTP status. Require 409 and no additional attempt. The browser disables `#update` while running.
- Cancel the selected attempt. Run `VERIFY_ATTEMPT=$(uv run --frozen python -c 'import json; print(json.load(open("update.json"))["latest_attempt"]["attempt_id"])')`, then `curl --fail-with-body -sS -H 'Content-Type: application/json' -d '{}' "$VERIFY_URL/api/guides/$VERIFY_GUIDE/attempts/$VERIFY_ATTEMPT/cancel" > cancelled.json`. Require latest attempt `cancelled` if it was still running. In the browser, click the visible `Cancel` button and capture the latest-attempt outcome.
- Check retained reading. Run `curl --fail-with-body -sS "$VERIFY_URL/api/guides/$VERIFY_GUIDE" > retained.json`. After cancellation or failure, require the prior article set and `last_retrieved_at`, plus the newer attempt outcome and timing. In the browser require old reading alongside the latest-attempt message. A successful update replaces reading even if its result is empty.
- Interruption and retry. From the repository root, run `CHAT_DEPLOYMENT=local .agents/skills/verify-source-guides/scripts/verify.py --port 8132 --interrupt-after-submit --evidence-dir docs/verification/source-guides/interruption-run`. Use a new directory for a repeat. The helper stops its own submitted running attempt, restarts with the same copy, runs doctor, requires `interrupted`, and POSTs update explicitly. Require `interrupted.json`, `retried.json`, a new attempt ID, and `sqlite-proof.json` with two attempts. This optional mode remains untested. The default helper restarts after a terminal outcome and does not prove interruption.

## Gotchas

- Fast assessment can finish before Cancel or the duplicate update arrives. That race does not prove cancellation or the 409 guard. Record the unmet running-state precondition and repeat only within authorization.
- Guide `status` may still describe old successful reading while `latest_attempt.status` reports failure or cancellation. Inspect both and `last_retrieved_at`.
- POST update accepts only `{}`. Editing question text creates a new guide through submission.
- There is no guide-delete API. Cleanup removes the run's whole disposable store after stopping its app.
- Interruption can race with completion. The helper fails if the attempt finishes before shutdown. Keep its owned lifecycle intact and report that unmet precondition.
- No attempt-control journey has been executed during generation.
