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

### Fixed (review pass on issue #19)
- **PEM private-key pattern now catches `ENCRYPTED PRIVATE KEY`** (standard
  PKCS#8 encrypted PEM, the output of `openssl pkcs8` and passphrase-
  protected `ssh-keygen`). Previously only the unencrypted variants matched,
  so an encrypted private key in session output could slip past both scrubs
  and the residual scan.
- `extra_secret_patterns` now mirror path/identifier rule semantics: bare
  strings are treated as literals (`re.escape`'d), `re:`-prefixed strings
  are compiled as regex. The earlier loader compiled bare strings raw, so
  `pattern: "C++"` silently became a regex with a quantifier.
- `extra_secret_patterns` with `pattern: "re:"` now raises `ConfigError`
  (same guard `_compile_rule` has for paths/identifiers). The previous
  loader accepted the empty regex, which matches every position and would
  trip the I-3 guard against every rule.
- `version` is now type-checked. YAML `version: true` (parses to Python
  `True`) and `version: 1.0` were silently accepted because Python treats
  `True == 1` and `1.0 == 1`; the loader now requires an `int` that is
  not a `bool`.
- I-3 replacement-leak guard no longer skips the self-rule comparison,
  so a rule whose own `replace` contains its own `match` (a non-
  idempotent rule that would leak the original pattern through the
  sidecar) is rejected with a focused error.
- `Config` field lists (`paths`, `identifiers`, `extra_secret_patterns`)
  are converted to tuples in `__post_init__`. `@dataclass(frozen=True)`
  blocks attribute reassignment but not list mutation; with mutable lists,
  downstream code could `config.paths.append(...)` after `load_config`
  returned, bypassing the I-3 guard.
- `load_config(path)` now expands `~` in the input path. Quoted
  `--config '~/.ccs-sanitize.yaml'` from the CLI was previously raising
  `FileNotFoundError` against a literal tilde.
- `read_text(encoding="utf-8")` errors and other `OSError` from the read
  step are now wrapped in `ConfigError` so the CLI's (eventual)
  `ConfigError` → exit 3 mapping catches them; previously a Windows
  UTF-16-saved config would surface as a bare `UnicodeDecodeError` and
  bypass the documented exit-code contract.
- Empty YAML sections — `paths:`/`identifiers:`/`extra_secret_patterns:`
  with no value (parses to `None`) — are now treated as empty lists,
  matching how `options:` already handles `None`. Previously the loader
  raised `ConfigError("paths must be a list, got NoneType")` for an
  ergonomic shape that should mean "no rules".
- `_check_replacement_leak` now uses a module-level `_BUILTIN_COMPILED`
  table instead of recompiling `SECRET_PATTERNS` on every call. The
  table compiles at module import, so a future typo in a vendored or
  batch pattern surfaces at import time, not on first config load.
- `ConfigOptions` defaults are owned by the dataclass; `_build_options`
  forwards only YAML-present keys instead of restating each default.
  Previously the defaults lived in both places and could drift.
- `Rule` and `ExtraSecretPattern` validate that `compiled.pattern` and
  `is_regex` are consistent with `pattern` in `__post_init__`. Both
  types are exported via `__all__`; without the check, a direct
  `Rule(pattern="/foo", compiled=re.compile("BAR"))` would lie about
  itself and pass through the I-3 guard miscompared.

Test suite grew from 31 to 44 cases (13 new, all passing) covering the
above, including bare-string-as-literal behavior, encrypted PEM
matching, and tuple-vs-list immutability.

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
