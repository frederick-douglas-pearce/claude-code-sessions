# format-scan

A local, observational scanner for Claude Code JSONL session-format drift. It
walks a Claude Code projects root (default `~/.claude/projects/`) and reports the
**shape** of the session data on disk — top-level `type` values, envelope keys
(overall and per type), content-block types, session subdirectories, the file
shape inside `tool-results/`, the key set of the per-subagent `meta.json`
manifests, and the Claude Code `version` values that produced the data. With
`--baseline` it diffs the observed taxonomy against what `reference/` already
documents, so the delta is "undocumented drift" — the input the
[`jsonl-format-watch`](../../.claude/skills/jsonl-format-watch/) queue wants.

## Security contract — read before editing

This tool reads **raw, unsanitized** session transcripts and **must never emit
their contents**. It emits only structural key names, public taxonomy enums
(`type`/`version`), value JSON-types (`str`/`int`/…), counts, sizes, file
extensions, and directory names. The full contract — and why the no-values
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
```

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
