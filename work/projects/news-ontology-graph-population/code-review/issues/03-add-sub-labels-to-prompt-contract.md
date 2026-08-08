Labels: ready-for-agent

## Parent

[Code Review: News Ontology and Graph Population, issues 02–07](../README.md)

## What to build

Legislative Events and Campaigns survive extraction. The generated ontology
section of the Extraction Prompt tells the model a sub-label is required for
both, but the hand-written output contract beside it shows an entity object with
no `sub_labels` field. The model is shown a contract with nowhere to put a value
it is required to supply, so both labels are systematically dropped — which
would make issue 08's label inventory measure a prompt defect rather than the
ontology.

The hand-written output contract gains the `sub_labels` field. Nothing else in
the hand-tuned prose changes; the generated section is already correct.

## Acceptance criteria

- [x] The Extraction Prompt's hand-written output contract shows `sub_labels` on
      the entity object.
- [x] A `LegislativeEvent` emitted with a sub-label survives conformance.
- [x] A `Campaign` emitted with a sub-label survives conformance.
- [x] No other change to the hand-written prose.
- [x] The suite is green.

## Blocked by

- None — can start immediately.
