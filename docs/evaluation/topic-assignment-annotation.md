# Topic Assignment annotation guideline

The standard the Topic Assignment Silver Set is annotated against. Every case in
`evals/gold/topic_assignment.yaml` names this file in its `annotation_guideline`
metadata, because a judgment call made one way in one article and the other way
in the next produces a Silver Set that no score can be read against.

You are producing a **gold-quality** annotation of the measure-to-area pairs one
Source Article supports, given the areas and the measures the stage is given.

## What a case is

One Source Article as its **coreference-resolved** text, together with the two
things the stage receives beside it:

- **the Policy Areas** `evals/gold/policy_area_classification.yaml` holds for the
  same article, which is the classified set the stage is handed; and
- **the measures** the article's extractions produced: every Bill and Prop, named
  by the surface string extraction reports.

All three are input, not context. Assignment is the only stage that sees every
measure in an article and every area in an article at once, and the judgement is
what that view is for.

The expectation is the set of **pairs**: one entry per measure-and-area the
article connects. The measure is named by its surface string and its label, the
area by its canonical name.

## The measures a case is given

The list is what extraction would hand the stage, so it is annotated by
extraction's rules, from `docs/evaluation/extraction-annotation.md`:

- The name is the **surface string the article used**, verbatim except for a
  leading article: `Assembly Bill 1883`, `SB 9`, `federal housing bill`. Never
  expand, normalize or decompose it. The same measure appears as `SB 9` in one
  article and `Senate Bill 1123` in the next because that is how each article
  wrote it, and the write path keys on what was written.
- A measure the article refers to only indefinitely — "another bill", "a San
  Francisco ballot measure" — is not a measure. A specific measure handled by a
  definite description is; take the fullest handle the article gives.
- The label is `Bill` or `Prop`, the two an `ABOUT_TOPIC` edge may start from.
- Every measure the extraction Silver Set produced for the article is in the
  list, under the surface string it produced. The list may hold more: the
  extraction set annotates sampled chunks, and the stage is given every chunk's
  measures.
- One entry per measure, not per mention.

An article that names no measure is given none, and supports no pairs. That is
a real case: the pipeline does not run the stage at all there, and a model that
returns nothing is right.

## The standard: the article connects them

Assign an area to a measure when the **article** says the measure concerns that
subject. Not the chunk — the article, all of it, which is the whole reason this
stage exists.

- **Subject, not consequence.** An insurance bill for ride-hailing is
  `Insurance` and `Transportation`. It is not `Judiciary` because a lawyer is
  quoted about it, and not `Labor & Employment` because it passed alongside a
  bill about drivers unionising. Ask what the measure is about, not what the
  article is about.
- **Co-occurrence is not connection.** An area the article discusses and a
  measure the article names are not a pair merely because both are in the
  article. Most of the mistakes this guideline exists to prevent are this one.
- **A measure can take several areas**, and often should: a bill regulating
  workplace brain-data collection is `Labor & Employment` and
  `Privacy & Consumer Protection`, because the article says it is about both.
- **A measure can take none.** A bill whose subject is an area outside the
  article's classified set gets no pair, and so does one the article names
  without ever saying what it concerns.
- **Passage, veto and failure change nothing.** A vetoed bill, a dead bill and a
  measure pulled from the ballot are about what they are about.
- **Federal and local measures** are annotated on the same standard as state
  ones.

## Only from the sets the stage was given

Two rules follow from the drops `knowledge_map.core.topic_assignment` enforces
before persistence, and the loading test holds the file to both:

- A pair may only name a measure **in the case's own measure list**.
- A pair may only name an area **in the case's own classified set**.

An area the article genuinely connects to a measure but classification did not
find is not an answer here. It is a classification miss, it is scored as one in
that Gold Set, and asking for it here would score the same mistake twice and
ask a model for an edge the pipeline would drop.

## Observed pairs per article

Measured from the twenty cases of `evals/gold/topic_assignment.yaml`.

| Pairs in one article | Articles |
| --- | --- |
| 0 | 7 |
| 1 | 2 |
| 2 | 4 |
| 3 | 3 |
| 4 | 4 |

Thirty-five pairs across twenty articles, over the twenty-five measures those
articles name: a mean of 1.75 pairs per article and a maximum of four. Seven
articles support no pair at all — five name no measure, and two name a measure
whose subject is outside the article's classified set. The twenty-three measures
that take any area take 1.52 areas each.

A test asserts this table against the file, so an added or re-annotated case
fails here rather than leaving the recorded distribution stale.

## Known open calls

Flagged during the twenty-article annotation pass and not yet settled. Listed so
a future pass makes the same choice rather than rediscovering the question.

- **A measure's subject versus its arena.** `Proposition 38` funds immunology
  research at a UC-affiliated institute, so it takes `Health` and
  `Higher Education`. It does not take `Government Operations`, though the
  article discusses the ballot process at length. The rule taken was that
  `Government Operations` describes the article's discussion of the mechanism,
  not the measure's subject; a future pass could reasonably read the measure's
  own spending machinery the other way.
- **Consumer effect as subject.** `SB 493` widens a price-gouging law covering
  gasoline, and takes both `Energy & Utilities` and
  `Privacy & Consumer Protection`. `Senate Bill 371` lowers a rideshare
  insurance floor with plainly consumer-facing effects, and takes neither
  consumer protection nor `Judiciary`. The line drawn is that the first measure
  regulates prices charged to consumers and the second regulates an insurer's
  liability; it is the thinnest line in the set.
- **Descriptive handles.** `federal housing bill`,
  `Common Sense Media bill banning AI chatbots for minors`,
  `Donald Trump's budget bill` and `Gavin Newsom's 2023 oil profits bill` are
  measures under long definite descriptions, as the extraction guideline already
  allows. No rule says how long a handle may get before it stops being one
  measure.
- **An enacted act as a `Bill`.** `National Alzheimer's Project Act` is a law
  from 2011 cited in an appeal, not pending legislation. It is annotated as a
  `Bill` because the label covers legislation whatever its stage, but the set
  holds only one of them.
