# format-scan

A local, observational scanner for Claude Code JSONL session-format drift. It
walks a Claude Code projects root (default `~/.claude/projects/`) and reports the
**shape** of the session data on disk — top-level `type` values, envelope keys
(overall and per type), content-block types, session subdirectories, the file
shape inside `tool-results/`, the key set of the per-subagent `meta.json`
manifests, and the Claude Code `version` values that produced the data. Manifest
shape is also bucketed **by** the version that produced it, which turns "this key
exists somewhere" into "this key appeared at version X". With `--baseline` it
diffs the observed taxonomy against what `reference/` already documents, so the
delta is "undocumented drift" — the input the
[`jsonl-format-watch`](../../.claude/skills/jsonl-format-watch/) queue wants.

## Security contract — read before editing

This tool reads **raw, unsanitized** session transcripts and **must never emit
their contents**. It emits only structural key names, public taxonomy enums
(`type`/`version`/`stop_reason`), value JSON-types (`str`/`int`/…), counts,
sizes, file extensions, directory names, the whitelisted `spawnDepth` counter,
**folded enum values** drawn from a fixed set with everything else bucketed, and
**fixed classification labels** for values read but never printed. The full
contract — and why the no-values
discipline is *this script's* responsibility, not the `block_secret_reads.py`
hook's — lives in the `SECURITY CONTRACT` docstring at the top of `scan.py`. See
also the [CLAUDE.md security posture](../../CLAUDE.md#security-posture--read-this-first).

## Usage

```bash
# Human-readable report over the default root
python3 scan.py

# Diff observed taxonomy against the checked-in baseline (shows drift)
python3 scan.py --baseline baseline-v2.1.150.json

# JSON output (for tooling), and sampling
python3 scan.py --json --max-files 200

# Probe tool_result contents for the tool-results/ externalization wrapper
# (fixed-marker presence + counts only — no content emitted)
python3 scan.py --probe-tool-results

# Probe multi-level subagent layout: nested subagents/ dirs, the spawnDepth
# histogram, and the rollup shape at each depth
python3 scan.py --probe-nesting
```

### Manifest shape by version

The default report's `meta_json_by_version` section answers "when did this
`meta.json` key appear, and what values did it take" — the shape most
format-drift questions need. A manifest carries no `version` of its own, so it
inherits the **earliest** version seen on its own sibling trace file (the
manifest is written at spawn time). Manifests whose trace is missing or
unversioned land in `manifests_unattributed` rather than being dropped, and
`traces_spanning_multiple_versions` counts traces that straddle a CC upgrade, so
both caveats stay visible in the output.

Only keys on the `EMITTABLE_META_VALUE_FIELDS` whitelist contribute their
**values** to a bucket (currently just `spawnDepth`, the runtime's own nesting
counter). Every other key contributes a name and a count and nothing else —
`description` and `worktreePath` carry PII and must never be printed.

### Message shape and the tool cycle

Two sections answer the "how often" questions that `reference/` cites, and both
carry their **denominator definitions inline** rather than only in code — a
figure whose denominator was never written down cannot be re-derived later,
which is the defect that made these numbers necessary in the first place.

`message_shape` holds the `stop_reason` distribution, cross-tabbed against a
synthetic-vs-real bucket derived from `message.model` (the model string itself is
never emitted), the `stop_sequence` field-state table, and the `user`
`message.content` shape split. Its `stop_reason` presence count is three-way —
`present_non_null`, `present_null`, `absent` — because a null is a real
observation, a line recording an incomplete turn, not a missing key.

`tool_cycle` joins each `tool_result` to its `tool_use` **within the same file**
and reports, per tool, the `toolUseResult` shape split and the conditional-key
presence counts, plus orphaned `tool_result` blocks split on `isSidechain`. The
join is per-file because subagent traces carry their own `tool_use_id` space, so
a cross-file join would resolve ids a real parser never could.

Three values are **folded**: `stop_reason` against `STOP_REASON_VALUES`, the
joined tool name against `TOOL_NAME_ALLOWLIST`, and the `tool-results/` filename
prefix against `TOOL_RESULT_PREFIX_ALLOWLIST`. Anything outside those fixed sets
is counted as the literal `<other>`, with one declared exception: an MCP
tool-results prefix folds to the fixed label `mcp` instead (below). Folding is
what lets an open-ended field be
counted without its bytes reaching output, and it is not a discard — an
unrecognized value still shows up as a count, which is the drift signal.

The filename prefix earns its fold the hard way. The probe takes everything
before the first `_` or `.`, which is a tool-kind label only when the filename
happens to be `<kind>_<id>.<ext>`; most real ones have no underscore and come
back whole, carrying per-invocation ids, decodable `webfetch-<epoch_ms>` stamps
and fetched documents' names. A prefix matching `mcp-` folds to the single label
`mcp`, so the family stays countable without the server name. Note that only the
hyphen form is recognised: a file named with the double-underscore convention
(`mcp__<server>__<tool>_...`) cuts at the first `_` and yields a bare `mcp`,
which lands in `<other>`. That is safe — nothing leaks either way — but it means
the `mcp` count is a floor, not a total.

### Retained scan artifacts

`scan-<YYYY-MM-DD>.json` is a committed `--json` report over the maintainer's
local corpus, retained so a figure cited in `reference/` can be checked against
the run that produced it. This exists because the 2026-08-25 pass behind Part 5
was ad hoc, kept no output and wrote down no denominators, which made ten
published figures uncheckable (#237).

Three rules. The third has already caught a real leak; the other two are
preventive:

- **The date lives in the filename, never in the body.** CCDC content-addresses
  a contribution by `sha256(scan.json)`, so a wall-clock field inside the JSON
  would make identical-corpus re-runs hash differently.
- **The corpus fingerprint is `summary` plus the top-level `versions`
  histogram** — `files_scanned`, `lines_scanned` and `max_files` from `summary`,
  and `versions` alongside it, not inside it. `max_files` is what distinguishes
  a full scan from a sample; without it two artifacts are not comparable.
- **A human reviews the artifact for PII before it is committed.** The
  content-free contract test proves the scanner does not emit *planted* values;
  it cannot prove a real corpus held nothing unanticipated. That review has
  already caught one real leak, in the filename-prefix probe.

Note the corpus is live, so two runs minutes apart differ slightly. An artifact
is a snapshot, not a reproducible constant.

Every `--json` report is stamped with a top-level `scan_version` (semver) and a
stable `tool` id (`ccs-format-scan`), so a structural profile self-describes
which scanner build produced it:

```json
{
  "scan_version": "0.1.0",
  "tool": "ccs-format-scan",
  "summary": { "files_scanned": 0, "lines_scanned": 0 }
}
```

These are tool-static, content-free strings (they describe the scanner, not the
scanned data). They exist because the [Claude Code Data Collective](https://github.com/frederick-douglas-pearce/claude-code-data-collective)
**attests** structural contributions by `(tool, scan_version)` instead of
re-deriving them. Bump `scan_version` on any change to the `--json` output —
see [`CHANGELOG.md`](CHANGELOG.md) for the policy.

The `--baseline` diff reports drift in **both directions**: `new_*` items
(observed but undocumented — a hard signal) and `removed_*` items (documented in
the baseline but not seen in this scan — a softer candidate-removal signal, since
an item can also be absent simply because this corpus or `--max-files` sample
didn't contain it). `versions` is additive-only — it's an open, ever-growing set,
not a closed vocabulary. Bump `baseline-v<version>.json` when `reference/` catches
up to a newer Claude Code version, so the diff keeps measuring real drift.

## Tests

The suite locks down both the taxonomy/diff output **and** the content-free
contract (a sentinel-leak gate that fails if any planted value reaches stdout).
Fixtures are synthetic only — no test ever points the scanner at real
`~/.claude/projects/` data. Run from the repo root:

```bash
python3 -m pytest tooling/format-scan/tests/
```

`pytest` is the only dev dependency (shared with the sanitizer suite).
