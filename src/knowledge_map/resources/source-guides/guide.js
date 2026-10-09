'use strict';

const form = document.querySelector('#question-form');
const question = document.querySelector('#question');
const progress = document.querySelector('#progress');
const guideView = document.querySelector('#guide');
const articles = document.querySelector('#articles');
const submit = document.querySelector('#submit');
const edit = document.querySelector('#edit');
const newQuestion = document.querySelector('#new');
let currentGuide = null;

const outcomeLabels = {
  completed: 'Articles to read',
  empty: 'No relevant articles were selected from this search.',
  declined: 'This question is outside the question policy.',
  needs_edit: 'Edit your complete question to continue.',
  assessment_failed: 'The question could not be assessed.',
  retrieval_failed: 'The search could not be completed.',
  assembly_failed: 'The retrieved material could not be prepared.',
  guidance_failed: 'Reading directions could not be prepared.',
};

function showGuide(guide) {
  currentGuide = guide;
  document.querySelector('#guide-question').textContent = guide.question;
  document.querySelector('#outcome').textContent = outcomeLabels[guide.status];
  document.querySelector('#message').textContent = guide.message || '';
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
  edit.disabled = busy;
  newQuestion.disabled = busy;
}

form.addEventListener('submit', async event => {
  event.preventDefault();
  const text = question.value.trim();
  if (!text) return;
  setBusy(true);
  guideView.hidden = true;
  progress.textContent = 'Searching for relevant reporting…';
  try {
    const response = await fetch('/api/questions', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({question: text}),
    });
    if (!response.ok) throw new Error('Submission failed');
    showGuide(await response.json());
    progress.textContent = '';
  } catch {
    progress.textContent = 'The question could not be completed. Try submitting it again.';
  } finally {
    setBusy(false);
  }
});

edit.addEventListener('click', () => {
  if (!currentGuide) return;
  question.value = currentGuide.question;
  question.focus();
});
newQuestion.addEventListener('click', () => {
  currentGuide = null;
  question.value = '';
  guideView.hidden = true;
  articles.replaceChildren();
  progress.textContent = '';
  question.focus();
});

fetch('/api/coverage').then(response => response.json()).then(coverage => {
  document.querySelector('#collections').textContent = coverage.entries.map(entry => {
    const dates = [entry.earliest_date, entry.latest_date].filter(Boolean).join(' to ');
    return dates ? `${entry.name}: published ${dates}` : entry.name;
  }).join(' · ');
}).catch(() => {});
