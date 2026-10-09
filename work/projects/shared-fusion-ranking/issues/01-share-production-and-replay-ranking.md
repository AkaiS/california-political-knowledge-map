# 01 Share ranking across production and report replay

Labels: ready-for-agent

## Parent

[Shared fusion ranking](../PRD.md)

## What to build

Production retrieval and compact-report replay use one fusion policy and return
the same chunk ordering and scores as before. Preserve the existing interfaces
and keep representation-specific provenance in their adapters. A completed
ticket is verifiable through both interfaces without a model or live graph.

## Acceptance criteria

- [ ] Characterize uncovered ranking rules through independent expected outputs
      before changing ownership; retain existing expected outcomes and parity
      checks rather than duplicating checks already present.
- [ ] One private implementation owns best branch ranks, unique-chunk nomination,
      eligibility, reciprocal-rank arithmetic, deterministic ties, and final
      truncation for production fusion and compact-report replay.
- [ ] Existing interfaces and return types remain compatible. Replay consumes
      retained ranks and recorded eligibility without fabricated provenance.
- [ ] Production and replay return unchanged chunk identities, ranks, and numeric
      scores for default and nondefault configurations. Exact adapter parity
      covers branch limits 2, 50, and 75, ties, duplicates, and deep cross-branch
      contributions.
- [ ] Production preserves all original contributions, their ordering, source
      identity validation, routes, branch scores, graph claims, and distinct graph
      identities. Input records remain unchanged.
- [ ] Configuration validation, defaults, and the production unweighted baseline
      retain their existing behavior. Raw scores cannot affect ranking.
- [ ] Failed, skipped, successful-empty, and entirely empty outcomes remain
      unchanged. Production selection observations remain accurate; replay
      introduces no production observation side effects.
- [ ] Existing compact reports replay without mutation or migration, honoring
      explicit eligibility when present and current derivation when absent.
- [ ] Focused fusion and retrieval-report behavior checks pass through uv.
      Inspect that both adapters use one ranking implementation. Record commands,
      outcomes, and material limitations in the completion comment.

## Blocked by

None. Can start immediately.

## Scope of this slice

Compact-report retention remains behaviorally compatible during this ticket.
Its separate eligibility calculation is replaced in ticket 02; it must not
grow a second shared policy or change the report format in the meantime.

## Comments

2026-10-08: Published after the user approved the two-ticket breakdown and
the dependency from ticket 02 to ticket 01. Implementation has not started.
