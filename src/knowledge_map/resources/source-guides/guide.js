'use strict';

const form = document.querySelector('#question-form');
const question = document.querySelector('#question');
const progress = document.querySelector('#progress');
const guideView = document.querySelector('#guide');
const articles = document.querySelector('#articles');
const submit = document.querySelector('#submit');
const edit = document.querySelector('#edit');
const newQuestion = document.querySelector('#new');
const guideList = document.querySelector('#guide-list');
const savedStatus = document.querySelector('#saved-status');
let currentGuide = null;
let guideSelection = 0;
let listRequest = 0;
let savedRevision = '';

const outcomeLabels = {
  completed: 'Articles to read',
  empty: 'No relevant articles were selected from this search.',
  declined: 'This question is outside the question policy.',
  needs_edit: 'Edit your complete question to continue.',
  assessment_failed: 'The question could not be assessed.',
  retrieval_failed: 'The search could not be completed.',
  assembly_failed: 'The retrieved material could not be prepared.',
  guidance_failed: 'Reading directions could not be prepared.',
  running: 'Searching for relevant reporting…',
  cancelled: 'This search was cancelled.',
  interrupted: 'This search was interrupted before it finished.',
};

const attemptLabels = {
  running: 'Running', completed: 'Completed', empty: 'Empty', failed: 'Failed',
  cancelled: 'Cancelled', interrupted: 'Interrupted',
};
const displayDate = value => new Date(value).toLocaleString();

function guideOutcome(guide) {
  const assessment = guide.assessment?.status;
  if (assessment === 'declined') return 'Declined';
  if (assessment === 'needs_edit') return 'Needs editing';
  const state = attemptLabels[guide.latest_attempt.status];
  return assessment === 'deferred' ? `Deferred · ${state}` : state;
}

async function loadSavedGuides() {
  const request = ++listRequest;
  try {
    const response = await fetch('/api/guides');
    if (!response.ok) throw new Error('Listing failed');
    const {guides} = await response.json();
    if (request !== listRequest) return;
    savedStatus.textContent = guides.length ? '' : 'No saved questions yet.';
    const revision = JSON.stringify(guides);
    if (revision === savedRevision) return;
    savedRevision = revision;
    guideList.replaceChildren();
    for (const guide of guides) {
      const row = document.createElement('li');
      const link = document.createElement('a');
      link.href = `#guide=${encodeURIComponent(guide.guide_id)}`;
      link.textContent = guide.question;
      const status = document.createElement('p');
      status.className = 'metadata';
      status.textContent = `${guideOutcome(guide)} · Saved ${displayDate(guide.created_at)}`;
      row.append(link, status);
      guideList.append(row);
    }
  } catch {
    if (request !== listRequest) return;
    savedStatus.textContent = 'Saved guides could not be loaded. Reload to try again.';
  }
}

async function readSavedGuide(identity) {
  const response = await fetch(`/api/guides/${encodeURIComponent(identity)}`);
  if (!response.ok) throw new Error('Guide unavailable');
  return response.json();
}

async function refreshGuides() {
  await loadSavedGuides();
  const selected = currentGuide;
  const selection = guideSelection;
  if (selected?.latest_attempt.status === 'running') {
    try {
      const guide = await readSavedGuide(selected.guide_id);
      if (selection === guideSelection) {
        showGuide(guide);
        progress.textContent = '';
      }
    } catch {
      if (selection === guideSelection) {
        progress.textContent = 'Search status is unavailable. Reconnecting to the local service…';
      }
    }
  }
  window.setTimeout(refreshGuides, 1000);
}

async function openSelectedGuide() {
  const selection = ++guideSelection;
  const identity = new URLSearchParams(location.hash.slice(1)).get('guide');
  if (!identity) {
    clearQuestion();
    return;
  }
  currentGuide = null;
  guideView.hidden = true;
  question.value = '';
  progress.textContent = 'Opening saved guide…';
  try {
    const guide = await readSavedGuide(identity);
    if (selection !== guideSelection) return;
    showGuide(guide);
    progress.textContent = '';
  } catch {
    if (selection !== guideSelection) return;
    progress.textContent = 'This saved guide could not be opened.';
  }
}

function showGuide(guide) {
  currentGuide = guide;
  document.querySelector('#guide-question').textContent = guide.question;
  document.querySelector('#outcome').textContent = outcomeLabels[guide.status];
  document.querySelector('#message').textContent = guide.message || '';
  document.querySelector('#guide-created').textContent = `Saved ${displayDate(guide.created_at)}`;
  document.querySelector('#guide-retrieved').textContent = guide.last_retrieved_at
    ? `Last retrieved ${displayDate(guide.last_retrieved_at)}` : 'No successful retrieval yet.';
  const attempt = guide.latest_attempt;
  document.querySelector('#guide-attempt').textContent =
    `Latest attempt: ${guideOutcome(guide)}. Started ${displayDate(attempt.started_at)}` +
    (attempt.finished_at ? `. Finished ${displayDate(attempt.finished_at)}` : '');
  articles.replaceChildren();
  for (const article of guide.articles) {
    const row = document.createElement('li');
    const link = document.createElement('a');
    link.textContent = article.citation.title;
    const url = new URL(article.citation.url);
    if (url.protocol === 'https:' || url.protocol === 'http:') {
      link.href = url.href;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
    }
    row.append(link);
    if (article.citation.published_date) {
      const date = document.createElement('p');
      date.className = 'metadata';
      date.textContent = `Published ${article.citation.published_date}`;
      row.append(date);
    }
    const direction = document.createElement('p');
    direction.textContent = article.reading_direction;
    row.append(direction);
    articles.append(row);
  }
  guideView.hidden = false;
}

function setBusy(busy) {
  form.setAttribute('aria-busy', String(busy));
  submit.disabled = busy;
  question.disabled = busy;
}

form.addEventListener('submit', async event => {
  event.preventDefault();
  const text = question.value.trim();
  if (!text) return;
  const selection = ++guideSelection;
  currentGuide = null;
  setBusy(true);
  guideView.hidden = true;
  progress.textContent = 'Saving your question…';
  try {
    const response = await fetch('/api/questions', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({question: text}),
    });
    if (!response.ok) throw new Error('Submission failed');
    const guide = await response.json();
    if (selection === guideSelection) {
      showGuide(guide);
      history.pushState(null, '', `#guide=${encodeURIComponent(guide.guide_id)}`);
      progress.textContent = '';
    }
    await loadSavedGuides();
  } catch {
    if (selection === guideSelection) {
      progress.textContent = 'The submission could not be confirmed. Check Saved guides before submitting again.';
    }
  } finally {
    setBusy(false);
  }
});

edit.addEventListener('click', () => {
  if (!currentGuide) return;
  question.value = currentGuide.question;
  question.focus();
});
function clearQuestion() {
  ++guideSelection;
  currentGuide = null;
  question.value = '';
  guideView.hidden = true;
  articles.replaceChildren();
  progress.textContent = '';
  question.focus();
}
newQuestion.addEventListener('click', () => {
  history.pushState(null, '', location.pathname);
  clearQuestion();
});

window.addEventListener('hashchange', openSelectedGuide);
refreshGuides();
openSelectedGuide();

fetch('/api/coverage').then(response => response.json()).then(coverage => {
  document.querySelector('#collections').textContent = coverage.entries.map(entry => {
    const dates = [entry.earliest_date, entry.latest_date].filter(Boolean).join(' to ');
    return dates ? `${entry.name}: published ${dates}` : entry.name;
  }).join(' · ');
}).catch(() => {});
