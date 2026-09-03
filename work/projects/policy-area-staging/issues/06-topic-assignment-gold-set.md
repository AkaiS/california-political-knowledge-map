# 06 — Topic Assignment Gold Set and evaluation task

Labels: completed

## Parent

[Policy Area Staging](../PRD.md)

## What to build

Assignment is measured rather than assumed. A second Gold Set of twenty
article-level cases joins the registry as its own task, over the same twenty
Stories as every other stage, so a run reports whether a model connects the right
measures to the right areas.

Each case is one Source Article together with the areas and the extracted
measures the stage is given, and its expectation is the set of measure-to-area
pairs the article supports. Scoring is on those pairs, with the measure named by
extraction's surface string — an article whose areas are right but whose bills
are mismatched cannot score as a pass.

The set is silver, labeled by `claude-opus-5` against its own written annotation
guideline, with each case naming that guideline in its metadata. Because a case
can only name measures that actually exist, its loading test checks that too:
every measure a case names is one the extraction Silver Set or the article itself
contains, so a case cannot ask for an assignment the stage could never make.

## Acceptance criteria

- [x] An annotation guideline for Topic Assignment is written and lives beside
      the other guidelines.
- [x] A Gold Set file holds twenty article-level cases over the same twenty
      Stories as the classification set, with held-out and training splits and
      silver metadata naming the annotator model and the guideline.
- [x] The task is registered with its own input, output, and metadata types and
      the assignment adapter as the callable under test.
- [x] Evaluators score precision, recall, and F1 over measure-to-area pairs; a
      case expecting no pairs and returning none scores a pass.
- [x] A test loads the Gold Set through the registered task's own types and
      asserts the case count, the splits, ids that address a Source Article, and
      that every measure a case names is one the extraction Silver Set or the
      article contains.

## Blocked by

- [04 — Topic Assignment, measures to areas](04-topic-assignment-stage.md)
