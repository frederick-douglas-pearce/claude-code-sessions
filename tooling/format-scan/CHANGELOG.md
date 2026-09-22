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

## [0.4.0] — two folds that test a claim

Added for issue #244. Part 6 reads the seven-key hook-execution family as a
general record of hook activity, and treats `toolDenialKind` as a field whose
value space is unknown. Three purpose-built sessions
(`fixtures/sanitized/hook-trace-*.jsonl`) contradicted the first and put one
value under the second. Three scratch sessions cannot settle either question;
this release is what settles them against the corpus.

Both folds are deliberately narrow. Neither exists to inventory a vocabulary,
which is the thing `TOOL_NAME_ALLOWLIST` already refuses to do. Each exists to
ask one question whose answer is a count.

- **New top-level report key `hook_records`.** Two cross-tabs and a corrected
  denominator.

  `by_subtype` folds every `system` line's `subtype` to
  `SYSTEM_SUBTYPE_ALLOWLIST` (`stop_hook_summary`, `turn_duration`,
  `informational`) or to `OTHER_BUCKET`. `hook_family_by_subtype` folds the
  subset carrying `hookCount` the same way. Read together they answer whether
  the hook family lands anywhere other than a Stop-hook summary. Against a
  464,037-line corpus it does not: all 4,154 family lines are
  `stop_hook_summary`, and `OTHER_BUCKET` is zero. A non-zero `OTHER_BUCKET`
  there would have falsified the claim and said by how much, which is why the
  fold reports it rather than dropping it.

  `tool_denial_by_kind` folds `toolDenialKind` to `TOOL_DENIAL_KIND_ALLOWLIST`
  (`permission-rule`, the one value a committed fixture attests) or to
  `OTHER_BUCKET`. The corpus holds 146 `permission-rule` and 86 `OTHER_BUCKET`,
  so the field carries at least two values and is not the single-value field one
  session suggested. What the other values *are* stays unread, by design.

- **`toolDenialKind` is now counted per LINE.** `tool_result_line_keys`
  increments per `tool_result` **block**, so a line carrying two results
  contributes its top-level keys twice, which makes that figure an upper bound
  on distinct lines rather than a count of them. `tool_denial_lines` is the
  line-weighted figure. On this corpus the two agree at 232, so no denial line
  carried a second `tool_result` — but that is an observation, not a guarantee,
  and the contract test plants exactly that case to keep the two apart.

- **Both allowlists are attested by committed fixtures.** Every member appears
  in `fixtures/sanitized/hook-trace-*.jsonl`. That is the bar
  `EMITTABLE_VALUE_FIELDS` sets: a closed, content-free vocabulary this file
  declares, not one the corpus supplies. Adding a member is output-affecting and
  bumps this version.

## [0.3.0] — five statistic families, and a fold rule for open enums

Added for issue #237. `reference/tool-invocation.md` needs ten figures that
exist only in a post, because the 2026-08-25 pass that produced them was ad hoc,
retained no output, and wrote down none of its denominators. They cannot be
sourced by citation, so they are re-derived here and the derivation is retained.

- **New top-level report key `message_shape`.** Carries the `stop_reason`
  distribution cross-tabbed against a synthetic-vs-real model bucket, the
  `stop_sequence` field-state table, and the `user` `message.content` shape
  split. The `stop_reason` presence split is **three-way** — `present_non_null`,
  `present_null`, `absent` — because `data-dictionary.md:99` treats a null as a
  real observation (an incomplete turn, "not safe to discard") rather than as an
  absence; a corpus sample turned out to be entirely `present_null` with zero
  truly-absent, so a two-way split would have mislabelled the whole bucket.

- **New top-level report key `tool_cycle`.** Joins each `tool_result` to its
  `tool_use` **within the same file** and reports, per tool, the
  `toolUseResult` shape split and the conditional-key presence counts
  (`structuredPatch`, `prompt`, `toolStats`), plus orphaned `tool_result` blocks
  split on `isSidechain`. Per-file is the correct scope, not merely the cheap
  one: `tool-invocation.md:83` documents that subagent traces carry their own
  `tool_use_id` space, so a cross-file join would resolve ids a real parser
  cannot. `tool_result_blocks == resolved + orphaned` holds by construction.

  The `toolUseResult` shape is split five ways — `dict`, `non_dict`, `null`,
  `absent`, `ambiguous_multi_block` — because each names a different fact. It is
  a **bare string** on a minority of results (240 on `Edit` alone,
  `tool-invocation.md:195`), so a dict-only denominator would drop those
  silently; a `null` is not the same observation as a missing key; and
  `toolUseResult` is one key on the **line**, so when a line carries several
  `tool_result` blocks (`tool-invocation.md:526`) the envelope belongs to no
  single result. Those contribute **no** conditional-key counts rather than
  crediting the same envelope to each block, which would both inflate the
  numerator and hand one tool's keys to another. A multi-block line whose
  envelope is *missing or null* keeps `absent`/`null` instead — ambiguity
  requires a body to misattribute, and there is none.

  Every one of these labels is defined in the report's own `denominators`, not
  only in this file, so a reader of a retained artifact who meets `non_string`
  or `ambiguous_multi_block` has something to read.

  `tool_cycle` also reports `files_dropped_mid_read`. A file that dies partway
  has its whole join buffer discarded — resolving a partial id set would
  manufacture orphans out of `tool_use` lines that were never reached — but its
  already-ingested lines still counted toward `content_block_types`. The counter
  is what lets a reader of a retained artifact explain that gap rather than find
  two figures that disagree for no stated reason.

  `message_shape` reports `assistant_lines_sidechain` and `user_lines_sidechain`
  and states in its own `denominators` that **subagent and parent traffic are
  pooled** in every figure it carries. The scan walks both, and
  `tool-invocation.md:524` warns that mixing them puts a subagent's parallelism
  into the parent's numbers.

- **`stop_reason` added to `EMITTABLE_VALUE_FIELDS`, with a fold.** This is the
  first whitelist member whose value space is **not closed**: the whitelist's bar
  is "a closed, content-free vocabulary", while `data-dictionary.md:99` says of
  this exact field "treat this as an open enum, not a closed switch". The two are
  reconciled by `STOP_REASON_VALUES`: documented values are emitted verbatim and
  anything else folds to the literal `<other>`. A fold is **not a drop** — an
  unrecognized value still surfaces as a count, which is the drift signal this
  scanner exists to raise. `stop_sequence` and `stop_details` stay off the
  whitelist entirely; the former carries the caller-supplied matched sequence
  and the latter free text.

- **New `TOOL_NAME_ALLOWLIST`**, currently `{"Edit", "Agent"}`, same fold rule.
  Tool names are not a closed vocabulary — MCP tools carry server-derived names
  and plugin/user tools author-chosen ones — which is the identical disqualifier
  already applied to `agentType`. An observed tool name is never emitted.
  Extending the set is output-affecting and requires a bump.

- **New `summary.max_files`** (int or `null`), recording the cap in force for the
  run. `files_scanned` alone cannot distinguish a full scan of N files from a
  `--max-files N` sample of a much larger corpus, so a retained artifact without
  it is not comparable against a later re-run. It is an invocation parameter, so
  it is content-free and deterministic — it does not reintroduce the wall-clock
  non-determinism that `sha256(scan.json)` addressing rules out.

- **`tool_results.name_prefixes` values are now FOLDED — the one change here to
  an existing key.** Its comment claimed the prefix is "a tool-kind label
  (`toolu`, `mcp-github-list`, ...), not content". Against a real corpus that is
  false: a run produced **466 distinct prefixes**, of which four were tool-kind
  labels. The rest were per-invocation ids (one file each),
  `webfetch-<epoch_ms>-<token>` stems whose timestamps decode to precise
  wall-clock activity times, and at least one fetched document's own filename.

  The cause is that the extraction takes everything before the first `_` or `.`,
  so it yields a tool-kind label only when the filename happens to be
  `<kind>_<id>.<ext>`; a filename with no underscore comes back whole. Now only
  `TOOL_RESULT_PREFIX_ALLOWLIST` members are emitted verbatim, the MCP family
  folds to the fixed label `mcp` (countable as a family, without the
  author-chosen server name), and everything else folds to `<other>`.

  **This narrows an existing key's value space rather than adding one.** The
  shape is unchanged — still `{str: int}` — so a consumer reading the prior
  shape does not break, which is why this is still `MINOR` rather than `MAJOR`.
  But a consumer that was *reading the prefix strings themselves* will see them
  disappear, and any profile attested at `0.2.0` carries the unfolded values.
  That is deliberate: those values should not have been emitted.

  Found by the human PII review of the first retained artifact, which is exactly
  the check that review exists to be. No sentinel test could have caught it —
  the fixture's `toolu_<sentinel>.txt` split at the underscore and yielded
  `toolu`, so the sentinel never reached the counter. The fixture now plants the
  three shapes a real corpus actually holds.

Except for that fold, no existing key changed, so this is a `MINOR` bump. CCDC's
`SCHEMA.md` reads this shape by name, so the heads-up names the two new keys
explicitly — `message_shape` and `tool_cycle` — and flags the
`tool_results.name_prefixes` value-space narrowing as the one behavioral change
to something it may already be reading.

## [0.2.0] — manifest shape by Claude Code version, and a nesting probe

Added for issue #169, which needed to settle "what subagent spawn depth did the
runtime actually reach, at which Claude Code version" from observation rather
than from a self-contradicting CHANGELOG.

- **New top-level report key `meta_json_by_version`.** Buckets `meta.json`
  manifest shape by the Claude Code version that produced it. Each bucket carries
  the manifest count, the per-key presence counts, and a value histogram for keys
  on the new `EMITTABLE_META_VALUE_FIELDS` whitelist. Versions are ordered
  numerically. This is the reusable half of the change: any "when did this
  manifest key appear" question now reads straight off the table.

  A manifest carries no version of its own, so it inherits the **earliest**
  version observed on its own sibling trace file — the manifest is written at
  spawn time. Manifests whose trace is missing or unversioned are counted in
  `manifests_unattributed` rather than dropped, and traces spanning a CC upgrade
  are counted in `traces_spanning_multiple_versions`.

- **New `EMITTABLE_META_VALUE_FIELDS` whitelist**, currently `{"spawnDepth"}`.
  This is the first time any `meta.json` *value* is emitted, so the bar is
  deliberately higher than for `EMITTABLE_VALUE_FIELDS`: a key qualifies only if
  its value space is a small closed set the runtime writes about its own
  bookkeeping, with no path through it for user content. Adding a key here is an
  output-affecting change and requires a bump.

- **New `--probe-nesting` mode** (own output shape, like `--probe-tool-results`).
  Counts nested `subagents/` directories, histograms `spawnDepth`, and joins each
  manifest's `toolUseId` to its spawning `Agent` `tool_result` to report — per
  depth — whether that line carries a `toolUseResult` rollup sibling, whether it
  carries the inline `subagent_tokens` trailer, and which file holds it.
  Unlocatable spawn sites are counted so the denominator stays honest.

No existing key changed shape, so this is a `MINOR` bump.

## [0.1.0] — first stamped version

First build to carry a `scan_version`. Nothing earlier was ever versioned or
attested, so `0.1.0` is not a back-compat claim about any prior output.

The stamped shape **already includes** the per-subagent `meta.json` manifest
probe (`meta_json_keys`) and the `tool-results/` file-shape probe added in
issues #96 / #97 — those landed before versioning existed and are part of the
`0.1.0` baseline, not a future bump.
