# Changelog — `claude-code-sessions-sanitizer`

All notable changes to this package will be documented here. The version
recorded in every `.scrubbed` sidecar (`sanitizer_version:` field, PRD section 10)
references this file.

## Bump policy

**Bump on any change that could alter the produced output bytes.** That
includes, non-exhaustively:

- New or modified path / identifier / secret rules.
- New entries in `VENDORED_PATTERNS` or `BATCH_PATTERNS`.
- Any change to the line-loop, the structural traversal skip-list, or the
  set of stripped line types.
- Changes to JSON serialization parameters (separators, key order, ASCII
  escaping) or the sidecar emission contract.
- Bug fixes in a regex that change which inputs match.

A bug fix that does **not** change which inputs match (e.g., refactoring a
helper, fixing an error message) does not require a bump.

The rule is conservative because the PRD's determinism contract — "same input
+ same config → byte-identical output" — only holds *within* a sanitizer
version. Downstream consumers (the fixture-validator, sibling projects) gate
on the sidecar's `sanitizer_version`. If the bytes change without the version,
the contract is meaningless.

Use semver: `MAJOR.MINOR.PATCH`.

- `PATCH` — bug fix that changes which inputs match a rule (no rule added or
  removed; no config-surface change).
- `MINOR` — new rule, new pattern, new CLI flag, new sidecar field. Backward
  compatible at the config-surface level.
- `MAJOR` — sidecar format change, config schema break, removal of a built-in
  pattern, or any change requiring re-running the sanitizer on previously
  scrubbed sessions.

## [Unreleased]

### Added (issue #19)
- YAML config loader at `ccs_sanitize.config.load_config`. Reads a `.ccs-sanitize.yaml`
  per PRD §12 schema and returns a typed `Config` (with `Rule`, `ExtraSecretPattern`,
  `ConfigOptions` sub-types). Surfaces `ConfigError` (a `ValueError` subclass) for
  malformed YAML, schema violations, invalid regex, attempts to add unknown keys, and
  I-3 replacement-leak failures. A missing file surfaces as `FileNotFoundError` so the
  CLI (#26) can map it to exit 1 distinct from `ConfigError` → exit 3 (PRD §11).
- Replacement-leak guard (I-3) at config load time: any path/identifier `replace:`
  value that matches any other path rule, any identifier rule, any built-in
  `SECRET_PATTERNS` entry, or any `extra_secret_patterns` regex is rejected with a
  message naming both the offending rule and the rule it leaked into.
- `VENDORED_PATTERNS` (Tier-1, copied verbatim from
  `.claude/hooks/detect_secrets_in_output.py`) and `BATCH_PATTERNS` (Tier-2, the §9
  sanitizer-only additions: PEM keys, bearer tokens, JWTs, DB connection strings,
  Slack tokens) land in `rules/secrets.py` so the I-3 guard has something to validate
  against. `SECRET_PATTERNS = VENDORED_PATTERNS + BATCH_PATTERNS`. The hook sync-test
  (I-4) and the scrub logic still land with #23.
- `PyYAML>=6` added to runtime dependencies. YAML parsing uses `yaml.safe_load`.

No version bump: this PR adds importable machinery but does not yet produce
output bytes. Per the bump policy above, the next byte-affecting story will
carry the bump.

## [0.1.0] — 2026-05-29

Initial scaffold (issue #18). No transform logic yet.

- `claude-code-sessions-sanitizer` package skeleton, hatchling-built.
- `ccs-sanitize` entry point with `--version`. Parser exits 1 on usage
  errors (PRD section 11 reserves exit 2 for safety failures).
- Stub modules for the PRD section 6 module layout.
- `rules/jitter.py` carries the v1 design (PRD section 9b) and a
  `JITTER_DISABLED = True` sentinel.
- Python 3.11+. Zero runtime dependencies. `pytest` is a dev extra.
