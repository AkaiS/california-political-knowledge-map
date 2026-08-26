# California Political Knowledge Map
California Political Knowledge Map is a web application that reduces voting friction in California politics. It does this by mapping news articles, legislative data, ballot information, etc. in order to answer natural language questions about California politics in as few queries as possible.

## Tech Stack and Architecture
- Language: Python 3.13.5
- Data validation: Pydantic v2
- LLM Providers: 
- Agent Framework: Pydantic AI
- Evals Framework: pydantic-evals
- Orchestration: 
- DB: neo4j (Graph Database)
- LLM Tooling:
- CI/CD: 

## A note from me
We have a shared vocabulary that we have defined in our domain docs. We should be working with this domain language in mind, not as a frozen vocabulary but as an agreed upon source of meaning.

We should avoid building anything that is already solved by libraries we are using. Additionally, we should engage in a 'measure twice, cut once' and yagni mentality. 

## Operational Constraints
- Always use `uv`. Don't call global versions of python, pip, etc.

## Worktrees
- Use ./scripts/setup-worktree.sh after spinning up a new worktree to set it up.

## Repo Organization

### Issue tracker

Issues and PRDs live as local Markdown under `work/`; `work/README.md` is the
authoritative entry point. `.scratch/` is reserved for disposable runtime
output. See [issue-tracker.md](file:///Users/akaisenghor/Projects/california-political-knowledge-map/main/docs/agents/issue-tracker.md).

### Triage labels

Triage roles map to default label strings (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See [triage-labels.md](file:///Users/akaisenghor/Projects/california-political-knowledge-map/main/docs/agents/triage-labels.md).

### Domain docs

Uses the "single-context" layout, with a single `CONTEXT.md` and `docs/adr/` at the repository root. See [domain.md](file:///Users/akaisenghor/Projects/california-political-knowledge-map/main/docs/agents/domain.md).

## Documentation
- Comments exist to describe the problem the code is solving. When a function is moved, so should the comments.
- The place to document architectural decisions is never directly in the code.

## Additional
- Don't verify with the browser or computer use unless asked for by the dev.