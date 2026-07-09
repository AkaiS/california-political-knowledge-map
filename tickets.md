# Tickets: Post-Extraction Relevance Classification & Silver-Standard Labeling

A pipeline that moves relevance classification to post-extraction, uses a silver-standard Pydantic AI agent with dynamic/static examples, caches all discovered HTMLs to prevent TypeError promotion crashes, and expands CLI labeling.

Work the **frontier**: any ticket whose blockers are all done.

## Database Schema Migration & Cache Table updates

**What to build:** Ensure the local cache schema supports tracking relevance sources and has a default/updated status structure. The system should automatically run a safe database migration on startup to introduce these columns to existing databases.

**Blocked by:** None — can start immediately

- [x] Database automatically migrates existing databases to add `relevance_label_source` with enum constraint (`'KEYWORD'`, `'LLM'`, `'HUMAN'`, `'MODEL'`) defaulting to `'KEYWORD'`
- [x] Database automatically updates `relevance_status` constraints to support `'PENDING'` status
- [x] Helper `get_gold_standard_examples` retrieves balanced human-labeled examples (max 3 per class) by joining cache and stories
- [x] `update_relevance_status` is updated to support updating the `relevance_label_source` column

## Classifier Model Training Update

**What to build:** Ensure that both gold-standard (human-annotated) and silver-standard (LLM-annotated) articles are used for Logistic Regression training, while excluding keyword heuristics and unverified model predictions.

**Blocked by:** Database Schema Migration & Cache Table updates

- [ ] Training query restricts retrieved training articles to those with `relevance_label_source IN ('HUMAN', 'LLM')`
- [ ] `ca-map classifier train` runs successfully using both human-labeled and LLM-labeled dataset entries

## Discovery Service Raw HTML Caching & Pending Relevance

**What to build:** Discovered article URLs are cached along with their full raw HTML immediately, setting validation and relevance statuses to `'PENDING'`, so HTML content is never missing when promoting/labeling.

**Blocked by:** Database Schema Migration & Cache Table updates

- [ ] ListingPageDiscoveryService caches raw HTML for all candidate URLs passing filters, setting validation to `'PENDING'` and relevance to `'PENDING'`
- [ ] ArchiveDiscoveryService caches raw HTML for all candidate URLs passing filters, setting validation to `'PENDING'` and relevance to `'PENDING'`
- [ ] No early keyword relevance check is performed on raw HTML during discovery runs (except cutoff extraction date checks for archive crawls)

## Async LLM Silver-Standard Agent (Pydantic AI)

**What to build:** An async LLM-based labeling agent using Pydantic AI to determine if extracted article content belongs to California politics, using dynamic gold-standard examples or falling back to high-quality static ones.

**Blocked by:** Database Schema Migration & Cache Table updates

- [ ] Async agent queries database for up to 3 positive and 3 negative gold-standard (`HUMAN`) examples
- [ ] Agent falls back to pre-defined static examples if database examples are missing
- [ ] Agent returns structured Pydantic output containing classification (`RELEVANT` or `IRRELEVANT`) and rationale

## Post-Extraction Relevance Pipeline (Async Validation)

**What to build:** Set the validation pipeline to be async. Immediately after selector extraction succeeds, run the relevance classifier (using Logistic Regression if weights exist, otherwise falling back to the LLM agent) on clean text. Store relevant articles as `'UNPROCESSED'` and irrelevant ones as `'IRRELEVANT'` in the stories table.

**Blocked by:** Discovery Service Raw HTML Caching & Pending Relevance, Async LLM Silver-Standard Agent (Pydantic AI)

- [ ] `ArticleValidatorService.validate_pending_articles` is async and runs classification on successfully extracted title/body
- [ ] Relevant articles saved in stories table with status `'UNPROCESSED'`; irrelevant articles saved with status `'IRRELEVANT'`
- [ ] Cache status is updated with correct relevance status and source (`'LLM'` or `'MODEL'`)
- [ ] Ingestion pipeline does not fetch articles marked with `'IRRELEVANT'` status

## CLI Auditing & Labelling Command Updates

**What to build:** Update CLI triggers to call the async validation pipeline. Extend the labeling command with a `--review-all` option to audit/label any cached article to seed the gold-standard dataset.

**Blocked by:** Post-Extraction Relevance Pipeline (Async Validation), Classifier Model Training Update

- [ ] All CLI commands (e.g. `update-sources`, `scrape-archive`, `validate-articles`) execute the async validation pipeline correctly via `asyncio.run`
- [ ] `ca-map classifier label` supports a `--review-all` flag to query all cached articles with `relevance_label_source != 'HUMAN'`
- [ ] Manually labeling an article via CLI updates `relevance_label_source` to `'HUMAN'` in the database
