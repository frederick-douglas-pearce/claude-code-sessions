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

### Added (issue #21)
- Layer 1 path scrubbing at `ccs_sanitize.rules.paths.build_path_transform`.
  Factory takes a `Sequence[Rule]` (typically `Config.paths`) plus a shared
  `SubstitutionTable` and returns a `TransformCallback` ready for
  `run_pipeline(transform=...)`. Per visited leaf, applies each rule's
  `re.sub` in declaration order; regex rules expand backrefs via
  `Match.expand`, literal rules use `replace` verbatim. Every match is
  recorded in the table so the sidecar (PRD §10) sees per-mapping
  occurrence counts and cross-line consistency holds.
- Declaration-order semantic is documented in the module. Two limitations
  of sequential application are called out so a future swap to a combined
  alternation regex doesn't change behavior silently: (a) leftmost-position
  divergence when one rule's match starts to the right of another's in the
  same leaf; (b) backref-bearing regex rules whose runtime-expanded
  replacement matches a later rule's pattern (the I-3 leak guard checks
  the literal `replace` template, not the expansion, so a config like
  `re:foo-(.+) -> bar-\1` plus literal `bar-x -> Z` passes I-3 but
  cascades at runtime). Output stays scrubbed and deterministic in both
  cases.
- Zero-width regex matches (lookahead-only patterns, `\b`, `^`) no longer
  pollute the substitution table with `('' -> X)` rows. `_apply_rule`'s
  callback short-circuits empty matches so the sidecar's audit log only
  carries interpretable mappings; the zero-width substitution itself
  becomes a no-op at that position.

Tests (`test_paths.py`, 14 cases): home-dir replacement across the surfaces
the issue body names (`cwd`, `tool_use.input.file_path`,
`toolUseResult.stdout`/`stderr`); project-slug regex with backref-preserved
project name; slug + cwd surfaces both scrubbed in one pipeline run;
cross-line consistency (same input → same placeholder across 3 lines, one
table entry with `occurrences=3`); first-match-wins ordering (more-specific
first vs general first); duplicate-rule dead-code case; two-runs-byte-
identical determinism (now also asserts table-snapshot equality, not just
output bytes); non-matching leaves pass through; empty rules = identity;
backref cascade past the I-3 guard (regression pin for limitation b);
zero-width match does not pollute the subtable.

No version bump: this PR adds importable machinery but the CLI (#26) does
not yet feed it. Output bytes from `ccs-sanitize` are still identity-pass.
Per the bump policy, the next byte-affecting story carries the bump.

### Changed (PEM coverage promoted to the live hook)
- `pem-private-key` is now a **Tier-1** pattern: present both in
  `VENDORED_PATTERNS` (sanitizer) and in the hook's `SECRET_PATTERNS`
  (`.claude/hooks/detect_secrets_in_output.py`). Previously the sanitizer
  carried it in `BATCH_PATTERNS` and the hook had no PEM coverage at all —
  so a live `cat ~/.ssh/id_rsa` or `openssl pkcs8` output (the
  catastrophic case the hook exists for) was not getting the block-from-
  further-propagation guard the hook provides for API tokens. The pattern
  shape is unchanged from the §19 review pass (still includes the
  `ENCRYPTED ` PKCS#8 variant).
- PRD §9 updated: the Tier-1 list now ends with `pem-private-key`; the
  Tier-2 rationale updated to "patterns the hook does not currently catch"
  (no longer "never had to catch" — that framing was an oversight). A
  separate backlog issue (#32) tracks whether the remaining Tier-2 patterns
  (JWT, bearer-token, conn-string-pw, slack-token) should follow.
- New hook test fixture `block_pem_private_key.json` and matching test
  case in `.claude/hooks/tests/test_hooks.py`.

### Fixed (review pass on issue #20)
- `default_skip_predicate` no longer over-skips bare `id` / `signature` /
  `model` field names that appear inside user-controlled content. PRD §6b B
  scopes these to specific parent paths (`message.model`, `message.id`,
  `tool_use.id`, `thinking.signature`); the predicate now anchors them via
  a `(parent, last)` set so e.g. an MCP `tool_use.input.id` value is visited
  by the transform and scrubbed by future rule layers instead of slipping
  through. `id`, `signature`, and `model` were removed from the
  unconditional bare-name set.
- `"usage" in path` was replaced with an immediate-parent check
  (`path[-2] == "usage"`). The previous membership-anywhere test would skip
  any descendant of any field literally named `usage` at any depth — over-
  broad relative to the PRD section 6b B scope.
- `run_pipeline` now fail-closes on non-object JSONL roots (a bare string /
  number / array slipping past the strip-types gate and being silently
  walked), on missing `type` field, and on non-string `type` field. Each
  raises `PipelineError` with the source line number. PRD §11 says shape
  violations should abort.
- `PipelineError` messages now reference the 1-indexed *input* line number
  rather than the post-filter record index, so users can locate the bad
  line in their source file when blank lines precede it.
- `SubstitutionTable.__iter__` snapshots the entries via `list(...)` so
  concurrent `record()` calls during iteration do not raise
  `RuntimeError: dictionary changed size during iteration`. A test pins
  the snapshot semantics.
- `serialize_line` adds `allow_nan=False`; NaN/Infinity input now raises
  `PipelineError` (`non-finite number in input`) instead of producing
  non-RFC-8259 JSON output that downstream strict parsers would reject.
- `PipelineCounts.stripped_lines` is now a `MappingProxyType`, not a raw
  mutable dict. The dataclass is frozen at the attribute level only; the
  proxy prevents callers from mutating the sidecar's tallies after the
  fact via the dict reference.
- `serialize_line` docstring weakened to the actually-achievable claim:
  two runs over the same parsed object produce byte-identical output. The
  previous "byte-stable for byte-stable input" wording was false for any
  numeric literal that `json.dumps` normalizes (e.g., `1e10` →
  `10000000000.0`).
- `make_skip_predicate(*, remap_uuids=False)` factory introduced so the
  identifier rule layer (#22) can produce a predicate that does NOT skip
  UUID fields when the user sets `remap_uuids: true` per PRD §8.
  `default_skip_predicate` is now the factory's no-arg result.
- `walk_strings` recursion moved into a nested helper; the public
  signature no longer exposes the `_path` recursion-state keyword that
  callers could accidentally pass.
- `SubstitutionTable` internal storage moved from `dict[str, list[object]]`
  with four `# type: ignore` markers to a typed `dict[str, _Row]` where
  `_Row` is a small mutable dataclass. No public behavior change; the
  `Entry` frozen view is unchanged.
- Test helper `_line()` now delegates to `serialize_line` instead of
  reimplementing it (the previous shadow implementation omitted
  `ensure_ascii=False`, which would have drifted from production if a
  fixture ever used non-ASCII).

### Added (issue #20)
- Pipeline core at `ccs_sanitize.pipeline.run_pipeline`. Line loop with
  Step A (strip-types per PRD §6b A / D-7: `file-history-snapshot` and
  `attachment` dropped wholesale by default, with per-type counts surfaced
  on the returned `PipelineCounts`) and Step B (structural traversal via
  `walk_strings`, which visits every string leaf whose JSON path is not
  skip-listed and calls a caller-supplied transform).
- `default_skip_predicate` encoding the PRD §6b B skip-list as a function
  over JSON paths: `version`/`type`/`role`/`model`, all UUID-graph fields
  (`uuid`/`parentUuid`/`sessionId`/`agentId`), id fields
  (`id`/`requestId`/`tool_use_id`), thinking signatures, any field whose
  name ends in `_tokens`, and any field under `usage` defensively. List
  indices are intentionally not part of the JSON path.
- `serialize_line` pins JSON output per PRD §11 I-1:
  `separators=(",", ":")`, `ensure_ascii=False`, and original key order
  preserved (no sort). Determinism is testable because of this pin.
- `PipelineError` typed exception on malformed JSONL — no
  `--skip-malformed` escape hatch in v0 per PRD §11.
- `SubstitutionTable` in `ccs_sanitize.subtable`: a deterministic,
  insertion-order-preserving map from original to replacement with an
  occurrence counter per entry. Records that conflict (same original,
  different replacement) raise `SubstitutionConflictError` so a rule
  layer cannot silently overwrite an established substitution.

Tests (`test_pipeline.py`, `test_subtable.py` — 27 cases): strip-types
behavior and counts; structural traversal across both `message.content`
shapes, tool_use inputs, tool_result content, and toolUseResult fields;
skip-list correctness for every documented field type; serialization
pins (compact separators, unicode preservation, key-order preservation);
malformed-JSONL surfacing as `PipelineError`; blank-line tolerance for
file iteration; determinism across runs; within-file consistency via a
transform funneled through a SubstitutionTable; SubstitutionTable
conflict semantics and iteration ordering.

No version bump: the pipeline is wired only at the import level. No
rule layers feed it yet, so no output bytes change versus a no-op
identity transform. The bump will land with the first byte-affecting
story (likely #21 once the path layer wires in).

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
