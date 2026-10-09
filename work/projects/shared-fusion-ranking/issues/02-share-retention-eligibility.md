# 02 Share retention eligibility and preserve review consumers

Labels: ready-for-agent

## Parent

[Shared fusion ranking](../PRD.md)

## What to build

Compact reports retain exactly the ranks needed to reproduce production fusion
using the shared eligibility policy from ticket 01. RAG review and sampled
chunk review recover unchanged rankings and Source Article identities from
those reports. This completes the spec's single ownership of ranking policy
across production, retention, and replay.

## Acceptance criteria

- [ ] Compact-branch retention uses the shared best-rank and nomination policy;
      no independent eligibility or ranking implementation remains across the
      production, retention, and replay adapters.
- [ ] Existing compaction and replay interfaces, serialized fields, counts,
      report versions, and configuration identities remain unchanged.
- [ ] Retention keeps the first 50 unique chunks per branch and only the deeper
      ranks required for eligible chunks, with explicit branch eligibility for
      configured nomination budgets above 50.
- [ ] End-to-end production, compact-retention, and replay checks preserve exact
      identities, ranks, and scores for branch limits 2, 50, and 75, duplicates,
      ties, cross-branch tail contributions, nondefault valid configuration,
      empty branches, and final truncation.
- [ ] Tests use existing interfaces and independent expected results alongside
      parity; private helper calls or intermediate maps are not test contracts.
- [ ] RAG projection and sampled top-ten chunk review preserve their established
      outputs and Source Article identities. Existing historical reports and
      compact inputs remain unmodified.
- [ ] Existing documentation accurately describes shared ownership, preserved
      interfaces, and bounded retention. There is no new dependency, public seam,
      report migration, prompt, model call, or change to measurement definitions.
- [ ] Focused deterministic fusion, retrieval-report, RAG projection, and chunk
      review checks pass through uv, with normal deterministic CI retained.
      Record completion evidence without claiming browser or model verification.

## Blocked by

- [01 Share ranking across production and report replay](01-share-production-and-replay-ranking.md).
  Retention must reuse the policy introduced there rather than create a
  competing implementation.

## Comments

2026-10-08: Published after the user approved the two-ticket breakdown.
Ticket 01 must complete before this ticket starts. Implementation has not started.
