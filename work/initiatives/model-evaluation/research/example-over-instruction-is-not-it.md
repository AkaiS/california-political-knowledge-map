# Attempt: a worked example that shows a populated `properties`

Not tied to a numbered issue. Written from four runs of `evals/silver/extraction.yaml`
against local `gemma4:26b`, all committed: two of the baseline tree (`0997321`, `e11a8b8`,
prompt digest `sha256:c6bf81fc0f65`) and two of the changed tree (`b69ea54`, `2edd47d`,
digest `sha256:6bf840761f51`). Every figure is read off those reports.

This is the fourth recorded attempt on one behaviour, and the last one a prompt can make.
It closes the prompt as a lever.

## What was wrong

Unchanged from the three attempts before it: the model emits relationships and gives them
no properties. 9 relationships, 0 carrying any property, in every run of every tree
measured so far. `claim_property_accuracy` `0.000` throughout.

## The hypothesis

Imitation over instruction. `src/knowledge_map/resources/extraction_prompt.txt` carried a
worked relationship example whose last line was literally `"properties": {}`, and a
demonstration of the output shape may simply beat a sentence describing it. This was the
only account left standing after
[alignment-is-not-a-wording-problem.md](alignment-is-not-a-wording-problem.md) established
that three separate wordings are inert.

The complication, named before the run: the node example immediately above shows
`"properties": {}` too, and nodes are the case where the model *does* emit properties. The
proposed resolution was positional — the node example's `{}` is not terminal, because
prose and a whole `### Properties by label` inventory follow it and override it, whereas
the relationship example had no such downstream recovery. That asymmetry predicted the
change would work.

## What was tried

In `b69ea54`, one file, paired examples:

- the existing `ENDORSED` example kept, now captioned as empty *because* `ENDORSED`
  declares no properties;
- a new terminal `DECLARED_STANCE` example carrying `{"alignment": "POSITIVE"}`, followed
  by "Write the alignment the passage states — `POSITIVE`, `NEGATIVE`, or `NEUTRAL`. The
  value above is this example's, not a default."

The node example was deliberately left alone as the control.

`POSITIVE` was chosen over `NEGATIVE` on purpose: three of the five checked silver stance
edges are `NEGATIVE`, so a literally-copied `NEGATIVE` would have scored 3/5 and looked
like partial success.

## What happened

Nothing, on the thing being measured.

| metric | baseline `0997321` | `b69ea54` | `2edd47d` |
| --- | --- | --- | --- |
| `claim_property_accuracy` | 0.0000 (n=5) | 0.0000 (n=5) | 0.0000 (n=5) |
| relationships emitted | 9 | 9 | 9 |
| carrying any property | 0 | 0 | 0 |
| `node_f1` | 0.4975 | 0.4441 | 0.4441 |
| `node_precision` | 0.5333 | 0.4643 | 0.4643 |
| `node_recall` | 0.4803 | 0.4360 | 0.4360 |
| `sub_label_accuracy` | 0.9621 (n=22) | 0.9583 (n=20) | 0.9583 (n=20) |
| `node_property_accuracy` | 0.6667 (n=3) | 0.3333 (n=3) | 0.3333 (n=3) |
| `extraction_validation_failure` | 0 | 0 | 0 |

`dirty` is false on all four reports. `expected_output` is byte-identical to the baseline
case for case, so no Data Set edit is in these numbers. The two runs of the changed tree
are byte-identical to each other, so they are one sample of the tree rather than two.

Not one relationship carries a key of any kind — not `alignment`, not `amount`, not an
invented one — while node properties are still emitted in the same responses
(`current_party`, `description`).

The feared failure mode did not occur. Per-edge, against the five known silver stance
edges:

| edge | expected | endpoints matched | emitted properties |
| --- | --- | --- | --- |
| Isaac Bryan → AB 1883 | `POSITIVE` | yes | `{}` |
| Newsom → SB 7 | `NEGATIVE` | yes | `{}` |
| Consumer Federation → SB 371 | `NEGATIVE` | yes | `{}` |
| Josh Hoover → AB 2211 | `POSITIVE` | yes | `{}` |
| State Building Trades → AB 1751 | `NEGATIVE` | yes | `{}` |

Nothing was copied because nothing was emitted. The scorer compares dicts for exact
equality, so an all-`POSITIVE` run would have scored `0.400`, not `0.000`. This is "did
not engage", not "engaged badly" — the same shape of non-response as the three attempts
before it.

The positional resolution of the node/relationship asymmetry is falsified too. Placement
was the difference the hypothesis rested on, and making the populated example terminal
changed nothing.

## The node cost, which is real

`node_f1` fell 0.053, and both trees are now two-sample points: the baseline reproduces
byte for byte at `e11a8b8`, and the two runs of this change are byte-identical to each
other. So the move is the change, not the draw.

Taking only nodes present in **both** baseline runs and absent from **both** runs of this
change, four silver nodes are lost:

| node | case | group |
| --- | --- | --- |
| `National Institutes of Health` | `health-research#chunk-25` | claimless |
| `UC Davis` | `health-research#chunk-25` | claimless |
| `California Department of Industrial Relations` | `ab-1751-trades-carpenters-fight#chunk-22` | claimless |
| `federal housing bill` | `#chunk-33` | claimless |

Every one sits in a chunk expecting no relationship. The Department of Industrial
Relations is the same node `f4addf2` and `8567ee5` each lost on the same chunk, which
makes this the third independent instance of one pattern: **a prompt narrowed toward
claims costs claimless nodes.** There is still no mechanism, and it stays a hypothesis —
but it now has three experiments behind it and a two-sample baseline underneath it.

The move is not one-directional. Two silver nodes are gained the same way —
`Antonio Villaraigosa` and `OpenAI` — so this is a redistribution with a net loss, not a
collapse.

One regression is a different defect and should not be counted with the four. In
`#chunk-8` the baseline emits `Gavin Newsom` and both runs of this change emit `Newsom`.
That is the same entity under a worse name, not a lost one, and it violates a rule the
prompt already carries: a bare surname is never enough to name a person. The subgraph
experiment produced bare `Steyer` and the claimless-entity change produced bare `Newsom`
twice. Three experiments, three surname regressions — the rule is not holding under any
prompt edit, which is its own finding and wants its own run.

`node_property_accuracy` 0.667 → 0.333 is one case on n=3 and is noise.

## What this closes

Four interventions now span both categories a prompt has to offer:

1. prose (first note);
2. the `entailed` sentence in the rendered block;
3. an explicit refusal of the empty object;
4. a populated worked example, terminal, with the copy risk called out in prose.

Every one produced zero relationship properties on every relationship in every run.
**Local `gemma4:26b` cannot be prompted into relationship properties on this task.** No
further prompt experiment on this lever is worth a run, and a fifth wording should be
turned down by reference to this note.

## What the next attempt should be, in order

1. **Model-level, and first.** One OpenRouter run of the *existing* prompt. Every
   extraction report in this repo is a single local model, so "the model cannot" is
   currently indistinguishable from "this model cannot". This is the cheapest run
   available and it decides whether the schema work below fixes a defect or designs around
   one. Until it is taken, the conclusion above is scoped to `gemma4:26b` and must be
   written that way.
2. **Schema-level.** Make `alignment` a field the parser rejects a `DECLARED_STANCE`
   without, so a silent `{}` becomes a validation retry with the error in front of the
   model. Watch for the trade this invites: an edge dropped entirely rather than a
   property supplied. `relationship_f1` would catch that where it cannot catch the current
   defect.

## What was kept

Nothing from `b69ea54`. The reports are committed at `d2c59fc` and `d903d2f`; the branch
holds the change.
