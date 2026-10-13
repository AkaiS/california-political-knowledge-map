# Read a guide

A completed Source Guide gives the person linked Source Articles and reading directions, with Article Groups, coverage limits, and optional verified highlights.

## Sub-features

- `reading-links` opens ordinary article links and available highlights in another tab.
- `reading-views` reorders the complete article list by relevance or an available question-specific view.
- `reading-details` exposes saved search limits and latest-attempt details.
- `reading-disclosures` distinguishes unmatched requests, partial failures, and missing coverage.

## How to get to it (user POV)

- Submit a complete question with `Find articles` and wait for reading.
- Choose a completed question under `Saved guides`.
- Open `/#guide=<guide_id>` directly, reload it, or return after restarting the service.
- Use the `Reading view` select and the `Search details` disclosure in the selected guide.

## Driving it with HTTP and authorized browser controls

Preconditions:

- Hold an owned app using `--pause-after-doctor`. Submit `What should I read about housing legislation in California?` through the question recipe and derive `VERIFY_GUIDE` from that submission. The attempt must finish with nonempty `articles` and `status: completed`.
- To check highlights, real Story wording must exist in the copied SQLite store and match the selected source evidence. A timeline or Article Group view requires the corresponding group or reading-order assessment in this guide.

- Inspect saved reading. Run `curl --fail-with-body -sS "$VERIFY_URL/api/guides/$VERIFY_GUIDE" > reading.json`. Require unchanged question, nonempty articles with citation URLs and nonempty `reading_direction`, and saved `search_details`. HTTP proves the response data only.
- Open the guide. Navigate to `http://127.0.0.1:8132/#guide=` followed by the returned guide ID, or click its exact question link in `#guide-list`. Require the question heading in `#guide-question`, `Articles to read` in `#outcome`, and article links inside `#articles`.
- Open an article. Click the first ordinary article link inside `#articles` using its title from `reading.json`. Require a new tab with the same HTTP or HTTPS citation URL. Record its URL and the originating rendered link; opening remote article content requires the browser path's authorization. Check recorded Publication and available publication date beneath the link.
- Change reading view. Select `All articles by relevance` in the select labeled `Reading view`. If available, select the Article Group label returned in `groups` or `Requested publication order`. Require the same complete set of article links, reordered according to that view, and matching text in `#view-description`. Views do not filter articles out.
- Inspect limits. Click the `Search details` summary in `#search-details`. Require collection dates, search completion, result limits, and included-article count when applicable. Capture `#disclosures` and `#attempt-disclosures` when visible alongside these details.
- Open a highlight. If an article has `section_links`, click its `Relevant highlight 1` link within that article row. Require a new tab whose URL matches the saved target, including its text fragment. Capture the source row and new-tab URL. If no verified highlight exists, record that entry point as unavailable.

## Gotchas

- The default missing-reference fixture never retrieves articles. It cannot satisfy this feature's precondition. Generation has not run this reading journey.
- Missing Story wording leaves ordinary links available and omits verified highlights. Publication metadata can also be absent. These are observable limits, not reasons to invent fixtures that bypass retrieval.
- Reading views and opening links run in browser JavaScript. GET responses do not prove those actions.
- Publication dates describe reporting; event dates, when present in Article Groups, describe reported events. Keep their assertions separate.
- Empty results and partial search failure do not establish absence in California politics or complete collection coverage.
