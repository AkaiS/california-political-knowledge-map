# Enforce explicit Source Guide publication bounds

Labels: bug, completed
Parent: [Source Guides](../projects/source-guides/PRD.md)

## Reproduction

SG-02 was found during user-like browser exploration on 2026-10-09. The exact
question was:

> Only show articles published from January 1, 2023 through December 31, 2024 about California Proposition 1 mental health funding. Put those articles in oldest-to-newest publication order.

The live guide included "Homeless counts dropped in these California counties
this year", published `2026-08-21T12:00:00Z`, with a direction to read that
August 2026 article. The Deferred explanation retained December 31, 2024 as the
end of the recoverable range. The original guide was
`b1f4637e-d706-4c60-83eb-cc59d5d38972` on port 8951. The original screenshot is
`/tmp/source-guides-exploration-20261009/screenshots/49-live-explicit-date-outcome.png`.
The same directory's `live-records.json` and `browser-actions.jsonl` retain the
API and browser evidence.

A disposable public HTTP reproduction reduced this to one dense candidate,
the exact question, a controlled Deferred assessment, and guidance choosing the
2026 article. It failed twice in under two seconds. Four ranked hypotheses
preceded probes. Six probes, Allowed and Deferred across each retrieval branch,
all retained that article. The final model input contained both the original
question and correct publication metadata.

The durable regression is
`test_publication_bounds_omit_later_articles_groups_and_highlights_after_restart`
in `tests/test_source_guide_publication_bounds.py`. It uses real FastAPI,
temporary SQLite, the existing Chat Agent and retrieval coordinator, and
deterministic external responses. With typed bounds present but before the
guard, it retained the out-of-window article and failed its inclusion assertion.

```sh
uv run --no-sync pytest -q tests/test_source_guide_publication_bounds.py
```

## Cause and correction

The shared Question Assessment recorded reading order but had no typed
publication restriction. Jev can construct publication filters, but that does
not constrain candidates from every retrieval branch or the final reading
directions. Final guidance validated source references while trusting the
model to obey the question's publication limit.

The existing Question Assessment now carries optional inclusive
`publication_date_from` and `publication_date_through` dates. Pydantic validates
calendar dates and rejects reversed bounds. Instructions version 13 extracts
these only from explicit article-publication restrictions. Event dates, session
years, chronological ordering, collection coverage, and Deferred prose supply
no publication restriction by themselves. Unspecified endpoints remain open.
Prior prompt versions and historical records remain intact; absent fields
default to no restriction.

Shared final guidance removes selected articles outside those assessed bounds.
It uses the calendar day stated by an ISO citation date or datetime, without
timezone conversion. Missing, invalid, and incomplete dates cannot establish
that an article satisfies an explicit bound. The standard-library parser
handles citation metadata; no natural-language date parser or new agent was
introduced. Existing membership validation removes rejected articles from
groups, and reader projection supplies highlights only for retained articles.
An all-rejected result remains a successful empty guide. Existing unknown-source
validation still runs. Retrieval participation and coverage eligibility do not
change.

Saved guides retain their content until an explicit Update. This correction
does not rewrite past guides or claim complete retrieval coverage.

## Acceptance and validation

- [x] Exact publication bounds govern final article inclusion across full-text,
  dense, and structural candidates, for Allowed and Deferred assessments.
- [x] Both boundary days are included. Timezone-bearing citation datetimes use
  their stated day. One-sided limits keep the other endpoint open.
- [x] Missing, invalid, and incomplete publication dates are excluded only when
  an explicit publication limit applies. Reversed or invalid assessment bounds
  remain assessment failures.
- [x] Event years and coverage prose do not become publication limits. Useful
  later and undated reporting remains eligible for those requests.
- [x] Excluded articles leave no ordinary links, groups, or highlights. Retained
  articles keep reading directions and verified highlights after restart.
- [x] An all-rejected result is empty, rather than a guidance failure.
- [x] New immutable instructions are selected explicitly; prior versions and
  shared evaluation behavior remain interpretable.
- [x] The configured model extracts the intended fields in fixed semantic checks.
- [x] The original live browser scenario has been rechecked on the correction.
- [x] Required deterministic Python and Node suites pass after final changes.

The 13 HTTP regressions cover the inclusion, metadata, group, persistence, and
outcome requirements of Source Guides tickets 01, 07, and 09. A broader focused
run including shared chat evaluations and prompt-resource checks passed 110
tests, with one existing event-loop deprecation warning.

Four configured `gemma4:26b` assessment checks passed for the exact range,
event-years-only, lower-only, and upper-only questions. Their records are in
`/tmp/source-guides-exploration-20261009/sg02/model-assessment-results.json`.
Replaying the captured exact-question assessment through the original
single-2026-article HTTP scenario returned an empty guide. These are fixed-case
semantic checks, not a claim that every natural-language bound will be extracted
correctly. The event-only spot check still produced an unwarranted Deferred
coverage explanation, an existing semantic limitation outside this correction.

Changed production modules and the new regression file pass `ty check`.
The prompt-resource module has six existing type diagnostics; checking the
version from baseline `9f6a16c` reproduced the same six diagnostics. Its only
change is the adopted prompt's checksum. Changed-file Ruff lint and formatting
pass. Prior prompt files are unchanged and no debug instrumentation was added.

Final local checks on 2026-10-09:

- `uv run --no-sync pytest -q tests`: 1598 passed, 61 skipped, one existing
  OpenRouter sampling warning, in 58.31 seconds with approved localhost access.
- `uv run --no-sync node --test tests/chat_eval_review_editing.test.mjs tests/rag_eval_review.test.mjs tests/chunk_eval_review.test.mjs`:
  29 passed.
- Focused HTTP, grouping, coverage, shared evaluation, and prompt-resource
  checks: 110 passed, including all 13 new publication-bound regressions.
- Changed production/new-test type checks, changed-file Ruff lint and format,
  and `git diff --check` passed. The six baseline prompt-test type diagnostics
  are documented above.

The independent explorer restarted the application and submitted the exact
question through the browser as a new guide,
`22f1fce9-227f-46f7-8314-21ae61e12470`. Its saved assessment contains
`2023-01-01` and `2024-12-31`, and its successful empty result includes no
articles. The original failing guide retains its historical result. A separate
controlled publication-bounded browser request retained three in-window
articles and excluded 2022 and undated articles. The corresponding event-years
request retained all six articles with both publication bounds unset. No browser
page errors occurred. An empty result makes no claim that matching reporting
does not exist. Independent code review is recorded by the orchestrating task.

After screenshots under the same local evidence directory are
`screenshots/61-fixed-live-date-result.png`,
`screenshots/66-fixed-live-date-details.png`,
`screenshots/62-fixed-controlled-in-window-reading.png`, and
`screenshots/63-fixed-controlled-event-years-unrestricted.png`.
`live-records-after-sg02.json`, `controlled-records-after-sg02.json`, and
`browser-actions.jsonl` retain the corresponding results and controls.

## Comments

2026-10-09: The missing shared publication contract was the confirmed cause.
A public test combining an explicit publication restriction with a relevant
article outside that restriction would have caught the defect. Existing tests
covered publication ordering and source-reference validity independently.
The maintainer-authorized application seam was sufficient to reproduce and
correct the failure; no new Chat Session test seam was needed.
