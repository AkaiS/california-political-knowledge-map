# Issue tracker: Local Markdown

Planned and active work for this repo lives as Markdown under `work/`.
`work/README.md` is the authoritative entry point. The `.scratch/` directory is
reserved for disposable runtime output such as logs, locks, generated reports,
and Dead Letter Queue records.

## Conventions

- Large, uncertain work is an initiative under
  `work/initiatives/<initiative-slug>/`.
- One bounded project lives at `work/projects/<project-slug>/`.
- A project's PRD is `work/projects/<project-slug>/PRD.md`.
- Project issues are
  `work/projects/<project-slug>/issues/<NN>-<slug>.md`, numbered from `01`.
- Standalone defects live in `work/issues/`.
- Unshaped ideas and reports go to `work/inbox.md`; do not create an issue until
  they have been triaged.
- Triage state is recorded only as a `Labels:` line near the top of each work
  item. Do not add a separate `Status:` field.
- Each work item has exactly one triage-state label. Additional descriptive
  labels may appear on the same comma-separated line.
- See `triage-labels.md` for the triage-state vocabulary.
- Comments and conversation history append to the bottom of the file under a `## Comments` heading

## When a skill says "publish to the issue tracker"

Publish the artifact the user requested:

- A spec or PRD goes in `work/projects/<project-slug>/PRD.md`. Create the project
  directory or update its existing PRD, and link the PRD from `work/README.md`.
  Publishing the spec completes a spec-only request. The PRD directly anchors
  any later implementation tickets; it needs no umbrella or handoff issue.
- Create implementation issues only when the user requests tickets or issues.
  Add them to the project's `issues/` directory using the conventions above.
  Existing issues remain in place when publishing or revising a spec.
- Put an unshaped report in `work/inbox.md` instead.

## When a skill says "fetch the relevant ticket"

Read the file at the referenced path. The user will normally pass the path or the issue number directly.
