Labels: completed

## Parent

[News Ontology and Graph Population](../PRD.md)

## What to build

Model output stops reaching the graph unchecked. Conformance lives in the Entity
Extraction Adapter — the boundary where untrusted model output enters the system.
The `EntityExtractionAdapter` protocol keeps its shape, taking chunk text and
returning an extraction result; the result it returns is conformed.

The extraction node schema gains a `sub_labels` field, which today does not exist
at all: the prompt asks for sub-labels and Pydantic silently drops them, so the
three labels the ontology defines by their sub-label — `LegislativeEvent`,
`Campaign`, `Organization` — arrive as bare base labels. Sub-label values are
validated against the News Ontology whitelist. A sub-label is **required** for
`LegislativeEvent` and `Campaign`: an article describing an event nearly always
says whether it was a vote, hearing or amendment, and a campaign is for a
candidate or a measure with no third option, so a model that cannot choose has
misread. It is **optional** for `Organization`, whose eleven structural types are
frequently never stated — requiring one would silently delete real organizations
for failing a question the article never answered.

Conformance **drops and logs; it never raises**. Raising would send a whole
Article Chunk to the dead letter queue over one mislabeled entity, which is
unaffordable against a nine-article corpus and would leave the parent ticket's
question about prompt/ontology disagreement unanswerable. Dropped: unknown
labels, unknown or missing-where-required sub-labels, unknown relationship types,
relationships whose endpoint labels violate the News Ontology relationship table,
relationships left dangling by a dropped node, and unknown property names.

The adapter accumulates an **adherence report** across a run — counts keyed by
rejected label, relationship type and property name, each with one example chunk
identifier — and the batch ingestion service writes it as JSON to `.scratch/` at
the end of a run. It is per-run and regenerated every run; a cumulative record
buys nothing at this corpus size.

Whether the agent extracts what we *want* is the evaluation suite's question, not
this ticket's; that suite has no extraction coverage and building it belongs to
the [Model Evaluation map](../../../initiatives/model-evaluation/MAP.md).

## Acceptance criteria

- [x] The extraction node schema carries `sub_labels`, and values survive to the
      adapter's returned result.
- [x] Off-ontology labels, relationship types, endpoint pairings and property
      names are dropped, and conforming entities in the same model response
      survive.
- [x] A relationship is dropped when either endpoint label violates the News
      Ontology relationship table, or when a dropped node leaves it dangling.
- [x] A missing sub-label drops a `LegislativeEvent` or `Campaign` node; an absent
      `Organization` sub-label does not.
- [x] Nothing in the conformance pass raises; every drop is logged.
- [x] The adherence report accumulates the expected counts with one example chunk
      per entry, and the batch ingestion service writes it to `.scratch/` as JSON
      at the end of a run.
- [x] Covered at the adapter seam with a scripted model, with no live model call.

## Blocked by

- [02 — Ontology package, News Ontology, and the conformance check](02-ontology-package-and-conformance-check.md)
