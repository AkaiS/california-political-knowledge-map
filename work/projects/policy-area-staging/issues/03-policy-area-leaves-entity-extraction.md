# 03 — Policy Area leaves Entity Extraction

Labels: ready-for-agent

## Parent

[Policy Area Staging](../PRD.md)

## What to build

The chunk extractor stops being asked for the one label a chunk usually cannot
support. `PolicyArea` leaves the labels Entity Extraction is responsible for, and
the topic relationship from a measure to an area leaves its relationship list.
`PolicyArea` stays in the News Ontology's labels — the graph still holds the
node, it is simply written by a different stage, which as of 02 it is.

The removals are enforced by conformance, not only by the prompt. A `PolicyArea`
node or a topic relationship arriving from the chunk extractor is dropped and
recorded in the Adherence Report, so a model that keeps producing them is
measurable rather than silently obeyed, and the entities beside it survive.

The chunk prompt loses the twenty-seven-line vocabulary with them. A chunk
supporting one entity is no longer preceded by twenty-seven lines it cannot use.

The Article Chunk topic edge is retired. With Policy Area gone from the chunk
stage there is nothing to derive it from, and deriving one for every chunk of the
article would assert that every chunk is equally about the topic — the
imprecision this project exists to remove. Retrieval still reaches Article Chunks
from a Policy Area: the subgraph runs through the Source Article and its chunk
edges, and Grounding Evidence is defined as the chunks a subgraph reaches rather
than the chunks an edge names directly.

The extraction Silver Set is re-annotated under the narrowed contract in this
same ticket, not a later one: its conformance assertion over every silver label
fails the moment the label leaves the extraction ontology. Its `PolicyArea` nodes
and topic edges are removed; its case counts stay as they are. The guideline's
`PolicyArea` section and its "Bare `PolicyArea`" open call are retired with them
— the guideline stops recording a question that is answered elsewhere.

## Acceptance criteria

- [ ] `PolicyArea` is no longer a label Entity Extraction is responsible for, and
      is still a label the News Ontology declares.
- [ ] The topic relationship from a measure to an area, and the chunk half of the
      article-or-chunk topic relationship, are no longer offered to the chunk
      extractor.
- [ ] The rendered extraction prompt contains no Policy Area vocabulary section.
- [ ] Conformance drops a `PolicyArea` node arriving from the chunk extractor,
      records it in the Adherence Report, and keeps the other nodes in the same
      result.
- [ ] Conformance drops a topic relationship arriving from the chunk extractor
      and records it in the Adherence Report.
- [ ] The Neo4j chunk extraction write no longer writes a chunk-level topic edge.
- [ ] The extraction Silver Set holds no `PolicyArea` node and no topic edge; its
      case count assertions are unchanged and its conformance assertion over
      every silver label passes.
- [ ] The extraction annotation guideline no longer has a `PolicyArea` section or
      a bare-`PolicyArea` open call, and points at the stage that now owns the
      question.

## Blocked by

- [02 — Policy Area Classification, once per Source Article](02-policy-area-classification-stage.md)
