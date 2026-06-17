# sanitizer/

CLI tool that scrubs raw Claude Code session JSONL files for safe publication.

**Status:** Implemented and in use (v0.2.0). All transform layers (path → identifier → secret-pattern, with the statistical-jitter stub) ship behind the `ccs-sanitize` CLI, covered by the `pytest` suite under [`tests/`](tests/). See [`CHANGELOG.md`](CHANGELOG.md) for release history.

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

## Layout

```
sanitizer/
├── pyproject.toml          # entry point: ccs-sanitize
├── CHANGELOG.md
├── src/
│   └── ccs_sanitize/
│       ├── __init__.py     # __version__
│       ├── cli.py          # argument parsing, --init, --no-check
│       ├── config.py       # resolve + validate the .ccs-sanitize.yaml rule set
│       ├── orchestrator.py # fail-closed driver: scrub or produce nothing
│       ├── pipeline.py     # per-line transform pipeline
│       ├── residual.py     # post-scrub residual-leak scan
│       ├── sidecar.py      # emit the .scrubbed audit sidecar
│       ├── subtable.py     # substitution bookkeeping
│       ├── rules/
│       │   ├── _engine.py
│       │   ├── paths.py
│       │   ├── identifiers.py
│       │   ├── secrets.py
│       │   └── jitter.py   # statistical jitter (stub for v0)
│       └── _templates/     # --init config templates
└── tests/                  # pytest suite — one module per rule + orchestration
```

Installed locally as the `ccs-sanitize` console script (see `pyproject.toml`); not yet published to a package index.

## Rule sources

- **Path/identifier scrubbing** — bespoke to this project; rules configurable per-project via a yaml file
- **Secret-pattern detection** — reuse the pattern library from [AgentFluent's `detect_secrets_in_output.py`](https://github.com/frederick-douglas-pearce/agentfluent/blob/main/.claude/hooks/detect_secrets_in_output.py) (Anthropic API keys, GitHub PATs, AWS keys, Google API keys, etc.)

## Sidecar format

Every scrubbed output file gets a `<filename>.scrubbed` sidecar:

```yaml
sanitizer_version: 0.2.0
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

## Getting started

The live `.ccs-sanitize.yaml` holds the literal PII strings the sanitizer
will scrub (real home dir, real email, real name, etc.) and is gitignored.
The committed `.ccs-sanitize.example.yaml` is a schema-only template. New
users (or forks) bootstrap with three steps:

```bash
ccs-sanitize --init                 # writes .ccs-sanitize.example.yaml +
                                    # .ccs-sanitize.yaml in the cwd from the
                                    # bundled template. Does NOT mutate .gitignore.
$EDITOR .ccs-sanitize.yaml          # fill in your real match values
ccs-sanitize <input> -o <output>    # the pre-run gitignore guard refuses
                                    # to scrub unless .ccs-sanitize.yaml is
                                    # gitignored (opt out with --no-check)
```

The pre-run gitignore guard is built in and runs on every invocation —
exit code 3 with an actionable message if the resolved config is not
gitignored. `--no-check` opts out (for CI environments without a `.git`
directory and for the test suite). The threat model and the full layered
defenses are documented in
[PRD §12b](../../.claude/specs/prd-sanitizer.md#12b-config-storage-and-safety).

## Development

The package is `uv`-managed and Python 3.11+. From `tooling/sanitizer/`:

```bash
uv venv
source .venv/bin/activate
uv pip install -e ".[dev]"
pytest                          # run the test suite
ccs-sanitize --version          # smoke-check the entry point
```

The runtime dependency surface is intentionally minimal (stdlib + PyYAML
once the config loader lands in #19). `pytest` is the only dev dep.

Version bumps follow [`CHANGELOG.md`](CHANGELOG.md)'s "bump on any
byte-affecting change" policy — because the value lands in every
`.scrubbed` sidecar and downstream consumers gate on it.

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
