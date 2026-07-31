# Guard human relevance labels against automated overwrites

Labels: completed

## Parent

[Pipeline Stage Ownership: Validation, Relevance, and Raw HTML Lifecycle](../PRD.md)

## What to build

A human relevance label survives every automated pipeline run. Today it does not:
running `classifier label --review-all` and then `validate-articles` erases every
`HUMAN` label, and `classifier reevaluate` erases them by a second, independent
path that never touches `--review-all` at all.

The relevance writer becomes the single point where this is enforced. It refuses
to change a row whose `relevance_label_source` is `'HUMAN'` unless the incoming
label source is itself `'HUMAN'`, so manual labeling keeps working by
construction and no new flag is introduced. Because the refusal lives in the
`UPDATE` predicate rather than in a prior read, a label applied concurrently with
a running classifier is still protected.

The writer reports back the status and source that are actually persisted, and
every caller acts on that returned value rather than on the value it attempted to
write. A classification that was discarded must not go on to produce a Story or
any other downstream effect. `classifier reevaluate` additionally excludes
human-labeled articles in its own selection, so it does not spend model calls on
rows it cannot write.

This ticket changes no schema and can land ahead of everything else. One cache
row is currently `relevance_status = 'RELEVANT'`, `relevance_label_source =
'HUMAN'`, and `validation = 'PENDING'`; the next validation run destroys it under
present behavior, and it is one of only three surviving human labels.

## Acceptance criteria

- [x] An automated relevance write against a `HUMAN`-labeled article leaves both `relevance_status` and `relevance_label_source` unchanged.
- [x] A manual relevance write against a `HUMAN`-labeled article succeeds, so re-answering a review question still works.
- [x] The relevance writer returns the effective persisted status and source, and a rejected write is distinguishable from an applied one by its return value alone.
- [x] The reported regression no longer reproduces end to end: seed a validated article, apply a `HUMAN` label, run validation, and both the label and its source are unchanged.
- [x] A caller whose relevance write was rejected creates no Story from the discarded classification and takes no other action derived from it.
- [x] `classifier reevaluate` run with model weights that would reclassify a `HUMAN`-labeled article leaves that article untouched.
- [x] `classifier reevaluate` does not select human-labeled articles for classification.
- [x] A `HUMAN` label applied between the validator reading an article and writing its classification survives, proven at the relevance writer seam.
- [x] The full deterministic test suite passes.

## Blocked by

None - can start immediately.
