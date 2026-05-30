# sanitizer/

CLI tool that scrubs raw Claude Code session JSONL files for safe publication.

**Status:** Designed (v0 PRD landed 2026-05-29); implementation pending.

**Design:** [`prd-sanitizer.md`](../../.claude/specs/prd-sanitizer.md) is the canonical v0
design. Where this README's sketches differ from the PRD — notably the [Sidecar format](#sidecar-format)
and [Rule sources](#rule-sources) sections below — the PRD wins. The PRD is kept current;
this README is a high-level pointer.

## Design goals

- **Standalone CLI** — usable independent of any sibling project; eventually publishable as a standalone package
- **Layered rules** — path scrub → identifier scrub → secret-pattern scrub → optional statistical jitter
- **Versioned output** — every scrubbed file carries the sanitizer version in its `.scrubbed` sidecar; downstream consumers can trust or distrust by version
- **Testable** — bad scrubs fail tests, not slip through to publication. Known-bad input fixtures drive the test suite.
- **Fail-closed** — if any rule errors, the file is not produced. No partial scrubs.
- **No silent transforms** — the `.scrubbed` sidecar enumerates every substitution made, so a reviewer can audit

## Planned shape

```
sanitizer/
├── pyproject.toml
├── src/
│   └── ccs_sanitize/
│       ├── __init__.py
│       ├── cli.py
│       ├── rules/
│       │   ├── paths.py
│       │   ├── identifiers.py
│       │   ├── secrets.py
│       │   └── jitter.py
│       └── sidecar.py
├── tests/
│   ├── unit/
│   └── fixtures/         # known-bad inputs that must be scrubbed correctly
└── README.md
```

Likely published as `claude-code-sessions-sanitizer` (or short alias like `ccs-sanitize`) once stable.

## Rule sources

- **Path/identifier scrubbing** — bespoke to this project; rules configurable per-project via a yaml file
- **Secret-pattern detection** — reuse the pattern library from [AgentFluent's `detect_secrets_in_output.py`](https://github.com/frederick-douglas-pearce/agentfluent/blob/main/.claude/hooks/detect_secrets_in_output.py) (Anthropic API keys, GitHub PATs, AWS keys, Google API keys, etc.)

## Sidecar format

Every scrubbed output file gets a `<filename>.scrubbed` sidecar:

```yaml
sanitizer_version: 0.1.0
input_hash: sha256:...     # hash of the unscrubbed input (for traceability, not stored)
scrubbed_at: 2026-MM-DD
rules_applied:
  - paths: 14 substitutions
  - identifiers: 3 substitutions
  - secrets: 0 matches
  - jitter: disabled
substitutions:             # one line per substitution, sorted by rule
  - paths: "/home/realuser/" → "/home/user/"
  - identifiers: "realname@example.com" → "user@example.com"
  ...
```

## Not in scope (for v0)

- GUI / interactive review mode
- Streaming sanitization of live sessions
- Automatic upload to any destination
- Reverse-mapping (the scrub is one-way)

## Open questions — resolved

These four questions originally gated implementation. All are resolved in
[`prd-sanitizer.md` §15](../../.claude/specs/prd-sanitizer.md#15-open-questions--resolutions):

1. ~~Yaml-configured rule sets vs. code-defined rules~~ → **Hybrid** (D-1): secrets in code (non-weakenable; additive YAML extension), paths/identifiers in YAML.
2. ~~Sidecar: embed substitution dictionaries vs. rule-level counts~~ → **Redacted detail** (D-2): per-substitution detail with category placeholders and the non-sensitive replacement; secrets count-only; originals never recorded.
3. ~~Statistical jitter granularity~~ → **Deferred to v1** (D-3); designed as a per-session timestamp offset coupled to a future session-bundle mode.
4. ~~Fixture-validator integration~~ → **Independent re-scan** (D-4); the validator never trusts the sidecar.

The PRD also adds [D-7](../../.claude/specs/prd-sanitizer.md#decision-d-7--v0-drops-high-risk-line-types):
v0 drops `file-history-snapshot` and `attachment` lines wholesale rather than scrub arbitrary
file bodies or opaque binary payloads.
