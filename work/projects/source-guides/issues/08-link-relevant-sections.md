# 08 Direct readers to relevant article sections

Labels: enhancement, ready-for-agent
Parent: [Source Guides spec](../PRD.md)

## What to build

Use internal selected evidence to offer relevant-section links that highlight
verified original Story wording on the actual article page where supported.
Each included article appears once as an ordinary, non-highlighted link, with a
list of available verified highlights nearby. Preserve its reading directions
and the complete article list in every reading view. Readers never see Article Chunks.

## Acceptance criteria

- [ ] Derive section targets only for included articles from confidently
  identified original Story substrings. Coreference-modified chunk text or
  resolved offsets alone cannot establish an original target.
- [ ] Best-effort text fragments use verified wording and sufficient context
  when needed. Ambiguous repeats, absent original text, and uncertain locations
  produce ordinary-link fallback rather than fabricated anchors.
- [ ] Save reader-safe targeted URLs with the guide so reopening needs no live
  scraping, graph hydration, or regeneration. Always preserve the ordinary URL.
- [ ] Each included article appears once as an ordinary, non-highlighted link,
  with all available verified highlight links listed nearby. Group directions
  and articles without highlights remain available in every reading view.
- [ ] Source and relevant-section links open in separate tabs. When browser
  support, publisher restrictions, or page changes prevent highlighting, the
  reader can still reach the article.
- [ ] Public guide and detail responses expose no chunk bodies or hidden chunk
  previews. Targets refer only to included sources and retain safe-link rules.
- [ ] No guarantee of a current live-page match, ingestion overhaul for DOM
  offsets, or new scraping pipeline is introduced.

## Blocked by

- [02 Save, browse, and reopen Source Guides](02-save-and-reopen-guides.md)

## Validation

Exercise application responses and persistence with real temporary SQLite and
fixtures for changed coreference wording, unchanged original matches, ambiguous
repeats, absent text, unsafe URLs, and omitted sources. A chunk sentinel must
never appear publicly. Browser-verify actual highlighting and separate-tab
navigation on controlled source pages, plus useful ordinary-link fallback.
Run required checks with uv without independent Chat Session tests.

## Comments

The maintainer clarified the presentation on 2026-10-09: "An article should
always appear once as a non-highlighted link and if we have them, a list of
relevant highlights should appear in close proximity." This applies alongside
ticket 07's consolidated article list and nearby group directions.

Implementation and test evidence: [ticket 08 validation](../validation/ticket-08.md).
Acceptance and the completed label remain pending independent review.
