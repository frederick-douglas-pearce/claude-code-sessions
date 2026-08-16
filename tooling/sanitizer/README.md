# sanitizer/

CLI tool that scrubs raw Claude Code session JSONL files for safe publication.

**Status:** Implemented and in use. All transform layers (path → identifier → secret-pattern, with the statistical-jitter stub) ship behind the `ccs-sanitize` CLI, covered by the `pytest` suite under [`tests/`](https://github.com/frederick-douglas-pearce/claude-code-sessions/tree/main/tooling/sanitizer/tests). See [`CHANGELOG.md`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/tooling/sanitizer/CHANGELOG.md) for release history and the current version.

**Design:** [`prd-sanitizer.md`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/.claude/specs/prd-sanitizer.md) is the canonical
design. Where this README differs from the PRD, the PRD wins. The PRD is kept current;
this README is a high-level pointer.

## Design goals

- **Standalone CLI** — usable independent of any sibling project, and installable on its own from PyPI
- **Layered rules** — path scrub → identifier scrub → secret-pattern scrub → optional statistical jitter
- **Versioned output** — every scrubbed file carries the sanitizer version in its `.scrubbed` sidecar; downstream consumers can trust or distrust by version
- **Testable** — bad scrubs fail tests, not slip through to publication. Known-bad input fixtures drive the test suite.
- **Fail-closed** — if any rule errors, the file is not produced. No partial scrubs.
- **No silent transforms** — the `.scrubbed` sidecar enumerates every substitution made, so a reviewer can audit

## Layout

```
sanitizer/
├── pyproject.toml          # entry point: ccs-sanitize
├── LICENSE                 # verbatim copy of the repo-root LICENSE, shipped in the artifacts
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

## Install

```bash
pip install claude-code-sessions-sanitizer   # installs the `ccs-sanitize` console script
```

The distribution is `claude-code-sessions-sanitizer`; the command it installs is
`ccs-sanitize`. `0.3.0` is the first public release.

The supported public surface is the **CLI** and the **`.scrubbed` sidecar format**. The
Python module surface (`orchestrator`, `pipeline`, `rules`, …) is private and may change
without a MAJOR bump. Customization is meant to happen through the YAML config and
additive `extra_secret_patterns`, which is data rather than code.

## Rule sources

- **Path/identifier scrubbing** — bespoke to this project; rules configurable per-project via a yaml file
- **Secret-pattern detection** — the pattern library lives here, in
  [`rules/secrets.py`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/tooling/sanitizer/src/ccs_sanitize/rules/secrets.py)
  (Anthropic API keys, GitHub PATs, AWS keys, Google API keys, PEM blocks, etc.). That
  copy is the one that ships in this package. This repo is upstream of
  [AgentFluent](https://github.com/frederick-douglas-pearce/agentfluent), whose
  `detect_secrets_in_output.py` hook is a peer consumer of the same Tier-1 set, not its
  source; a sync test in this repo keeps the two element-wise identical so the shipped
  artifact cannot drift below the hook's floor. See
  [PRD D-6](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/.claude/specs/prd-sanitizer.md#decision-d-6--vendor-the-secret-pattern-library).
  Config may **add** patterns via `extra_secret_patterns`; it can never remove a built-in.

## Sidecar format

Every scrubbed output file gets a `<filename>.scrubbed` sidecar. It is an audit record,
not a second copy of the data: it names the *kind* of thing that changed and how often,
and never records an original value. Secrets contribute a count only.

```yaml
sanitizer_version: <version> # the version that produced this file; consumers gate on it
scrubbed_at: 2026-05-31T18:30:00Z
input_filename: real-subagent-trace.jsonl # basename only, never the full path
input_sha256: 9f2c... # one-way hash of the raw input; the hash is stored, the input is not
config_version: 1
config_source: .ccs-sanitize.yaml # basename only
lines_processed: 512 # survivors + stripped + blank lines
stripped_lines: # whole lines dropped by --strip-types
  file-history-snapshot: 8
  attachment: 1
rules_applied:
  paths: { substitutions: 14, distinct: 3 }
  identifiers: { substitutions: 6, distinct: 2 }
  secrets: { matches: 2 } # COUNT ONLY, never the matched bytes
  jitter: disabled
substitutions: # placeholder + replacement, never the original
  - { rule: paths, placeholder: "<home-dir>", replacement: "/home/user", occurrences: 9 }
  - { rule: identifiers, placeholder: "<email>", replacement: "user@example.com", occurrences: 6 }
residual_scan: clean # post-scrub re-scan; a file that is not clean is never written
```

The field-level contract is [PRD §10](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/.claude/specs/prd-sanitizer.md#10-the-scrubbed-sidecar).

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
[PRD §12b](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/.claude/specs/prd-sanitizer.md#12b-config-storage-and-safety).

## Development

The package is `uv`-managed and Python 3.11+. From `tooling/sanitizer/`:

```bash
uv venv
source .venv/bin/activate
uv pip install -e ".[dev]"
pytest                          # run the test suite
ccs-sanitize --version          # smoke-check the entry point
```

The runtime dependency surface is intentionally minimal: stdlib plus PyYAML
for config parsing. `pytest` is the only dev dep.

Version bumps follow [`CHANGELOG.md`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/tooling/sanitizer/CHANGELOG.md)'s "bump on any
byte-affecting change" policy — because the value lands in every
`.scrubbed` sidecar and downstream consumers gate on it.

## Not in scope (for v0)

- GUI / interactive review mode
- Streaming sanitization of live sessions
- Automatic upload to any destination
- Reverse-mapping (the scrub is one-way)

## Open questions — resolved

These four questions originally gated implementation. All are resolved in
[`prd-sanitizer.md` §15](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/.claude/specs/prd-sanitizer.md#15-open-questions--resolutions):

1. ~~Yaml-configured rule sets vs. code-defined rules~~ → **Hybrid** (D-1): secrets in code (non-weakenable; additive YAML extension), paths/identifiers in YAML.
2. ~~Sidecar: embed substitution dictionaries vs. rule-level counts~~ → **Redacted detail** (D-2): per-substitution detail with category placeholders and the non-sensitive replacement; secrets count-only; originals never recorded.
3. ~~Statistical jitter granularity~~ → **Deferred to v1** (D-3); designed as a per-session timestamp offset coupled to a future session-bundle mode.
4. ~~Fixture-validator integration~~ → **Independent re-scan** (D-4); the validator never trusts the sidecar.

The PRD also adds [D-7](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/.claude/specs/prd-sanitizer.md#decision-d-7--v0-drops-high-risk-line-types):
v0 drops `file-history-snapshot` and `attachment` lines wholesale rather than scrub arbitrary
file bodies or opaque binary payloads.
