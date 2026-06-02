# fixtures/

Sample session JSONL files for use in posts, reference docs, and tests.

## Security policy

**Raw session data is never committed to this repository.** Two acceptable paths exist:

### `sanitized/`

Files derived from real session JSONL, scrubbed by `tooling/sanitizer/`. Every file in this directory **must** have a sidecar `<filename>.scrubbed` proving it passed validation at a known sanitizer version. The fixture-validator CI gate rejects PRs that add files here without a sidecar.

Before scrubbing, the sanitizer needs a `.ccs-sanitize.yaml` config holding the literal PII strings to replace — that file is **sensitive** and gitignored. Bootstrap with `ccs-sanitize --init`, then fill in your match values; the built-in pre-run guard refuses to scrub unless the config is gitignored. See [PRD §12b](../.claude/specs/prd-sanitizer.md#12b-config-storage-and-safety) for the threat model and defense layers.

The sanitizer scrubs:

- File paths (replaced with placeholders like `/home/user/project/`)
- User identifiers (usernames, email addresses, machine names)
- Secret patterns (API keys, tokens — defense in depth on top of secret-detection hooks)
- Custom project-specific identifiers (configurable per project)

It does **not** scrub:

- The structural shape of the data (field names, message types, tool names)
- Token counts, timestamps, durations (unless statistical jitter is explicitly enabled for a given fixture)
- Public tool names (Read, Write, Edit, Bash, Agent, etc.)

### `synthetic/`

Files fabricated for illustration — never derived from real sessions. Each synthetic fixture documents its origin in a sibling `<filename>.generator.md` file (which script created it, by-hand authoring notes, etc.).

**Synthetic is the safe default.** Use sanitized only when you need data shape that synthetic generation can't realistically reproduce (e.g., a multi-hour real subagent trace).

## Filename convention

`<scenario>-<short-description>.jsonl`

Examples:

- `subagent-trace-pm-invocation.jsonl`
- `tool-error-permission-denied.jsonl`
- `multi-turn-retry-loop.jsonl`
- `cache-hit-warm-session.jsonl`

## Adding a fixture

1. **Generate or sanitize** — use the appropriate `tooling/` CLI
2. **Verify by hand** — read the file end-to-end and confirm no real data leaked. The tooling is defense-in-depth, not a guarantee.
3. **Run the fixture-validator** — `<command TBD once tooling lands>`
4. **Commit** — `.jsonl` file alongside its `.scrubbed` (sanitized) or `.generator.md` (synthetic) sidecar
5. **Reference** — link to it from the post or reference doc that uses it

## If you find leaked data

If you find a file in this repo that contains real personal data (paths, names, secrets), **file an issue immediately** and the file will be removed via history rewrite. Don't fix it in a regular PR — credentials in git history persist even after deletion.
