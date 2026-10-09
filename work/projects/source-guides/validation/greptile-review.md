# PR 39 review corrections

This batch addresses three Greptile findings on `a782841`. The five deferred
UI/UX entries in `work/inbox.md` remain unchanged.

## Configured document store

The default guide store used `sqlite_db.DEFAULT_DB_PATH` instead of the configured
SQLite path. Application construction also preceded dependency startup, where the
production environment is loaded. A public HTTP regression reproduced missing
Publication metadata when `SQLITE_DB_PATH` pointed to a populated temporary
corpus; the explicit-path control passed.

The store now uses `SQLITE_DB_PATH` with the existing configured SQLite setting
as fallback. An explicit `guide_db_path` still wins. Application startup resolves
the store after dependency initialization, so configuration is available before
guide persistence and original Story lookups. Tests cover environment selection,
explicit precedence, Publication and verified highlight lookup, reopening saved
results from the selected store, and configuration loaded during startup.

## Publication reading views

The browser used `Date.parse` for group views while the server ordered articles
by their stated calendar day. A controlled browser test reproduced the mismatch
between `2024-01-02T00:30:00+02:00` and `2024-01-01T23:00:00Z`. It also showed an
incomplete date being treated as a sortable publication date.

The application now supplies complete publication-order ID lists using the
existing server date key, `datetime.fromisoformat(value).date().toordinal()`.
The browser applies those lists for requested publication order and publication
groups. Both directions preserve relevance order for equal days and put missing,
incomplete, or invalid dates last. Articles outside a selected group remain in
the complete reading list. Group membership is unchanged.

The order lists are computed from saved content when the application returns a
guide. Historical content needs no migration, model call, or update. Six added
browser cases cover ascending and descending requested views, both group views,
equal days, missing/incomplete/invalid dates, ungrouped articles, relevance order,
and reload at desktop and mobile sizes. All six passed after reproducing the
incorrect browser order before the fix.

## Saved-guide list projection

Listing guides opened one connection for identities and another connection per
guide, then constructed every complete `SavedSourceGuide` before discarding
article content. The regression observed 13 connections for 12 guides. A second
case with malformed article bodies in otherwise valid saved JSON failed during
full-content validation even though the list only needed summary metadata.

The store now returns `SavedGuideSummary` and `GuideAttemptSummary` through one
joined query. SQLite extracts status and assessment metadata; Python does not
receive or construct the full article content. The 12-guide regression now uses
one connection and returns a bounded summary response for both large valid
article bodies and malformed article bodies. This is evidence about connection
count and materialization, not a general latency measurement.

The list retains guide identity, question, saved outcome and timestamps, plus
the latest attempt's identity, timing, state, outcome, and assessment. Full reads
continue to supply content and detailed disclosures. Existing interruption,
retry, update, and cancellation tests verify those operations after the projection
change. The polling interval is unchanged, and no database migration was added.

## Validation

- The focused application suite passed 132 tests.
- The full deterministic Python suite passed 1,714 tests with 77 skips and the
  existing OpenRouter sampling-parameter warning. Six new browser cases are
  opt-in and account for the increase in skipped tests.
- All 16 Source Guides browser regressions passed, including the six new cases.
- All 31 Node reviewer tests passed.
- All changed Python modules and tests pass `ty check`, Ruff lint, and formatting.
  Reader JavaScript syntax and `git diff --check` also passed.

No historical prompts or evaluation reports changed. The running user application
was not restarted during these checks; browser tests used temporary storage and
controlled requests.
