# Attempt: making `alignment` necessary in the rendered ontology block

Not tied to a numbered issue. Written from three runs of `evals/silver/extraction.yaml`
against local `gemma4:26b`, all committed: the baseline (`0997321`) and two runs of the
same changed tree (`f4addf2`, `61b4365`, prompt digest `sha256:374106d6f86c`). Every
figure below is read off those report files. Where a claim is a hypothesis rather than a
count, it says so.

Recorded because it failed, and because it retires a premise that a handoff note and this
attempt both worked from. This is the third recorded failure on the same lever, and the
three together say something the individual failures do not.

## What was wrong

`claim_property_accuracy` is `0.000` in every committed extraction run. The model emits
relationships and gives them no properties at all — 9 relationships and 0 carrying any
property in the baseline — while emitting node properties freely in the same responses.

Five silver `DECLARED_STANCE` edges match on endpoints with the alignment value expected
and none supplied: Isaac Bryan→AB 1883 `POSITIVE`, Newsom→SB 7 `NEGATIVE`, Consumer
Federation→SB 371 `NEGATIVE`, Josh Hoover→AB 2211 `POSITIVE`, State Building
Trades→AB 1751 `NEGATIVE`.

`relationship_f1` reads `0.9533` over the top of this because `relationship_identity` in
`src/knowledge_map/evaluation/tasks/extraction.py` keys on endpoints and type alone. The
headline metric cannot see the defect, which is why it survived this long.

## The premise this attempt retires

The lever this attempt set out to pull was the one named in the handoff: the Claim Key
column in the rendered ontology never states `alignment`'s allowed values, and the prose
above it tells the model that a Claim Key property "is not required of the extractor".

**The extractor never sees that text.** There are two renderers.
`render_extraction_ontology()` fills the `{{NEWS_ONTOLOGY}}` placeholder
(`src/knowledge_map/adapters/extraction.py:51`); `render_news_ontology()` writes
`news-ontology.md`, whose only consumer in the repo is `tests/test_ontology.py`. The
"not required" sentence lives in the second and reaches no model.

The block the extractor does see already read, at `e11a8b8`:
`alignment: exactly one of POSITIVE, NEGATIVE, NEUTRAL … Always write this one`. Both
halves of the proposed fix were already in place and had already failed — that sentence
is the `entailed` flag from
[extraction-prompt-contradiction-attempt.md](extraction-prompt-contradiction-attempt.md),
measured inert there.

## What was tried

Two edits, in `f4addf2`:

- In `render_extraction_ontology()`, the permissive opener ("Attach any property the text
  supports") was dropped, and the entailed property was made to refuse the empty object:
  a `DECLARED_STANCE` whose `properties` is `{}` is incomplete — write `alignment` or do
  not emit the relationship at all.
- In `render_news_ontology()`, the write-path sentence was reworded so the `needs_review`
  fact stays true without addressing the extractor, and `news-ontology.md` regenerated.

## What happened

Nothing, on the thing being measured.

| metric | baseline `0997321` | `f4addf2` | `61b4365` |
| --- | --- | --- | --- |
| `claim_property_accuracy` | 0.000 (n=5) | 0.000 (n=5) | 0.000 (n=5) |
| relationships emitted | 9 | 9 | 9 |
| carrying any property | 0 | 0 | 0 |
| `relationship_f1` | 0.9533 | 0.9533 | 0.9533 |
| `node_f1` | 0.4975 | 0.4575 | 0.4575 |
| `node_precision` | 0.5333 | 0.4933 | 0.4933 |
| `node_recall` | 0.4803 | 0.4403 | 0.4403 |
| `sub_label_accuracy` | 0.9621 (n=22) | 0.9583 (n=20) | 0.9583 (n=20) |
| `extraction_validation_failure` | 0 | 0 | 0 |

The emitted relationship set is identical to the baseline's edge for edge, all still
`properties={}`. The same five stance edges are still bare. Both runs are byte-identical
to each other across all 50 cases, and `dirty` is false on all three reports.
`expected_output` is byte-identical to the baseline case for case, so no Data Set edit is
in these numbers.

The feared failure mode did not occur either: no invented properties and no new spurious
relationships. The model did not try to satisfy the requirement badly. It did not engage
with it.

`node_f1` fell 0.040 on exactly two cases, each losing one claimless `GovernmentAgency` —
`community-college-prisons#chunk-11` (Department of Corrections and Rehabilitation) and
`ab-1751-trades-carpenters-fight#chunk-22` (Department of Industrial Relations).

**That cost is real, not draw.** `e11a8b8` is a second sample of the baseline's source
tree under the same prompt digest `sha256:c6bf81fc0f65`, and it reproduces `0997321` byte
for byte — every aggregate equal to four decimals, 38 nodes, and zero cases whose output
differs. Both agencies are emitted in both baseline runs and in neither run of this change.

There is still no mechanism. A sentence about relationship properties should not decide
whether a claimless agency is named in a chunk with zero relationships. But the draw
explanation is now closed, and what is left is a hypothesis with support from three
independent runs: narrowing the prompt toward claims costs claimless nodes. The subgraph
experiment (`8567ee5`) lost the same Department of Industrial Relations node on the same
chunk, the fourth attempt on this lever (`b69ea54`) lost it again, and the
claimless-entity change recovers the whole class.

## What this says with the two attempts before it

Three distinct wordings have now been measured against this behaviour:

1. "None are required." narrowed to the `entailed` sentence — inert.
2. The `entailed` sentence alone, present at `e11a8b8` — inert.
3. An explicit refusal of the empty object, above — inert.

All three produce exactly zero relationship properties, on every relationship, in every
run. **Wording is not the variable.** Further rewording of the rendered block is not worth
a run.

A fourth has since been measured and is inert too — a worked example carrying a populated
`properties`, at `b69ea54`. See
[example-over-instruction-is-not-it.md](example-over-instruction-is-not-it.md), which
supersedes the section below.

## What the next attempt should change instead

The hypothesis left standing is imitation over instruction:
`src/knowledge_map/resources/extraction_prompt.txt` carries a worked relationship example
whose last line is literally `"properties": {}`. A demonstration of the output shape may
simply beat a sentence describing it.

The complication that makes this worth measuring rather than assuming: the node example
immediately above shows `"properties": {}` too, and nodes are the case where the model
*does* emit properties. So the imitation account is not clean, and a run is the only way
to separate it from the alternative — that this model cannot be prompted into
relationship properties at all, and the fix is schema-level (a required field the parser
rejects without) or model-level rather than prompt-level.

Label both of those as hypotheses. Nothing here has tested either.

## What was kept

Nothing from `f4addf2`. The `render.py` half is worth landing on its own — it removes a
false statement about the extractor from a file that does not address the extractor, and
is provably model-inert — but it must not be bundled with a prompt edit, because a report
citing a commit that mixes them cannot separate the two.
