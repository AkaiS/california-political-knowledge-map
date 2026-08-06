Labels: ready-for-agent

## Parent

[News Ontology and Graph Population](../PRD.md)

## What to build

The Extraction Prompt's ontology section stops being hand-maintained prose and is
generated from the News Ontology at load time, so that editing the ontology
cannot leave the prompt stale.

The prompt file stays a file and keeps its hand-tuned prose — the role framing,
the output contract, and rules such as not inferring endorsement from quotation
and resolving pronouns only when the antecedent is unambiguous. These have no
machine source and want to be edited as text without a code change. The file
carries a placeholder into which the generated section is injected: the label
set, the sub-label rules, **per-label** property names, the relationship list with
its endpoint types, and the Policy Area vocabulary. Nothing about the ontology is
stated twice.

Per-label property names matter on their own: today the model is shown one flat
list spanning every entity type, so it is never told which properties belong to
which label.

Removed from the prompt entirely: `NewsArticle`, `Chunk`, `HAS_CHUNK` and the
entity-to-chunk edge, all of which become write-path-owned; the excluded tenure,
district and redistricting labels and relationships; `party_affiliation` and the
instruction distinguishing it from `current_party`; and the two instructions
telling the model to use names "defined by `ontology.md`" — a file it is never
shown, which makes both instructions inert.

## Acceptance criteria

- [ ] The loaded prompt contains the label set, sub-label rules, per-label
      property names, relationship list with endpoint types, and Policy Area
      vocabulary, all derived from the News Ontology.
- [ ] No ontology fact appears in the prompt file's own prose.
- [ ] The hand-tuned prose survives and is still editable as text.
- [ ] `NewsArticle`, `Chunk`, `HAS_CHUNK`, the entity-to-chunk edge, the excluded
      tenure/district/redistricting vocabulary, `party_affiliation`, and both
      `ontology.md` references are gone from the prompt.
- [ ] Verified at the Entity Extraction Adapter seam with a scripted model — the
      prompt the agent receives carries the injected label set and Policy Area
      vocabulary — rather than by asserting on an intermediate prompt string.

## Blocked by

- [02 — Ontology package, News Ontology, and the conformance check](02-ontology-package-and-conformance-check.md)
