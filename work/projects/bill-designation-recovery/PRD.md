# Product Requirements: Bill Designation Recovery

Labels: ready-for-agent

## Problem Statement

The graph holds thirteen `Bill` nodes and two of them carry a session. The other
eleven have `session`, `session_verified`, `session_inferred` and `needs_review`
all unset, and their keys sit under `Bill:unresolved:`. Bill Session Resolution
was built, shipped, and is running on two nodes out of thirteen.

Four causes produce that, and they compound.

The Entity Extraction Adapter is asked for a `number` property alongside the
`Bill` node's name, and it supplies the bare digits: `Senate Bill 9` arrives with
`number="9"`, `Assembly Bill 1751` with `number="1751"`, `Senate Bill 1305` with
the integer `1305`. Five of the seven `Bill` nodes carrying a `number` carry
digits with no chamber. A bill number without its chamber does not identify a
bill — `9` is not a bill, `SB 9` is — so the property the write path trusts most
is the property the model is least able to supply.

Bill number normalization reads that property in preference to the node's name,
and only falls back to the name when the property is empty rather than when the
property fails to normalize. `Senate Bill 9` therefore normalizes `"9"`, fails,
and never tries the name. The normalizer would have failed on the name too: it
matches two or three letters before the digits, so it accepts `ll 623` and
rejects `Senate Bill 9`, `Assembly Bill 1751` and every other spelled-out form in
the graph. It is broad where it produces garbage and narrow where it matters.

A number that fails to normalize is left out of the resolution map entirely, and
the Graph Database Adapter reads a missing entry as "this node is not a numbered
bill, write nothing". It cannot distinguish that from "this is a numbered bill
whose number could not be parsed, which a human should see", so eleven nodes
carry `needs_review = null` instead of the eleventh carrying `needs_review =
true`. The failure is silent by construction. Bill Session Resolution is the
place that knows which of the two happened, and it is not the place that decides
what gets written.

Finally, one node exists only because of a chunk boundary. `Article Chunk`
overlap is applied by prepending the previous chunk's trailing characters to the
next chunk's text, sliced at a character offset with no word boundary. In the
Uber ballot-measure article that slice landed inside `Senate Bill 623`, so the
chunk began `ll 623 would also prohibit the sale of such liens`, the model
extracted a `Bill` named `ll 623`, and the graph gained a second node for a bill
it already had. The same article names `Senate Bill 623` in full in five other
chunks. Every chunk in that article begins mid-word; this one merely began
mid-word inside something that mattered.

## Solution

A `Bill` node is identified by its **Bill Designation** — the chamber and number
together, normalized to `SB 623` or `AB 1751`. The Entity Extraction Adapter
stops being asked for a number at all and reports only the name as the article
wrote it. Bill Session Resolution derives the Bill Designation from that name,
and where the name does not yield one, tries to recover it from the rest of the
Source Article before any key is minted.

Recovery is what the `ll 623` case needs and what the article already supports.
Resolution sees every extraction for the article at once, so a name that yields
no Bill Designation but does contain a number is matched against the Bill
Designations the article did yield. `ll 623` finds exactly one article-level
match at `623` and adopts `SB 623`. It then resolves to the same session as
`Senate Bill 623` and mints the same key, so the two collapse to one node instead
of being written as two and repaired later.

Bill Session Resolution returns a resolution for every extracted `Bill` node,
including the ones that recovered nothing. A node like `the bill` or
`Richardson's legislation` gets a resolution that says so — no Bill Designation,
no session, `needs_review` set — rather than being absent from the map. The Graph
Database Adapter stops testing whether a resolution exists, stops normalizing
anything itself, and writes what it is handed. Under ADR 0002 that is what it was
always meant to do, and under ADR 0015 the article-scope resolver is where the
decision belongs.

Separately, chunk overlap stops mutilating words. An `Article Chunk`'s text is
exactly what the recursive chunker produced, split at separators, and the overlap
travels in the chunk's context field where it is already carried. The overlap is
retained: the Embedding Adapter and the chunk write consume context concatenated
with text, byte-identical to what they receive today. The Entity Extraction
Adapter receives the text alone, so an entity named in the overlap region is
extracted once, from the chunk that owns it.

## User Stories

1. As a retrieval consumer, I want a `Bill` node to be identified by its chamber
   and number together, so that `SB 9` and `AB 9` are never the same node.
2. As a retrieval consumer, I want `Senate Bill 623` and `SB 623` in the same
   article to be one node, so that counting mentions of a bill counts a bill.
3. As a retrieval consumer, I want a bill named in an article whose chunk
   boundary cut its name to still land on the correct node, so that chunk size is
   not visible in my results.
4. As a retrieval consumer, I want a `Bill` node that could not be identified to
   be visibly flagged, so that I can tell an unidentified bill from an identified
   one without querying for absent properties.
5. As a graph maintainer, I want the count of `Bill` nodes needing review to be a
   queryable number, so that I can measure how much of the bill layer is
   unresolved.
6. As a graph maintainer, I want the proportion of sessions that were verified
   from a link rather than inferred from a publication date to stay measurable,
   so that the guarantee issue 07 established is not lost in this change.
7. As a graph maintainer, I want a `Bill` whose name never yielded a designation
   to keep a stable key across re-ingestions, so that a later authoritative
   ingester can find and re-key it.
8. As a pipeline developer, I want the Entity Extraction Adapter to be asked only
   for a `Bill`'s name, so that the model is not asked for a decomposition it
   cannot reliably produce.
9. As a pipeline developer, I want Bill Designation parsing to accept exactly the
   four forms California uses — `SB`, `AB`, `Senate Bill`, `Assembly Bill`, in any
   case — so that `ll 623` and `to 5` are rejected as the non-designations they
   are.
10. As a pipeline developer, I want a name that fails to parse and a name that
    parses to be handled on separate paths, so that a parse failure triggers
    recovery rather than silence.
11. As a pipeline developer, I want the Graph Database Adapter to perform no
    normalization and no existence check, so that the resolution decision is made
    in one place and read in another.
12. As a pipeline developer, I want Bill Session Resolution to hold the properties
    a `Bill` node is written with, so that adding a flag does not mean editing a
    Cypher write site.
13. As a pipeline developer, I want an `Article Chunk`'s text to begin and end at
    a separator, so that no extracted entity name is a fragment of a real one.
14. As a pipeline developer, I want the overlap context passed to extraction as
    context rather than as text, so that entities are extracted once from the
    chunk that contains them.
15. As a pipeline developer, I want recovery to run before keys are minted, so
    that duplicate nodes are never written rather than written and merged.
16. As a pipeline developer, I want recovery to be order-independent across
    chunks, so that ADR 0015's guarantee holds for this resolution too.
17. As a pipeline developer, I want a name matching two different article-level
    Bill Designations to resolve to neither, so that ambiguity is reviewed rather
    than decided by iteration order.
18. As a domain reader, I want **Bill Designation** defined in `CONTEXT.md`, so
    that "number", "designation" and "name" are not used interchangeably in the
    next ticket.
19. As a domain reader, I want the superseded `number` property gone from the
    model rather than left unwritten, so that no query is written against a
    field nothing populates.

## Implementation Decisions

**Bill Designation is a new domain term.** The chamber and number of a
California bill, together, normalized to the initials form: `SB 623`, `AB 1751`.
It is what qualifies a `Bill`'s identity alongside its session, and it replaces
every current use of "bill number" standing alone. `CONTEXT.md` gains the entry.

**The Bill Designation is the `Bill`'s `name`.** No new property is introduced.
`:Bill` declared `number` alone, which cannot identify a bill without its
chamber, so under ADR 0014 `:Bill` now declares `name` holding the designation
and `number` is gone. What also changes is who supplies it: Bill Session
Resolution rather than the extraction model. The primary ontology's `SB-32`
example is reconciled to the normalized form, so the legislative ingester that
arrives later writes the same string. Where no designation was recovered, the
surface string the article used stands in as the name and `needs_review` says so.

**Extraction reports the surface string only.** The Extraction Prompt stops
asking for a `Bill`'s `number` property, and does not ask for its `name` either.
The surface string is whatever the article wrote — `Senate Bill 623`, `SB 623`,
`the bill`. Nothing downstream reads `properties["number"]`.

**Bill Designation parsing accepts four forms and nothing else.** `SB`, `AB`,
`Senate Bill`, `Assembly Bill`, case-insensitive, followed by digits with
optional intervening space or hyphen, producing `SB <n>` or `AB <n>`. There is no
general two-or-three-letter rule. A name that does not match this yields no Bill
Designation, and that is a distinct path, not a null return threaded through the
same one.

**Recovery runs inside Bill Session Resolution, before keys are minted.** For a
name that yields no Bill Designation, the digits in that name are matched against
the Bill Designations that other extractions from the same Source Article did
yield. Exactly one match adopts that designation. Two or more matches adopt none
and set `needs_review`. No digits in the name means no recovery is attempted, and
the resolution records no designation and no session with `needs_review` set.
Recovery reads all of the article's extractions at once, so it does not depend on
chunk order.

**Bill Session Resolution covers every extracted `Bill` node.** The resolution
map is keyed by the surface string the article used rather than by a normalized
designation, because a node whose surface string yields no designation has no
designation to key on.
Each resolution carries the Bill Designation it resolved to, the session, and the
three provenance flags. Two names in one article that recover to the same Bill
Designation resolve to the same session and mint the same key, which is what
merges them.

**The Graph Database Adapter looks up and writes.** It finds the resolution by
the node's surface string, applies the resolution's properties to the node, and mints the
key from the resolution's session and Bill Designation. It calls no parser and
tests for no missing entry. Its import of the normalizer goes away.

**The three session tiers from issue 07 are unchanged.** A link naming the
session verifies it; absent a link the publication date infers it; two links
disagreeing leave it unset and flag review. Only the value the tiers are keyed on
changes, from bill number to Bill Designation.

**Chunk text is separator-split; overlap travels as context.** The recursive
chunker's output text is used unmodified. The overlap refinery no longer prepends
to the chunk's text; the overlap is carried in the chunk's context field, snapped
outward to a word boundary, so that context concatenated with text reproduces a
contiguous span of the article. The Embedding Adapter and the chunk write consume
that concatenation and are unaffected. The Entity Extraction Adapter receives the
text alone.

Extraction does not receive the context. Coreference Resolution already runs on
the whole Source Article before chunking, so canonical names are substituted
throughout and the overlap is not what carries entity identity across a boundary.
The cost is measured: across the 73 stories in the document store, 1613 chunk
boundaries fall 91.1% at a paragraph end, 8.6% at a sentence end, and 0.3%
mid-sentence. Those five boundaries are the accepted loss, and they are cheaper
than a rule that lets the model claim entities from text it does not own.

**The `Bill` key shape does not change.** It stays session, then the slugged Bill
Designation where one exists and the slugged name where none does, with the
unresolved session sentinel as before. A recovered designation therefore lands on
the same key an unbroken chunk would have produced.

**Passing prior chunks' extractions forward was considered and rejected.** Giving
the extraction model the entities found in earlier chunks would attach
`MENTIONED_IN` edges to chunks whose text does not mention the entity, which
falsifies the Retrieval Evidence the edge points at. Coreference Resolution
already supplies the canonical-name consistency it would buy, and the change
cannot be evaluated until the Entity Extraction evaluation is unblocked.

## Testing Decisions

A good test here asserts what the graph ends up holding and what the adapters
were handed, not how the resolver arrived there. Parser internals, regex shapes,
and intermediate maps are not the subject; the node that gets written is.

**Story Pipeline with mock adapters, prior art `tests/test_pipeline.py`.** This
is the existing seam for Bill Session Resolution and stays the primary one:
`test_pipeline.py` already asserts that one resolution map is built per Source
Article, shared across every chunk, and equal to an expected
`BillSessionResolutions`. The cases this spec adds are observable there — the
spelled-out and initials forms of one bill resolving to one designation, `ll 623`
recovering from its article, a two-way ambiguous recovery flagging review, `the
bill` resolving to a flagged nothing, and the same extractions in reversed order
producing an equal map.

**Graph Database Adapter with a mocked driver, prior art
`tests/test_graph_db.py`.** `test_bill_session_participates_in_node_primary_key`
is the pattern for asserting minted keys and written properties.
`test_a_bill_without_a_resolution_gets_no_session_properties` asserts the
behaviour this spec inverts and is rewritten, not deleted: a `Bill` the resolver
could not identify is now written with `needs_review` set.

**Chunking as a pure utility, prior art `tests/test_chunking.py`.** The existing
tests assert the context field's length and its relationship to the previous
chunk's text; they are updated to the new contract — that no chunk's text begins
or ends mid-word, and that the context begins at a word boundary. The `ll 623`
case is worth a regression test written from the real article text.

No new Neo4j integration tests are added. Every claim above is observable at an
existing seam with mock adapters.

## Out of Scope

The Entity Extraction Adapter emitting vague references as `Bill` nodes.
`the bill`, `transportation bill`, `data sharing plan`, `plan to set a $28
minimum wage`, `Richardson's legislation` and `bill to study whether California
should bring back grizzly bears` are six of the thirteen nodes, and no resolution
change reaches them. They will resolve to a flagged nothing and be countable,
which is the input to deciding whether the Extraction Prompt should be emitting
them at all. That decision is a separate ticket.

Migrating the eleven existing `Bill:unresolved:` nodes in place. Issue 08 rebuilds
the graph; this spec changes what the rebuild writes.

Joining against authoritative legislative data to correct a mis-inferred session.
Issue 07 recorded that error mode as accepted, and it stays accepted.

Chunk size and overlap percentage as tuning values. This spec changes where the
overlap is carried, not how much of it there is.

## Further Notes

The two nodes that did resolve are not equally trustworthy. `AB 1751` is
`session_verified` from a link in its article. `SB 9` is `session_inferred` from
the publication date, so its `2025-2026` is a guess that happens to be plausible.
After this change the verified proportion is the number to watch, and it should
rise as recovery moves nodes out of `unresolved` rather than because inference
got more confident.

`ll 623` is evidence about chunking, not about extraction. The model read its
chunk correctly; the chunk was wrong. Every chunk in that article begins
mid-word, so the same defect has been producing subtler damage — truncated
person and organization names — that no one has counted. Fixing the overlap is
worth doing for reasons beyond the one bill it visibly broke.

The damage is the refinery's, not the chunker's. Measured across all 73 stories
before the refinery runs, exactly one of 1613 chunk boundaries falls inside a
word, and that one splits the hyphenated `cross-collaboration`. Every mid-word
chunk head in the Uber article was introduced afterwards, by the character-sliced
overlap prefix.
