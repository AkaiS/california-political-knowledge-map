# 19 — Keep concurrent Evaluation Case requests isolated and ordered

**What to build:** Request provenance remains attached to the Evaluation Case
that caused it and receives a stable request sequence within that case. A
single-call Relevance Filter case and a multi-call Coreference Resolution case
use the same reporting mechanism, even when several cases execute concurrently.

**Blocked by:** 03 — Pass a Model Deployment through Coreference Resolution;
16 — Record the actual OpenRouter route for each request.

Labels: ready-for-agent

- [ ] Every request record names the authored Evaluation Case id that caused it.
- [ ] Requests within one case receive an unambiguous sequence in call order.
- [ ] Coreference Annotator, Coreference Critic, and correction requests remain distinguishable in one case's sequence.
- [ ] Concurrent cases cannot exchange, duplicate, or lose request records.
- [ ] Relevance and both Coreference Evaluation Tasks use the same association mechanism.
- [ ] Concurrent mock-transport tests prove isolation and ordering without relying on completion order.

