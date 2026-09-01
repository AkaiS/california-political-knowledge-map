# 18 — Record attempts for each request

**What to build:** Every reported model request shows the operational burden of
reaching its final response. The record distinguishes OpenRouter route attempts,
application transport attempts, and retries.

**Blocked by:** 11 — Pause every OpenRouter caller after a 429; 16 — Record the
actual OpenRouter route for each request.

Labels: completed

- [x] A request record carries OpenRouter route attempts when the response supplies them.
- [x] The record carries the application's total attempt count and retry count.
- [x] Missing OpenRouter attempt metadata remains unavailable rather than being inferred from application retries.
- [x] Agent tests prove the values from retries through report serialization.
