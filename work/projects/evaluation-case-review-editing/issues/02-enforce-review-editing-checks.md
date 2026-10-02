# 02 Run review editing checks on every pull request

Labels: ready-for-agent

## Parent

[Evaluation Case review editing](../PRD.md)

## What to build

Make a pull request fail when the review editing module violates its durability
or ordering contract. Normal CI runs its deterministic Node checks alongside
the existing Python checks. Maintainers have documented local commands for both
and can distinguish these checks from the optional browser workflows.

## Acceptance criteria

- [ ] Normal pull-request CI explicitly installs Node 22 and runs the review
      editing tests with Node's built-in runner. Tests are required to pass and
      are not conditional on a browser opt-in variable or a preinstalled runtime.
- [ ] Existing deterministic pytest still runs through uv. The new checks require
      no browser, npm package installation, model service, or database service.
- [ ] Reviewer documentation explains the editing module's ownership and gives
      the exact local Node and uv test commands. It retains the optional browser
      command and states which behaviors still require browser verification.
- [ ] The Node review-editing checks, focused reviewer Python checks, and full
      deterministic Python suite pass. Record counts, commands, and any existing
      skips or warnings accurately. Browser tests remain unexecuted.
- [ ] The final diff preserves review files, report identity, public review JSON,
      shortcuts, and trace presentation, and contains no new mutable-state access
      from the page into the module. Standards and spec review findings are fixed
      before the implementation is considered complete.
- [ ] Ticket completion comments record the evidence, and the parent PRD and
      work index reflect the completed project once all acceptance criteria pass.

## Blocked by

- [01 Concentrate Evaluation Case review editing](01-concentrate-review-editing.md)

## Verification

Run the same Node command used by CI and the repository's full deterministic
pytest command through uv. Inspect the workflow and retained browser tests
without launching a browser. The final green pull request supplies CI evidence;
do not call checks green while required runs are still pending.
