# sanitizer/

CLI tool that scrubs raw Claude Code session JSONL files for safe publication.

**Status:** Planned. Not yet implemented.

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

## Dependencies on this scaffold

The sanitizer needs its design pass before implementation. Open questions:

1. Yaml-configured rule sets vs. code-defined rules
2. Should the sidecar embed substitution dictionaries (more reviewable but also more leaky), or just rule-level counts?
3. Statistical jitter granularity — per-field, per-message, per-session?
4. Integration with the fixture-validator (does the validator re-scan, or trust the sidecar?)
