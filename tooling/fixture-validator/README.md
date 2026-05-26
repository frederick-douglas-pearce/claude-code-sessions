# fixture-validator/

CI gate that refuses to publish fixtures lacking proof of sanitization.

**Status:** Planned. Not yet implemented.

## Purpose

Every `.jsonl` file in `fixtures/sanitized/` must have a corresponding `<filename>.scrubbed` sidecar. Every `.jsonl` file in `fixtures/synthetic/` must have a `<filename>.generator.md` sidecar. No `.jsonl` files may exist outside those two directories. The validator enforces this in CI.

## Planned checks

1. **Sidecar presence**
   - Every `.jsonl` in `fixtures/sanitized/` has a `.scrubbed` sidecar
   - Every `.jsonl` in `fixtures/synthetic/` has a `.generator.md` sidecar
2. **Sanitizer version validity**
   - The `.scrubbed` sidecar names a sanitizer version that exists in `tooling/sanitizer/`
3. **No stray fixtures**
   - Repo-wide scan: no `.jsonl` exists outside `fixtures/sanitized/` or `fixtures/synthetic/`
4. **Defense-in-depth pattern scan** (optional, configurable)
   - Re-runs the secret-pattern library against every fixture
   - Flags anything that looks like an unscrubbed credential or path

## Failure modes

Validator failures are blocking on CI. They cannot be bypassed without an explicit override commit message (TBD policy, probably `[skip-fixture-validator]` with reviewer sign-off documented in the PR).

## Implementation note

The validator is a small Python script (~100 lines) that walks the repo and applies the checks above. It's separate from the sanitizer because:

- It runs in CI on every PR; the sanitizer runs locally when a contributor creates a fixture
- It needs no rule library, just file-presence and pattern checks
- Keeping them separate means the validator can flag fixtures sanitized at an unknown version (e.g., if `tooling/sanitizer/` is later restructured)
