# Bring an opened saved Source Guide into view

Labels: bug, completed
Parent: [Source Guides](../projects/source-guides/PRD.md)

## Reproduction

SG-03 was observed during user-like browser exploration on 2026-10-09. With
14 saved guides, opening the newest saved question loaded the correct content
below the saved list but left that content outside the viewport. The selected
question's heading was at `y=2296.14` in a `1120x1000` desktop viewport and
`y=2556.67` in a `390x844` mobile viewport. Readers had to scroll several screens
to see the result of their selection.

The explorer initially recorded this as a usability suggestion, rather than a
failed acceptance criterion. The maintainer's authorized follow-up accepted a
narrow navigation correction to reduce that friction. Saved content and the
existing controls were functional before the correction.

The retained browser regression is `tests/test_source_guide_browser.py`. It
loads the real packaged reader in Chromium, passes browser HTTP requests to the
actual FastAPI application, and seeds temporary SQLite through public question
submission. Model and retrieval responses are deterministic. The first explicit
selection regression failed on both viewport sizes before the source change.

```sh
RUN_SOURCE_GUIDE_BROWSER_TESTS=1 uv run --no-sync --with playwright pytest -q tests/test_source_guide_browser.py
```

Chromium must be installed with `uv run --with playwright playwright install
chromium`. The checks are opt-in, like the existing review-interface browser
tests. They are skipped by the default deterministic suite.

## Cause and correction

Saved-guide navigation rendered the selected content without scrolling to it.
The shared rendering function also handles background status polling, so adding
scrolling there would pull readers away every second while a search runs.

Explicit saved-guide navigation now scrolls to the guide after its read succeeds
and its selection is still current. It waits for the initial saved-list load
before scrolling. A delayed-list browser probe found that otherwise a freshly
restored guide could scroll first, then move outside the desktop viewport when
the list arrived. The existing selection guard also rejects late responses
after New question or another selection.

Selecting the already-open saved link also follows that navigation path. Its
URL fragment does not change, so the existing `hashchange` listener alone did
not handle that click. A normal click now reopens it; modified clicks retain
the anchor's browser behavior. The repeated-selection browser check failed on
both sizes before this final correction.

No layout, schema, prompt, or retrieval behavior changed. Article links,
nearby reading directions, and verified highlights use the existing rendering.

## Acceptance and validation

- [x] Explicit saved-guide selection brings the selected question into view on
  desktop and mobile with 14 saved guides, including a repeated selection.
- [x] Opening a saved `#guide` URL handles a delayed initial saved list.
- [x] Edit question focuses a visible input containing the complete question;
  New question focuses a visible empty input.
- [x] A delayed saved-guide response cannot leave New question or move its
  focused input out of view.
- [x] Two consecutive running-guide polls preserve the reader's manual scroll
  back to the question input.
- [x] The original controlled browser reproduction passes after the correction.

The opt-in Chromium suite passed all 10 desktop/mobile checks in 13.95 seconds.
The original controlled server reproduction now places the question heading
at `y=45.14` on desktop and `y=45.67` on mobile. Before/after screenshots,
measurements, and the original red run are retained under
`/tmp/source-guides-exploration-20261009/sg03/`. These temporary artifacts support
the exploration report; the regression itself is committed.

The independent explorer confirmed explicit selection and Edit/New controls
on both viewport sizes. A running search kept the reader's manual `scrollY=1752`
unchanged across 6.5 seconds of polling, with no browser errors. Captures
`screenshots/68-fixed-saved-selection-desktop.png` through
`screenshots/72-fixed-background-poll-preserves-scroll.png` in the exploration directory
record that pass. Whole-sequence code review is owned by the orchestrating task.

Final local checks on 2026-10-09 after the repeated-selection correction:

- `uv run --no-sync pytest -q tests`: 1598 passed, 71 skipped, one existing
  OpenRouter sampling warning, in 55.21 seconds. The ten additional skips are
  these opt-in browser cases, which passed separately above.
- `uv run --no-sync node --test tests/chat_eval_review_editing.test.mjs tests/rag_eval_review.test.mjs tests/chunk_eval_review.test.mjs`:
  29 passed.
- Changed-file `ty check`, Ruff lint and formatting, reader JavaScript syntax,
  and `git diff --check` passed. No debug instrumentation remains.

## Comments

2026-10-09: The diagnosis considered missing explicit scrolling, initial list
expansion, and later refreshes. Browser probes confirmed the first two. The
correction keeps scrolling in guarded navigation, and the polling regression
protects the reader's chosen position. No private rendering state or DOM
snapshot is used as an assertion.
