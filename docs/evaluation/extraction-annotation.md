# Extraction annotation guideline

The standard the extraction Silver Set is annotated against. Every case in
`evals/silver/extraction.yaml` names this file in its `annotation_guideline`
metadata, because a judgment call made one way in one chunk and the other way
in the next produces a Silver Set that no score can be read against.

You are producing a **careful, guideline-faithful** extraction annotation of one Article
Chunk against the News Ontology.

## What a case is

One Article Chunk, and nothing else. The chunks were cut by `chunk_article`
from the 20 Stories of `evals/silver/coreference.yaml` **after** their accepted
silver Mention Spans were substituted, so the text reads the way extraction
sees it in production: repetitive, with canonical names standing where
pronouns were. Annotate that text as it is.

- The chunk is the whole world. Do not use the rest of the article, the
  headline, the URL, or anything you know about the entity.
- The chunk's overlap context is **not** part of the case. `ArticleChunk.text`
  is what extraction reads, so an entity named only in the overlap is not here.
- Recursive chunking keeps sentences whole, so a mid-sentence edge is rare: one
  of the fifty cases has one, where substitution grew a sentence past the 512-
  character chunk size. Annotate what the partial sentence actually says.
- A chunk starting on a lowercase word is usually **not** a partial sentence. It
  is a whole one whose opening pronoun was replaced: `It's likely to have…`
  reaches extraction as `the block grant carrot and stick provision's likely to
  have…`. Read it as the sentence it is.
- A chunk supporting nothing is annotated as two empty lists. Five of the fifty
  cases are exactly that, deliberately.

## Labels

Only the seven extracted labels exist: `Politician`, `Organization`, `Bill`,
`Prop`, `Committee`, `Campaign`, `LegislativeEvent`. There is no `Person`, no
party, no district and no place, so an entity that is none of the seven is not
annotated at all.

What an article is about is not among them. That question is answered once per
Source Article by Policy Area Classification, over the whole resolved text, so
no case here asks what topic a chunk covers or which topic a measure concerns.

### Politician (load-bearing)

A named person is a `Politician` only when the chunk itself marks them as
holding or seeking office. Any one of these marks is enough:

- an office or title on the name — `Gov.`, `Sen.`, `Assemblymember`,
  `former Los Angeles Mayor`, `President`;
- a party label attached to the person — "a Napa Democrat";
- the chunk showing them legislating — voting, carrying, authoring or vetoing;
- the chunk placing them in an election — running, being endorsed, having
  "competitors" in a primary.

Everyone else is **not annotated**: spokespeople, lobbyists, academics,
executives, union officials, police chiefs, donors, private citizens. This
drops article subjects from chunks that never say who they are, which is the
correct and consistent answer to "who is this, reading only this chunk".

A person node also requires a **full name** in the chunk. A bare surname
(`Newsom`, `Trump`, `Bruce-Lane`) is not enough to key a node, so it is not
annotated even when the office marker is there.

### Organization

Every organization the chunk names by its own name: agencies, companies,
unions, trade groups, nonprofits, advocacy groups, news outlets, colleges.

- A **descriptive reference** is not a name. "the Stanford design thinking
  school", "state Insurance Department", "another consumer advocacy group"
  are skipped unless the chunk also gives the organization's own name.
- Apply a sub-label only where the chunk supports it. Public colleges,
  university systems, and state and federal bodies take `GovernmentAgency`;
  private companies `Corporation`; unions `LaborUnion`; industry groups
  `TradeAssociation`; news outlets `MediaOrganization`. Where the chunk says
  nothing about what kind of organization it is, emit **no** sub-label rather
  than one you know from elsewhere.

### Bill

`name` is the **surface string the chunk used**, verbatim except for a leading
article: `Assembly Bill 1883`, `SB 9`, `federal housing bill`. Never expand,
normalize or decompose it — the Bill Designation is written by Bill Session
Resolution, not by extraction, and a bill with no designation keeps its
surface string as its name.

A measure the chunk refers to only indefinitely ("another bill", "the special
session gas-price laws") is not a Bill node. A specific measure the chunk
handles by a definite description is; use the fullest handle the chunk gives.

### LegislativeEvent

Annotate one when the chunk reports that a vote, a hearing or an amendment
happened. The sub-label is required, and the name is derived so two
annotators write the same string:

- `Vote on <bill surface string>`
- `Hearing on <bill surface string>`
- `Amendment to <bill surface string>`

A veto is none of the three. It is a `DECLARED_STANCE` from the governor.

### Campaign

Only where the chunk speaks of a campaign as a thing. The one exception is the
endorsement convention below, which mints one.

## Relationships

Only the 16 permitted types, only where the chunk states the connection.
Never infer a claim from quotation, coverage, employment, funding or mention.

- **Stance vs lobbying.** `LOBBIED_FOR` / `LOBBIED_AGAINST` need lobbying
  activity in the chunk — a registered lobbyist, lobbying spend, advocacy at
  the Legislature. Support or opposition stated any other way is
  `DECLARED_STANCE` with `alignment` `POSITIVE` or `NEGATIVE`.
- **Authorship is a stance.** A lawmaker carrying, authoring or pushing a bill
  is `DECLARED_STANCE` `POSITIVE`; the ontology has no authorship edge.
  A veto is `DECLARED_STANCE` `NEGATIVE`.
- **An officer speaks for the organization.** A named executive director or
  president stating a position in that capacity is the organization's
  `DECLARED_STANCE`, not the person's — the person usually has no node at all.
- **Endorsing a candidate mints a Campaign.** `ENDORSED` cannot point at a
  `Politician`, so an endorsement of a candidate is annotated as a
  `Campaign` node named `<Politician name> campaign`, sub-label
  `CandidateCampaign`, a `CAMPAIGN_FOR` edge to the `Politician`, and the
  `ENDORSED` edge to the campaign. Mint one only for a candidate the chunk
  names in full.

## Properties

Sparse and stated, never inferred.

- Never emit `id` or `embedding`. Persistence mints the key from the name.
- Never repeat the node's `name` inside `properties`. It is the top-level
  field, and the write path copies it there itself.
- The properties this Silver Set actually carries are `current_party` on a
  `Politician` the chunk gives a party for, and `number` on a `Prop`.
- On a relationship, `alignment` on every `DECLARED_STANCE`, and `amount` or
  `date` on a `FUNDED` where the chunk states one in the fixed form.

## Known open calls

Flagged during the 50-chunk annotation pass and not yet settled. Listed so a
future pass makes the same choice rather than rediscovering the question.

- **The Politician office marker.** It costs the article's own subject in
  chunks that never restate who they are — Steve Hilton in a chunk about his
  beliefs, Katie Porter in a chunk about her temperament. The alternative,
  labeling every named political actor a `Politician`, mints Politician nodes
  for lobbyists and professors, which is worse for the graph. The marker rule
  won on that trade, not on principle.
- **Descriptive Bill handles.** `federal housing bill` and
  `Common Sense Media bill banning AI chatbots for minors` are annotated as
  Bill nodes because the ontology says a surface string stands in where no
  designation was recovered. Where the handle gets long, the fullest form was
  taken, and no rule says how long is too long.
- **Public universities as `GovernmentAgency`.** UCLA, UC Davis, Cal State
  Northridge and Mt. San Antonio College carry it; Cornell and McMaster carry
  no sub-label. The line is public-vs-private, which the chunk rarely states.
- **`Congress`, `U.S. Navy` and other bodies as `Organization`.** They are
  actors the chunk names, so they are annotated, but nothing else in a case
  ever connects to them.
