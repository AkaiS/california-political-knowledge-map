# Reopen saved guides

Saved Source Guides retain each explicit question, its outcome, and available reading across selection, page reload, and application restart. Reopening a guide does not start another search.

## Sub-features

- `saved-list` lists saved questions and latest-attempt summaries.
- `saved-open` restores an existing guide through list selection or a direct fragment.
- `saved-restart` restores content and status after the service restarts.
- `saved-independent` keeps multiple questions independent while searches continue.

## How to get to it (user POV)

- Submit any complete question with `Find articles`.
- Click a question under `Saved guides`, including the currently selected question.
- Open or reload `/#guide=<guide_id>`.
- Restart the local application using the same owned SQLite copy, then reopen the question.
- Submit another question and switch between saved questions or close the page while the app remains running.

## Driving it with HTTP and authorized browser controls

Preconditions:

- A guide has finished assessment or retrieval on the owned instance. Keep its returned guide and attempt IDs.
- Use the automatic helper for the service-restart journey. Its restart keeps the same isolated SQLite copy and cleans up afterward.

- List guides. Run `curl --fail-with-body -sS "$VERIFY_URL/api/guides" > saved-list.json`. Require the original question, guide ID, latest attempt ID, and correct summary status.
- Reopen without searching. Run `curl --fail-with-body -sS "$VERIFY_URL/api/guides/$VERIFY_GUIDE" > reopened.json` twice. Require identical terminal content, saved timestamps, and latest attempt ID. The helper also checks the stored question and one attempt in SQLite using a read-only connection.
- Restart persistence. Run the default helper from `SKILL.md`. It stops only its captured app process group, launches again with the same copy, runs doctor, and captures `persisted.json`. Require identical content and attempt identity. This proves service reopening and restart, not browser reload.
- Select in the browser. Click the exact question link under `Saved guides`. Require the same complete heading and saved outcome. Click that same selected link again and require unchanged timing and attempt identity.
- Direct fragment and reload. Navigate to `http://127.0.0.1:8132/#guide=` followed by the returned guide ID. Reload the page. Require restored reading or assessment outcome without a new attempt. Capture the fragment, rendered guide, and GET response before and after reload.
- Independent questions. Submit `Who supported that bill?` and then `What is happening with housing policy in California?` through the form. Switch between their exact Saved guides links. Require distinct IDs and preserved wording; the second guide supplies no conversational context to the first. Close the page, keep the owned service running, and reopen the first guide by fragment. Confirm both remain listed.

## Gotchas

- The URL uses a fragment, not a server route such as `/guides/<id>`. HTTP GET `/` cannot prove fragment selection.
- Saved-guide selection and submission affect browser focus and scrolling. Those require browser evidence.
- A currently running attempt changes as background work finishes. Compare terminal content for equality; for running attempts, compare identity and preserved question instead.
- Reopening and restart must never POST an update. The helper's request trace makes that service behavior reviewable.
- Generation passed the saved-list, reopening, SQLite, and service-restart checks for the missing-reference guide. Browser selection, direct-fragment reload, and multiple independent questions remain untested.
