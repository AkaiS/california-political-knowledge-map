# Coreference annotation guideline

The standard the coreference Silver Set is annotated against. Every case in
`evals/silver/coreference.yaml` names this file in its `annotation_guideline`
metadata, because a judgment call made one way in one article and the other
way in the next produces a Silver Set that no score can be read against.


You are producing an **exhaustive, guideline-faithful** coreference annotation of one
news article, to replace a thin machine-generated "silver" annotation.

## What a Mention Span is

A referring expression that points at an entity named elsewhere in the article,
recorded as four fields:

- `sentence_label` — the number in brackets at the start of the sentence line.
- `mention_text`   — the mention copied **verbatim**, exact capitalization.
- `occurrence`     — 1-based index of that exact text within that sentence.
- `canonical_entity_name` — the fully expanded name of the referent.

## Include

- Personal pronouns: he, him, his, she, her, hers, they, them, their, it, its.
- Demonstratives used as references: that, this, those, these — **only** when
  they stand for a concrete entity, not a proposition.
- Definite descriptions that re-refer to an already-named entity:
  "the governor", "the agency", "the bill", "the company", "the Democrat".
- Group/collective references: "the pair", "both men", "the two agencies".
- Relative pronouns with a concrete antecedent: who, whom, whose, which.
- Reflexives: himself, herself, itself, themselves.
- Possessive determiners on the same terms as pronouns ("his campaign" → annotate
  `his`, not the whole phrase — see Overlap below).
- Repeat occurrences within one sentence. If a sentence contains `he` twice,
  that is **two** Mention Spans, `occurrence` 1 and 2.

## Exclude

- **Pleonastic / expletive `it`**: "it is unclear that…", "it rained", "it takes
  three years", "it could help Hilton that…". No referent, no span.
- **Generic `you` / `we` / `they`**: "you have to be respectful", "they say".
- **Propositional or abstract antecedents**: "that" standing for a whole clause,
  event, or idea rather than an entity.
- **First mentions / proper names**: `Steve Hilton` is the antecedent, not a
  mention span. Only annotate expressions that *refer back*.
  - Exception: a shortened proper name that is genuinely a re-reference
    (`Hilton` after `Steve Hilton`) — **exclude** these too. Keep this
    annotation to pronouns and definite descriptions only, so the set is
    consistent across all 20 articles.
- Speaker-attribution `I`/`my`/`me` inside a **direct quotation** — **include**
  these, mapped to the speaker, because the pipeline must resolve them.
  (This is an include, listed here because it is the common judgment call.)
- Mentions inside the article's byline, standfirst, or boilerplate footer if the
  referent is not an entity discussed in the body.

## Overlap rule (load-bearing)

Deterministic validation **discards** a span whose character range overlaps an
earlier accepted span. So never annotate a mention nested inside another
mention. For "his campaign manager, who said…", annotate `his` and `who`
separately; do **not** also annotate "his campaign manager".
Prefer the shortest expression that carries the reference.

## Occurrence counting (load-bearing)

Occurrence is counted by a **case-sensitive**, word-boundary regex over the
sentence text: `(?<!\w)<mention_text>(?!\w)`.

- `He` and `he` are **separate** counters. If a sentence reads
  "He paused and he coughed", that is `He` occurrence 1 and `he` occurrence 1 —
  not occurrence 1 and 2.
- `his` does **not** match inside `history`, because of the word boundaries.
- If you are unsure, run the validator (below); it tells you the exact count.

## Canonical entity names

- Fully expanded and **consistent across the whole article**. Pick one spelling
  and reuse it byte-for-byte: `Steve Hilton` everywhere, never also `Hilton`
  or `Steve  Hilton`.
- For a joint referent, join with ` and `: `Steve Hilton and Giles Gibbons`.
- Use straight ASCII apostrophes in entity names even if the article uses curly
  ones. (`mention_text` still copies the article verbatim, curly quote included.)
- For an organization, use the form the article establishes:
  `California Air Resources Board`, not `CARB` and not `the board`.

## Known open calls

These were flagged during the 20-article annotation pass and are not yet
settled. They are listed so a future pass makes the same choice rather than
rediscovering the question.

- **Relative `that`.** Excluded throughout: the Include list names only
  who/whom/whose/which. Worth roughly six spans per article.
- **First-person plurals in quotation.** `I`/`my`/`me` are included by the
  rule above; `we`/`our`/`us` were included when they clearly speak for a
  named organization and excluded when generic. The rule does not actually
  say this.
- **Acronym re-reference.** `The CNA`, `SB 7` and bare surnames are excluded
  under the shortened-proper-name rule, while definite-description
  paraphrases (`the health giant`, `the nurse union`) are included. The
  boundary between "acronym behind a definite article" and "definite
  description" is the least stable line in this document.
- **Provision-level entities.** Where an article re-refers to individual
  provisions of one bill (`the provision`, `the measure`), those were given
  their own canonical names rather than collapsed into the parent bill.
- **Anonymous sources.** Distinct unnamed people are distinct entities, not
  one merged `an anonymous nurse`.
