import assert from 'node:assert/strict';
import {test} from 'node:test';
import {createReviewEditor} from '../scripts/chat_eval_review_editing.mjs';

const draftKey = 'chat-review-drafts:run:report-identity';

function controlledPersistence() {
  const writes = [], available = [], waiting = [];
  return {
    writes,
    persistReview(payload) {
      return new Promise((resolve, reject) => {
        const write = {payload, succeed: resolve, fail: reject};
        writes.push(write);
        if (waiting.length) waiting.shift()(write);
        else available.push(write);
      });
    },
    nextWrite() {
      return available.length ? Promise.resolve(available.shift()) : new Promise(resolve => waiting.push(resolve));
    },
  };
}

function fixture({storedEntries = [], ...options} = {}) {
  let now = 0, nextTimer = 0;
  const timers = new Map(), stored = new Map(storedEntries), writes = [], changes = [];
  const scheduler = {
    setTimeout(callback, delay) {
      const id = ++nextTimer;
      timers.set(id, {at: now + delay, callback});
      return id;
    },
    clearTimeout(id) { timers.delete(id); },
  };
  const storage = {
    getItem: key => stored.get(key) ?? null,
    setItem: (key, value) => stored.set(key, value),
    removeItem: key => stored.delete(key),
  };
  const editor = createReviewEditor({
    caseNames: ['case-a', 'case-b', 'case-c'], reviews: {},
    runId: 'run', reviewIdentity: 'report-identity', storage, scheduler,
    persistReview: async payload => { writes.push(payload); },
    onChange: state => changes.push(state), ...options,
  });
  return {
    editor, stored, writes, changes,
    advance(milliseconds) {
      now += milliseconds;
      for (const [id, timer] of timers) {
        if (timer.at <= now) { timers.delete(id); timer.callback(); }
      }
    },
  };
}

test('note edits back up immediately and save after 350 milliseconds without another edit', async () => {
  const {editor, stored, writes, advance} = fixture();
  assert.equal(editor.state.selectedCase, 'case-a');
  assert.deepEqual(editor.state.reviews['case-a'], {verdict: null, note: ''});
  assert.equal(editor.state.canUndo, false);
  editor.editNote('First thought');
  assert.deepEqual(JSON.parse(stored.get(draftKey)), {
    review_identity: 'report-identity',
    reviews: {'case-a': {verdict: null, note: 'First thought'}},
  });
  advance(349);
  assert.deepEqual(writes, []);
  editor.editNote('The complete thought');
  advance(349);
  assert.deepEqual(writes, []);
  advance(1);
  await Promise.resolve();
  assert.deepEqual(writes, [{
    name: 'case-a', review: {verdict: null, note: 'The complete thought'},
    review_identity: 'report-identity',
  }]);
  await editor.flush();
  assert.equal(editor.state.pendingDraftCount, 0);
  assert.equal(editor.state.saveStatus, 'Saved to review file');
  assert.equal(stored.has(draftKey), false);
});

test('verdicts flush immediately, clear keeps the note, and unchanged reviews add no Undo', async () => {
  const {editor, writes, advance} = fixture();
  editor.editNote('');
  await editor.setVerdict(null);
  assert.equal(editor.state.canUndo, false);
  assert.deepEqual(writes, []);
  editor.editNote('Keep this explanation');
  await editor.setVerdict('fail');
  assert.deepEqual(writes.at(-1).review, {verdict: 'fail', note: 'Keep this explanation'});
  await editor.setVerdict(null);
  await editor.setVerdict(null);
  assert.deepEqual(writes.at(-1).review, {verdict: null, note: 'Keep this explanation'});
  await editor.undo();
  assert.deepEqual(editor.state.reviews['case-a'], {verdict: 'fail', note: 'Keep this explanation'});
  await editor.undo();
  assert.deepEqual(writes.at(-1).review, {verdict: null, note: 'Keep this explanation'});
  await editor.undo();
  assert.deepEqual(writes.at(-1).review, {verdict: null, note: ''});
  assert.equal(editor.state.canUndo, false);
  const savedCount = writes.length;
  advance(350);
  await editor.flush();
  assert.equal(writes.length, savedCount);
});

test('relative navigation preserves each action and uses selection and filter membership at execution', async () => {
  const persistence = controlledPersistence();
  const {editor, changes} = fixture(persistence);
  let matching = ['case-a', 'case-b', 'case-c'];
  editor.editNote('Save before moving');
  const first = editor.navigate(1, () => matching);
  const second = editor.navigate(1, () => matching);
  const write = await persistence.nextWrite();
  assert.equal(editor.state.selectedCase, 'case-a');
  matching = ['case-a', 'case-c'];
  write.succeed();
  assert.equal(await first, true);
  assert.equal(await second, true);
  assert.equal(editor.state.selectedCase, 'case-c');
  assert.equal(changes.some(state => state.selectedCase === 'case-b'), true);
  assert.deepEqual(write.payload.review, {verdict: null, note: 'Save before moving'});
  assert.equal(await editor.selectCase('case-a'), true);
  matching = ['case-a', 'case-b', 'case-c'];
  await Promise.all([editor.navigate(1, () => matching), editor.navigate(1, () => matching)]);
  assert.equal(editor.state.selectedCase, 'case-c');
  editor.editNote('Save on the last case');
  const final = editor.navigate(1, () => matching);
  const lastWrite = await persistence.nextWrite();
  assert.equal(editor.state.selectedCase, 'case-c');
  lastWrite.succeed();
  assert.equal(await final, true);
  assert.equal(lastWrite.payload.review.note, 'Save on the last case');
  await editor.navigate(-1, () => matching);
  assert.equal(editor.state.selectedCase, 'case-b');
});

test('Undo selects its case immediately, invalidates earlier navigation, and still saves across cases', async () => {
  const persistence = controlledPersistence();
  const {editor} = fixture(persistence);
  const verdict = editor.setVerdict('pass');
  (await persistence.nextWrite()).succeed();
  await verdict;
  await editor.selectCase('case-b');
  editor.editNote('Undo this pending edit');
  const previous = editor.navigate(-1, () => ['case-a', 'case-b', 'case-c']);
  const oldWrite = await persistence.nextWrite();
  const absolute = editor.selectCase('case-c');
  const restored = editor.undo();
  assert.equal(editor.state.selectedCase, 'case-b');
  assert.equal(editor.state.reviews['case-b'].note, '');
  assert.equal(persistence.writes.length, 2);
  oldWrite.succeed();
  const undoWrite = await persistence.nextWrite();
  assert.equal(editor.state.selectedCase, 'case-b');
  assert.deepEqual(undoWrite.payload.review, {verdict: null, note: ''});
  undoWrite.succeed();
  assert.equal(await restored, true);
  assert.equal(await previous, false);
  assert.equal(await absolute, false);
  assert.equal(editor.state.selectedCase, 'case-b');
  await editor.selectCase('case-c');
  const acrossCases = editor.undo();
  assert.equal(editor.state.selectedCase, 'case-a');
  const original = await persistence.nextWrite();
  assert.equal(original.payload.name, 'case-a');
  assert.deepEqual(original.payload.review, {verdict: null, note: ''});
  original.succeed();
  await acrossCases;
  assert.equal(editor.state.canUndo, false);
  await editor.navigate(1, () => ['case-a', 'case-b', 'case-c']);
  assert.equal(editor.state.selectedCase, 'case-b');
});

for (const status of [503, 409]) {
  test(`a ${status} save failure retains selection and drafts until explicit retry`, async () => {
    const persistence = controlledPersistence();
    const {editor, stored} = fixture(persistence);
    editor.editNote('Keep my review');
    const moving = editor.selectCase('case-b');
    (await persistence.nextWrite()).fail(Object.assign(new Error(`Save failed: ${status}`), {status}));
    assert.equal(await moving, false);
    assert.equal(editor.state.selectedCase, 'case-a');
    assert.equal(editor.state.reviews['case-a'].note, 'Keep my review');
    assert.equal(editor.state.pendingDraftCount, 1);
    assert.equal(JSON.parse(stored.get(draftKey)).reviews['case-a'].note, 'Keep my review');
    assert.match(editor.state.saveStatus, /case-a: .*Edits kept in this browser.*Use Save \/ retry/);
    if (status === 409) assert.match(editor.state.saveStatus, /report changed\. Reload to review the current report/);
    const retry = editor.flush();
    (await persistence.nextWrite()).succeed();
    assert.equal(await retry, true);
    assert.equal(editor.state.pendingDraftCount, 0);
    assert.equal(editor.state.saveStatus, 'Saved to review file');
    assert.equal(stored.has(draftKey), false);
    assert.equal(await editor.selectCase('case-b'), true);
  });
}

test('concurrent flushes share writes and include edits made before the last write completes', async () => {
  const persistence = controlledPersistence();
  const {editor, stored, changes} = fixture(persistence);
  editor.editNote('Older note');
  const firstFlush = editor.flush(), repeatedFlush = editor.flush();
  let finished = false;
  firstFlush.then(() => { finished = true; });
  const firstWrite = await persistence.nextWrite();
  assert.equal(persistence.writes.length, 1);
  editor.editNote('Newer note');
  const afterEdit = changes.length;
  const thirdFlush = editor.flush();
  assert.equal(persistence.writes.length, 1);
  firstWrite.succeed();
  const secondWrite = await persistence.nextWrite();
  assert.equal(finished, false);
  assert.equal(editor.state.pendingDraftCount, 1);
  assert.equal(JSON.parse(stored.get(draftKey)).reviews['case-a'].note, 'Newer note');
  assert.equal(changes.slice(afterEdit).some(state => state.saveStatus === 'Saved to review file'), false);
  assert.deepEqual(secondWrite.payload.review, {verdict: null, note: 'Newer note'});
  editor.editNote('Edit during the second write');
  secondWrite.succeed();
  const thirdWrite = await persistence.nextWrite();
  assert.equal(finished, false);
  assert.equal(thirdWrite.payload.review.note, 'Edit during the second write');
  thirdWrite.succeed();
  assert.deepEqual(await Promise.all([firstFlush, repeatedFlush, thirdFlush]), [true, true, true]);
  assert.equal(persistence.writes.length, 3);
  assert.equal(editor.state.pendingDraftCount, 0);
});

test('an older failed write cannot replace a newer draft or its visible status', async () => {
  const persistence = controlledPersistence();
  const {editor, stored} = fixture(persistence);
  editor.editNote('Old note');
  const leaving = editor.flush();
  const oldWrite = await persistence.nextWrite();
  editor.editNote('Current note');
  const currentStatus = editor.state.saveStatus;
  oldWrite.fail(new Error('Save failed: offline'));
  assert.equal(await leaving, false);
  assert.equal(editor.state.saveStatus, currentStatus);
  assert.equal(editor.state.reviews['case-a'].note, 'Current note');
  assert.equal(JSON.parse(stored.get(draftKey)).reviews['case-a'].note, 'Current note');
  const retry = editor.flush();
  const currentWrite = await persistence.nextWrite();
  assert.equal(currentWrite.payload.review.note, 'Current note');
  currentWrite.succeed();
  assert.equal(await retry, true);
});

test('same-report valid known drafts recover on load and retry in order without touching other keys', async () => {
  const persistence = controlledPersistence();
  const {editor, stored} = fixture({
    ...persistence,
    caseNames: ['case-a', 'case-b', 'case-c', 'case-d'],
    reviews: {'case-c': {verdict: 'pass', note: 'Already saved'}},
    storedEntries: [
      ['chat-review-drafts:run', 'legacy draft'],
      ['chat-review-drafts:run:another-report', 'other report draft'],
      [draftKey, JSON.stringify({review_identity: 'report-identity', reviews: {
        'case-a': {verdict: null, note: 'Recovered note'},
        'case-b': {verdict: 'defer', note: 'Recovered verdict'},
        'case-c': {verdict: 'invalid', note: 'Ignore this'},
        'case-d': {verdict: 'pass', note: 4},
        'unknown-case': {verdict: 'fail', note: 'Ignore unknown case'},
      }})],
    ],
  });
  assert.equal(editor.state.pendingDraftCount, 2);
  assert.equal(editor.state.canUndo, false);
  assert.deepEqual(editor.state.reviews['case-c'], {verdict: 'pass', note: 'Already saved'});
  assert.deepEqual(editor.state.reviews['case-d'], {verdict: null, note: ''});
  const first = await persistence.nextWrite();
  assert.equal(first.payload.name, 'case-a');
  assert.equal(first.payload.review.note, 'Recovered note');
  assert.equal(persistence.writes.length, 1);
  first.succeed();
  const second = await persistence.nextWrite();
  assert.equal(second.payload.name, 'case-b');
  assert.deepEqual(second.payload.review, {verdict: 'defer', note: 'Recovered verdict'});
  second.succeed();
  await editor.flush();
  assert.deepEqual([...stored], [
    ['chat-review-drafts:run', 'legacy draft'],
    ['chat-review-drafts:run:another-report', 'other report draft'],
  ]);
});

test('storage failures retain edits, keep-open guidance and an unload warning until the review file saves', async () => {
  const persistence = controlledPersistence();
  const unavailable = () => { throw new Error('Storage unavailable'); };
  const {editor} = fixture({
    ...persistence,
    storage: {getItem: unavailable, setItem: unavailable, removeItem: unavailable},
  });
  assert.equal(editor.state.shouldWarnOnUnload, false);
  editor.editNote('Only in memory');
  assert.equal(editor.state.reviews['case-a'].note, 'Only in memory');
  assert.equal(editor.state.shouldWarnOnUnload, true);
  assert.match(editor.state.saveStatus, /Keep this page open/);
  assert.equal(editor.prepareForUnload(), true);
  const saving = editor.flush();
  const failed = await persistence.nextWrite();
  assert.match(editor.state.saveStatus, /Keep this page open/);
  assert.equal(editor.prepareForUnload(), true);
  failed.fail(new Error('Save failed: offline'));
  assert.equal(await saving, false);
  assert.match(editor.state.saveStatus, /Keep this page open/);
  const retry = editor.flush();
  (await persistence.nextWrite()).succeed();
  assert.equal(await retry, true);
  assert.equal(editor.state.shouldWarnOnUnload, false);
  assert.equal(editor.prepareForUnload(), false);
  assert.equal(editor.state.saveStatus, 'Saved to review file');
});

for (const stored of [
  'invalid json', 'null', '[]',
  JSON.stringify({review_identity: 'another-report', reviews: {'case-a': {verdict: 'fail', note: 'Wrong report'}}}),
  JSON.stringify({review_identity: 'report-identity', reviews: {'case-a': null, 'case-b': {note: 'Missing verdict'}}}),
]) {
  test(`recovery ignores malformed or mismatched drafts: ${stored}`, async () => {
    const {editor, writes} = fixture({storedEntries: [[draftKey, stored]]});
    assert.equal(editor.state.pendingDraftCount, 0);
    assert.deepEqual(editor.state.reviews['case-a'], {verdict: null, note: ''});
    await editor.flush();
    assert.deepEqual(writes, []);
  });
}

test('observable state and constructor inputs cannot mutate the editor reviews or selection', async () => {
  const caseNames = ['case-a', 'case-b'];
  const reviews = {'case-a': {verdict: 'defer', note: 'Loaded note'}};
  const {editor, changes, writes} = fixture({caseNames, reviews});
  caseNames.reverse();
  reviews['case-a'].note = 'Changed externally';
  const snapshot = editor.state;
  snapshot.selectedCase = 'case-b';
  snapshot.reviews['case-a'].verdict = 'pass';
  editor.editNote('Reviewer edit');
  changes.at(-1).reviews['case-a'].note = 'Changed notification';
  await editor.flush();
  assert.equal(editor.state.selectedCase, 'case-a');
  assert.deepEqual(writes[0].review, {verdict: 'defer', note: 'Reviewer edit'});
  assert.deepEqual(snapshot.reviews['case-a'], {verdict: 'pass', note: 'Loaded note'});
});

test('before-unload backs up synchronously and reports a new storage failure', async () => {
  let failStorage = false;
  const stored = new Map();
  const {editor} = fixture({storage: {
    getItem: key => stored.get(key),
    setItem(key, value) {
      if (failStorage) throw new Error('Quota exceeded');
      stored.set(key, value);
    },
    removeItem: key => stored.delete(key),
  }});
  editor.editNote('Backup on unload');
  stored.clear();
  assert.equal(editor.prepareForUnload(), false);
  assert.equal(JSON.parse(stored.get(draftKey)).reviews['case-a'].note, 'Backup on unload');
  failStorage = true;
  assert.equal(editor.prepareForUnload(), true);
  assert.equal(editor.state.shouldWarnOnUnload, true);
  assert.match(editor.state.saveStatus, /Keep this page open/);
  await editor.flush();
  assert.equal(editor.prepareForUnload(), false);
});

test('empty reports allow save and unload without editing errors', async () => {
  const {editor, writes} = fixture({caseNames: []});
  editor.editNote('Nothing selected');
  assert.equal(await editor.setVerdict('pass'), true);
  assert.equal(await editor.undo(), true);
  assert.equal(await editor.navigate(1, () => []), true);
  assert.equal(await editor.flush(), true);
  assert.equal(editor.prepareForUnload(), false);
  assert.equal(editor.state.selectedCase, null);
  assert.equal(editor.state.pendingDraftCount, 0);
  assert.equal(editor.state.canUndo, false);
  assert.deepEqual(writes, []);
});

test('a malformed reviews envelope cannot recover an array element as a named case', async () => {
  const {editor, writes} = fixture({
    caseNames: ['0'],
    storedEntries: [[draftKey, JSON.stringify({
      review_identity: 'report-identity', reviews: [{verdict: 'fail', note: 'Malformed envelope'}],
    })]],
  });
  assert.deepEqual(editor.state.reviews['0'], {verdict: null, note: ''});
  await editor.flush();
  assert.deepEqual(writes, []);
});

test('leaving stays pending for edits during a save and fails when their write fails', async () => {
  const persistence = controlledPersistence();
  const {editor, stored} = fixture(persistence);
  editor.editNote('First edit');
  const leaving = editor.flush();
  let departureAllowed = false;
  leaving.then(saved => { departureAllowed = saved; });
  const firstWrite = await persistence.nextWrite();
  editor.editNote('Edit before leaving');
  firstWrite.succeed();
  const latestWrite = await persistence.nextWrite();
  assert.equal(departureAllowed, false);
  latestWrite.fail(new Error('Save failed: disconnected'));
  assert.equal(await leaving, false);
  assert.equal(departureAllowed, false);
  assert.equal(editor.state.selectedCase, 'case-a');
  assert.equal(JSON.parse(stored.get(draftKey)).reviews['case-a'].note, 'Edit before leaving');
});

test('Undo still saves its restored value when the superseded write fails', async () => {
  const persistence = controlledPersistence();
  const {editor} = fixture(persistence);
  editor.editNote('Undo after an offline save');
  const navigation = editor.selectCase('case-c');
  const firstWrite = await persistence.nextWrite();
  const undo = editor.undo();
  firstWrite.fail(new Error('Save failed: disconnected'));
  const restoredWrite = await persistence.nextWrite();
  assert.equal(editor.state.selectedCase, 'case-a');
  assert.equal(editor.state.saveStatus, 'Saving to review file…');
  assert.deepEqual(restoredWrite.payload.review, {verdict: null, note: ''});
  restoredWrite.succeed();
  assert.equal(await navigation, false);
  assert.equal(await undo, true);
  assert.equal(editor.state.pendingDraftCount, 0);
  assert.equal(editor.state.saveStatus, 'Saved to review file');
});

test('absolute selection keeps its requested destination behind an earlier move', async () => {
  const persistence = controlledPersistence();
  const {editor} = fixture(persistence);
  editor.editNote('Finish before selecting');
  const next = editor.navigate(1, () => ['case-a', 'case-b', 'case-c']);
  const pendingWrite = await persistence.nextWrite();
  const selected = editor.selectCase('case-a');
  pendingWrite.succeed();
  assert.equal(await next, true);
  assert.equal(await selected, true);
  assert.equal(editor.state.selectedCase, 'case-a');
});
