Labels: completed

## Parent

[Code Review: News Ontology and Graph Population, issues 02–07](../README.md)

## What to build

The record stops contradicting the build. Two acceptance criteria are ticked for
work that was not done, and one PRD paragraph specifies a decision that was
deliberately taken the other way.

**The PRD's provenance paragraph is amended** to the decision actually taken. No
provenance property is stamped on news-derived structure. Traceability is
structural and already complete: every extracted entity carries `MENTIONED_IN` to
its Article Chunk, and every extractor-produced relationship carries the chunk
list. The paragraph's rejection of reachability is what gets amended. The chunk
list on relationships is reclassified from an unspecified addition to a
load-bearing one, so that nobody removes the only traceability an
extractor-produced edge has.

**The PRD's justification for retaining `LegislativeEvent` is widened.** Avoiding
the conflation of a bill's multiple votes is only half the reason; the event is
also the one place a reliable date lives.

**Issue 06's provenance acceptance criterion** claims every node and relationship
is stamped with provenance. Nothing is stamped anywhere. It is rewritten to the
structural-traceability decision and points at the amendment.

**Issue 02's "`ontology.md` is unmodified" criterion** is false — the file was
changed, and is changed again by ticket 05. It is rewritten to match the history
and points at the authored-not-frozen ADR.

## Acceptance criteria

- [x] The PRD's provenance paragraph states structural traceability and names the
      chunk list on relationships as load-bearing.
- [x] The PRD's `LegislativeEvent` retention justification names the date.
- [x] Issue 06's provenance criterion states what was decided, not what was
      claimed.
- [x] Issue 02's `ontology.md` criterion matches the history.
- [x] Each rewritten criterion points at the amendment or ADR superseding it.

## Blocked by

- [05 Move `sequence_number` onto `LegislativeEvent`](05-move-sequence-number-onto-legislative-event.md)
