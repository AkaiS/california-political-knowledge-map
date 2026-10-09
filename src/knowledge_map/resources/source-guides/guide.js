'use strict';

const form = document.querySelector('#question-form');
const question = document.querySelector('#question');
const progress = document.querySelector('#progress');
const guideView = document.querySelector('#guide');
const articles = document.querySelector('#articles');
const viewDescription = document.querySelector('#view-description');
const articleOrder = document.querySelector('#article-order');
const submit = document.querySelector('#submit');
const edit = document.querySelector('#edit');
const update = document.querySelector('#update');
const cancel = document.querySelector('#cancel');
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
  const assessment = guide.latest_attempt.assessment?.status;
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
  const sameGuide = currentGuide?.guide_id === guide.guide_id;
  const newReading = !sameGuide || currentGuide?.last_retrieved_at !== guide.last_retrieved_at;
  currentGuide = guide;
  document.querySelector('#guide-question').textContent = guide.question;
  document.querySelector('#outcome').textContent = outcomeLabels[guide.status];
  document.querySelector('#message').textContent = guide.message === outcomeLabels[guide.status]
    ? '' : guide.message || '';
  document.querySelector('#message').hidden = Boolean(guide.disclosures?.length);
  renderDisclosures(document.querySelector('#disclosures'), guide.disclosures);
  document.querySelector('#guide-created').textContent = `Saved ${displayDate(guide.created_at)}`;
  document.querySelector('#guide-retrieved').textContent = guide.last_retrieved_at
    ? `Last retrieved ${displayDate(guide.last_retrieved_at)}` : 'No successful retrieval yet.';
  const attempt = guide.latest_attempt;
  const retainedReading = guide.last_retrieved_at && guide.last_retrieved_at !== attempt.finished_at;
  renderDisclosures(document.querySelector('#attempt-disclosures'), retainedReading ? attempt.disclosures : []);
  if (!sameGuide) document.querySelector('#search-details').open = false;
  renderSearchDetails(document.querySelector('#content-search-details'), guide.search_details,
    retainedReading ? 'Saved reading' : 'This search');
  const attemptDetails = document.querySelector('#attempt-search-details');
  attemptDetails.replaceChildren();
  if (retainedReading) renderSearchDetails(attemptDetails, attempt.search_details, 'Latest attempt');
  update.textContent = ['failed', 'interrupted'].includes(attempt.status) ? 'Retry' : 'Update guide';
  update.disabled = attempt.status === 'running';
  cancel.hidden = attempt.status !== 'running';
  cancel.disabled = false;
  document.querySelector('#guide-attempt').textContent =
    `Latest attempt: ${guideOutcome(guide)}. Started ${displayDate(attempt.started_at)}` +
    (attempt.finished_at ? `. Finished ${displayDate(attempt.finished_at)}` : '');
  document.querySelector('#attempt-message').textContent = guide.last_retrieved_at
    ? (attempt.status === 'running'
      ? 'Updating this guide. Saved reading remains available below.'
      : ['failed', 'interrupted'].includes(attempt.status)
        ? `${attempt.disclosures?.length ? '' : attempt.message || outcomeLabels[attempt.outcome]} Saved reading below is from the last successful retrieval.`
        : attempt.outcome !== guide.status ? attempt.message || outcomeLabels[attempt.outcome] : '')
    : '';
  const previousOrder = articleOrder.value;
  articleOrder.replaceChildren();
  const addOption = (value, label) => {
    const option = document.createElement('option');
    option.value = value;
    option.textContent = label;
    articleOrder.append(option);
  };
  addOption('relevance', 'All articles by relevance');
  const chronological = ['publication_asc', 'publication_desc'].includes(guide.assessment?.reading_order);
  if (chronological) addOption('requested', 'Requested publication order');
  for (const [index, group] of (guide.groups || []).entries()) {
    addOption(`group:${index}`, group.label);
  }
  const eventTimeline = (guide.groups || []).findIndex(group =>
    group.kind === 'timeline' && group.order === guide.assessment?.reading_order);
  articleOrder.value = newReading
    ? chronological ? 'requested' : eventTimeline >= 0 ? `group:${eventTimeline}` : 'relevance'
    : previousOrder;
  document.querySelector('#all-articles-heading').hidden = !guide.articles.length;
  renderArticles();
  guideView.hidden = false;
}

function renderDisclosures(container, disclosures = []) {
  container.replaceChildren();
  for (const disclosure of disclosures) {
    const row = document.createElement('li');
    if (disclosure.kind === 'unmatched_request') {
      const portion = document.createElement('strong');
      portion.textContent = `Unmatched part of your question: ${disclosure.request_portion}`;
      row.append(portion);
    } else if (disclosure.kind === 'deferred') {
      const label = document.createElement('strong');
      label.textContent = 'Deferred coverage';
      row.append(label);
    }
    const message = document.createElement('p');
    message.textContent = disclosure.message;
    row.append(message);
    container.append(row);
  }
  container.hidden = !container.children.length;
}

function collectionLabel(entry) {
  const basis = entry.date_basis === 'event_date' ? 'event dates' : 'publication dates';
  const dates = entry.earliest_date && entry.latest_date
    ? `${entry.earliest_date} to ${entry.latest_date}`
    : entry.earliest_date ? `from ${entry.earliest_date}`
      : entry.latest_date ? `through ${entry.latest_date}` : 'unavailable';
  return `${entry.name}: ${basis} ${dates}`;
}

function renderSearchDetails(container, details, label) {
  container.replaceChildren();
  const title = document.createElement('h4');
  title.textContent = label;
  container.append(title);
  const add = text => {
    const paragraph = document.createElement('p');
    paragraph.textContent = text;
    container.append(paragraph);
  };
  if (!details) {
    add('Search limits were not recorded for this saved guide.');
    return;
  }
  add(details.collections.length
    ? `Collections: ${details.collections.map(collectionLabel).join(' · ')}`
    : 'Collection dates were not recorded for this search.');
  const completion = {
    running: 'Running', completed: 'Completed', partial: 'Partly failed', failed: 'Failed',
    not_searched: 'Not searched', cancelled: 'Cancelled', interrupted: 'Interrupted',
  };
  add(`Search completion: ${completion[details.completion]}.`);
  if (details.bounded_selection) add('Result limits: This search examines a limited selection of available reporting. It does not establish complete coverage. All articles with a supported reading direction are shown.');
  if (details.selection_limited) add('Some retrieved material was omitted before relevance review because the selection limit was reached.');
  if (['completed', 'partial'].includes(details.completion)) add(`Included articles: ${details.included_articles}.`);
}

const timelineLabels = {
  publication_asc: 'Publication order, oldest first. Publication dates do not establish event dates.',
  publication_desc: 'Publication order, newest first. Publication dates do not establish event dates.',
  event_asc: 'Reported event order, earliest first. Publication dates are shown separately. Undated reading follows.',
  event_desc: 'Reported event order, latest first. Publication dates are shown separately. Undated reading follows.',
};

function renderArticles() {
  articles.replaceChildren();
  const ordered = [...currentGuide.articles];
  const selectedIndex = articleOrder.value.startsWith('group:')
    ? Number(articleOrder.value.slice(6)) : -1;
  const selectedGroup = currentGuide.groups?.[selectedIndex];
  if (articleOrder.value === 'relevance' || selectedGroup) {
    const order = new Map((currentGuide.relevance_order || []).map((identity, index) => [identity, index]));
    ordered.sort((left, right) =>
      (order.get(left.citation.source_article_id) ?? 0) - (order.get(right.citation.source_article_id) ?? 0));
  }
  if (selectedGroup && ['publication_asc', 'publication_desc'].includes(selectedGroup.order)) {
    const newest = selectedGroup.order === 'publication_desc';
    const date = article => Date.parse(article.citation.published_date || '');
    ordered.sort((left, right) => {
      const leftDate = date(left), rightDate = date(right);
      if (Number.isNaN(leftDate)) return Number.isNaN(rightDate) ? 0 : 1;
      if (Number.isNaN(rightDate)) return -1;
      return newest ? rightDate - leftDate : leftDate - rightDate;
    });
  } else if (selectedGroup) {
    const order = new Map();
    for (const member of selectedGroup.members) {
      if (!order.has(member.source_article_id)) order.set(member.source_article_id, order.size);
    }
    ordered.sort((left, right) =>
      (order.get(left.citation.source_article_id) ?? Infinity) - (order.get(right.citation.source_article_id) ?? Infinity));
  }
  viewDescription.textContent = selectedGroup
    ? `${timelineLabels[selectedGroup.order] || 'Related articles appear first.'} Every included article remains available.`
    : articleOrder.value === 'requested'
      ? timelineLabels[currentGuide.assessment.reading_order]
      : 'Each article appears once. Reading directions and available highlights are listed beneath its link.';
  for (const article of ordered) articles.append(articleRow(article, selectedIndex));
}

articleOrder.addEventListener('change', renderArticles);

function articleRow(article, selectedIndex) {
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
  if (article.publication) {
    const publication = document.createElement('p');
    publication.className = 'metadata';
    publication.textContent = article.publication;
    row.append(publication);
  }
  if (article.citation.published_date) {
    const date = document.createElement('p');
    date.className = 'metadata';
    date.textContent = `Published ${article.citation.published_date}`;
    row.append(date);
  }
  const direction = document.createElement('p');
  direction.textContent = article.reading_direction;
  row.append(direction);
  const highlights = document.createElement('ul');
  highlights.className = 'section-links';
  highlights.setAttribute('aria-label', 'Relevant highlights');
  for (const [index, target] of (article.section_links || []).entries()) {
    const section = new URL(target);
    if (section.protocol !== 'https:' && section.protocol !== 'http:') continue;
    const item = document.createElement('li');
    const highlight = document.createElement('a');
    highlight.href = section.href;
    highlight.target = '_blank';
    highlight.rel = 'noopener noreferrer';
    highlight.textContent = `Relevant highlight ${index + 1}`;
    item.append(highlight);
    highlights.append(item);
  }
  if (highlights.children.length) row.append(highlights);
  const directions = document.createElement('ul');
  directions.className = 'reading-directions';
  for (const [index, group] of (currentGuide.groups || []).entries()) {
    for (const member of group.members) {
      if (member.source_article_id !== article.citation.source_article_id) continue;
      const item = document.createElement('li');
      if (index === selectedIndex) item.className = 'selected-direction';
      const label = document.createElement('strong');
      label.textContent = group.label;
      item.append(label);
      if (group.kind === 'timeline') {
        const basis = document.createElement('p');
        basis.className = 'metadata';
        basis.textContent = timelineLabels[group.order];
        item.append(basis);
      }
      if (member.reported_event_date) {
        const date = document.createElement('p');
        date.className = 'metadata';
        date.textContent = `Reported event date: ${member.reported_event_date}`;
        item.append(date);
      }
      const reading = document.createElement('p');
      reading.textContent = member.reading_direction;
      item.append(reading);
      directions.append(item);
    }
  }
  if (directions.children.length) row.append(directions);
  return row;
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

update.addEventListener('click', async () => {
  const selected = currentGuide;
  if (!selected || selected.latest_attempt.status === 'running') return;
  const selection = ++guideSelection;
  update.disabled = true;
  progress.textContent = 'Starting a search for this saved question…';
  try {
    const response = await fetch(`/api/guides/${encodeURIComponent(selected.guide_id)}/update`, {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}',
    });
    if (!response.ok && response.status !== 409) throw new Error('Update failed');
    const guide = response.status === 409
      ? await readSavedGuide(selected.guide_id) : await response.json();
    if (selection === guideSelection) {
      showGuide(guide);
      progress.textContent = response.status === 409
        ? 'This guide is already being searched. Wait for it to finish before searching again.' : '';
    }
    await loadSavedGuides();
  } catch {
    if (selection === guideSelection) {
      progress.textContent = 'The search could not be confirmed. Reopen this saved guide to check its status.';
    }
  } finally {
    if (selection === guideSelection) {
      update.disabled = currentGuide.latest_attempt.status === 'running';
    }
  }
});

cancel.addEventListener('click', async () => {
  const selected = currentGuide;
  if (!selected || selected.latest_attempt.status !== 'running') return;
  const selection = ++guideSelection;
  cancel.disabled = true;
  progress.textContent = 'Cancelling this search…';
  try {
    const response = await fetch(
      `/api/guides/${encodeURIComponent(selected.guide_id)}/attempts/${encodeURIComponent(selected.latest_attempt.attempt_id)}/cancel`,
      {method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}'},
    );
    if (!response.ok) throw new Error('Cancellation failed');
    const guide = await response.json();
    if (selection === guideSelection) {
      ++guideSelection;
      showGuide(guide);
      progress.textContent = guide.latest_attempt.status === 'cancelled'
        ? '' : 'The selected search is no longer running. Its saved outcome is shown below.';
    }
    await loadSavedGuides();
  } catch {
    if (selection === guideSelection) {
      progress.textContent = 'Cancellation could not be confirmed. Reopen this saved guide to check its status.';
    }
  } finally {
    if (selection === guideSelection) cancel.disabled = false;
  }
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
  document.querySelector('#collections').textContent = coverage.entries.length
    ? `Available collections: ${coverage.entries.map(collectionLabel).join(' · ')}`
    : 'Available collection dates are unavailable.';
}).catch(() => { document.querySelector('#collections').textContent = 'Available collection dates could not be loaded.'; });
