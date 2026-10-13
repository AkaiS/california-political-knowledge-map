# Submit and assess a question

A complete question starts a saved Source Guide. Assessment preserves its wording, accepts meaningful broad California political questions, and asks the person to edit a missing reference.

## Sub-features

- `question-submit` saves a question before searching.
- `question-needs-edit` explains an unresolved reference without running retrieval.
- `question-broad` accepts a meaningful broad topic.
- `question-edit` restores the saved wording for submission as a new guide.
- `question-new` clears the input and selected guide.

## How to get to it (user POV)

- Open `/`, fill the `Complete question` textbox, and choose `Find articles`.
- Open any Saved guides link or `/#guide=<guide_id>` and choose `Edit question`.
- Choose `New question` from the question form.

## Driving it with HTTP and authorized browser controls

Preconditions:

- Doctor passes on the owned instance. Start with no saved guides for the default helper.
- For manual HTTP actions, hold the helper with `--pause-after-doctor` and set `VERIFY_URL=http://127.0.0.1:8132` in the second terminal. Run commands from the proof directory so response files persist after teardown.

- Missing-reference submission. Run `curl --fail-with-body -sS -D submit.headers -H 'Content-Type: application/json' -d '{"question":"Who supported that bill?"}' "$VERIFY_URL/api/questions" > submit.json`. Require HTTP 202, unchanged `question`, `guide_id`, and a running latest attempt. The automatic helper performs this same production action and polls to completion.
- Read the result. Run `VERIFY_GUIDE=$(uv run --frozen python -c 'import json; print(json.load(open("submit.json"))["guide_id"])')`, then `curl --fail-with-body -sS "$VERIFY_URL/api/guides/$VERIFY_GUIDE" > result.json`. Repeat GET until `latest_attempt.status` leaves `running`. Require `status: needs_edit`, a nonempty assessment explanation, no articles, and `search_details.completion: not_searched`.
- Browser submission. Fill the textbox labeled `Complete question` with `Who supported that bill?`, then click the button named `Find articles`. Require a new Saved guides link with that wording and the outcome `Edit your complete question to continue.` in `#outcome`. Capture the explanation, screenshot, and accessibility state. API proof alone leaves this entry point unverified.
- Broad topic. Fill the same textbox with `What is happening with housing policy in California?` and click `Find articles`. The equivalent HTTP action is `curl --fail-with-body -sS -H 'Content-Type: application/json' -d '{"question":"What is happening with housing policy in California?"}' "$VERIFY_URL/api/questions" > broad.json`. Poll its returned ID. Require assessment `allowed`; final retrieval may complete, return empty, or fail with a disclosed reason. A retrieval failure does not prove a successful reading journey.
- Edit a saved question. Open the missing-reference guide, click `Edit question`, and require the textbox to contain its complete wording. Replace it with `What is happening with housing policy in California?` and click `Find articles`. Require a new guide ID and both guides in the saved list. There is no HTTP edit endpoint; POSTing a new question verifies new-guide creation only.
- New question. Click `New question`, whose stable ID is `#new`. Require an empty question input, hidden guide section, cleared selected fragment, and retained Saved guides. This is a browser-only action.

## Gotchas

- The browser trims submitted input. Use the exact fixture wording above when asserting preservation.
- Questions share no implicit conversational context. `that bill` remains unresolved even after another guide names a bill.
- `needs_edit` and `declined` use a completed attempt but do not search. Inspect guide outcome and search completion, not only attempt status.
- The seed corpus does not supply a named referent for the missing-reference fixture. That missing precondition is intentional. Broad-topic retrieval requires actual corpus evidence and working retrieval dependencies.
- Generation passed the missing-reference HTTP journey against the real local model. Browser submission, Edit question, New question, and broad-topic retrieval remain untested.
