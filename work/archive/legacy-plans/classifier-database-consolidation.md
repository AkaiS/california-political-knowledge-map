# California Politics Classifier & Database Consolidation Implementation Plan

This plan consolidates the database tables tracking crawled articles and integrates a vectorized relevance classifier. It replaces the separate `rejected_articles` table with a single state-machine in `scraped_html_cache`, introduces a pre-computed embedding storage system, and builds a classifier module in a decoupled `uv` workspace package to keep heavy ML dependencies separate from the scraper core.

---

## User Review Required

> [!IMPORTANT]
> **Database Consolidation & Migration**
> We are migrating all records from the `rejected_articles` table into `scraped_html_cache` and dropping the `rejected_articles` table. Based on feedback, we will dump the old tables' existing data without retrofitting embeddings. A database backup will be performed automatically before running this step.

> [!TIP]
> **Dependency Isolation via `uv` Workspace**
> By placing `numpy` and `scikit-learn` in a separate `classifier` package within the workspace, the core scraper package remains lightweight and free of heavy machine learning binaries. Relevance inference in the scraper runtime will be performed using a pure-Python dot-product fallback when `numpy` is not loaded.

---

## Proposed Changes

### Component 1: UV Workspace Configuration

#### [MODIFY] [pyproject.toml](file:///Users/akaisenghor/Projects/california-political-knowledge-map/pyproject.toml)
* Define the workspace members:
  ```toml
  [tool.uv.workspace]
  members = ["classifier"]
  ```

#### [NEW] [pyproject.toml](file:///Users/akaisenghor/Projects/california-political-knowledge-map/classifier/pyproject.toml)
* Create the separate classifier package:
  ```toml
  [project]
  name = "ca-political-classifier"
  version = "0.1.0"
  description = "NumPy and scikit-learn classifier package for California Politics relevance filter"
  requires-python = ">=3.13"
  dependencies = [
      "numpy>=2.0.0",
      "scikit-learn>=1.4.0",
  ]

  [build-system]
  requires = ["hatchling"]
  build-backend = "hatchling.build"
  ```

---

### Component 2: SQLite Database Consolidation

#### [MODIFY] [sqlite_db.py](file:///Users/akaisenghor/Projects/california-political-knowledge-map/src/knowledge_map/adapters/sqlite_db.py)
* Update `init_db` to perform safe schema migrations:
  1. Add columns to `scraped_html_cache`: `headline` (TEXT), `description` (TEXT), `embedding` (BLOB), `relevance_status` (TEXT CHECK(relevance_status IN ('RELEVANT', 'IRRELEVANT', 'INCONCLUSIVE')) DEFAULT 'RELEVANT'), and `raw_metadata_json` (TEXT).
  2. Modify `validation` CHECK constraint to support `'PENDING_RELEVANCE'`.
  3. Migrate existing records from `rejected_articles` to `scraped_html_cache` mapping `relevance_status` and setting `validation` to `'PENDING_RELEVANCE'` for `INCONCLUSIVE` and `NULL` for `IRRELEVANT` articles.
  4. Drop `rejected_articles` table.
* Update check functions:
  * Simplify `is_url_known(url)` to query only `scraped_html_cache` and `stories` tables.
  * Implement `update_relevance_status(url, status, validation)` and a utility to clear `raw_html` while keeping metadata.

---

### Component 3: Relevance Filter & Inference Update

#### [MODIFY] [relevance.py](file:///Users/akaisenghor/Projects/california-political-knowledge-map/src/knowledge_map/core/relevance.py)
* Refactor `classify_article` to support model inference:
  1. Calculate probability using model coefficients (`classifier_weights.json`) if present. To keep the scraper core dependency-free, inference can run as a pure-Python dot product:
     $$z = \sum (w_i \cdot x_i) + b$$
     $$\text{probability} = \frac{1}{1 + e^{-z}}$$
  2. Implement the threshold zones:
     - $p \geq 0.7$: Return `'RELEVANT'`
     - $0.3 \leq p < 0.7$: Return `'INCONCLUSIVE'`
     - $p < 0.3$: Return `'IRRELEVANT'`
  3. If coefficients are missing, fallback to keyword heuristics.
* Implement a helper to serialize/deserialize float lists to binary BLOBs for SQLite storage.

#### [MODIFY] [discovery.py](file:///Users/akaisenghor/Projects/california-political-knowledge-map/src/knowledge_map/core/discovery.py)
* Update crawlers to align with the new consolidated workflow:
  1. Scrape URL -> Extract metadata.
  2. Compute embedding using `EmbeddingAdapter`.
  3. Run relevance classifier.
  4. Write a single unified row to `scraped_html_cache`. 
     - If `RELEVANT`: Write `raw_html` and set `validation = 'PENDING'`.
     - If `INCONCLUSIVE`: Set `validation = 'PENDING_RELEVANCE'` and `raw_html = NULL`.
     - If `IRRELEVANT`: Set `validation = NULL` and `raw_html = NULL`.

---

### Component 4: Model Training & CLI Integration

#### [NEW] [trainer.py](file:///Users/akaisenghor/Projects/california-political-knowledge-map/classifier/src/classifier/trainer.py)
* Create training/evaluation pipeline inside the `classifier` package:
  * Pull all labeled articles from `scraped_html_cache`.
  * Train `scikit-learn` LogisticRegression.
  * Export weights, intercept, and threshold parameters to `src/knowledge_map/resources/classifier_weights.json`.

#### [MODIFY] [main.py](file:///Users/akaisenghor/Projects/california-political-knowledge-map/src/knowledge_map/cli/main.py)
* Add a `classifier` CLI parser branch with subcommands:
  * `ca-map classifier label`: Run LLM labeling or interactive active-learning terminal prompt for human feedback on uncertain predictions (filtering for `validation = 'PENDING_RELEVANCE'`).
  * `ca-map classifier train`: Trigger training, print evaluation report, and export weights.
  * `ca-map classifier reevaluate`: Run vectorized predictions over all inconclusive/rejected records in SQLite. Flag transitioned records for scraping.

---

## Verification Plan

### Automated Tests
* Create unit tests in `tests/test_relevance_classifier.py`:
  - Verify database migration functions and consolidated table operations.
  - Test model inference using dummy weights to verify probability boundaries ($p \geq 0.7$, $0.3 \le p < 0.7$, $p < 0.3$).
  - Verify that binary BLOB conversions preserve float array precision.

### Manual Verification
* Run a mock crawl sequence to verify that relevant articles save HTML, and irrelevant/inconclusive articles save metadata and embeddings but NULL the raw HTML.
* Manually inspect SQLite records to verify consolidated schema columns.
