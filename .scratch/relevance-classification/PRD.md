Post-Extraction Relevance Classification & Silver-Standard Labeling

Status: ready-for-agent

## Parent

[Scraping Pipeline PRD](../PRD.md)

## Problem Statement

The developer has implemented a Logistic Regression classifier to replace the noisy, hard-to-tune keyword heuristics for California politics relevance. However, the classifier is untrained because there is no initial labeled dataset. The existing labeling tool only lets developers label `INCONCLUSIVE` articles, but since `INCONCLUSIVE` and `IRRELEVANT` cache entries are stored without their raw HTML, manually promoting them to `RELEVANT`/`PENDING` causes validation to crash with a `TypeError` due to missing raw HTML. Additionally, relevance classification is currently run *before* article extraction, which means the classifier evaluates raw and noisy HTML metadata instead of high-quality clean article text.

## Solution

Update the relevance classification pipeline to run *after* successful article extraction (validation). Implement a silver-standard LLM labeling agent using Pydantic AI that classifies successfully extracted clean text using dynamic gold-standard examples (human-labeled) from the database or high-quality static fallback examples if no human labels exist. Store all candidate HTML pages during discovery so that they are always available for extraction, and flag irrelevant articles in the database with status `'IRRELEVANT'` so they build the dataset but are ignored by the ingestion pipeline. Finally, extend the CLI labeling command with a `--review-all` option to allow auditing/labeling any cached article to seed the gold-standard dataset.

## User Stories

1. As a developer, I want all candidate article HTML pages to be cached during discovery, so that their HTML is always available for subsequent extraction and validation.
2. As a developer, I want relevance classification to occur on successfully extracted clean article body text, so that the LLM agent and Logistic Regression model evaluate high-quality content instead of noisy metadata.
3. As a developer, I want the LLM silver-standard labeling agent to use balanced few-shot examples (both relevant and irrelevant cases) from human-labeled database entries, so that its classifications are accurate and unbiased.
4. As a developer, I want the LLM agent to fall back to high-quality static examples when no human-labeled articles are in the database, so that the labeling pipeline works out-of-the-box.
5. As a developer, I want irrelevant validated articles to be stored in the stories database with `status = 'IRRELEVANT'`, so that they build a training dataset for the Logistic Regression model without polluting the Neo4j ingestion pipeline.
6. As a developer, I want to be able to review and label any machine-classified cached article using the CLI, so that I can quickly build a gold-standard training dataset.
7. As a developer, I want the database to track the source of relevance labels (e.g. human vs. machine/LLM), so that only gold-standard labels are used for few-shot prompts and model training.

## Implementation Decisions

- **Schema changes**: Add a `relevance_label_source` column to the `scraped_html_cache` table, using an enum constraint ('KEYWORD', 'LLM', 'HUMAN', 'MODEL') and defaulting to 'KEYWORD'. Implement a database migration to add this column to existing databases.
- **Discovery adjustments**: Change the discovery service to cache the raw HTML for all candidate URLs passing discovery filters, setting `validation = 'PENDING'` and `relevance_status = 'PENDING'`.
- **Validation & Extraction pipeline**: Make validation async. If selector validation succeeds, run the relevance classifier on the clean extracted title and body. Save the story to the database, setting `status = 'UNPROCESSED'` for relevant and `status = 'IRRELEVANT'` for irrelevant stories. Update `scraped_html_cache` with the relevance outcome and the label source (`'LLM'` or `'MODEL'`).
- **LLM Silver-Standard Agent**: Implement an async LLM agent using Pydantic AI. Query up to 3 gold-standard examples for both `RELEVANT` and `IRRELEVANT` classes separately. If none are found, use a static default set of examples in the system prompt.
- **CLI Updates**: Asynchronously run the validation pipeline in `update-sources`. Extend the `ca-map classifier label` CLI command with a `--review-all` flag to query all cached articles where `relevance_label_source != 'HUMAN'`, updating them with `relevance_label_source = 'HUMAN'` when manually labeled.

## Testing Decisions

- Validate database migration and column constraints for `relevance_label_source`.
- Verify that `get_gold_standard_examples` retrieves a balanced class list.
- Mock the LLM agent to test the post-extraction classification flow, ensuring that relevant articles get saved with status `'UNPROCESSED'` and irrelevant articles with status `'IRRELEVANT'`.
- Verify that the ingestion pipeline does not pull `'IRRELEVANT'` stories.

## Out of Scope

- Automatically running the logistic regression trainer (it remains a manual CLI command run on demand).
- Fine-tuning the embeddings adapter.

## Further Notes

None.
