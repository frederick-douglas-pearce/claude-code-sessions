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

## [0.1.0] — 2026-05-29

Initial scaffold (issue #18). No transform logic yet.

- `claude-code-sessions-sanitizer` package skeleton, hatchling-built.
- `ccs-sanitize` entry point with `--version`. Parser exits 1 on usage
  errors (PRD section 11 reserves exit 2 for safety failures).
- Stub modules for the PRD section 6 module layout.
- `rules/jitter.py` carries the v1 design (PRD section 9b) and a
  `JITTER_DISABLED = True` sentinel.
- Python 3.11+. Zero runtime dependencies. `pytest` is a dev extra.
