# 03. Register Publication with Categories

Status: completed

## Parent

[PRD.md](../PRD.md)

## What to build

We need a way to easily specify the valid categories when registering a publication, either via the CLI command `register-publication` or when calling `register_publication` in python code.

### Requirements
1. Update `register_publication` in `src/knowledge_map/adapters/sqlite_db.py` to accept an optional `categories: Optional[List[str]] = None` parameter.
2. If `categories` is supplied, it should update or create the `valid_categories` list within the publication's `discovery_config_json` field.
3. Update the `register-publication` subcommand in `src/knowledge_map/cli/main.py` to accept a new CLI option `--categories` (a space-separated list of strings).
4. Update unit tests to verify:
   - Python API registration works with categories and updates the discovery config JSON correctly.
   - CLI command registration with `--categories` parses and persists the categories correctly.

## Acceptance criteria

- [x] `register_publication` function accepts `categories: Optional[List[str]] = None`.
- [x] If `categories` is passed, the categories are serialized under the `"valid_categories"` key in the publication's `discovery_config_json` field.
- [x] Existing keys in `discovery_config_json` are preserved when `categories` are added/updated.
- [x] The CLI command `register-publication` supports `--categories`.
- [x] Passing multiple categories via `--categories` works correctly (e.g., `--categories housing politics`).
- [x] Unit tests verify both Python and CLI options for categories work as expected.
