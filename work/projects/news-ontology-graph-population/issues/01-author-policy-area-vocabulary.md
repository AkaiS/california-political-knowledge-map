Labels: completed

## Parent

[News Ontology and Graph Population](../PRD.md)

## Deliverable

[The Policy Area vocabulary](../policy-area-vocabulary.md) — 27 topic slugs,
reviewed and accepted on 2026-08-06. Ticket 02 consumes it.

## What to build

The closed Policy Area vocabulary that every later ticket consumes: the list of
topics a `PolicyArea` node may take, derived from the Assembly and Senate
subject-matter standing committees rather than invented.

Each committee contributes its *topic*, not its committee name — an "Assembly
Transportation Committee" yields a `transportation` policy area. Topics appearing
in both chambers are deduplicated to a single entry. Process committees —
Appropriations, Rules, Budget, Elections and their equivalents — are excluded, so
that a bill dying in Appropriations is not recorded as being about the policy
area of appropriations.

The deliverable is the reviewed list itself, with each entry traceable to the
committee or committees it came from, and a short note on any judgement calls
(chamber-specific committees with no counterpart, committees whose topic split or
merged). It is authored here and consumed by the News Ontology module in ticket
02; nothing about it is decided again downstream.

`PolicyArea` remains a distinct label from `Committee`. The committee rosters are
the *source* of this vocabulary, not the nodes themselves — no `Committee` node is
created by this ticket.

## Acceptance criteria

- [x] Every entry is a topic slug, not a committee name, and names the standing
      committee or committees it was derived from.
- [x] Topics common to both chambers appear exactly once.
- [x] Appropriations, Rules, Budget, Elections and other process committees are
      absent, and the exclusion rule applied is written down.
- [x] Judgement calls — committees with no cross-chamber counterpart, splits, and
      merges — are recorded alongside the list.
- [x] A human has reviewed the list before it is committed.

## Blocked by

- None — can start immediately.
