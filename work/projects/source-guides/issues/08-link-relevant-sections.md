# 08 Direct readers to relevant article sections

Labels: enhancement, ready-for-agent
Parent: [Source Guides spec](../PRD.md)

## What to build

Use internal selected evidence to offer a relevant-section link that highlights
verified original Story wording on the actual article page where supported.
Always retain the ordinary article link. Readers never see Article Chunks.

## Acceptance criteria

- [ ] Derive section targets only for included articles from confidently
  identified original Story substrings. Coreference-modified chunk text or
  resolved offsets alone cannot establish an original target.
- [ ] Best-effort text fragments use verified wording and sufficient context
  when needed. Ambiguous repeats, absent original text, and uncertain locations
  produce ordinary-link fallback rather than fabricated anchors.
- [ ] Save reader-safe targeted URLs with the guide so reopening needs no live
  scraping, graph hydration, or regeneration. Always preserve the ordinary URL.
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
