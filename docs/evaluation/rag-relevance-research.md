# RAG relevance judgments and retrieval precision

Researched October 2, 2026. Scope: the `evaluate-rag` skill, primary guidance
from Hamel Husain and Shreya Shankar, and the implication for our selected
evidence reviewer. This note records findings and a proposed review design.
It does not change the annotation schema.

## What the skill says

The local [evaluate-rag skill](/Users/akaisenghor/.agents/skills/evaluate-rag/SKILL.md)
requires queries paired with relevant chunks. It prioritizes Recall@k for
first-pass retrieval and Precision@k, MRR or NDCG@k for ranking quality.
Generation has separate faithfulness and answer relevance judgments.
Its context-relevance diagnosis table uses High/Low, but it does not specify
whether humans must label each chunk or the entire context package.

The skill lists omissions under faithfulness. Our review contract deliberately
keeps reference evidence coverage in recall and complete-evidence metrics.
Faithfulness checks unsupported or misrepresented claims; answer relevance
checks the requested focus. That distinction should stay explicit.

## Primary-source findings

Husain and Shankar treat retrieval as a search problem with query-document
references and IR metrics. They separate generation evaluation into whether
context answers the information need, whether the answer is grounded in that
context, and whether the answer addresses the question. They recommend error
analysis, human labels and validated judges rather than adopting generic
judge prompts without checking their fit. Their joint RAG FAQ does not prescribe
per-chunk annotation or a package-wide label.
[Source: joint RAG FAQ](https://hamel.dev/blog/posts/evals-faq/how-should-i-approach-evaluating-my-rag-system.html).

Their binary-evaluation guidance favors clear pass/fail criteria over rating
scales. It explicitly recommends separate binary checks on subcomponents to
measure gradual improvements. High/Low can implement this if the criterion
explains exactly what High means. This supports a chunk-level design, but
that application is our inference, not a RAG-specific instruction from them.
[Source: joint binary-label FAQ](https://hamel.dev/blog/posts/evals-faq/why-do-you-recommend-binary-passfail-evaluations-instead-of-1-5-ratings-likert-scales.html).

They recommend giving an LLM judge only the parts of a trace needed for its
failure mode. They advise testing context choices against human labels and
removing unnecessary information through ablations. This supports bounded
review inputs and argues against attaching every branch candidate to every
judgment. It does not establish our particular 50-chunk budget.
[Source: joint judge-context FAQ](https://hamel.dev/blog/posts/evals-faq/how-much-of-a-trace-should-i-give-an-llm-judge.html).

Their calibration advice separates training, development and untouched test
examples. Evaluate judges with both the fraction of true failures caught and
the fraction of good outputs passed, TPR and TNR. Repeated prompt tuning on
development labels can overfit. This applies if we later automate subjective
chunk or answer labels. Deterministic reference-set calculations need correctness
checks, not an LLM judge.
[Source: joint evaluator-validation FAQ](https://hamel.dev/blog/posts/evals-faq/how-do-i-know-if-i-can-trust-my-automated-eval.html).

Shankar and coauthors' EvalGen paper shows why evaluator alignment requires
human feedback. Reviewers refine criteria while inspecting examples, a process
they call criteria drift. The paper studies evaluator design and human alignment;
it does not establish a RAG chunk-relevance metric or require each retrieved
chunk to receive a label. Its finding supports recording reasons, revising
unclear criteria and reviewing affected labels when definitions change.
[Source: Shankar et al., Who Validates the Validators?](https://arxiv.org/html/2404.12272v1).

Their sample-size guidance recommends LLM judges for failures that require
subjective or domain judgment. They propose 100 to 200 expert-labeled examples
per failure mode, with sufficient passing and failing examples to evaluate
both classes. Those are practical targets rather than a guarantee of accuracy.
Twenty-five questions can support a pilot, but they are not a substantial
held-out generation-judge calibration set.
[Source: joint sample-size FAQ](https://hamel.dev/blog/posts/evals-faq/how-many-examples-do-i-need-for-an-eval.html).

## Implication for this pipeline

The following is our proposed application of those findings. Per-selected-chunk
context relevance gives more actionable information than a single package
label. A package with one useful passage and nine distractions otherwise
requires an arbitrary threshold for High. Individual labels identify which
selected passages add useful evidence.

Judge each exact passage supplied to the Chat Agent against the approved
question and scope. High means it provides evidence useful to answering the
question or one required hop. A passage need not answer the entire question
alone. Low means it contributes no useful answer evidence, including material
that is only topically similar. Include a short description field per chunk.
Check named subjects, legislative session, relationship direction and temporal
status when they matter. Leave unreviewed passages unlabeled.

Keep answer relevance and faithfulness as independent answer-level judgments.
Faithfulness needs the entire supplied evidence package because a claim may
combine several passages. Low relevance in one passage does not itself make
the generated answer unfaithful. Redundant but useful passages can be relevant;
relevance labels alone do not measure redundancy or collective sufficiency.

Only the selected passages need text and human review. Preserve existing compact
branch ranks for ranking metrics. Expanding the annotation unit does not require
restoring thousands of discarded candidates to the report.

## Keep two measurements distinct

| Measurement | Inputs | Meaning and limit |
| --- | --- | --- |
| Reference-based Precision@k | Ranked IDs and the versioned silver reference IDs | Fraction of the top k that match known positive references. Unlisted useful passages lower this score. It measures reference agreement. |
| Human selected-context relevance rate | Binary labels on passages supplied to the Chat Agent | Fraction of judged passages rated High. Show annotation coverage. Only a fully labeled package gives the relevance fraction for the complete selected package. |
| Reference Recall@k and complete evidence | Ranked IDs and reference witness groups | Known evidence coverage. Labeling selected passages cannot reveal evidence never retrieved. |

For the 25-case dataset, 22 cases use Article Chunk IDs and three E3 cases use
Source Article IDs. A chunk from a reference Source Article can be irrelevant
as a passage; article membership alone cannot supply its human chunk label.
The dashboard should state the grain and chunk budget, especially when combining
cases. Reference precision must retain the same provisional silver-label caveat
as reference recall.

Do not silently replace reference labels with run-specific human judgments.
Human-reviewed additional useful chunks can become proposals for a new dataset
version. Annotation scope, evidence text and reference version then remain clear
when comparing runs. Labeling only selected evidence measures selection quality;
it does not produce human Precision@50 for unreviewed branch candidates.

The next interface change should therefore put an independent High/Low control
and description beside each selected passage, retain the answer-level controls,
and show reviewed/total passage counts. Any migration must preserve historical
package labels as historical judgments rather than copy them onto every chunk.

## A practical judge pilot

Yes, their guidance recommends using LLM judges for subjective RAG relationships,
including context relevance, with human labels and validation. It recommends
those steps together. It does not require an uncalibrated model judgment to
become the quality score as soon as the judge runs.
[Source: joint RAG FAQ](https://hamel.dev/blog/posts/evals-faq/how-should-i-approach-evaluating-my-rag-system.html).

Our proposed pilot would use these separate inputs and outputs:

| Judge | Inputs | Output |
| --- | --- | --- |
| Selected-chunk relevance | Approved question, scope, one exact supplied passage and its citation metadata | High/Low and a description citing the passage's useful evidence or why it does not help |
| Answer faithfulness | Final answer, all supplied passages and citation mapping | High/Low and the specific unsupported or misrepresented claims |
| Answer relevance | Approved question, scope and final answer | High/Low and whether the requested focus is addressed |

The rubric needs examples for political relationships, legislative sessions,
support versus enactment, and useful partial evidence for multi-hop questions.
These criteria and the choice of one passage per relevance call are our design
recommendations. They are not a quoted recipe from Husain or Shankar.

Start by labeling a diverse selection of the existing passages manually. Draft
judges from these examples and compare their independent predictions with the
human labels. Keep machine proposals separate from human decisions, inspect
disagreements and preserve explanations. Human approval should not silently
inherit model predictions as calibration labels.

The 25 questions can yield more than 25 chunk judgments, but repeated passages
and related queries are correlated. Our proposed validation split groups
related queries and repeated evidence together to reduce leakage. It also adds
new real-user questions for an untouched test set. Do not call a large count
of correlated passage labels a large independent benchmark.

Measure TPR and TNR on each judge and report class counts and uncertainty.
Their RAG FAQ recommends correcting aggregate estimates with measured judge
error rates. Our caution is that correction can be unstable with tiny calibration
sets or changed populations. The cited guidance does not require a particular
prediction-powered inference library for this pilot.

Keep reference Precision@k deterministic. Judges add a separate semantic signal
about selected evidence and generation; they do not replace the versioned silver
reference calculation or turn existing training cases into held-out examples.
