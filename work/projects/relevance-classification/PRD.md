Post-Extraction Relevance Classification & Silver-Standard Labeling

Labels: completed

## Parent

[Scraping Pipeline PRD](../scraping-pipeline/PRD.md)

## Problem Statement

The developer has implemented a Logistic Regression classifier to replace the noisy, hard-to-tune keyword heuristics for California politics relevance. However, the classifier is untrained because there is no initial labeled dataset. The existing labeling tool only lets developers label `INCONCLUSIVE` articles, but since `INCONCLUSIVE` and `IRRELEVANT` cache entries are stored without their raw HTML, manually promoting them to `RELEVANT`/`PENDING` causes validation to crash with a `TypeError` due to missing raw HTML. Relevance decisions must occur after extraction so an LLM fallback can use the clean article text, while the logistic model intentionally uses the consistently available headline/description metadata representation.

## Solution

Update the relevance classification pipeline to run *after* successful article extraction (validation). Implement a silver-standard LLM labeling agent using Pydantic AI that classifies extracted clean text and uses dynamic human-labeled examples when available; otherwise it operates zero-shot. The Logistic Regression model deliberately uses headline/description metadata embeddings so discovery, manual labeling, and validation share one representation. Store all candidate HTML pages during discovery so that they are always available for extraction, and flag irrelevant articles in the database with status `'IRRELEVANT'` so they build the dataset but are ignored by the ingestion pipeline. Finally, extend the CLI labeling command with a `--review-all` option to allow auditing/labeling any cached article to seed the labeled dataset.

## User Stories

1. As a developer, I want all candidate article HTML pages to be cached during discovery, so that their HTML is always available for subsequent extraction and validation.
2. As a developer, I want relevance classification to occur after successful extraction, so that the LLM fallback can evaluate clean article text while the Logistic Regression model uses the shared headline/description metadata representation.
3. As a developer, I want the LLM silver-standard labeling agent to use balanced few-shot examples (both relevant and irrelevant cases) from human-labeled database entries when available, so that its classifications are accurate and unbiased.
4. As a developer, I want the LLM agent to operate zero-shot when no human-labeled articles are in the database, so that the labeling pipeline works out-of-the-box without a fabricated fallback set.
5. As a developer, I want irrelevant validated articles to be stored in the stories database with `status = 'IRRELEVANT'`, so that they build a training dataset for the Logistic Regression model without polluting the Neo4j ingestion pipeline.
6. As a developer, I want to be able to review and label any machine-classified cached article using the CLI, so that I can quickly build a gold-standard training dataset.
7. As a developer, I want the database to track the source of relevance labels (e.g. human vs. machine/LLM), so that human labels can seed few-shot prompts and human plus LLM labels can form the silver-standard training dataset.

## Implementation Decisions

- **Schema changes**: Add a `relevance_label_source` column to the `scraped_html_cache` table, using an enum constraint ('KEYWORD', 'LLM', 'HUMAN', 'MODEL') and defaulting to 'KEYWORD'. Implement a database migration to add this column to existing databases.
- **Discovery adjustments**: Change the discovery service to cache the raw HTML for all candidate URLs passing discovery filters, setting `validation = 'PENDING'` and `relevance_status = 'PENDING'`.
- **Validation & Extraction pipeline**: Make validation async. If selector validation succeeds, use metadata embeddings (headline and description) for Logistic Regression when weights are available. On fallback, run the LLM classifier on the clean extracted title and body. Save the story to the database, setting `status = 'UNPROCESSED'` for relevant and `status = 'IRRELEVANT'` for irrelevant stories. Update `scraped_html_cache` with the relevance outcome and label source (`'LLM'` or `'MODEL'`).
- **LLM Silver-Standard Agent**: Implement an async LLM agent using Pydantic AI. Query up to 3 human-labeled examples for both `RELEVANT` and `IRRELEVANT` classes separately. If either class has no examples, run the agent zero-shot rather than adding static examples.
- **Training data**: Train the Logistic Regression model on both `HUMAN` and `LLM` labeled metadata embeddings. Human labels remain the exclusive source of few-shot examples.
- **CLI Updates**: Asynchronously run the validation pipeline in `update-sources`. Extend the `ca-map classifier label` CLI command with a `--review-all` flag to query all cached articles where `relevance_label_source != 'HUMAN'`, updating them with `relevance_label_source = 'HUMAN'` when manually labeled.

## Testing Decisions

- Validate database migration and column constraints for `relevance_label_source`.
- Verify that `get_gold_standard_examples` retrieves a balanced class list.
- Mock the LLM agent to test the post-extraction fallback flow, ensuring that relevant articles get saved with status `'UNPROCESSED'` and irrelevant articles with status `'IRRELEVANT'`.
- Verify that the ingestion pipeline does not pull `'IRRELEVANT'` stories.

## Out of Scope

- Automatically running the logistic regression trainer (it remains a manual CLI command run on demand).
- Fine-tuning the embeddings adapter.

## Further Notes

None.

## Decision History

### 2026-07-09 — Reconciled implementation intent

- The Logistic Regression model is intentionally metadata-based: it embeds the headline and description, not the extracted body. This keeps the model representation consistent across discovery, manual labeling, and post-extraction validation.
- The LLM fallback remains post-extraction and receives the clean title and body.
- `LLM` labels are intentionally included with `HUMAN` labels for model training as silver-standard data. Only `HUMAN` labels supply few-shot examples.
- A fresh database intentionally uses zero-shot LLM classification; static fallback examples are not part of the desired behavior.
- Once the Logistic Regression model performs well enough to make reliable metadata-based decisions, move relevance classification back to pre-extraction so irrelevant pages can be discarded before extraction.
