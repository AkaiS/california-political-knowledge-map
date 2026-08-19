# 03 — Every extracted Bill gets a resolution

Labels: completed

## Parent

[Bill Designation Recovery](../PRD.md)

## What to build

Bill Session Resolution returns a resolution for every extracted `Bill` node,
including the ones that yielded no Bill Designation, and the Graph Database
Adapter stops deciding anything.

Today a name that fails to parse is left out of the resolution map, and the
adapter reads a missing entry as "not a numbered bill, write nothing". It cannot
distinguish that from "a bill whose designation could not be parsed, which a
human should see", so eleven of the graph's thirteen `Bill` nodes carry
`needs_review = null` rather than the unidentifiable ones carrying `true`. The
failure is silent by construction, and the module that knows which case occurred
is not the module that decides what is written.

The resolution map is keyed by the `Bill` node's extracted name, because a node
whose name yields no designation has no number to key on. Each resolution carries
the Bill Designation it resolved to, the session, and the three provenance flags,
and it owns the full set of properties the node is written with. Two names in one
Source Article that resolve to the same Bill Designation and session mint the
same key and collapse to one node.

The adapter finds the resolution by the node's name, applies its properties, and
mints the key from its session and Bill Designation. It calls no parser, tests
for no missing entry, and imports nothing from the resolution module but the
domain model. This is what [ADR 0002](../../../docs/adr/0002-story-pipeline-architecture.md)
asks of an adapter and what [ADR 0015](../../../docs/adr/0015-resolve-identity-bearing-values-once-per-source-article.md)
asks of an article-scope resolver.

## Acceptance criteria

- [x] Every `Bill` node in an article's extractions has an entry in the
      resolution map, keyed by the node's extracted name.
- [x] A name yielding no Bill Designation resolves with no designation, no
      session, and `needs_review` set, and the node is written with those flags.
- [x] `the bill` and `Richardson's legislation` are countable by a query on
      `needs_review`, where today they carry a null.
- [x] The Graph Database Adapter performs no bill parsing and no test for a
      missing resolution.
- [x] The resolution supplies every session-related property the `Bill` node is
      written with, including the Bill Designation.
- [x] Two names in one Source Article resolving to the same Bill Designation and
      session mint one key.
- [x] The adapter test asserting that a `Bill` without a resolution gets no
      session properties is rewritten to the inverted contract, not deleted.
- [x] The resolution map is still built once per Source Article and shared
      across every chunk, as issue 07 established.

## Blocked by

- [02 — Bill Designation parsing, four forms only](02-bill-designation-parsing.md)
