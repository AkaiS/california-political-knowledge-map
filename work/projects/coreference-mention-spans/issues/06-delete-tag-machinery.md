# 06 — Delete the tag machinery

**What to build:** Removal of the `<ref>` tag mechanism now that nothing calls it.
The contract step of this project: from ticket 03 onward these functions sit
unused, and this ticket deletes them so the module carries one coreference
mechanism instead of two.

Going: the tag stripper, the whitespace normalizer, the Structural Identity
Check, the tag-to-entity replacement, the markdown fence cleaner, the
`structural_mismatch` failure type and its branch of the retry loop, and every
test covering them. A reader of the module afterwards should find no evidence
that annotation was ever done by rewriting text.

This is deletion only. No behaviour changes.

**Blocked by:** 05 — Zero-survivor failures and Dead Letter Queue payload.

**Status:** ready-for-agent

- [ ] The tag stripper, whitespace normalizer, Structural Identity Check, tag-to-entity replacement, and markdown fence cleaner no longer exist in the codebase.
- [ ] The `structural_mismatch` failure type and its branch of the retry loop no longer exist.
- [ ] Tests covering the deleted functions are removed rather than skipped or left asserting nothing.
- [ ] No remaining code or prompt in the codebase references `<ref>` tags.
- [ ] The full test suite passes, and no test was weakened to make it pass.
- [ ] Resolved text produced before and after this ticket is identical for the same inputs.
