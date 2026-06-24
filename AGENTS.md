## Tech Stack and Architecture
- Language: Python 3.13.5
- Data validation: Pydantic v2
- LLM Providers: 
- Agent Framework: Pydantic AI
- Evals Framework: 
- Orchestration: 
- DB: neo4j (Graph Database), (semantic cache / msg queue)
- LLM Tooling:
- CI/CD: 

## Operational Constraints
- Always use `uv`. Never install packages globally.

## Agent skills

### Issue tracker

Issues and PRDs live as local markdown files under `.scratch/`. See [issue-tracker.md](file:///Users/akaisenghor/Projects/california-political-knowledge-map/docs/agents/issue-tracker.md).

### Triage labels

Triage roles map to default label strings (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See [triage-labels.md](file:///Users/akaisenghor/Projects/california-political-knowledge-map/docs/agents/triage-labels.md).

### Domain docs

Uses the "single-context" layout, with a single `CONTEXT.md` and `docs/adr/` at the repository root. See [domain.md](file:///Users/akaisenghor/Projects/california-political-knowledge-map/docs/agents/domain.md).