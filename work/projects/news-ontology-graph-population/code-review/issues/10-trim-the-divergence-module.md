Labels: ready-for-agent

## Parent

[Code Review: News Ontology and Graph Population, issues 02–07](../README.md)

## What to build

The Divergence module is reduced to what is actually called, so that it stops
implying capability that does not exist.

The `Divergence` declaration itself stays — conformance reads it to assert that
declared divergences match what the write path stamps, and the generator renders
it into `news-ontology.md`. Three helpers on it are called by nothing but tests,
and there is an unused resolvable-label alias; all four go.

The module's framing narrows from every extraction source to news. There is one
source, and writing for a hypothetical second one makes the module harder to read
than the thing it describes.

## Acceptance criteria

- [x] The `Divergence` declaration and the two call sites that read it are
      unchanged.
- [x] The three uncalled helpers are deleted.
- [x] The unused resolvable-label alias is deleted.
- [x] The module docstring describes news-derived divergence, not extraction
      sources in general.
- [x] The suite is green.

## Blocked by

- [05 Move `sequence_number` onto `LegislativeEvent`](05-move-sequence-number-onto-legislative-event.md)
