# Scraping Pipeline PRD

Labels: ready-for-human

## Problem Statement

Website layout changes frequently cause CSS-based scrapers to break or extract malformed text, leading to empty fields, boilerplate text (navigation links, ads, sidebars), or missing sections. Ingesting malformed text is highly problematic for GraphRAG entity extraction because it is expensive and pollutes the knowledge graph with dirty data.

Additionally, news sites publish many articles that are irrelevant to California political networks (e.g., sports, lifestyle, recipes, general national news). Crawling and running LLM extractions on these irrelevant articles is highly expensive and contaminates our knowledge base. 

As the number of tracked news publications grows, we need a robust method to:
1. Validate that scraped article content matches ground truth.
2. Store historic iterations of selectors since websites change over time.
3. Automatically generate and self-heal CSS selectors using LLMs when layout drift is detected.
4. Bootstrap article selectors for new publications using sample articles.
5. Provide a human-in-the-loop validation step to approve new selectors before they are promoted and applied.
6. Manage all publication configurations dynamically in the database, avoiding static files and enabling easy registration of new publications at runtime.
7. Filter out non-political articles during URL discovery using a URL-path blocklist (/sports/, /gardening/, etc.).
8. Filter out non-political articles using metadata keywords, with a hook for a future logistic regression embeddings-based classification model.
9. Filter out navigation, utility, and index links during listing discovery using anchor text heuristics.

## Solution

We will build an advanced scraping pipeline with self-healing capabilities:
- **Registry**: A database table `publications` that specifies publication details, crawl policies, and entry points, but does *not* contain HTML selectors. It tracks validation failure points, active healing status, and paused status.
- **Selector Store**: Mapped in SQLite (`publication_selectors`), storing versioned CSS selectors for article pages mapped to execution success windows (`earliest_success_date` and `latest_success_date`).
- **Relevance Filter**: Performs a two-phase check. Discards URLs matching a path blocklist (pre-fetch) or failing anchor text heuristics during listing discovery. For remaining candidates, crawls the target URL to extract and check metadata (JSON-LD or meta tags) against keywords. If relevant, the raw HTML is cached as `PENDING` validation, bypassing a duplicate fetch.
- **Article Validator**: Grounded in JSON-LD structure. Validates CSS-extracted title, author, and date. Compares word counts within a tight ratio if `wordCount` is present in JSON-LD, falling back to link density and stopword ratio check if absent. Articles whose HTML contains no JSON-LD at all are marked `UNVALIDATABLE` (no failure points, never healing targets).
- **Raw HTML Store**: Stores the raw HTML of articles in SQLite (`scraped_html_cache`) with a 30-day retention policy for successfully validated/processed articles.
- **Selector Healing Pipeline**: An asynchronous LLM-driven process (Generator/Critic loop capped at 3 iterations), triggered when a publication's circuit breaker trips, that analyzes the validation failure and runs on a preprocessed/cleaned version of the raw HTML (with head, scripts, styles, and other non-article tags stripped to save tokens) to generate new article selectors. Proposals are persisted in the `selector_proposals` SQLite table.
- **Decoupled validation & Circuit Breaker**: Scraping and validation are separate processes. If validation fails repeatedly (measured using weighted failure points: 3 for ground-truth mismatches, 1 for fallback failures), validation is paused for the publication while scraping continues, and the Selector Healing Pipeline is triggered. The circuit breaker is unpaused through human approval of healed/manually input selectors and a subsequent successful recovery check on the triggering article (which must succeed).
- **Publication Bootstrapper**: An LLM-driven process to discover article selectors for a new publication.
- **Observability & Telemetry**: Integrates Pydantic Logfire tracing for HTTP requests, article validation steps, and LLM self-healing/bootstrapping agent loops to track latencies, costs, and failures.
- **Pipeline Evaluation (Evals)**: Repeatable offline benchmarks using `pydantic-evals` over dedicated datasets under `tests/evals/data/` to prevent regressions in political relevance filtering and LLM CSS selector generation.
- **CLI Management**:
  - `ca-map register-publication` - CLI command to register a new publication in the database and trigger the bootstrapper.
  - `ca-map update-sources` - Incremental crawl using Crawl4AI's link extraction that skips existing URLs (checking `scraped_html_cache`, `rejected_articles`, and `stories`, so previously rejected or inconclusive URLs are not re-fetched and re-classified on every run), filters relevance, and flags validation failures.
  - `ca-map scrape-archive` - Archive crawl using Crawl4AI's `DomainMapper` that respects the `DiscoveryState` (stored in the database), relevance filtering, and configurable cutoff.
  - `ca-map heal-selectors` - CLI command to run/retry the self-healing pipeline for paused/failed publications. Supports `--retry` to re-run and `--context "..."` to inject developer guidance/context hints.
  - `ca-map purge-cache` - CLI command that applies the HTML cache retention policy (nulling `raw_html` for eligible `VALIDATED` and `UNVALIDATABLE` rows), meant to be run periodically by an external task scheduler (like `cron` or `launchd`).
  - `ca-map review-selectors` - CLI utility for developers to view LLM-generated selector candidates, preview extraction outputs, and approve/promote them. Also supports directly specifying and promoting manually defined selectors with `--manual <path_to_json_file>` (where the JSON file contains the new selectors and the identifier/URL of the validation-failed article to run the recovery check against) to bypass LLM loops.

## User Stories

1. As a developer, I want to define publications in a SQLite database table instead of a static configuration file, so that publication configurations are dynamic and can be queried and modified at runtime.
2. As a developer, I want to use `ca-map register-publication` to register a new publication in the database, so that adding new sources is fully automated.
3. As the scraper, I want to query the SQLite `Selector Store` using the article's fetch date, so that I can attempt the selector version with the closest success window first, falling back to other historical selectors if validation fails.
4. As the scraping pipeline, I want to extract JSON-LD metadata from scraped pages to get an authoritative ground truth baseline for validation.
5. As the validation step, I want to fail validation if the CSS-extracted title, author, or date does not match the JSON-LD ground truth, or if the body word count ratio falls outside [0.9, 1.1] (falling back to link density and stopword ratio checks if word count is absent), so that malformed data does not enter the ingestion pipeline.
6. As the scraper, I want to save the raw HTML of any article that we scrape.
7. As the scraper, I want to set the validation status of a validation-failed article to `VALIDATION_FAILED` in `scraped_html_cache` and increment the publication's failure points, keeping it out of the `stories` table.
8. As a developer, I want an asynchronous self-healing loop, triggered when a publication's circuit breaker trips, that reads the `VALIDATION_FAILED` article that tripped it and preprocessed/cleaned HTML (stripping head, scripts, and other non-article tags) to generate new selector candidates using a Generator/Critic LLM team, while tracking the active healing status in the database to prevent duplicate requests.
9. As a developer, I want successfully validated cached pages to be marked `VALIDATED` in `scraped_html_cache`, their extracted data inserted into the `stories` table as `UNPROCESSED`, and the publication's failure points reset to 0 during active validation to handle transient/intermittent failures without immediately tripping the circuit breaker.
10. As a developer, I want to bootstrap a new Publication by pointing the system to a few sample article URLs, which runs the LLM selector generator to produce the initial article selectors.
11. As a developer, I want to run `ca-map review-selectors` to inspect proposed selectors, view a visual diff/preview of the extracted content against the raw page, and approve them before they are written as active `Selector Versions`.
12. As a developer, I want the system to run a recovery check on the article that triggered self-healing once the selectors are promoted, and prioritize previously `VALIDATION_FAILED` articles when restarting the pipeline.
13. As a developer, I want the scraper to check metadata keywords to determine if a URL is about California politics, with inconclusive articles saved for future logistic regression classification.
14. As a system administrator, I want to save the URLs, relevance status, and metadata of rejected and inconclusive articles to calculate false negative rates.
15. As the scraper, I want to continue crawling and caching raw HTML for a publication even if its validation pipeline is paused due to repeated validation failures.
16. As a developer, I want to automatically pause the validation pipeline for a publication if its failure points reach or exceed 10, avoiding validation overhead. 
17. As a developer, I want all relevance filtering, validation outcomes, and circuit breaker state changes to be logged with structured JSON fields, so that I can easily query and filter them in Logfire.
18. As a developer, I want to run offline regression evaluations using `pydantic-evals` on curated datasets in `tests/evals/data/`, so that I can ensure relevance filter modifications and LLM prompt updates do not introduce regressions.
19. As the scraper, I want to filter discovered links on a listing page using anchor text heuristics, so that navigation menu items and footer links are filtered out before making network requests.
20. As the validation step, I want articles whose HTML contains no JSON-LD at all to be marked `UNVALIDATABLE` in `scraped_html_cache` without accruing failure points or becoming healing/recovery targets, so that articles selector healing cannot fix do not trip the circuit breaker or waste LLM calls.

## Implementation Decisions

- **Registry & Selector Store SQLite Schema**:
  ```sql
  CREATE TABLE IF NOT EXISTS publications (
      id TEXT PRIMARY KEY,               -- e.g., 'calmatters'
      name TEXT NOT NULL,                -- e.g., 'CalMatters'
      base_url TEXT NOT NULL,            -- e.g., 'https://calmatters.org'
      crawl_delay REAL DEFAULT 2.0,
      max_concurrency INTEGER DEFAULT 2,
      use_robots_txt BOOLEAN DEFAULT 1,
      discovery_config_json TEXT,        -- JSON containing listing_urls, sitemap_urls, url_path_blocklist, etc.
      archive_cutoff_years INTEGER DEFAULT 5,
      validation_paused BOOLEAN DEFAULT 0, -- Circuit breaker state
      failure_points INTEGER DEFAULT 0,  -- Circuit breaker points
      healing_in_progress BOOLEAN DEFAULT 0, -- Active LLM healing loop status
      created_at DATETIME DEFAULT CURRENT_TIMESTAMP
  );

  CREATE TABLE IF NOT EXISTS publication_selectors (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      publication_id TEXT NOT NULL,
      selectors_json TEXT NOT NULL,      -- JSON containing article selectors (title, author, date, body)
      earliest_success_date DATETIME,     -- Start boundary of validity success window (based on fetch date)
      latest_success_date DATETIME,       -- End boundary of validity success window (based on fetch date)
      created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
      FOREIGN KEY(publication_id) REFERENCES publications(id) ON DELETE CASCADE
  );

  CREATE TABLE IF NOT EXISTS publication_discovery_state (
      publication_id TEXT PRIMARY KEY,
      state_json TEXT NOT NULL,          -- JSON object tracking progress (e.g., last_page, last_sitemap_index, last_date)
      updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
      FOREIGN KEY(publication_id) REFERENCES publications(id) ON DELETE CASCADE
  );
  ```

  > [!NOTE]
  > All `DATETIME` columns in SQLite are stored as text representing ISO 8601 formatted strings (e.g., `YYYY-MM-DDTHH:MM:SSZ`), ensuring consistent handling when comparing success windows and calculating distances in Python.
- **Raw HTML Store SQLite Schema**:
  ```sql
  CREATE TABLE IF NOT EXISTS scraped_html_cache (
      url TEXT PRIMARY KEY,
      publication_id TEXT NOT NULL,
      raw_html TEXT,
      validation TEXT CHECK(validation IN ('PENDING', 'VALIDATED', 'VALIDATION_FAILED', 'UNVALIDATABLE')) DEFAULT 'PENDING',
      validation_date DATETIME,
      scraped_at DATETIME DEFAULT CURRENT_TIMESTAMP,
      FOREIGN KEY(publication_id) REFERENCES publications(id) ON DELETE CASCADE
  );

  CREATE TABLE IF NOT EXISTS rejected_articles (
      url TEXT PRIMARY KEY,
      publication_id TEXT NOT NULL,
      relevance_status TEXT CHECK(relevance_status IN ('IRRELEVANT', 'INCONCLUSIVE')) NOT NULL,
      metadata_json TEXT,
      checked_at DATETIME DEFAULT CURRENT_TIMESTAMP,
      FOREIGN KEY(publication_id) REFERENCES publications(id) ON DELETE CASCADE
  );
  ```
- **Selector Proposal Store SQLite Schema**:
  ```sql
  CREATE TABLE IF NOT EXISTS selector_proposals (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      publication_id TEXT NOT NULL,
      selectors_json TEXT NOT NULL,       -- Candidate article selectors (title, author, date, body)
      trigger_article_url TEXT NOT NULL,  -- The VALIDATION_FAILED article that tripped the breaker (Recovery Check target)
      status TEXT CHECK(status IN ('PENDING_REVIEW', 'APPROVED', 'REJECTED', 'HEALING_FAILED')) DEFAULT 'PENDING_REVIEW',
      critic_iterations INTEGER,          -- Number of Generator/Critic iterations consumed
      created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
      resolved_at DATETIME,
      FOREIGN KEY(publication_id) REFERENCES publications(id) ON DELETE CASCADE
  );
  ```
- **Pre-fetch Path Blocklist**:
  - Filter URLs during discovery (pre-fetch) using a blocklist of URL path segments (e.g., `["/sports/", "/recipes/", "/obituaries/", "/author/", "/category/", "/tag/", "/search/"]`).
  - Configured per-publication in `discovery_config_json` under the `url_path_blocklist` key, with a global fallback in `config.py`.
- **Anchor Text Heuristics**:
  - For listing discovery (during incremental crawls), only follow links where the anchor text length is >= 5 words and >= 25 characters to eliminate navigation menu items, tags, and sidebar links.
  - This heuristic filter is bypassed for archive crawls using `DomainMapper` and for `sitemap` discovery where anchor text is not available.
- **Full Page Scrape & Relevance Filter**:
  - Configured as a global constant list `POLITICAL_RELEVANCE_KEYWORDS` in `config.py` (e.g., california, sacramento, newsom, legislature, etc.).
  - Since metadata (JSON-LD or HTML meta tags) resides on the article page itself, the system crawls the candidate URL first to get its full HTML.
  - It extracts the JSON-LD `headline` / `description` (or HTML meta tags if JSON-LD is missing) and searches for keyword matches in this metadata.
  - **Classification Logic:**
    1. **RELEVANT**: Matches high-confidence political keywords. The scraped raw HTML is retained in `scraped_html_cache` as `PENDING` validation, avoiding a duplicate network request.
    2. **IRRELEVANT**: Discarded (we do not care about this article). Matches negative keywords/topics (lifestyle, sports, food, recipes, etc.) or contains zero political keyword matches. The URL is saved in `rejected_articles` with `relevance_status = 'IRRELEVANT'`.
    3. **INCONCLUSIVE**: Neither (we are not sure if we should care about this article). Does not match high-confidence political keywords but contains secondary local/state news terms without negative topic matches. The URL is saved in `rejected_articles` with `relevance_status = 'INCONCLUSIVE'`. A clear hook is left in the code to pass these to a future Logistic Regression embeddings-based classifier running on metadata embeddings (headline and description).
- **Validation Rules (JSON-LD Grounding)**:
  - **Ground Truth Baseline:** Extracted from JSON-LD schema (e.g. `NewsArticle`, `BlogPosting` objects in the head) containing `headline`, `author`, `datePublished`, and (optionally) `wordCount`. JSON-LD is a strict requirement; if JSON-LD is completely missing from the HTML, the article is marked `UNVALIDATABLE` in `scraped_html_cache` and skipped. `UNVALIDATABLE` articles accrue no failure points and are never used as healing or Recovery Check targets, since selector regeneration cannot fix missing JSON-LD.
  - **Title**: Case-insensitive string similarity (edit distance ratio >= 0.90) between CSS-extracted title and JSON-LD baseline headline.
  - **Author**: Both the CSS-extracted and JSON-LD author values are normalized before comparison: filler words are stripped (e.g., "By", "Staff", "Special to"), multi-author strings are split on commas and "and", and comparison is case-insensitive. Each JSON-LD author name must match one of the extracted names using Damerau-Levenshtein similarity (edit distance ratio >= 0.90). If JSON-LD has no author, the CSS author is accepted as-is.
  - **Date**: CSS-extracted publish date resolves to the same calendar day as JSON-LD `datePublished`. For comparison and storage, dates are converted to and stored in UTC, extracting the datetime from HTML time tags with datetime attributes (or resolving timezone offsets) to prevent timezone-related mismatch failures.
  - **Body Word Count**: If `wordCount` exists in JSON-LD, the ratio of CSS-extracted word count to JSON-LD word count must fall within `[0.9, 1.1]` (loose enough to absorb differences in how publishers count words, e.g. captions and bylines).
  - **Fallback Sanity (when `wordCount` is absent in JSON-LD):**
    - **Link Density**: Characters inside anchor tags (`<a>`) / total body characters must be `< 0.15` (filters out sidebars and nav leaks).
    - **Stopword Ratio**: Percentage of common English stopwords in the body must be `> 0.25` (verifies natural language prose).
- **Decoupled validation & Circuit Breaker**:
  - Scraping is decoupled from validation. Crawlers discover URLs, scrape raw HTML, and save to `scraped_html_cache` as `PENDING`.
  - The validation process reads `PENDING` cache entries and validates them.
  - Failures accumulate "points" per publication:
    - **Ground Truth Mismatch (3 pts):** Fails to match explicit JSON-LD data (title, author, publish date, or word count).
    - **Fallback Failure (1 pt):** JSON-LD is present but lacks `wordCount`, and fallback rules for body checks (link density, stopwords) fail.
    - **No points for `UNVALIDATABLE`:** Articles missing JSON-LD entirely are marked `UNVALIDATABLE` and accrue no points (healing cannot fix them, so they must not trip the breaker).
  - **Success Points Reset:** While validation is `ACTIVE`, a successful article validation resets the failure points to 0. This ensures transient/intermittent failures do not trip the circuit breaker if the publication is still mostly validating successfully.
  - **Circuit Breaker Trip:** If validation failures accumulate and the failure points reach or exceed 10 (indicating that nothing or very little is successfully validating), the validation state is set to `PAUSED` in `publications` and the Selector Healing Pipeline is triggered. Tripping the breaker is the *only* automatic healing trigger; isolated failures below the threshold simply remain `VALIDATION_FAILED` (we accept missing some articles rather than firing an LLM run on every transient failure).
  - **Pause Behavior:** When validation is `PAUSED`, routine validation of `PENDING` articles is completely skipped to avoid continuing validation indefinitely and wasting resources when selectors are entirely broken. Crawling and caching of raw HTML continue in the background.
  - **Healing & Recovery Sequence (Escape Hatch):**
    1. **Breaker-Trip Healing Trigger**: When the circuit breaker trips (failure points reach or exceed 10, either during automated `ACTIVE` validation or via manual developer-initiated validation runs during `PAUSED`), the Selector Healing Pipeline is triggered on the `VALIDATION_FAILED` article whose failure tripped the breaker, to generate a new CSS selector proposal. (Because `UNVALIDATABLE` articles accrue no points, the tripping article is always a healable target.)
       - **Strict Single Proposal Limit:** To prevent redundant API usage and overlapping selectors, the self-healing pipeline must only run if there is no unresolved proposal row (`status = 'PENDING_REVIEW'` or `'HEALING_FAILED'`) for the publication in `selector_proposals` and no healing run is currently in progress for it (checking the `healing_in_progress` column in the database).
       - **Single Representative Target:** The healing loop executes on exactly *one* representative failed article (the one that tripped the breaker) rather than spawning parallel or sequential runs for other failing articles sharing the same template.
    2. The candidate selector is saved as a `PENDING_REVIEW` row in `selector_proposals`.
    3. The developer reviews the candidate using `ca-map review-selectors` (or submits manual/custom context overrides).
    4. Upon developer approval/promotion, the new selector is registered in the `Selector Store`, triggering a **Recovery Check** on the specific article that triggered the self-healing run.
    5. A successful validation of this article using the new selector—or a successful Recovery Check run on the triggering article during manual CLI promotion—**immediately resets** the publication's failure points to `0` and marks validation `ACTIVE` (`validation_paused = 0`). Because manual submissions also run the Recovery Check, it must succeed to unpause and reset the points (there is no `--force` command to bypass this check).
    6. Once validation is set back to `ACTIVE` and the pipeline restarts, the system must prioritize processing/validating previously `VALIDATION_FAILED` articles before processing newer `PENDING` articles. While validation is `PAUSED`, any transient successes from other articles do *not* reset the failure points or unpause validation.
- **Selector Selection & Fallback**:
  - When a selector version is newly created/promoted, `earliest_success_date` and `latest_success_date` are initialized to the fetch date `D` of the validated recovery article (or the current fetch date at the time of manual promotion).
  - For an article fetched at date `D`, calculate the distance to each selector's success window:
    - If `D` is within `[earliest_success_date, latest_success_date]`, distance = `0`.
    - Otherwise, distance = `min(abs(D - earliest_success_date), abs(D - latest_success_date))`.
  - Try selectors by shortest distance first.
  - On success, update that selector's window: `earliest_success_date = min(earliest_success_date, D)`, `latest_success_date = max(latest_success_date, D)`.
  - On failure, fall back to the next closest selector.
  - If all fail, mark the article validation state as `VALIDATION_FAILED` in `scraped_html_cache` and increment the publication's failure points, weighted by the *best attempt* across all selector versions tried (e.g., if any version reached the fallback checks, the failure counts as a 1-point fallback failure rather than a 3-point ground-truth mismatch). The Selector Healing Pipeline is *not* triggered per-article; it is triggered only when the accumulated points trip the circuit breaker (subject to the single active proposal limit, checking both the `selector_proposals` table and the `healing_in_progress` database flag).
- **Generator/Critic Agent Flow**:
  - **HTML Preprocessing (Cleaning)**: Before raw HTML is passed to the LLM (Generator and Critic agents), it is cleaned to strip out non-article-bearing tags and content, reducing token consumption and noise. Specifically, we:
    - Strip out entire `<head>`, `<script>`, `<style>`, `<svg>`, `<noscript>`, `<footer>`, `<nav>`, `<iframe>`, and `<img>` tags.
    - Remove large inline data attributes, inline styles, base64-encoded images, and non-essential attributes, while preserving essential structure and classes/IDs needed for CSS selector generation and evaluation.
  - **Generator Agent**: Receives the preprocessed cleaned HTML, target JSON-LD metadata, and CSS schemas. Outputs CSS selectors for article fields (title, author, date, body).
  - **Critic Agent**: Receives the preprocessed cleaned HTML and the content extracted using the proposed selectors. Validates presence, cleanliness, and length ratio. Outputs approval or specific feedback. Capped at a maximum of 3 iterations per proposal.
  - **Limits**:
    - **Single Active Proposal:** No more than one unresolved proposal or healing run should exist or be in progress per publication at a time. The pipeline must reject or skip any new healing trigger for a publication if an unresolved row (`status = 'PENDING_REVIEW'` or `'HEALING_FAILED'`) already exists in `selector_proposals` or if the `healing_in_progress` flag is set to `1` in the database. During the LLM healing loop execution, the `healing_in_progress` flag in the `publications` table is set to `1`, and reset to `0` once the loop completes (successfully producing a candidate proposal or failing after 3 iterations).
    - **Startup Flag Reset:** On pipeline startup, all `healing_in_progress` flags are reset to `0`, so a crash mid-healing-loop cannot leave a stale flag that silently blocks future healing.
    - **No Re-healing until Resolved:** A proposal must be explicitly resolved by a developer (row marked `APPROVED` or `REJECTED`) before any further self-healing can be initiated. If a proposal is unresolved (`PENDING_REVIEW` or `HEALING_FAILED`), subsequent breaker trips will not trigger self-healing.
  - **Loop Exhaustion Handling (Critic Failure)**: If the Generator/Critic loop exhausts its 3 iterations without generating a proposal that the Critic approves:
    - The self-healing attempt is saved to `selector_proposals` with `status = 'HEALING_FAILED'` (retaining the last rejected selectors for retry context).
    - The publication validation remains `PAUSED`.
    - A critical warning is logged and a console alert is dispatched.
    - **Developer Recovery Options:** The system provides three CLI/command pathways to resolve loop exhaustion:
      1. **Re-run Healing**: Run `ca-map heal-selectors --retry --publication <id>` to retrieve the failed proposal from the `selector_proposals` table, extract the failed selectors, mark that row `REJECTED` (with `resolved_at` set), and re-execute the Generator/Critic loop on the failed article(s) while passing the failed selectors to the Generator agent as negative context so it avoids regenerating the same failing selectors.
      2. **Re-run with Custom Context**: Run `ca-map heal-selectors --publication <id> --context "Hint content"` to re-execute the loop, appending developer-supplied context or instructions to the Generator's prompt (e.g. telling the model which tags/classes contain the content). Any manual execution of `ca-map heal-selectors` (specifying `--retry` or custom `--context`) implicitly bypasses the unresolved-proposal check and resets or bypasses the `healing_in_progress` database flag for that publication so that developers do not have to manually resolve rows or reset flags to retry.
      3. **Manually Register Selectors**: Run `ca-map review-selectors --manual <path_to_json_file>` (where the JSON file contains the new selectors and the identifier/URL of the validation-failed article to run the recovery check against) to bypass the LLM healing loop entirely and directly promote developer-specified selectors. This action triggers the standard Recovery Check on the specified validation-failed article and, on success, resets the failure points to `0` and sets validation status back to `ACTIVE`. There is no `--force` command to bypass the Recovery Check.
- **Discovery Drift & Failure Warnings**:
  - If a discovery run using Crawl4AI's link extraction (for incremental crawls) or `DomainMapper` (for archive crawls) returns 0 candidate URLs from a request that successfully returned `200 OK`, emit a console warning alert. This signals that the listing page layout, domain structure, or sitemap has drifted, or that the filters (blocklists and heuristics) are overly restrictive.
- **HTML Cache Retention**:
  - Raw HTML for `VALIDATION_FAILED` articles is stored indefinitely until resolved.
  - For `VALIDATED` pages, the `raw_html` column in `scraped_html_cache` is purged (set to `NULL`) 30 days after its corresponding story in `stories` is marked `COMPLETED` (tracked using the story's `completed_at` / `updated_at` timestamp).
  - For `UNVALIDATABLE` pages, the `raw_html` column is purged (set to `NULL`) 30 days after `validation_date` (nothing can heal them, so there is no reason to retain the HTML indefinitely).
  - Purging is executed by the `ca-map purge-cache` CLI command, run periodically by an external task scheduler (like `cron` or `launchd`); no purging happens implicitly inside other commands.
- **Human Approval Seam**: Proposed selectors are saved as rows in the `selector_proposals` SQLite table. The CLI command `ca-map review-selectors` reads unresolved proposals from the table, displays the preview, and prompts for confirmation `y/n` input to promote it (marking the row `APPROVED` or `REJECTED` and setting `resolved_at`). In addition, the CLI command accepts a `--manual <path_to_json_file>` flag to bypass the LLM proposal flow and directly register/promote custom hand-selected selectors, which also prompts the developer for confirmation. The JSON file must include the new selectors and the identifier/URL of the validation-failed article we want to test against. Manual promotion still triggers the standard Recovery Check on the specified article, and it must succeed to unpause validation.
- **Structured Logging & Telemetry Specifications**:
  - **Structured Log Schemas**: Emit structured logs for discovery stats (e.g., `links_found`, `blocklist_filtered`, `anchor_filtered`, `new_candidates_found`), relevance checks, validation outcomes, and circuit breaker actions. Discarded URLs must record the precise filter reason (e.g., `blocklist_hit` or `anchor_heuristic_dropped`).
  - **Logfire Tracing**: Enable `logfire.instrument_pydantic_ai()` and `logfire.instrument_httpx(capture_all=True)` to trace all LLM runs, costs (input/output tokens), and HTTP operations. Use custom Logfire spans (e.g., `scrape_publication`, `heal_selectors`).
  - **Console Warning Alerts**: Integrate circuit breaker tripping and discovery drift warnings with `ConsoleNotifier` warning banners.
- **Pipeline Evals Specifications**:
  - **Relevance Benchmark Dataset**: A curated dataset of ~100-200 representative URLs, titles, and descriptions, manually labeled with ground truth (`RELEVANT`, `IRRELEVANT`, `INCONCLUSIVE`), stored in `tests/evals/data/relevance_dataset.json`.
  - **Selector Healer Snapshot Dataset**: A collection of historical website HTML snapshots and their corresponding JSON-LD targets, stored in `tests/evals/data/healer_dataset/`.
  - **Evaluation Metrics**:
    - *Relevance*: Compute Precision, Recall, and F1-score.
    - *Selector Healer*: Compute Syntactic Validity, Functional Success (Title similarity >= 0.90, author match, date resolution), and Convergence Speed (number of Critic iterations <= 3).

## Testing Decisions

- **Good Test Criteria**: Tests must verify lookup of selectors by success window proximity, the logic of the `Article Validator` comparison rules (including JSON-LD title, author normalization/splitting and Damerau-Levenshtein matching, date, word count ratio, link density, and stopword fallback), `UNVALIDATABLE` handling for articles missing JSON-LD (status set, no failure points, excluded from healing/recovery targets), metadata keyword relevance filtering, circuit breaker point accumulation/reset and breaker-trip healing trigger, the startup reset of `healing_in_progress` flags, selector generator mock runs, and the `heal-selectors` CLI command execution behaviors (proper parsing, validation of custom context propagation, and retry overrides). In addition, tests must verify Crawl4AI link extraction, pre-fetch path blocklist filters, anchor text heuristics, and domain mapping discovery.
- **Modules to Test**:
  - Selector Store queries (success window proximity and fallback).
  - Discovery & Link Filtering (link extraction, domain mapping, pre-fetch path blocklists, anchor text heuristics word/char boundary limits).
  - Relevance filter (full page scrape metadata checks, keyword matches, inconclusive/irrelevant classification and caching).
  - Article Validator (JSON-LD grounding, link density, stopword fallback).
  - Circuit Breaker (failure points accumulation, `UNVALIDATABLE` exclusion from points, pause state, breaker-trip healing trigger, recovery check validation, prioritisation of validation-failed articles on restart).
  - CLI parser subcommand additions (`register-publication`, `review-selectors`, `scrape-archive`, `update-sources`, `heal-selectors`, `purge-cache`).
  - HTML cache retention purge (`purge-cache` eligibility rules for `VALIDATED` and `UNVALIDATABLE` rows).
  - CLI `heal-selectors` command execution (verifying parser options `--publication`, `--retry`, `--context`, handling of missing/invalid publications, bypassing of the proposal existence constraint when `--retry` is passed, and correct propagation of developer `--context` guidance to the LLM generator prompt).
  - Asynchronous healing coordinator.
  - Relevance evaluation benchmarks and Selector Healer LLM-evaluation loops.
- **Prior Art**: We will mock the LLM calls for Generator/Critic and mock JSON-LD structures to test the self-healing and validator modules in isolation.
- **Evaluation Runner**: Evals will be implemented using `pydantic-evals` under the `tests/evals/` directory and can be executed via a dedicated script or test hook.

## Out of Scope

- Detailed Publication Bootstrapper design (sample article fetching, proposal review flow, and initial success window seeding) — deferred to a separate PRD. This PRD only establishes that `ca-map register-publication` triggers it and that its proposals land in `selector_proposals`.
- Automatic correction of sitemap formats or RSS layout changes.
- Human-in-the-loop UI (the terminal CLI is sufficient for the approval step).
- Healing of third-party APIs (strictly covers news publication HTML websites).

## Further Notes

- Once a Selector Version is approved or successfully validated, the system runs the recovery check on the article that triggered self-healing, and upon success, resets the failure points to 0, sets validation to active, and prioritizes previously `VALIDATION_FAILED` articles when restarting the pipeline.
