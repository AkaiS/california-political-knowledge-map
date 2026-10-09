# Sort verified reported event dates in Source Guides

Labels: bug, completed
Parent: [Source Guides](../projects/source-guides/PRD.md)

## Reproduction

SG-01, found during user-like browser exploration on 2026-10-09. A completed
guide's optional "Reported event timeline" says earliest first but places the
2021-09-16 signing before the 2021-04-15 hearing. Both ISO dates occur in the
selected evidence. The model supplied the two members in that reversed order.

The controlled guide was `976f914e-0c11-40dd-8b75-65d2ca415cf0` on port 8952.
The browser runner, action log, and original screenshot are local artifacts under
`/tmp/source-guides-exploration-20261009/`; the screenshot is
`screenshots/39-controlled-sourced-event-order.png`.

The durable minimal reproduction is
`test_optional_event_timeline_orders_verified_dates_before_saving` in
`tests/test_source_guide_groups.py`. It submits a question through the public
FastAPI HTTP interface, using deterministic model responses and temporary real
SQLite. Its two included articles have verified ISO dates and an optional
`event_asc` group. Before the fix, it failed twice in approximately two seconds,
returning `["2021-09-16", "2021-04-15"]` instead of
`["2021-04-15", "2021-09-16"]`.

Run the regression with:

```sh
uv run --no-sync pytest -q tests/test_source_guide_groups.py -k event_timeline_orders
```

## Cause and correction

Event guidance validation partitioned dated and undated members but trusted the
model's ordering within those partitions. A requested direction change merely
reversed that order. The reader then used the saved membership order.

The shared guidance path now compares the verified dates before saving a guide.
It honors the requested event direction or the optional group's direction.
Existing accepted date formats use standard-library calendar parsing. A partial
date supplies only its possible calendar range for comparison; its displayed
text stays unchanged. Non-overlapping ranges establish precedence. Topological
ordering respects those comparisons and uses model order among currently
available members, so overlapping ranges do not imply invented precision.
Missing, unsupported, and invalid calendar dates follow dated members.

The ordinary article link, nearby reading directions and verified highlights,
default relevance order, and complete article list retain their existing
contracts. Saved guides retain their recorded content until an explicit Update.
No prompt, schema, or persistence migration changed.

## Acceptance and validation

- [x] Verified comparable event dates appear chronologically in optional
  ascending and descending views.
- [x] Requested event direction overrides the model's group direction.
- [x] Reopening after application restart preserves the corrected membership
  order, while default relevance order remains available.
- [x] Partial dates keep their text and precision. Mixed month/year dates
  respect all known comparisons even when a year overlaps both months.
- [x] Absent or invalid calendar dates do not discard their articles or borrow
  publication dates.
- [x] The original browser scenario has been rechecked after explicit Update.
- [x] Required deterministic Python and Node suites pass after the final fix.

The HTTP tests map to ticket 07's chronology, article completeness, and saved
view criteria. Existing overlap and highlight tests cover the maintainer's
article-once and nearby-highlights rule.

Final local checks on 2026-10-09:

- `uv run --no-sync pytest -q tests/test_source_guide_groups.py`: 23 passed.
- `uv run --no-sync pytest -q tests`: 1585 passed, 61 skipped, one existing
  OpenRouter sampling warning, in 54.75 seconds. This run had approved localhost
  access. The first sandboxed run encountered only existing HTTP-server tests'
  socket-bind permission errors.
- `uv run --no-sync node --test tests/chat_eval_review_editing.test.mjs tests/rag_eval_review.test.mjs tests/chunk_eval_review.test.mjs`:
  29 passed.
- Changed-file `ty check`, Ruff lint and formatting, and `git diff --check`
  passed. No debug instrumentation remains.

The independent explorer restarted the controlled app, reopened the original
guide, chose Update, then selected the event view through browser controls.
The hearing now precedes the signing. All six ordinary article links remain
unique; nearby directions and highlights remain present, with no browser page
errors. After screenshots are `screenshots/58-fixed-event-ascending.png` and
`screenshots/59-fixed-comparison-reading.png` in the same local evidence
directory. The action log retains the observed DOM and article order.
Independent code review is recorded separately by the orchestrating task.

## Comments

2026-10-09: The diagnosis first reduced the browser symptom to two included
articles. The public regression was red before source changes. Three ranked
hypotheses were reported before probes; inspection confirmed the missing date
comparison before persistence. No temporary debug instrumentation was needed.
Separate red-green cycles checked ambiguous partial dates and invalid calendar
dates. A regression supplying reversed model order would have prevented this
defect; the existing event test supplied its comparable dates in correct order.
