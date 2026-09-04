# Attempt: two prompt contradictions in Entity Extraction

Not tied to a numbered issue. Written from three runs of `evals/gold/extraction.yaml`
against local `gemma4:26b`, committed alongside this note: one before the change
(`25e803d`) and two after it (`bbaa22b`, prompt digest `sha256:b8238763274e`). Every
figure below is read off those report files. Where a claim is a hypothesis rather than
a count, it says so.

Recorded because half of it failed, and the failed half is the part worth knowing
about: the obvious fix is the one that does not work.

## What was wrong

The extraction prompt told the model two contradictory things, twice.

**Properties the write path owns.** `src/knowledge_map/resources/extraction_prompt.txt`
says "Do not repeat it inside `properties`, and never emit an `id`: both are written
for you." The generated ontology block two paragraphs below listed `id` as an allowed
property for all seven extracted labels, `name` for three of them, and `first_name` /
`last_name` for `Politician`. Nothing had declared those as gaps, so
`news.PROPERTIES` still carried them, so the renderer still advertised them and
conformance still accepted them.

**The stance direction.** The prompt's rules say "Support or opposition stated in prose
is `DECLARED_STANCE` with an `alignment`." The generated relationship-properties block
below said "Attach any property the text supports. None are required."

In both cases the model followed the generated block over the prose.

## What was tried

Four `Divergence` entries in `news.py` for `id`, `name`, `first_name` and `last_name`.
This is the mechanism the ontology already had for exactly this: `PROPERTIES` subtracts
every declared divergence, so one declaration stops the prompt advertising the property,
starts conformance dropping it, and writes the reason into `news-ontology.md`.

A new `PropertySpec.entailed` flag, set on `alignment` alone, rendering as "Always write
this one: a passage that states the claim has already stated this value." The blanket
"None are required." line was narrowed rather than removed, because the reason behind it
is sound for every other property: an article can state a `FUNDED` claim without naming
an amount, and demanding one would be asking the model to invent it. `alignment` is the
case that reasoning does not reach — a stance whose direction the passage withheld is
not a stance — and `NEUTRAL` covers the hedged case, so the vocabulary is total.

## What happened

The divergences worked.

| | before | after (2 runs) |
| --- | --- | --- |
| node properties emitted | 29 | 9, 11 |
| of those, ontology fields | 6 | 9, 11 |
| `Politician.first_name` / `last_name` | 17 | 0, 0 |
| `id` and `name` | 6 | 0, 0 |
| spurious nodes | 7 | 0, 4 |
| `node_property_accuracy` | 0.333 | 0.667, 1.000 |

The `alignment` change did nothing. `claim_property_accuracy` is 0.000 in all three
runs, on the same five stance edges — the model identifies the edge correctly and emits
`properties: {}`.

## Why the wording fix failed

Counting every relationship across both after-runs: **20 emitted, 0 carrying a property
of any kind.** Not `alignment`, not `amount`, nothing — while node properties are
emitted freely in the same responses.

So the model is not judging that the direction is unsupported. It is not populating a
relationship `properties` dict at all, under any circumstances, and no amount of
instruction text next to the property list changed that.

The hypothesis, untested: the cause is the single worked relationship example in
`extraction_prompt.txt`, which is the only place the model sees the shape and which ends

    "properties": {}

The node example ends the same way, but node properties are emitted anyway — which
weakens the hypothesis rather than confirming it, and is the reason this is recorded as
untested. The next attempt should populate the relationship example with a real
`DECLARED_STANCE` carrying `{"alignment": "NEGATIVE"}` and re-run before touching any
wording again.

## An open number

The two after-runs agree with each other to within 0.001 on `node_f1` (0.445, 0.446) and
sit about 0.05 under the single before-run (0.498). Whether that is a real cost of the
change or a favourable draw in the before-run is not settled: it needs a second run of
the pre-change tree, which was not taken because another session held the shared
worktree at the time. There is no mechanism by which removing property names from the
prompt would change which entities get named, so the gap is more likely the draw — but
that is reasoning, not evidence.

## Unrelated, and the larger number

Both before and after, roughly 30 of 50 cases return zero nodes where only 5 should.
The misses are overwhelmingly free-standing `Organization` nodes — CalMatters, UC
Berkeley, Congress, Teamsters, UPS — in chunks whose expected relationship count is 0.
Nothing above addresses this, and it is the single largest term in `node_recall`.

The graph handles such nodes fine: `ingest_chunk_extraction` merges nodes in their own
loop and attaches each to its chunk with `MENTIONED_IN` before any relationship is
written. The gap is that the prompt never tells the model an entity is worth naming when
no claim is made about it, while `docs/evaluation/extraction-annotation.md` tells the
annotator exactly that.
