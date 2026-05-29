<!--
PRs are required for changes under tooling/, .claude/hooks/, .github/, and fixtures/.
Content/docs (posts/, social/, reference/, copy edits) may go direct to main.
Replicate every section below; squash-merge to main.
-->

## Summary

<!-- 1-3 bullets: what this PR does and why. Reference the issue (e.g. Closes #12). -->

## Test plan

<!-- Check what applies; not every row applies to every PR. -->

- [ ] Hook tests pass: `python3 .claude/hooks/tests/test_hooks.py` (for `.claude/hooks/` changes)
- [ ] Fixtures validated (for `fixtures/` changes — once the validator exists)
- [ ] Tooling exercised locally (for `tooling/` changes)
- [ ] Rendered / fact-checked the change (for `reference/` or substantial content)

## Security review

<!-- This repo documents a format that can carry secrets. Confirm all that apply. -->

- [ ] **No raw session JSONL** — only synthetic fixtures, or sanitized fixtures with a `.scrubbed` sidecar.
- [ ] **No secrets** in fixtures, posts, examples, or commit history.
- [ ] **Closer read done** if this PR touches `.claude/hooks/`, `tooling/sanitizer/`, `fixtures/`, `tooling/publish-to-pages.py`, path/JSONL parsing, or `.github/workflows/`.

## Breaking changes

<!--
Does this change a contract that AgentFluent/CodeFluent or readers depend on? If yes, describe before/after. Examples:
- A reference/ field definition changed meaning
- A fixture's shape or filename changed
- Sanitizer CLI flags or .scrubbed sidecar format changed
-->
