# Policy Area Classification annotation guideline

The standard the Policy Area Classification Silver Set is annotated against.
Every case in `evals/gold/policy_area_classification.yaml` names this file in
its `annotation_guideline` metadata, because a judgment call made one way in one
article and the other way in the next produces a Silver Set that no score can be
read against.

You are producing a **gold-quality** Policy Area annotation of one Source
Article against the closed vocabulary the News Ontology declares.

## What a case is

One Source Article, whole, as its **coreference-resolved** text — the same text
the classification stage reads in production, after the accepted silver Mention
Spans of `evals/gold/coreference.yaml` have been substituted and before the
article is cut into chunks.

- The article is the whole world, and all of it. Unlike the extraction Silver
  Set, no chunk boundary limits what you may read: a Policy Area is a property
  of the article's discussion, which is exactly the thing a chunk could not see.
- Read the resolved text as it is. Substitution makes it repetitive, with
  canonical names standing where pronouns were. That changes nothing about what
  the article discusses.
- The headline is part of the article and may be read.
- An article the vocabulary does not cover is annotated as an **empty list**.
  That is a real answer, not a missing one, and it scores as a pass when the
  model also returns nothing.

## The vocabulary

The twenty-seven areas of `knowledge_map.ontology.news.POLICY_AREAS`, written by
their **canonical name**, copied exactly — `Education (K–12)` with its en dash,
`Housing & Community Development`, `Veterans' & Military Affairs`. The name is
what the write path keys the node on; the id is not an answer.

Nothing outside the vocabulary is annotated. An article about a subject the
twenty-seven do not name contributes no area rather than its nearest miss.

## The standard: discussed, not mentioned

Annotate an area when the article **discusses** it — when some passage of the
article is about that subject and a reader would say the article covers it.

Do not annotate an area because a word from its name appears. The test is
sustained attention, not vocabulary overlap:

- One passing clause is not discussion. A profile that notes in one sentence
  that its subject once endorsed home loans as reparations is not an article
  about `Housing & Community Development`.
- A subject the article returns to, devotes a section to, or uses to explain
  what is at stake **is** discussion, even without a bill attached to it.
- A measure whose subject the article states is discussion of that subject. A
  bill regulating rent increases makes the article discuss
  `Housing & Community Development` whether or not the bill passes.
- Quoted advocacy counts as discussion when the article carries it as substance,
  not when it is a single line of colour.

There is **no minimum and no maximum**. An article discusses as many areas as it
discusses; the set records that distribution rather than capping it.

## The areas that need a rule

These are the ones the twenty-article pass had to decide repeatedly.

- **`Government Operations`** is the machinery of governing itself: how an
  agency is run, how a department is reorganized, procurement, records,
  redistricting mechanics, how the Legislature or a ballot process works.
  Politics is not automatically Government Operations. A campaign story, an
  endorsement fight, or a primary result is **not** this area unless the article
  discusses how government is administered.
- **Elections and campaigns** have no area of their own. An article purely about
  who is running, who is ahead, and who endorsed whom classifies to **nothing**
  unless it discusses the policy subjects the candidates are fighting over. This
  is the single largest source of empty and near-empty cases, and it is correct:
  the vocabulary is a policy vocabulary.
- **`Revenue & Taxation`** covers taxes, tax credits, and how revenue is raised.
  The size of a budget deficit, and what a spending cut does to a program, is
  annotated as the **program's** area — and as `Revenue & Taxation` only where
  the article discusses the revenue side.
- **`Labor & Employment`** covers wages, hours, workplace rules, unions and
  hiring. A public employee's pay or pension is `Public Employment & Pensions`
  instead; annotate both only where the article discusses private-sector labour
  as well.
- **`Health`** covers health care, coverage, public health and health services.
  `Human Services` covers welfare, food assistance, child and family services,
  homelessness services and disability services. An article on Medi-Cal
  eligibility is `Health`; one on CalFresh is `Human Services`.
- **`Public Safety`** covers policing, crime, corrections and emergency response
  by law enforcement. `Judiciary` covers courts, judges, lawsuits and legal
  process. A criminal justice article that turns on what a court did takes both.
- **`Privacy & Consumer Protection`** and **`Technology & Communications`** part
  on what the article is arguing about: harms to a person's data or a consumer's
  dealings take the first; the technology, platforms and networks themselves
  take the second. An article on AI chatbots and minors' safety takes both when
  it discusses both the technology and the harm.
- **`Immigration` does not exist** in this vocabulary. Immigration enforcement
  discussed as policing takes `Public Safety`; discussed as court process,
  `Judiciary`; discussed as services, `Human Services`. Where it is none of
  those, it contributes no area.
- **`Environment & Natural Resources`**, **`Energy & Utilities`** and **`Water`**
  are three areas, not one. Emissions rules and land are the first; electricity,
  gas and the utilities that sell them the second; supply, drought and delivery
  the third.

## Federal and out-of-state subjects

Annotate what the article discusses, wherever it happens. An article about a
federal shutdown's effect on Californians discusses the areas the shutdown hits.
An article about a candidate's earlier career abroad is annotated on the same
standard as any other passage: sustained discussion counts, a clause does not.

## Observed areas per article

Measured from the twenty cases of `evals/gold/policy_area_classification.yaml`,
recorded here because the classification schema deliberately sets **no maximum**:
any future cap belongs to a distribution we measured rather than to a guess.

| Areas in one article | Articles |
| --- | --- |
| 0 | 1 |
| 1 | 1 |
| 2 | 4 |
| 3 | 10 |
| 4 | 2 |
| 5 | 2 |

Fifty-seven area labels across twenty articles: a mean of 2.85, a median of 3,
a minimum of 0 and a maximum of 5. Twenty of the twenty-seven areas are used at
least once. `Labor & Employment` is the most frequent at nine articles;
`Aging & Long-Term Care`, `Arts, Entertainment & Tourism`, `Banking & Finance`,
`Education (K–12)`, `Public Employment & Pensions`, `Veterans' & Military
Affairs` and `Water` are unused, which is a fact about these twenty articles and
not a judgment about the vocabulary.

A test asserts this table against the file, so an added or re-annotated case
fails here rather than leaving the recorded distribution stale.

## Known open calls

Flagged during the twenty-article annotation pass and not yet settled. Listed so
a future pass makes the same choice rather than rediscovering the question.

- **Where discussion begins.** The line between a passage and a passing clause
  is a judgment, taken here at roughly a paragraph of sustained attention. Two
  or three cases per pass sit close to it.
- **Profiles of a politician.** A profile is annotated by the policy positions
  it actually walks through, not by the whole platform it alludes to. A profile
  whose subject is the person rather than the positions can legitimately reach
  no areas at all.
- **`Government Operations` on ballot-measure mechanics.** An article about how
  a proposition qualifies or how districts are drawn is annotated with it; an
  article about who wins because of that map is not. The pair reads inconsistent
  until the rule above is applied, and it was applied both ways before settling.
