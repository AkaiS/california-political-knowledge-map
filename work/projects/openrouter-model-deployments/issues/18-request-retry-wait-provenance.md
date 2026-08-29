# 18 — Record attempts and rate-limit waits for each request

**What to build:** Every reported model request shows the operational burden of
reaching its final response. The record distinguishes OpenRouter route attempts,
application transport retries, and total time spent waiting for rate limits.

**Blocked by:** 11 — Pause every OpenRouter caller after a 429; 16 — Record the
actual OpenRouter route for each request.

Labels: completed

- [x] A request record carries OpenRouter route attempts when the response supplies them.
- [x] The record carries the application's total attempt count, retry count, and accumulated rate-limit wait time.
- [x] Request-local non-rate retries do not fabricate rate-limit wait time.
- [x] Missing OpenRouter attempt metadata remains unavailable rather than being inferred from application retries.
- [x] Controlled-clock Agent tests prove the values from rate limit through report serialization.
