# Plan: #237 — feat(format-scan): re-derive Part 5's five statistic families and retain the output as a committed artifact

**Route:** code **Branch:** `feature/237-format-scan-statistic-families`

## Value framing (route-scaled — `feat:`)

**Backbone activity:** a reader of `reference/tool-invocation.md` wants to check a number, and
today cannot, because the number's derivation was never retained.

- **As a reference reader (and as AgentFluent/CodeFluent, which link here rather than
  re-documenting), I want each statistic in `reference/` to name its denominator and its
  provenance, so that I can tell a measured claim from a remembered one.**
  Who benefits: every downstream consumer of `reference/`. Prevalence: all ten figures #226 wants
  to backfill are in this state — a repo-wide grep finds them only in
  `posts/2026-09-10-the-tool-call-completely.md`, nowhere in `reference/`, `.claude/specs/`, or
  #210's body. Falsifier: **if the local corpus contained ~0 instances of these surfaces, the
  counters would be measuring nothing.** DISCHARGED below — it does not fire.
- **As the maintainer, I want the scanner to compute these families itself, so that the next
  re-derivation is a command rather than an ad-hoc pass whose definitions are lost again.**
  Who benefits: #231's re-verification cadence, which re-stamps these same sections. Prevalence:
  this is the second time these numbers are needed and the first derivation is already
  unrecoverable. Falsifier: **if `scan.py` already computed them, this is redundant.** Discharged:
  it does not — `EMITTABLE_VALUE_FIELDS` is `{"type", "version"}` and no counter in
  `Observation` touches `stop_reason`, `structuredPatch`, `tool_use_id` joins, or
  `message.content` shape on `user` lines.

### Falsifier discharge — content-free probe over the local corpus, 60-file sample

Run at plan time (scratchpad script; emits only counts against fixed strings we supply, the same
argument that makes `PERSISTED_MARKERS` content-free). **The falsifier does not fire** — every
family has real instances:

| Surface | 60-file sample |
| --- | --- |
| `tool_use` / `tool_result` blocks | 1,342 / 1,342 |
| assistant lines with `stop_reason` | 1,797 present, **658 absent** (of 2,455) |
| `stop_reason` values | `tool_use` 1,699 · `end_turn` 95 · `stop_sequence` 3 |
| `stop_sequence` key present | 3 |
| `message.model == "<synthetic>"` | 3 |
| `user` `message.content` shape | list 1,346 · str 154 |
| `toolUseResult` dicts | 976 (`structuredPatch` 146 · `prompt` 13 · `toolStats` 1) |
| `tool_use.name` | `Edit` 138 · `Agent` 13 · `Bash` 762 · `Read` 289 |

**Three findings the prior architect pass did not have, all bearing on its own I3 ruling:**

1. **27% of assistant lines carry no `stop_reason` at all** (658 of 2,455). The denominator for
   family 1 is therefore *not* "assistant lines" — it has to be stated, and the absent count has
   to be reported rather than smoothed away, or the distribution silently renormalizes.
2. **`structuredPatch` appears on MORE results than there are `Edit` tool_uses** (146 vs 138), so
   it is not `Edit`-exclusive — `Write`/`MultiEdit`/`NotebookEdit` plausibly carry it too. A naive
   "count `structuredPatch` occurrences" over-counts against an `Edit` denominator. This is direct
   evidence for I3's insistence that the denominator be defined by the join, not by the key.
3. **All 3 `stop_sequence` occurrences in the sample coincide with the 3 `<synthetic>` model
   lines.** Early signal that #234 item 2 resolves toward "harness lines, not real terminations" —
   which is exactly what family 1's cross-tab is being built to settle. Not asserted as the
   answer; a 60-file sample is not the corpus.

### Source-fidelity note

The rationale leans on an external source — #226's "All five come from the same 2026-08-25 scan
behind #210, so the provenance exists." **That claim was checked and is false**; the correction is
already posted to #226 (`issuecomment-5740664408`, write-once, do not re-post). This issue exists
*because* the source did not support the generalization, which is the source-fidelity check
resolving in the direction of "re-derive" rather than "cite".

## Acceptance criteria (verbatim from issue)

- [ ] `tests/test_content_free_contract.py` plants sentinels in every new value the counters read, including `stop_sequence` and `stop_details.explanation`, and passes. This lands before the counters.
- [ ] All five families are computed, placed per the two classes above, with each denominator defined in code.
- [ ] `stop_reason` added to `EMITTABLE_VALUE_FIELDS`; `stop_sequence` and `stop_details` are not.
- [ ] The synthetic-vs-real bucket emits fixed labels only, with an `absent` bucket, and never the model string.
- [ ] `__version__` bumped to `0.3.0` with a `CHANGELOG.md` entry; no timestamp in the `--json` body.
- [ ] Tests for every new counter under `tooling/format-scan/tests/`.
- [ ] A scan is run over the local corpus and its `--json` report committed, with the date in the filename and a corpus fingerprint derivable from the body.
- [ ] The artifact is reviewed by a human for PII before commit.
- [ ] The `stop_reason` cross-tab result is recorded on #234, answering item 2.

## Approach

**Revised after the architect pass (step 4c). Dispositions are marked `[adopted]`, `[adapted]` or
`[declined]` against the architect's own severity. The frozen pre-image above is what this is
diffed against at step 5.**

**Step 0 — placement fork RESOLVED: option (c), per-file join inside `scan()` `[adopted, the
architect's own I1 placement ruling changed].**
The prior pass put class-2 families into a probe on `probe_nesting`'s precedent. That premise is
false and I verified it by reading: `probe_nesting`'s join is genuinely global and two-phase —
`targets` is built across every session dir (`scan.py:558-572`), then matched in a second full
`rglob` over every transcript (`:579-624`). This join is **intra-file**, and `scan()` already
accumulates per-file state and resolves it at EOF (`is_trace`/`file_versions` → `obs.trace_versions`,
`scan.py:361-382`). Per-file is also the *correct* scope, not merely the convenient one:
`reference/tool-invocation.md:83` documents that subagent traces carry their own `tool_use_id`
space, so a cross-file join would resolve ids a real parser cannot.
Rejected: two artifacts (breaks CCDC's `sha256(scan.json)` content-addressing, `CHANGELOG.md:26-28`,
and gives the second blob no `scan_version` story); probe-plus-fold (double-reads the corpus or
duplicates the join).
**Constraint:** per-file buffers do NOT hang off `Observation` — its docstring is "across all
scanned files" (`scan.py:186`) and per-file mutable state would break that invariant as a
state-bleed bug no test catches. A small per-file object is created in the `scan()` loop body
beside `file_versions` and resolved into `obs` at EOF.
**Report shape:** two new top-level keys, not five — `message_shape` (families 1-2) and
`tool_cycle` (families 3-5), each carrying its denominators inline (I3). Smaller CCDC surface.
`print_human()` needs matching sections (`scan.py:715-806`). **No baseline change:**
`_DIFF_CATEGORIES` (`scan.py:409-416`) covers taxonomies, not counters — stated so the implementer
does not invent a `baseline-*.json` edit.

**Step 1 — the sentinel test lands FIRST (B1), alone, against the UNMODIFIED scanner.**
Extend `planted_root` in `tests/test_content_free_contract.py`. The original list
(`stop_sequence`, `stop_details.explanation`, an `Edit` `toolUseResult`, an `Agent`
`toolUseResult.prompt`, a string-shaped `user` `message.content`, a real-looking `message.model`)
**was incomplete — three blocking gaps, all adopted:**

- **`[adopted, blocking]` The join keys themselves.** Verified: `test_content_free_contract.py:55-57`
  plants a `tool_use` with **no `id`** and a `tool_result` with **no `tool_use_id`**; `S_UUID` sits
  on the line's `uuid` (`:50`) and on manifest `toolUseId` (`:79`), never on a content block. Family
  4 is *defined by* unresolvable ids and the natural debug output for an unresolvable set is the
  set. Plant `"id": S_UUID + "-tu"` with a matching `tool_result`, **plus** a second `tool_result`
  carrying `"tool_use_id": S_UUID + "-orphan"` matching nothing, so the orphan path is specifically
  covered. (This also closes a half-covered gap in `probe_nesting`'s existing join at `scan.py:603`.)
- **`[adopted, blocking]` `tool_use.name`.** The counters read it for the `Edit`/`Agent` join, so
  AC-1 requires a sentinel on it. It must **never** be emitted as a free histogram: tool names are
  not a closed vocabulary (MCP tools carry server-derived `mcp__<server>__<tool>` names; plugin and
  user tools carry author-chosen ones). This is the identical disqualifier the code already applies
  to `agentType` at `scan.py:100-102` — "user-defined agents put arbitrary author-chosen names in
  it." Add a module-level `TOOL_NAME_ALLOWLIST` beside `SUBAGENT_TOKENS_MARKER` (`scan.py:105-111`)
  carrying the same "strings WE supply" comment plus an explicit never-emit-an-observed-name line;
  fold everything else to a fixed `<other>`. Plant `"name": "mcp__" + S_PROMPT + "__do"` and assert
  both that it does not surface and that it lands in `<other>`.
- **`[adopted, blocking]` `stop_reason`'s own value — this reinterprets AC-1 and AC-3.** Two
  verified statements contradict each other: `scan.py:86-89` sets the whitelist bar at "a **closed,
  content-free vocabulary**", while `reference/data-dictionary.md:99` says of this exact field
  "**Treat this as an open enum, not a closed switch.**" So promoting it to raw emission puts an
  explicitly-open value space into a corpus-derived artifact in a public repo — and B1 structurally
  cannot gate it, because planting a sentinel *in* `stop_reason` would make the sentinel test fail
  by design. **Resolution: fold, don't drop.** Emit the seven documented values from a fixed
  `STOP_REASON_VALUES` constant, plus `null` and `absent`, and fold anything unrecognized into a
  fixed `<other>`. The artifact becomes a reviewable closed set; an unrecognized value still
  surfaces as drift (`<other>` > 0 is exactly the format-watch signal this scanner exists for); and
  the surface becomes testable — plant `S_PROMPT` in `stop_reason`, assert it lands in `<other>` and
  the sentinel never appears. **`stop_reason` still goes on `EMITTABLE_VALUE_FIELDS` (AC-3
  unchanged); what changes is HOW it is emitted**, which was unspecified when the prior pass ruled.
- **`[adopted]` Bare-string `toolUseResult`.** Verified `reference/tool-invocation.md:195`: on a
  minority of results `toolUseResult` is a bare string — **`Edit` 240** of them, alongside `Bash`
  1,075 / `Read` 607 / `Write` 139. This bites family 3 directly: a dict-only denominator silently
  drops 240 `Edit` results, which is finding 2's lesson repeating. Plant a sentinel-bearing
  bare-string `toolUseResult` and report a `toolUseResult_non_dict` count beside the dict
  denominator.
- **`[adopted]` `toolStats` sub-keys.** `tool-invocation.md:539` describes them as **category**
  counters whose keys are tool names. Family 5 only tests `"toolStats" in <dict>`, which is fine;
  add a one-line comment forbidding a key histogram over it, for the Q3-b reason.

**Step 2 — line-streamable families into `Observation.ingest_line` (I1 class 1).**

- *Family 1 — `stop_reason` × synthetic-vs-real.* Denominator: lines with `type == "assistant"` and
  a dict `message`. **`[adopted]` Three states, not two:** `present_non_null`, `present_null`,
  `absent` — `reference/data-dictionary.md:99` treats key-absent and present-`null` as different
  facts ("`null` also appears… on lines recording an incomplete turn… not safe to discard"), and a
  merged 658 cannot be re-derived into the claim `reference/` will make. `without_stop_reason` stays
  derivable as the sum. **`[adopted]` Also count `isApiErrorMessage` presence** on assistant lines —
  `data-dictionary.md:108` documents it as an API-error record that "should be excluded from token
  and turn metrics", it is a boolean (content-free), and it is the leading hypothesis for a chunk of
  the 658. That turns "27% absent" into "27% absent, of which N are API-error records".
  Values folded per Step 1's `STOP_REASON_VALUES`. Cross-tab against a `message.model` bucket:
  `synthetic` when `== SYNTHETIC_MODEL_MARKER`, `absent` when missing/null, `real` otherwise. The
  observed model string never reaches output — only the three fixed labels.
- *Family 1b — `[adopted]` companion `stop_sequence` state table.* The 2-axis cross-tab settles the
  `stop_reason`-value half of #234 item 2, but **not** the claim `data-dictionary.md:100` actually
  stakes, which is about the **field**: "the only non-`null` instance in this repo's fixtures is an
  **empty string** on a `message.model == "<synthetic>"` line." Add `stop_sequence` state × model
  bucket with four fixed labels — `absent` / `null` / `empty_string` / `non_empty_string`.
  Content-free by construction (`json_type()`-style bucketing, `scan.py:114-136`, plus a length
  test) and it settles the field-level claim **without ever emitting the value**, which is precisely
  why `stop_sequence` stays off the whitelist.
- *Family 2 — `user` `message.content` shape.* Denominator: lines with `type == "user"` and a dict
  `message`. Buckets `list` / `str` / `other` / `absent`.
- `stop_reason` and only `stop_reason` joins `EMITTABLE_VALUE_FIELDS`; never `stop_sequence`
  (`data-dictionary.md:100`) and never `stop_details` (`:101`). SECURITY CONTRACT docstring updated
  in the same edit, including the fold rule.

**Step 3 — join-requiring families, per-file inside `scan()` (I1 class 2, placement per Step 0).**
Id used purely as a join key, never emitted.

- *Family 3 — `Edit` envelope.* Denominator: `tool_result` blocks whose `tool_use_id` resolves, **in
  the same file**, to a `tool_use` with `name == "Edit"`. Numerator: `"structuredPatch"` present in a
  dict `toolUseResult`. Report the unresolvable count (mirroring `spawn_sites_not_located`) **and**
  the non-dict count, so neither shape is silently dropped. **`[adopted]` Cross-tab `structuredPatch`
  presence by joined tool name from `TOOL_NAME_ALLOWLIST`, `<other>` folded** — `reference/` already
  documents it as non-`Edit`-exclusive (`tool-invocation.md:236` Write, `:247` Edit), so the scan's
  job is to confirm *which* set carries it rather than to rediscover that it isn't exclusive. This
  makes the artifact answer finding 2 instead of raising it.
- *Family 4 — orphan `tool_result`.* A `tool_result` whose `tool_use_id` matches no `tool_use` `id`
  in the same file. Split on the line's `isSidechain`. Denominator: all `tool_result` blocks.
- *Family 5 — `Agent` envelope conditional keys.* Same join, `name == "Agent"`; presence counts for
  `"prompt"` and `"toolStats"`.

**Step 4 — version, changelog, artifact.**
`__version__` `0.2.0` → `0.3.0`, the defined MINOR case (`CHANGELOG.md:36-38`), with an entry
**naming the two new top-level keys** — CCDC's `SCHEMA.md` reads this shape by name
(`scan.py:71-76`), so the heads-up has to name them. No wall-clock timestamp in the attested body
(I4). **`[adopted]` Add `max_files` (int or `null`) to `summary`** (`scan.py:663-668`): AC-7 wants a
fingerprint derivable from the body, and `files_scanned`/`lines_scanned`/`versions` cannot tell a
full scan from a `--max-files 60` sample — the exact confusion this plan's own falsifier section has
to disclaim. It is an invocation parameter, content-free and deterministic, so it does not violate
I4. **`[adopted]` README paragraph** for the two new keys and their denominators
(`README.md:46-60` precedent) — I3 is only half-served if the artifact's reader never sees the
definitions.

**Step 5 — run the scan, then STOP for the human's PII gate (AC-8).**
**`[adopted]` Write the report to the scratchpad, never into the working tree.** `.gitignore` has no
rule under `tooling/format-scan/` (verified, full file read), so an untracked corpus-derived JSON
sitting in the tree is one `git add -A` from being committed unreviewed. Hand the scratchpad path
to the human; `mv` into `tooling/format-scan/scan-<YYYY-MM-DD>.json` only after AC-8 clears.

**Step 6 — record BOTH tables on #234 (AC-9).** `[adapted]` The cross-tab alone half-answers item 2;
the `stop_sequence` state table is the other half.

**`[DECLINED — escalated to the human instead, not decided here]` Architect (f): add
`tooling/format-scan/tests` to CI.** The finding is **correct and verified** — grep for
`format-scan`/`scan.py` across `.github/` returns no matches, so B1, the single enforcing leak gate
for this change, runs only when someone remembers to type the command. But adopting it would touch
`.github/workflows/`, which is outside every one of #237's nine ACs, and the human has **already
ruled on this territory in this run**: #235 was left out precisely because it "routes `code` via
`.github/workflows/`, a different pipeline shape from every other row here." Folding a CI job in
here would quietly reverse that curation decision. Recommendation carried to the plan gate as a
follow-up issue; the human can overrule.

**Files to touch:** `tooling/format-scan/tests/test_content_free_contract.py` (first, alone),
`tooling/format-scan/scan.py`, a new `tooling/format-scan/tests/test_statistic_families.py`,
`tooling/format-scan/CHANGELOG.md`, `tooling/format-scan/README.md`, plus the generated artifact
(staged in the scratchpad until AC-8 clears).

**Tests to add:** per-family unit tests over synthetic fixtures via `_helpers.make_session` — the
three-state `stop_reason` denominator; the `<other>` fold for an unrecognized `stop_reason` and an
unallowlisted tool name; the four-label `stop_sequence` state table; unresolvable-join and
non-dict-`toolUseResult` counts; the orphan split on `isSidechain`; and the `Edit`-join denominator
against a fixture where `structuredPatch` also rides a non-`Edit` result (finding 2 as a regression
test). **`[adopted]` Extend the vacuous-pass guard** at `test_content_free_contract.py:131-145` so
each new report section's key **and** a non-zero denominator are asserted on the planted fixture —
otherwise a counter silently returning `{}` reads green on both tests.

## Approach as reviewed (frozen before the design gate) — write-once, do not edit

**Step 1 — the sentinel test lands FIRST (B1), before any counter.**
Extend `planted_root` in `tests/test_content_free_contract.py` to plant `S_PROMPT`/`S_PATH`/
`S_UUID`/`S_CRED` into every surface the new counters read and none currently cover:
`message.stop_sequence`, `message.stop_details.explanation`, an `Edit` `toolUseResult`
(`filePath`/`oldString`/`newString`/`structuredPatch` body), an `Agent` `toolUseResult.prompt`,
and a string-shaped `user` `message.content`. Also plant a non-`<synthetic>` `message.model`
string, since the synthetic-vs-real bucket reads it. Commit this alone and watch it pass against
the *unmodified* scanner — that is what makes it a gate rather than a description of what the new
code happens to do.

**Step 2 — line-streamable families into `Observation.ingest_line` (I1 class 1).**

- *Family 1 — `stop_reason` × synthetic-vs-real.* Denominator: lines with `type == "assistant"`
  and a dict `message`. Report `assistant_lines`, `with_stop_reason`, and `without_stop_reason`
  explicitly (finding 1 above), then the value histogram cross-tabbed against a bucket derived
  from `message.model`: `synthetic` when `model == SYNTHETIC_MODEL_MARKER`, `absent` when the key
  is missing or null, `real` otherwise. `SYNTHETIC_MODEL_MARKER = "<synthetic>"` is a fixed
  constant we supply, mirroring `PERSISTED_MARKERS`/`SUBAGENT_TOKENS_MARKER` at `scan.py:105-111`.
  **The observed model string never reaches output** — only the three fixed bucket labels.
- *Family 2 — `user` `message.content` shape.* Denominator: lines with `type == "user"` and a dict
  `message`. Buckets `list` / `str` / `other` / `absent`.
- Add `stop_reason` and only `stop_reason` to `EMITTABLE_VALUE_FIELDS`. Never `stop_sequence`
  (`reference/data-dictionary.md:100` — carries the caller-supplied matched sequence) and never
  `stop_details` (`:101` — free text). Update the SECURITY CONTRACT docstring in the same edit.
  Note this is declarative: `scan.py:239-240` is `... "type" in EMITTABLE_VALUE_FIELDS: pass` and
  `version` is emitted at `:242-244` with no membership check, so the frozenset is advisory and
  the sentinel test is the only enforcing gate. Verified against source.

**Step 3 — join-requiring families (I1 class 2).**

The join is **per-file** (`tool_use_id` → tool name within one transcript), which is why it does
not stream in `ingest_line`. Following `probe_nesting`'s precedent (`scan.py:523-639`): hold the
id map, use the id purely as a join key, never emit it.

- *Family 3 — `Edit` envelope.* Denominator: `tool_result` blocks whose `tool_use_id` resolves, in
  the same file, to a `tool_use` with `name == "Edit"`, and whose line carries a dict
  `toolUseResult`. Numerator: those with `"structuredPatch"` in that dict. Report the unresolvable
  count too, mirroring `spawn_sites_not_located`, so the denominator stays honest.
- *Family 4 — orphan `tool_result`.* A `tool_result` block whose `tool_use_id` matches no
  `tool_use` `id` anywhere in the same file. Split on the **line's** `isSidechain`
  (true → sidechain, false/absent → parent). Denominator: all `tool_result` blocks.
- *Family 5 — `Agent` envelope conditional keys.* Same join, `name == "Agent"`; presence counts
  for `"prompt"` and `"toolStats"` in the dict `toolUseResult`.

**Open placement question for the architect:** the prior pass ruled these into a *probe* on
`probe_nesting`'s precedent, but a probe has its own output shape and does not appear in the main
`--json` report — which collides with AC-7's single committed artifact. The per-file scope of the
join means a second pass inside `scan()` is also viable without breaking streaming. Resolved
before implementation.

**Step 4 — version, changelog, artifact.**
Bump `__version__` `0.2.0` → `0.3.0` (the defined MINOR case, `CHANGELOG.md:36-38`) with a
`CHANGELOG.md` entry. **No timestamp in the attested JSON body** (I4). The date goes in the
filename; the corpus fingerprint is derivable from `files_scanned`/`lines_scanned` plus the
`versions` histogram. `SCHEMA.md` is owned by `claude-code-data-collective` and is not edited from
here.

**Step 5 — run the scan, then STOP for the human's PII gate (AC-8).**
Full-corpus `--json` run, output written to `tooling/format-scan/scan-<YYYY-MM-DD>.json`. The loop
does not commit it.

**Step 6 — record the cross-tab on #234 (AC-9).**

**Files to touch:** `tooling/format-scan/tests/test_content_free_contract.py` (first, alone),
`tooling/format-scan/scan.py`, `tooling/format-scan/tests/test_scan.py` (or a new
`test_statistic_families.py`), `tooling/format-scan/CHANGELOG.md`, `tooling/format-scan/README.md`
if a new flag lands, plus the generated artifact.

**Tests to add:** per-family unit tests over synthetic fixtures via `_helpers.make_session` —
denominator correctness (including the absent-`stop_reason` and unresolvable-join cases), the
three fixed bucket labels with a planted real model string asserted absent from output, the
orphan split on `isSidechain`, and the `Edit`-join denominator against a fixture where
`structuredPatch` also appears on a non-`Edit` result (finding 2 above, made into a regression
test).

## Architect triggers hit

- **"A new reference-doc contract that AgentFluent or CodeFluent will link to"** — indirectly: the
  `--json` shape is the CCDC cross-repo interface, keyed by `(tool, scan_version)`, and this
  change moves it.
- **"The orchestrator is unsure"** — the placement question above (probe vs. second pass in
  `scan()`) is unresolved and AC-7 makes it load-bearing rather than cosmetic.
- A prior architect pass ruled on this design as part of #226 (I1/I3/I4/B1/S1, recorded in the
  issue body verbatim). This consult is **narrow and non-relitigating**: the three new falsifier
  findings bear on its own I3 denominator ruling, and the probe-vs-`scan()` collision with AC-7
  was not visible when it ruled.

## Risks / open questions for human

- **AC-8 is a hard stop the loop cannot discharge.** The artifact is corpus-derived; the sentinel
  test proves the scanner does not emit planted values and cannot prove the corpus held nothing
  unanticipated. The iteration will stop and hand the artifact over before any commit of it.
- **The corpus has drifted substantially since 2026-08-25.** The 60-file sample already shows
  top-level types absent from `baseline-v2.1.150.json` (`ai-title`, `atis-latch`,
  `bridge-session`, `attachment`, `file-history-delta`, `queue-operation`, …). Fresh figures will
  differ from Part 5's by more than sampling noise, which #226 must frame (its I2 banner) rather
  than present as a correction of the old ones. Out of scope here; flagged so it is not a surprise.
- **`structuredPatch` is not `Edit`-exclusive** (finding 2). The `Edit`-join denominator is the
  right definition, but it means the committed artifact's number will not match a naive grep, and
  `reference/` should say so.
