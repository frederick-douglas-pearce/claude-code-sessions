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

The mechanical check on this list is `tests/test_golden_determinism.py`. It
diffs the produced output and sidecar against committed bytes in
`tests/golden/`, on every interpreter in the CI matrix. **A red golden test is
the bump trigger firing**, so treat it as a finding: confirm the diff is the
change you meant, bump, and record it here — then regenerate the fixture, in
that order. Regenerating first turns the trigger off without answering it.

The rule is conservative because the PRD's determinism contract — "same input
+ same config → byte-identical output" — only holds *within* a sanitizer
version. Downstream consumers (the fixture-validator, sibling projects) gate
on the sidecar's `sanitizer_version`. If the bytes change without the version,
the contract is meaningless.

Versions are semver, `MAJOR.MINOR.PATCH`. **What each level promises to a
consumer is stated once, publicly, in the README's
[Stability and the determinism contract](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/tooling/sanitizer/README.md#stability-and-the-determinism-contract).**
That section is the authority; this file does not restate the level
definitions, so the two cannot drift. What lives here is the maintainer-facing
trigger list above: whether a given change requires a bump at all.

Releases are tagged `sanitizer-v<version>` (component-scoped, not a bare `v*`:
this is a monorepo and a bare tag filter would fire the publish workflow on
unrelated tags).

## [Unreleased]

No version bump: nothing below changes the produced bytes.

### Added (issue #191 — adversarial placement matrix)
- **`tests/test_adversarial_placement.py`** — the parametrized form of the
  structural-traversal test PRD section 14 calls C-1. One planted value at 14
  structural positions (nested tool inputs, `tool_result` content arrays,
  `toolUseResult` siblings, thinking blocks, JSON-inside-a-JSON-string, dict
  keys, URL query parameters) crossed with four payload families. Asserts on
  the verdict (redacted / fail-closed / leaked) rather than on output bytes,
  so the jitter work planned for v1 cannot turn it spuriously red.
  Byte-exactness stays owned by `test_golden_determinism.py`.
- Three cells land as `xfail(strict=True)` against **#190**: a config-driven
  rule cannot reach a value sitting in a dict key, because the structural walk
  transforms string leaves only. A secret in that position still trips the
  residual scan and fails closed; a path or identifier leaks silently with a
  sidecar reading `residual_scan: clean`. Strict, so closing #190 turns those
  cells red and forces them out of `KNOWN_LEAKS`.
- The module drives the console script rather than importing `ccs_sanitize`,
  per D-5a, so one file covers both the source tree and the built artifact.
  `CCS_SANITIZE_BIN` points it at a specific binary; CI uses that to run the
  matrix against the wheel from `python -m build`, which is how #190 was found
  in the first place. It falls back to `python -m ccs_sanitize.cli` rather than
  skipping, because 57 silently-skipped security assertions reporting green is
  the failure this workflow exists to prevent.
- `test_adversarial_placement.py` joins the security-critical presence list in
  `sanitizer-ci.yml`, so deleting or renaming it fails the build.
### Changed (issue #166 — the `ccs-sanitize` name is deliberately unclaimed)
- **README `Install`** now states that no `ccs-sanitize` distribution exists on
  PyPI, that anything published under that name is not this tool, and that the
  omission is deliberate. Reverses the reservation half of ruling Q3, recorded
  as PRD decision D-9: an inert placeholder meets PEP 541's name-squatting
  criterion ("package has no functionality or is empty") and is reclaimable, so
  it would have been cheap to claim and revocable to hold.

  Note for the next release: a README change reaches the PyPI project page only
  when a version is published, so this note is invisible to a `pip` user until
  then. That is the point at which the mitigation actually takes effect.

### Added (issue #162 — Python CI and the cross-interpreter golden fixture)
- **`tests/golden/`** — a committed determinism artifact: a synthetic session,
  a pinned config, and the exact expected output and sidecar bytes.
  `tests/test_golden_determinism.py` asserts them in every cell of the CI
  matrix, so 3.11, 3.12, and 3.13 must all reproduce the same bytes on disk
  rather than merely matching themselves. The determinism tests that predate
  this all ran the same input twice on one interpreter, which proves an
  interpreter agrees with itself and nothing more — and consumers do not scrub
  and validate on the same host.
- **`.github/workflows/sanitizer-ci.yml`** — the pytest matrix (3.11 / 3.12 /
  3.13, matching the declared classifiers), `python -m build`,
  `twine check --strict`, and a clean-environment smoke test of the built
  wheel that exercises `--init` so a dropped package-data template fails a
  pull request instead of a `twine upload`. The aggregate `sanitizer-ci` job
  is the required status check.

### Fixed (issue #182 — the shipped suite runs outside a checkout)
- **`tests/test_secret_patterns_in_sync.py`** skips, rather than failing,
  when it is run from an unpacked sdist. `tests` ships in the sdist so that
  a packager or an auditor can re-run it against the exact published source,
  but the D-6 drift guard loads `.claude/hooks/detect_secrets_in_output.py`
  from the repo root, and an sdist has neither a repo root nor a `.claude/`.
  The published source therefore produced three red tests in the
  secret-pattern drift guard of a security tool, on the first thing its
  packaging comment invites a reader to do.
  The skip is conditional on `PKG-INFO`, which every sdist carries and a
  checkout never does, rather than on the hook simply being missing. That
  condition would read a deleted hook as a reason to stop checking. In a
  checkout an absent hook stays a failure, now named by
  `test_the_hook_is_reachable_in_a_checkout` instead of surfacing as a
  `FileNotFoundError` several frames down. Pre-existing since issue #36; no
  behavior change to the sanitizer.
- **`.github/workflows/sanitizer-ci.yml`** gained two assertions that make
  the above hold on its own. The `package` job unpacks the sdist it just
  built and runs the **shipped** suite from outside the checkout, so the next
  test that reaches for a repo path it cannot see fails on a pull request
  rather than in a stranger's terminal. The `tests` job asserts the drift
  guard reported neither a skip nor a failure, because a skipped test still
  reports green: without it, a misfiring sdist condition would silently stop
  checking the hook against `VENDORED_PATTERNS` and nothing would go red.

## [0.3.0] — 2026-08-17

**First public release.** Everything below has been accumulating unreleased
since `0.1.0`; the interim `0.2.0` was an in-tree bump that was never
published, so `0.3.0` is the first version a `pip install` can produce
(ruling Q2, [PRD D-5a](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/.claude/specs/prd-sanitizer.md#d-5-amendment)).
Tagged `sanitizer-v0.3.0`.

### Added (issue #160 — first public version and the determinism contract)
- **`sidecar_schema_version: 1`** is emitted as the first field of every
  `.scrubbed` sidecar (Q9, ruled 2026-08-17). It versions the sidecar *shape*
  only: fields added, removed, renamed, or retyped. `sanitizer_version`
  continues to key the byte-level determinism contract. The asymmetry is what
  forced the decision now rather than later: added at `0.3.0`, every
  public-era sidecar carries it; added at `0.4.0`, consumers handle its
  absence forever. PRD §9b jitter, which turns the `jitter` scalar into a
  structured value, is the first expected consumer of a bump to `2`.
  A new sanitizer version does **not** imply a new schema version.
- **"Stability and the determinism contract"** section in the README, stating
  in quotable form what PATCH / MINOR / MAJOR promise about output bytes, that
  byte-stability holds only *within* a version so consumers must record the
  `sanitizer_version` they scrubbed under, that byte-identity holds across the
  supported Python versions (3.11, 3.12, 3.13), that a scrubbed artifact stays
  pinned to the version that produced it and re-scrubbing after a MAJOR bump is
  a deliberate manual act, and that yanks are for security only. It also notes,
  for the future fixture-validator (PRD §13 / D-4), that "a recognized
  `sanitizer_version`" has to mean a maintained allowlist of historical
  versions rather than "the current one."
- **Tagging convention decided:** `sanitizer-v<version>`. Component-scoped
  because this monorepo also holds posts, reference docs, and two other tools;
  a bare `v*` filter in the release workflow (#163) would fire the PyPI publish
  job on any future repo-level or Pages tag.
- The bump policy in this file's head no longer restates the semver level
  definitions. It defers to the README section, so there is one authority.
- Sidecar field order changed (a new leading field), which is a sidecar shape
  change and therefore byte-affecting for the sidecar. It is carried by this
  release's MINOR bump rather than a MAJOR because no existing field changed
  name, type, or meaning, and `0.3.0` is the first version any external
  consumer can have gated on.

### Added (issue #161 — SECURITY.md and the limitation notice)
- **`SECURITY.md`** at the repository root: private disclosure through GitHub
  Security Advisories (private reporting enabled on the repo), an explicit
  request not to open a public issue for a scrubbing bypass, what is worth
  reporting versus what is a documented limitation, what to include (and the
  instruction not to attach real session data to a report), the
  supported-version policy, and the response play: fix, publish, **yank rather
  than delete** the affected version so it stays installable by exact pin for
  forensics, publish an advisory, and state the re-scrub obligation. SECURITY.md
  owns version lifecycle; the README owns the determinism contract; each links
  the other.
- **A limitation notice at the top of the README**, ahead of everything else,
  written for someone who has never seen this repo: the tool *reduces*
  disclosure risk and does **not** guarantee zero leakage; free-text prompts and
  tool output are not scrubbed for arbitrary PII; human review of the
  `.scrubbed` sidecar is still required before publishing. It renders at the top
  of the PyPI project page, which is the first thing a stranger evaluating a
  tool named "sanitizer" reads. Links to PRD §4 for the full statement.
- The notice also records a behavior the PRD §12b sidecar-safety claim did not
  cover for external users: **a custom `-c` config basename is written verbatim**
  into `config_source`. `acme-prod.yaml` or `jsmith-laptop.yaml` lands in the
  artifact the docs call safe to commit, and the emit-time leak guard cannot
  catch it because the string is not in the user's match list. Documented as
  fixed behavior with the guidance to name configs generically. No placeholder
  or hashing scheme at `0.3.0`; engineering around it would be disproportionate.

### Changed (issue #159 — packaging made PyPI-correct)
- **PEP 639 license metadata.** `license = { text = "MIT" }` becomes the SPDX
  expression `license = "MIT"` plus `license-files = ["LICENSE"]`, and the now
  redundant `License :: OSI Approved :: MIT License` classifier is dropped.
  Build backends warn when the classifier is mixed with the SPDX expression.
  Requires `hatchling>=1.27`, so the build-system pin is raised.
- **`LICENSE` ships in the artifacts.** `tooling/sanitizer/LICENSE` is a verbatim
  copy of the repo-root `LICENSE`; the package root is the build context, so the
  root copy is out of reach. It now lands in the wheel
  (`*.dist-info/licenses/LICENSE`) and in the sdist. A published security tool
  with no license text in the artifact is a real audit gap downstream.
- **README is PyPI-safe.** Every repo-relative link (`../../.claude/specs/...`,
  `tests/`, `CHANGELOG.md`) becomes an absolute `github.com/.../blob/main/...`
  URL, since a pip user never cloned the repo and the project page is the first
  thing anyone evaluating the tool reads. In-page `#anchor` links are unchanged.
- **`readme` content type pinned** to `text/markdown` via the table form rather
  than inferred from the file extension.
- **Three content errors corrected in the README**, all of which render on the
  PyPI project page:
  - the sidecar example used `input_hash` and claimed the hash was "not stored."
    The field is `input_sha256` and it *is* stored (PRD §10 had already recorded
    the README as wrong). The example now matches `sidecar.py`'s emitted payload
    field-for-field, and `sanitizer_version` is a `<version>` placeholder so the
    example cannot go stale on a bump.
  - the "Rule sources" section credited AgentFluent's hook as the source of the
    secret-pattern library. This repo is upstream (PRD D-6): the shipped copy is
    `rules/secrets.py`, and the hook is a peer consumer held in sync by
    `test_secret_patterns_in_sync.py`.
  - "not yet published to a package index" is replaced by an Install section that
    also states the supported public surface: the CLI and the sidecar format are
    the contract, the module surface is private (PRD D-5a, Q8).
- No behavior change and no output-byte change, so no version bump under the
  policy above. `tests/` stay in the sdist and out of the wheel, deliberately:
  an auditor can re-run the fail-closed suite against the published source.

### Added (issue #45 — config storage and safety, PRD §12b)
- `ccs-sanitize --init` bootstraps a fresh repo or fork: writes
  `.ccs-sanitize.example.yaml` (if missing) and `.ccs-sanitize.yaml`
  (if missing, populated from the bundled template) into the cwd, and
  prints a one-line reminder to add the live config to `.gitignore`.
  Does NOT mutate `.gitignore` — silently editing a tracked file on
  first run is surprising and risks merge conflicts (architect review).
  Idempotent: re-running on a populated cwd leaves user edits intact.
- Built-in pre-run gitignore guard: after config discovery and before
  `load_config`, the CLI asks `git check-ignore -v <config>` whether
  the resolved config path is gitignored. If not, exits 3 with an
  actionable message naming the file and pointing at
  `.ccs-sanitize.example.yaml`. If `git` is unavailable or the cwd is
  not a git repository, the check warns to stderr and proceeds, so
  exit 3 is reachable only from inside a git repository. `--no-check`
  is a deliberate override of the guard rather than the remedy for
  exit 3 — defense-in-depth, not the only defense
  (the convention layer and the future hook layer [#47] cover the same
  threat from other angles).
- Template lives at `ccs_sanitize/_templates/ccs-sanitize.example.yaml`
  (package data, accessed via `importlib.resources`). The committed
  `.ccs-sanitize.example.yaml` at the repo root is byte-identical; a
  drift-guard test in `test_init_and_check.py` pins the equality.
  Single source of truth survives `pip install` and eventual extraction
  from the monorepo (PRD §12 D-5).
- Template fix: the example `Real Name -> Real Name` identifier rule
  was a same-string mapping that failed the I-3 idempotency guard at
  load time (`_check_replacement_leak`). Updated to
  `Real Name -> Example Author` with an inline comment explaining the
  constraint, so a freshly-`--init`-ed config loads cleanly without
  requiring the user to read the I-3 docstring first.
- PRD §12b "Config storage and safety" added: threat model
  (`git add .` primary, Read-into-transcript secondary), gitignore +
  template convention, pre-run gitignore guard (default-on; opt out
  with `--no-check`), hook layer (#47) as defense-in-depth,
  sidecar-safety claim (`config_source` is basename-only by design).
- Tests (`tests/test_init_and_check.py`, 10 cases): `--init` writes
  both files into cwd from the bundled template and prints the
  gitignore reminder; `--init` is idempotent and does not overwrite a
  user-edited live config; `--init` does not mutate `.gitignore`;
  package-data template equals the committed repo-root copy
  byte-for-byte (drift guard); shipped template loads via
  `load_config` without I-3 violations; pre-run check exits 3 on a
  non-ignored config in a real git repo and refuses to write anything;
  gitignored config proceeds normally; `--no-check` bypasses the
  guard; missing-git-repo path warns and proceeds; missing-git-binary
  path warns and proceeds.

### Added (issue #26 — CLI implementation, atomic write, end-to-end wiring)
- `ccs-sanitize` now scrubs end-to-end. `cli.py` wires config discovery
  (explicit `--config` > `./.ccs-sanitize.yaml` > `<input_dir>/.ccs-sanitize.yaml`),
  `sanitize_session`, `build_sidecar`, and the atomic write into one
  fail-closed pipeline. Per PRD section 11 / I-5, the sidecar temp file
  is renamed into place FIRST and the output temp file SECOND, so a
  crash in the gap leaves only an orphan sidecar (harmless, overwritten
  on re-run) and never a scrubbed output without a sidecar.
  `_atomic_write_pair` keeps that ordering plus the cleanup-on-failure
  logic in one auditable function.
- New CLI flags per PRD §11: positional `<input.jsonl>`,
  `-o/--output`, `-c/--config`, `--dry-run`, `--force`,
  `--strip-types`, `-v/--verbose`. `--strip-types ""` is the explicit
  opt-out of stripping (frozenset()); omitting the flag falls back to
  the default set (`file-history-snapshot,attachment`).
- Exit-code map honored: 0 success, 1 usage (bad args, missing input
  file, output exists without `--force`, explicit or discovered config
  not found), 2 safety (`PipelineError`, `ResidualSecretError`,
  `SidecarLeakError`, malformed UTF-8 input), 3 config (`ConfigError`).
  `FileNotFoundError` from `load_config` maps to exit 1 -- "file does
  not exist at that path" is a usage problem; "file exists but is
  broken" is exit 3. `config.py` re-raises the two separately so the
  CLI keeps the distinction.
- D-2 invariant preserved at the CLI surface: `ResidualSecretError`
  and `SidecarLeakError` already carry only category labels (not the
  matched bytes), so `print(str(exc))` in the exit handler is safe.
- Input must be a regular file. Directories, dangling symlinks, and
  device nodes exit 1 early. Symlink TOCTOU, FIFO input, and umask
  concerns are explicitly deferred for v0.
- `--verbose` writes pipeline milestones to stderr (loaded config,
  read N lines, pipeline ran, sidecar built, renamed sidecar, renamed
  output). No `logging` module dependency; a future migration is one
  line per call site.
- Tests (`tests/test_cli.py`, 23 cases): `--version` exit 0, unknown
  flag exit 1, missing/nonexistent/directory input exit 1, existing
  output without `--force` exit 1 (and pre-existing bytes preserved),
  `--force` overwrites, explicit-missing-config exit 1 vs malformed
  config exit 3, no-discoverable-config exit 1, discovery finds config
  in CWD and alongside input, malformed JSONL exit 2 with no files
  written, planted-secret residual failure exit 2 with no files
  written (and the same input under `--dry-run` also exit 2 -- the
  dry-run path runs the residual gate), dry-run prints valid sidecar
  YAML and writes nothing, `--strip-types` override changes which line
  types drop (and the sidecar's `stripped_lines` reflects the override),
  empty `--strip-types` means strip nothing, atomic-write orphan-sidecar
  invariant under second-rename failure (monkeypatched `os.replace`),
  full cleanup when the first rename fails (no leftover temp files
  either side), end-to-end synthetic session with paths + identifiers +
  fake AWS key + drop-by-default file-history-snapshot, `--verbose`
  surfaces stderr output.

### Fixed (review pass on issue #26)
- `_run` now splits input via `text.split("\n")` instead of
  `text.splitlines()`. The latter also splits on `\v`, `\f`,
  `\x1c`-`\x1e`, `\x85`, and crucially U+2028 / U+2029, which a JSON
  string value can legally carry raw under `ensure_ascii=False`. The
  prior code would fragment one valid JSONL record into two
  unparseable halves and exit 2 on well-formed input.
- Input symlinks are now rejected explicitly. The previous code used
  `Path.is_file()` (which follows symlinks), so a symlink whose target
  was a regular file slipped past the guard. `_validate_input` now
  checks `is_symlink()` first, then `exists()`, then `is_file()`,
  matching the CHANGELOG/docstring promise and removing the TOCTOU
  surface CLAUDE.md's "Security posture" section warns about.
- `--force` guard is now symmetric on the audit record: a pre-existing
  `<output>.scrubbed` requires `--force` to overwrite, mirroring the
  output check. Dangling symlinks at either path are detected via
  `is_symlink()` (which `exists()` would miss), so a stale link at the
  destination cannot bypass the overwrite guard.
- `--dry-run` no longer requires `-o/--output`. Dry-run writes nothing,
  so the output path is genuinely optional; the required-arg check is
  deferred under `--dry-run`. The CHANGELOG/help text framed dry-run
  as a preview, but the prior code still demanded an output path.
- `output_path.with_name(...)` now sits behind `_derive_sidecar_path`,
  which raises `_UsageError` if the output path has no filename
  component (`-o /`, `-o .`). Previously a `ValueError` from
  `with_name("")` propagated as an unhandled traceback.
- Top-level exit-code mapping in `main()` tightened: the broad
  `except FileNotFoundError` that misrouted any post-config FNFE
  (missing output directory, race-deleted input) to "config file not
  found" is gone. `load_config`'s FNFE is wrapped to `_UsageError`
  inside `_run` so only the load-config call site can produce that
  diagnostic. A defense-in-depth `except Exception -> exit 2` was
  added at the bottom of `main()`'s except chain so an unexpected
  exception from the scrub pipeline (the CLI docstring's promise) no
  longer escapes as a traceback that could leak local-variable bytes.
- `OSError` from `_atomic_write_pair` (ENOSPC, EROFS, PermissionError,
  NotADirectoryError, missing output directory) is now caught inside
  `_run` and re-raised as `_UsageError` -> exit 1 with a tailored
  "cannot write output" message that names the real destination,
  rather than a random tempfile path.
- Cleanup loop in `_atomic_write_pair` now swallows every `OSError`
  on `unlink()`, not just `FileNotFoundError`. The previous narrow
  catch could let a `PermissionError` mask the original exception
  AND leak the temp file -- losing both the diagnostic and the
  no-leftover invariant the test claims to enforce.
- `test_cli.py` now imports `serialize_test_line` from
  `tests/_helpers.py` instead of re-implementing `_line`; sibling
  test files use the shared helper, so test_cli no longer drifts
  from a future centralization of the serialization contract.
- `test_force_overwrites_existing_output` now asserts the output is
  actually scrubbed (paths/identifiers gone, placeholders present,
  sidecar valid), not just that the bytes differ from the
  pre-existing placeholder string. A regression that wrote garbage
  on the `--force` path would have passed the weaker assertion.
- New tests: `--dry-run` without `-o/--output`; input symlink
  rejection; existing sidecar without `--force` exits 1 and leaves
  the sidecar untouched; dangling symlink at output requires
  `--force`; `-o .` rejected as usage error; raw U+2028 inside a
  JSON string value round-trips as one record; `OSError` from
  `os.replace` at the CLI level maps to exit 1 via `main()` (the
  prior tests only exercised the helper); missing output directory
  yields exit 1 with a message that is NOT "config file not found".
- README sample sidecar bumped from `sanitizer_version: 0.1.0` to
  `0.2.0` to match the live tool. (PRD section 10 example left at
  0.1.0; it is a spec snapshot, not the user-facing surface.)
- **Known limitation** (not fixed in this pass): under `--force` and
  a pre-existing output, an I/O failure on the SECOND
  `os.replace` (output rename) can leave the disk in an
  inconsistent state -- the new sidecar has already been renamed
  into place, but the output file is still the prior run's bytes.
  Rolling back the sidecar rename requires pre-stashing the old
  sidecar bytes and is deferred. The orphan-sidecar invariant
  documented in PRD section 11 holds only when the output did not
  pre-exist; `--force` callers should be aware that crash recovery
  may require deleting both files and re-running.

### Changed
- `__version__` bumped from 0.1.0 to 0.2.0. This is the cutover where
  `ccs-sanitize` first produces non-identity output bytes; per the
  CHANGELOG bump policy and the carve-outs in prior PRs (#21, #22,
  #24), this is the byte-affecting story that carries the bump. MINOR
  rather than MAJOR because the sidecar schema, config schema, and
  built-in pattern floor are all unchanged.

### Fixed (issue #38 — I-3 leak guard extension)
- `_check_replacement_leak` now rejects:
  - any user rule (path or identifier) whose `match:` matches a
    `<REDACTED:kind>` placeholder for any built-in or extra kind. On a
    second pass (idempotency, fixture-validator re-run) such a rule
    would re-substitute the placeholder, breaking the determinism
    contract;
  - any `extra_secret_patterns` rule whose pattern matches the
    `gitBranch` placeholder (`feature/example`). Symmetric to the
    existing user-rule check; an unguarded extra would cause the
    residual scan to fire on every output where gitBranch was scrubbed;
  - any `extra_secret_patterns` rule whose pattern matches any
    `<REDACTED:kind>` placeholder for any built-in or extra kind
    (including its own kind). An extra catching a redaction placeholder
    would make the orchestrator's "if `sanitize_session` returns,
    residual passed" invariant unreachable for any input containing a
    built-in secret.
- `rules/secrets.py` promotes `_placeholder_for` to public
  `placeholder_for`. The loader's I-3 guard and the secret transform
  share one definition of the redaction-placeholder format. The single
  internal call site is migrated in the same diff; no alias retained.
- `placeholder_for("")` raises `ValueError`, mirroring
  `SecretCounts.record` — a programmatic caller bypassing the loader
  with an empty kind can no longer produce a wildcard-like
  `<REDACTED:>` that the I-3 leak guard would feed into its
  placeholder enumeration.
- `_check_replacement_leak` now builds its placeholder set via
  `iter_all_secret_patterns(extras)` rather than re-iterating
  `COMPILED_SECRET_PATTERNS` then extras inline. The "built-ins first,
  extras last" ordering invariant now lives in one place, structurally,
  shared by `build_secret_transform`, `scan_residual`, and the leak
  guard.
- User-rule placeholder-match error message includes
  `(kind={kind!r})`, symmetric with the extras-side error.
- New tests: explicit own-kind self-match case (the prior test that
  claimed to cover it was actually a cross-extras case; both axes are
  now pinned distinctly), cross-extras placeholder cycle (pins the
  iterative-resolution semantics against future lazy-build refactors),
  and `placeholder_for("")` rejection.

### Changed (review pass on issue #24)
- `scan_residual` now scans per-line instead of over a joined buffer.
  Eliminates two latent gate-weakening footguns at once: anchored extras
  (`re:^...$`) would have matched only buffer boundaries in the joined
  form, and patterns using `\s+` (bearer-token, conn-string-pw) could
  in principle have matched across the line-join separator. Per-line is
  also the semantic that ``build_secret_transform`` applies per leaf, so
  detect-during-scrub and verify-after-scrub now share the same matching
  semantics structurally.
- `rules/secrets.py` exposes ``iter_all_secret_patterns(extras)`` --
  ``build_secret_transform`` and ``scan_residual`` both consume it, so
  the "built-ins first, extras last" ordering and any future addition
  to the pattern floor lives in one place rather than two.
- Tests: `_BASE_CONFIG` no longer commits a real email; uses the RFC-2606
  reserved ``user-old@example.test`` instead. PEM-armor test fixture
  constructed via string concatenation so the test source itself does
  not match the repo's own pem-private-key hook regex on grep/cat.
  Determinism test uses heterogeneous records (was ``[x] * 5`` aliases).
  Idempotency parametrized over every built-in kind so a future pattern
  that accidentally matches its own ``<REDACTED:kind>`` placeholder is
  caught. `_line` helper lifted to ``tests/_helpers.py`` as
  ``serialize_test_line``. `test_strip_types_passthrough_drops_lines`
  now actually passes ``strip_types=`` (was relying on the default).
  `test_no_partial_scrub_on_missing_type_field` pins ``"line 2"``
  symmetrically with the malformed-JSON sibling. New per-line anchored
  extra test pins the new scan semantics.

### Added (issue #24 — residual scan + fail-closed orchestration)
- `residual.py`: `scan_residual(text, extras)` re-runs the secret-pattern
  detector over the serialized output as the final safety gate. A match
  raises `ResidualSecretError(kind)` carrying only the pattern's `kind`
  label -- never the matched bytes -- so the D-2 invariant survives
  propagation through tracebacks and logs. Re-imports
  `COMPILED_SECRET_PATTERNS` directly (rather than accepting a pattern
  list from the caller) so the D-1 floor is structural: there is no API
  to pass a pruned subset of built-ins.
- `orchestrator.py`: `sanitize_session(lines, config, *, strip_types)`
  builds the three transform layers (paths -> identifiers -> secrets),
  composes them in PRD-mandated order, plugs the composed transform into
  `run_pipeline`, and runs the residual gate over the joined output.
  Returns `(serialized_lines, PipelineCounts, SubstitutionTable,
  SecretCounts)` so the sidecar (#25) and CLI (#26) can compose without
  re-running the pipeline. If the function returns, the residual scan
  passed -- the sidecar can unconditionally record `residual_scan: clean`.
- `pipeline.py` docstring updated: the "does NOT ship" carve-out now
  points at `residual.py` and `orchestrator.py`; the atomic write that
  follows them still lives in the CLI layer (#26).
- Tests: `tests/test_residual.py` (10 cases) pins clean/empty/redacted-
  placeholder happy paths, Tier-1 and Tier-2 kinds, extras with the
  built-in-wins-on-overlap ordering, and the "exception message names
  the kind but not the bytes" D-2 surface. `tests/test_orchestrator.py`
  (8 cases) covers three-layer happy path, `strip_types` passthrough,
  determinism (PRD §14, I-1), idempotency (PRD §14), the realistic
  fail-closed survival path (Tier-1 secret planted in skip-listed
  `thinking.signature`), a pure unit-test fail-closed (monkeypatch
  `build_secret_transform` to identity), and no-partial-scrub on both
  malformed-JSON and missing-`type` errors.

### Fixed (review pass on issue #22)
- `_remap_uuid` now uses a null-byte delimiter between the seed and the
  original: `sha256(seed_bytes + b'\x00' + original_bytes)`. Without it,
  `(seed='ab', original='cd')` and `(seed='abc', original='d')` hash
  identically -- the function was pure over `seed+original`, not over
  `(seed, original)`. With a single fixed seed in v0 the risk is benign,
  but the determinism contract is documented as a function of two
  inputs and now matches.
- `build_identifier_transform` rejects empty `uuid_seed` at factory
  entry, mirroring the loader's check at `_build_options`. A
  programmatic caller (test, future CLI bypass) can no longer construct
  a transform whose hash depends only on the original UUID.
- UUID remap now short-circuits on the substitution table: a sessionId
  shared across 10,000 lines hashes once instead of 10,000 times. The
  occurrence counter still increments correctly via `record(leaf, cached)`,
  so sidecar counts are unchanged.
- `_remap_uuid` now raises `ValueError` on empty input (defense-in-depth;
  the transform-level guard at the call site still handles the
  happy-path passthrough).
- The seed is pre-encoded once when the transform is built; per-leaf
  `(seed + original).encode("utf-8")` is no longer reallocated.
- I-3 replacement-leak guard extended: any user rule (path or
  identifier) whose pattern matches the literal `GIT_BRANCH_PLACEHOLDER`
  (`"feature/example"`) is rejected at load time. Without this check, a
  config like `identifiers: [{match: 'feature/example', replace: 'X'}]`
  would load successfully and at runtime produce an internally
  inconsistent subtable (gitBranch field records
  `real_branch -> 'feature/example'` while the user rule records
  `'feature/example' -> 'X'` elsewhere).
- Stale docstring in `_reject_zero_width_pattern` updated:
  `rules/paths.py _apply_rule` → `rules/_engine.py apply_rule`.
- `test_git_branch_left_alone_when_option_off` docstring corrected: the
  earlier claim "identifier regex rules also do not fire on the value"
  was wrong. With `scrub_git_branch: false`, gitBranch values fall
  through to the identifier rule loop -- the option opts out of the
  placeholder, not out of all scrubbing. The behavior is unchanged; the
  test docstring was overclaiming.
- `test_uuid_remap_null_parent_uuid_passes_through` had a dead
  `assert None not in originals` -- the comprehension produces a set of
  strings so the assertion was tautological. Replaced with a meaningful
  table-shape assertion (`len(entries) == 1` plus the expected original).
- New test `test_paths_and_identifiers_compose_under_remap_uuids` pins
  end-to-end graph integrity when both layers compose and the
  skip-list is lifted: a benign path rule does not interfere with UUID
  remapping, and the `parentUuid → uuid` link survives the full
  pipeline. The earlier composition test only exercised the default
  (remap_uuids=False) skip predicate.
- New config test `test_i3_rejects_user_rule_matching_git_branch_placeholder`
  pins the extended I-3 check.
- Shared test helpers (`_config`, `_table_snapshot`) moved to
  `tests/_helpers.py` (`write_config`, `table_snapshot`); previously
  duplicated byte-for-byte between `test_paths.py` and
  `test_identifiers.py`. A future addition to the substitution-table
  shape now updates one helper instead of two.

### Added (issue #22)
- Layer 2 identifier scrubbing at
  `ccs_sanitize.rules.identifiers.build_identifier_transform`. Factory
  takes a `Sequence[Rule]` (typically `Config.identifiers`), a shared
  `SubstitutionTable`, and three identifier-specific options
  (`scrub_git_branch`, `remap_uuids`, `uuid_seed`) that the CLI in #26
  will source from `Config.options`. Per visited leaf the transform makes
  one routing decision in priority order: gitBranch field → whole-value
  replacement with `GIT_BRANCH_PLACEHOLDER` ("feature/example"); UUID-graph
  field under `remap_uuids` → deterministic SHA-256-based remap to a
  UUID-shaped string; default → apply each identifier rule via the shared
  `apply_rule` engine. Field-anchored substitutions and identifier regex
  rules do not compose: the whole-value placeholder wins so the audit
  trail stays clean.
- Shared per-rule engine extracted to `ccs_sanitize.rules._engine.apply_rule`.
  Both Layer 1 (`rules/paths.py`) and Layer 2 (`rules/identifiers.py`)
  import it so the subtle zero-width handling lives in one place. Drift
  between the two layers would silently produce divergent substitution
  tables for the same input, breaking the PRD §7 determinism contract.
  `paths.py` no longer carries its own copy of `_apply_rule`; its module
  docstring points at `_engine.py` for the per-rule semantics.
- `ConfigOptions.uuid_seed` field (default `"ccs-sanitize/v1"`). Surfacing
  the seed on `Config.options` rather than burying it in a function
  default makes the determinism contract auditable: the sidecar can
  report which seed produced its substitution table, and a seed change in
  a config diff signals that every remapped UUID in every fixture will
  change. The YAML key is validated as a non-empty string at load time
  (`ConfigError` exit 3) -- an empty seed would silently weaken the hash
  input to depend only on the original UUID.
- UUID remap is deterministic by construction: `sha256(seed + original)`
  truncated to 16 bytes and formatted as a UUID. RFC 4122 version/variant
  bits are NOT forced -- downstream consumers parse these fields as
  opaque strings, and forcing the bits would narrow the output range
  without buying anything. Empty-string UUIDs and gitBranch values pass
  through unchanged so they don't become phantom graph nodes / fake
  branches.
- `UUID_FIELDS` mirrors `pipeline._UUID_NAMES` and is pinned by a test --
  the skip-list (what to *visit*) and the remap set (what to *remap*) are
  two sides of the same contract; adding a field to one without the
  other would silently leak or no-op.

Tests (`test_identifiers.py`, 22 cases): exact email replaced across
lines with consistent subtable entry; catch-all regex covers unknown
addresses; exact-before-catch-all ordering produces specific replacement;
gitBranch on/off; gitBranch empty-string passthrough (not-in-a-repo
signal); gitBranch wins over identifier regex; UUID remap OFF leaves
fields untouched (pipeline skip-list filters them); UUID remap ON
preserves `parentUuid → uuid` graph link; `sessionId` shared key stays
shared; `toolUseResult.agentId` (nested) remaps to the same value as
top-level `agentId` (parent↔subagent link); injectivity (distinct UUIDs
→ distinct remaps); empty-string UUID passes through; null parentUuid
stays null (string-only walker invariant); two-runs-byte-identical
determinism with table-snapshot equality; seed change yields different
output; within-file consistency (same UUID twice → one entry, two
occurrences); `UUID_FIELDS` matches pipeline skip-list; composition with
Layer 1 paths through one shared SubstitutionTable; subtable conflict
fail-closes through the pipeline.

Tests (`test_config.py`, +4 cases): `uuid_seed` defaults when omitted;
custom value loaded; empty-string and wrong-type rejected at load time.

PRD-vs-implementation tension noted in test docstrings: PRD §8's example
config uses `user@example.com` as the replacement for both the exact
email rule AND the catch-all email regex. That config would be rejected
by the I-3 replacement-leak guard (the catch-all regex self-matches its
own replacement, and the exact rule's replacement matches the catch-all).
The test uses bracketed placeholders (`[redacted-email]`, `[known-user]`)
that don't match an email shape. Whether to relax I-3 for self-
referential idempotent rules, or to update the PRD example, is tracked
separately.

No version bump: importable machinery only; the CLI (#26) does not yet
feed it, so `ccs-sanitize` byte output is still identity-pass.

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
- Zero-width regex patterns are now rejected at config load time by
  `_reject_zero_width_pattern` in `config.py`: any rule whose compiled
  regex matches the empty string with zero span (anchors `^`, `$`, `\A`;
  empty groups `(?:)`; unbounded-optional quantifiers `.*`, `a*`, `a?`)
  surfaces as `ConfigError` (exit 3) instead of silently no-op-ing at
  runtime. PRD section 11 fail-closed posture: for a security tool,
  silent acceptance of misconfigured rules is the wrong default. The
  check also applies to `extra_secret_patterns`, which share the same
  matching infrastructure.
- The rule layer's runtime backstop (`_apply_rule` in `rules/paths.py`)
  stays for input-dependent zero-width matches the static check cannot
  see: lookaheads (`(?=foo)`) and `\b` only match zero width when the
  surrounding string supplies the context, so they slip past the load-
  time check. The backstop returns an empty string so `re.sub` inserts
  nothing at the zero-width position and the substitution table never
  records a meaningless `('' -> X)` row.

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
zero-width lookahead pattern handled by runtime backstop.

Tests (`test_config.py`, +3 cases): anchor-only regex (`re:^`) and
unbounded-optional regex (`re:.*`) rejected at load time with a clear
`ConfigError`; the same static check applies to `extra_secret_patterns`.

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
