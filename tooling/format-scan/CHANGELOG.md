# Changelog — `ccs-format-scan`

All notable changes to `scan.py` are documented here. The `scan_version` field
stamped into every `--json` report (alongside the `tool` identifier) references
this file.

## Bump policy

**Bump `scan_version` on any change that alters the `--json` output's shape or
semantics.** That includes, non-exhaustively:

- A new, renamed, or removed top-level report key, or a change to any nested
  structure under one.
- A change to what a probe records (new `meta.json` key surfaced, a new
  taxonomy category in the baseline diff, a changed counting/aggregation rule).
- A change to the `EMITTABLE_VALUE_FIELDS` whitelist or anything else that
  changes which values appear in the output.

A change that does **not** affect the `--json` output (refactor, comment, a
human-report-only `print_human()` tweak, a test-only change) does not require a
bump.

The rule is conservative because CCDC's Tier 2 "structural" tier **attests**
these profiles by `(tool, scan_version)` rather than re-deriving them — the
contributor withholds the raw projects-root, so the version is the only handle
CCDC has on what shape the bytes are in. CCDC also content-addresses each
contribution by `sha256(scan.json)` (`sort_keys=True`, so deterministic), which
means any output-affecting change is observable downstream and must move the
version. See CCDC `SCHEMA.md` ("Upstream dependencies") and
`docs/prd-ccdc.md` (D-CCDC-2).

Use semver: `MAJOR.MINOR.PATCH`.

- `PATCH` — output-affecting bug fix (e.g. a miscount corrected) with no key
  added, removed, or renamed.
- `MINOR` — a new top-level key or probe surface; additive, existing keys
  unchanged.
- `MAJOR` — a key renamed or removed, or any restructuring that breaks a
  consumer reading the prior shape. Reserve `1.0.0` for the point at which the
  `--json` shape is declared stable.

## [0.1.0] — first stamped version

First build to carry a `scan_version`. Nothing earlier was ever versioned or
attested, so `0.1.0` is not a back-compat claim about any prior output.

The stamped shape **already includes** the per-subagent `meta.json` manifest
probe (`meta_json_keys`) and the `tool-results/` file-shape probe added in
issues #96 / #97 — those landed before versioning existed and are part of the
`0.1.0` baseline, not a future bump.
