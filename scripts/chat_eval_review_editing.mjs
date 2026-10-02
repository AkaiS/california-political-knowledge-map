/**
 * Evaluation Case editing, independent of the page and browser APIs.
 * persistReview resolves after the file is saved, or rejects with an Error
 * carrying the HTTP status when available. Storage and scheduling use the
 * getItem/setItem/removeItem and setTimeout/clearTimeout interfaces.
 * State is copied. Notifications identify selection/undo redraws separately
 * from review/status changes so typing and save completion keep the caret.
 * Save and navigation promises return false when saving or movement is blocked.
 */
export function createReviewEditor({
  caseNames, reviews: loadedReviews, runId, reviewIdentity,
  persistReview, storage, scheduler, onChange = () => {},
}) {
  const names = [...caseNames];
  const reviews = Object.fromEntries(names.map(name => [name, {
    verdict: loadedReviews[name]?.verdict ?? null,
    note: loadedReviews[name]?.note ?? '',
  }]));
  const drafts = new Map(), revisions = new Map(), statuses = new Map();
  const draftKey = `chat-review-drafts:${runId}:${reviewIdentity}`;
  let selectedCase = names[0] ?? null, storageFailed = false, saveTimer;
  let saveChain = Promise.resolve(true);
  let navigationChain = Promise.resolve(true), navigationGeneration = 0;
  const pendingSaves = new Map();
  const history = [];

  function state() {
    const failed = [...drafts.keys()].filter(name => /failed/i.test(statuses.get(name) || ''));
    const shouldWarnOnUnload = storageFailed && drafts.size > 0;
    let saveStatus = failed.length ? failed.map(name => `${name}: ${statuses.get(name)}`).join(' ') : statuses.get(selectedCase) || '';
    if (shouldWarnOnUnload && !saveStatus.includes('Keep this page open')) saveStatus += ' Keep this page open until saved.';
    return {
      selectedCase,
      reviews: Object.fromEntries(names.map(name => [name, {...reviews[name]}])),
      saveStatus,
      saveFailed: failed.length > 0,
      pendingDraftCount: drafts.size,
      canUndo: history.length > 0,
      shouldWarnOnUnload,
    };
  }
  function notify(change = 'status') { onChange(state(), change); }
  function persistDrafts() {
    try {
      if (drafts.size) storage.setItem(draftKey, JSON.stringify({review_identity: reviewIdentity, reviews: Object.fromEntries(drafts)}));
      else storage.removeItem(draftKey);
      storageFailed = false;
    } catch (_) { storageFailed = true; }
  }
  function setStatus(name, revision, status) {
    if (revisions.get(name) !== revision) return;
    statuses.set(name, status);
    notify();
  }
  function markEdited(name) {
    revisions.set(name, (revisions.get(name) || 0) + 1);
    drafts.set(name, {...reviews[name]});
    persistDrafts();
    statuses.set(name, storageFailed ? 'Local backup failed. Keep this page open until saved.' : 'Saved locally; saving to review file…');
  }
  function editNote(note) {
    if (selectedCase === null) return;
    changeReview({...reviews[selectedCase], note});
    scheduler.clearTimeout(saveTimer);
    saveTimer = scheduler.setTimeout(flush, 350);
  }
  function changeReview(review) {
    const before = reviews[selectedCase];
    if (before.verdict === review.verdict && before.note === review.note) return;
    history.push({name: selectedCase, before: {...before}});
    reviews[selectedCase] = review;
    markEdited(selectedCase);
    notify('review');
  }
  function setVerdict(verdict) {
    if (selectedCase === null) return Promise.resolve(true);
    changeReview({...reviews[selectedCase], verdict});
    return flush();
  }
  function undo() {
    const action = history.pop();
    if (!action) return Promise.resolve(true);
    // Keep the restored case selected when an earlier navigation finishes saving.
    navigationGeneration++;
    reviews[action.name] = action.before;
    selectedCase = action.name;
    markEdited(action.name);
    notify('undo');
    return flush();
  }
  function saveCase(name) {
    if (!drafts.has(name)) return Promise.resolve(true);
    const review = {...reviews[name]}, revision = revisions.get(name);
    const key = JSON.stringify([name, revision]);
    if (pendingSaves.has(key)) return pendingSaves.get(key);
    setStatus(name, revision, 'Saving to review file…');
    const operation = saveChain.then(async () => {
      try {
        await persistReview({name, review, review_identity: reviewIdentity});
        if (revisions.get(name) === revision) { drafts.delete(name); persistDrafts(); }
        setStatus(name, revision, 'Saved to review file');
        return true;
      } catch (error) {
        const message = error.status === 409 ? 'Save failed: report changed. Reload to review the current report' : error.message;
        setStatus(name, revision, `${message}. ${storageFailed ? 'Keep this page open.' : 'Edits kept in this browser.'} Use Save / retry.`);
        return false;
      } finally { pendingSaves.delete(key); }
    });
    pendingSaves.set(key, operation);
    saveChain = operation;
    return operation;
  }
  async function flush() {
    scheduler.clearTimeout(saveTimer);
    while (drafts.size) {
      const results = await Promise.all([...drafts.keys()].map(saveCase));
      if (!results.every(Boolean)) return false;
    }
    return true;
  }
  function moveTo(destinationFor) {
    const generation = navigationGeneration;
    navigationChain = navigationChain.then(async () => {
      if (generation !== navigationGeneration) return false;
      const destination = destinationFor();
      if (!await flush()) return false;
      if (generation !== navigationGeneration) return false;
      if (destination !== undefined && destination !== selectedCase) {
        if (!names.includes(destination)) return false;
        selectedCase = destination;
        notify('selection');
      }
      return true;
    });
    return navigationChain;
  }
  function selectCase(name) { return moveTo(() => name); }
  function navigate(delta, matchingCases) {
    return moveTo(() => {
      const matching = new Set(matchingCases());
      const index = names.indexOf(selectedCase);
      const positions = names.map((name, position) => matching.has(name) ? position : -1).filter(position => position >= 0);
      const destination = delta < 0 ? positions.filter(position => position < index).at(-1) : positions.find(position => position > index);
      return names[destination];
    });
  }
  function prepareForUnload() {
    persistDrafts();
    notify();
    return state().shouldWarnOnUnload;
  }
  try {
    const stored = JSON.parse(storage.getItem(draftKey) || '{}');
    const recovered = stored?.review_identity === reviewIdentity && stored.reviews && typeof stored.reviews === 'object' && !Array.isArray(stored.reviews) ? stored.reviews : {};
    for (const name of names) {
      const draft = recovered?.[name];
      if (draft && [null, 'pass', 'fail', 'defer'].includes(draft.verdict) && typeof draft.note === 'string') {
        reviews[name] = {verdict: draft.verdict, note: draft.note};
        drafts.set(name, {...reviews[name]});
        revisions.set(name, 1);
        statuses.set(name, 'Recovered browser edits; saving to review file…');
      }
    }
  } catch (_) { storageFailed = true; }
  persistDrafts();
  if (drafts.size) Promise.resolve().then(flush);
  return {get state() { return state(); }, editNote, setVerdict, undo, flush, selectCase, navigate, prepareForUnload};
}
