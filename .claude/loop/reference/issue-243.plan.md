# Plan: #243 — docs(reference): Part 6 scan contradicts two hook rows

**Route:** docs  **Branch:** `fix/243-hook-rows-data-dictionary`

## Value framing (route-scaled — see step 3)

**Who reads it.** `reference/` is the source of truth two sibling projects link to instead of
duplicating format docs (CLAUDE.md § Sibling project relationship): AgentFluent and CodeFluent both
parse `~/.claude/projects/*.jsonl`. A parser author deciding whether to branch on `toolDenialKind`
has no row to read today, and one reading the `hookAdditionalContext` row is told the field is
"Rare" when it sits on 2,981 lines.

**What it unblocks.**

- **#244** now carries an acceptance criterion to come back and drop this row's
  "value vocabulary unobserved" qualifier once the fold lands. That AC has nothing to edit until
  this row exists.
- **#153** (enumerate observed `system` subtype values) cites this same section.
- **PR #245 / Part 6** states both corrections in prose and defers to `reference/` as the source of
  truth. Landing this first means the post never ships contradicting the doc it defers to.

**Falsifier.** *If the counts the issue cites do not survive re-derivation from the committed
artifact, the corrections are misdirected and the issue should be re-scoped rather than
implemented.*

### Falsifier DISCHARGED at plan time — and it changed the plan

Re-derived every figure from `tooling/format-scan/scan-2026-09-19.json` rather than trusting the
issue body. The counts hold. **Two premises did not.**

**(1) The `toolDenialKind` count is EXACT, not an upper bound.** The two counters differ in
weighting, and the issue reasoned from only one of them:

| Counter | Increments | Site | Cross-check |
|---|---|---|---|
| `keys_by_type` / `top_level_keys` | once **per line** | `scan.py:496-497`, loop over `obj.keys()` | `keys_by_type.user.cwd` = 107,267 = `top_level_types.user` |
| `tool_result_line_keys` | once **per `tool_result` block** | `scan.py:577`, inside the block loop | `tool_result_line_keys.cwd` = 96,608 = `content_block_types.tool_result` |

Both identities hold exactly, so the weighting of each is established rather than assumed. The issue
cites `tool_result_line_keys.toolDenialKind = 227` and concludes "227 is an upper bound on distinct
lines". But **`keys_by_type.user.toolDenialKind` is also 227**, and that counter is line-weighted —
so 227 is the **exact count of distinct `user` lines** carrying the key, out of 107,267 `user` lines.

The block-weighted caveat is still worth a sentence, because the two counters agreeing is itself
informative: `tool_result_line_keys` can only exceed the line count when a line carries multiple
`tool_result` blocks, so equality is consistent with every `toolDenialKind`-bearing line carrying
exactly one. That is an observation, not a proof — one 0-block line offset by one 2-block line would
also produce equality — so it is stated as consistent-with, never as established.

**This reinterprets AC-3**, which asks the row to "state the block-weighted denominator". It also
contradicts the instruction carried into this invocation ("the 227 observations are an UPPER BOUND
on distinct lines... keep it"). Flagged for the human at step 5 rather than silently overridden or
silently complied with.

**(2) AC-4's version note cannot be written as asked.** It asks both rows to carry
"Verified against Claude Code v2.1.278". Two problems:

- **The section banners would be lying.** `### system` currently reads "Verified against Claude Code
  v2.1.170" and `### user` reads "v2.1.150". Bumping either to v2.1.278 asserts the *whole section*
  was re-verified. It was not. That is the exact defect **#231** is open about, so satisfying AC-4
  the obvious way would manufacture a new instance of the problem another row in this queue exists
  to fix.
- **The figures are not a single-version observation.** The corpus spans **130 versions**, v2.1.4
  through v2.1.278, and v2.1.278 contributes **1,303 of 436,010 lines** (0.3%). A count derived that
  way is a corpus aggregate; "verified against v2.1.278" misdescribes how it was obtained.

## Acceptance criteria (verbatim from issue)

- [ ] `hookAdditionalContext` row no longer says "Rare"; replacement wording cites counts and keeps the co-occurrence caveat
- [ ] New `toolDenialKind` row added, on the `user` / tool-result side of the doc, not under `system`
- [ ] The `toolDenialKind` row states the block-weighted denominator and marks the value vocabulary unobserved
- [ ] Both carry a "Verified against Claude Code v2.1.278" note, consistent with the section convention
- [ ] Figures traceable to `tooling/format-scan/scan-2026-09-19.json`

## Approach

**Files to touch:** `reference/data-dictionary.md` only. No fixture, no tooling, no post.

**Architect pass ran** (`architect`, one round, cross-repo-interface trigger). Four findings: three
important, one suggestion. **All four adopted**; the revisions are marked *(architect)* below.

**Step 1 — `hookAdditionalContext` (line 283).** Replace the trailing `Rare.` with a count-based
statement: 2,981 `system` lines carry it, against 3,964 carrying the seven-key hook-execution family
and 10,429 `system` lines in the corpus. **Compare counts; do not assert a ratio or a subset.** All
three are line-weighted and therefore directly comparable, but equal-or-lesser aggregates cannot
prove the 2,981 sit inside the 3,964 — the scanner counts keys per line and never joins them. 2,981
absolute occurrences retires "Rare" regardless of the join.

Supporting figure for the family denominator, re-derived: `hookCount`, `hookInfos`, `hookErrors`,
`hasOutput`, `preventedContinuation`, `stopReason` and `toolUseID` all sit at **exactly 3,964** on
`system`.

*(architect, forward-compat)* **Keep this edit narrow.** #153 (enumerate observed `system` subtype
values) cites this same subsection; touching adjacent hook-family prose would step on its later enum
work.

**Step 2 — new `toolDenialKind` row, in the `### user` top-level sibling table (~line 144).**
*Not* the `### tool_result` block table at line 402. The architect confirmed placement on independent
evidence: both counters that report this key iterate `obj.keys()` (`scan.py:497` and
`scan.py:575-577`), so `toolDenialKind` is provably a **top-level line key**, not a field inside the
block. Putting it in the block table would misstate where a parser finds it.

Row content:

- Type: string.
- *(architect)* **Lead unhedged: 227 distinct `user` lines of 107,267.** That figure rests entirely
  on `keys_by_type.user.toolDenialKind`, which is the distinct-line count by construction — it does
  not depend on the block-weighted counter at all. The dual-counter epistemics stay in this plan and
  the PR body; a hedge-heavy row would bleed uncertainty onto the one fact that is certain.
- *(architect)* **The denial's source is unobserved — name three candidates, each labelled a
  candidate, none asserted:** a hook deny (→ `system` § `preventedContinuation` / `stopReason`), a
  user rejection at a permission prompt, and the `PermissionDenied` auto-mode classifier event
  (line 562). Point at **#244** for the fold that settles which.
- *(architect)* **Do NOT splice this into the `hookAdditionalContext` ↔ Hook-response-schema
  cross-link chain.** That chain is about `additionalContext` injection on `Stop`/`SubagentStop` — a
  different contract. Wiring a denial marker into it would assert a denial-is-a-hook-artifact
  correspondence the scan cannot support, which is the unobserved-cross-family-join error this doc is
  otherwise scrupulous about.

**Step 2b *(architect, NEW)* — discoverability cross-reference.** The structural home and the
semantic entry point differ: a reader investigating denials looks at the `tool_result` block first
and would find nothing. The doc already has the precedent for exactly this split at line 415 ("the
actionable tool metadata is NOT in `tool_result` — it's in the sibling `toolUseResult` envelope").
Mirror it: add a one-line see-also in the `### tool_result` section pointing up to the new row. A
whole new subsection is not warranted for one scalar string key with unread values.

Also reword the `### user` table lead-in at line 142 — "One optional top-level sibling key is
significant:" becomes wrong once there are two. Reword so it carries both **without** making
`toolDenialKind` a peer of `toolUseResult`, which the doc calls "one of the highest-information
surfaces in the format" (line 218). They share a structural position, not a weight.

**Step 3 — provenance at row scope, reaching BOTH sections *(architect-revised)*.** The pre-review
plan anchored provenance to "the hook-execution subsection" only. That covers `hookAdditionalContext`
(under `system`) but **not** `toolDenialKind`, which lives in the `user` section under a v2.1.150
banner — it would have shipped with a bare count and no corpus attribution, under-serving AC-5 for
that row.

Instead: state the corpus facts **once**, by extending the existing scan-provenance sentence at line
258 (`scan-2026-09-19.json`, 3,500 files / 436,010 lines / 130 versions v2.1.4–v2.1.278, values not
read), and have the `user`-side row cite the artifact and its counter **by name** and point there,
rather than restating numbers that would drift on the next scan.

Leave both section banners untouched (`system` v2.1.170, `user` v2.1.150); **#231** owns that sweep.
Note the hand-off in the PR body so #231 knows these two rows are already provenance-stamped at row
scope, and does not re-stamp or assume they are stale.

**Claim-scoped provenance is this doc's existing convention**, so this satisfies AC-4's "consistent
with the section convention" clause even though it does not use the literal string
"Verified against Claude Code v2.1.278" — and that literal string is the part that would be false.
Verified precedents: `entrypoint`'s `"sdk-py"` value pinned to "SDK 0.2.106 / CLI 2.1.185" under a
different banner (**line 69** — the architect cited this at line 193; substance confirmed, citation
corrected), the assistant API-error markers "added in the v2.1.170 re-verification" (line 83), and
the `stop_*` rows explicitly carrying no separate version marker (line 85).

**Step 4 — traceability.** Cite `tooling/format-scan/scan-2026-09-19.json` by path and name the
counter each figure comes from (`keys_by_type.system.*`, `keys_by_type.user.toolDenialKind`,
`top_level_types.*`), so a reader can re-derive rather than trust. Use a full GitHub URL for the
in-repo reference, per the Pages-portability convention.

*(architect, forward-compat)* **#93 boundary.** #93 catalogues top-level tool-linkage keys on
`system` lines (`toolUseID`). `toolDenialKind` is user-side and distinct, so this row must not claim
#93's surface, and #93 must not later re-own this key. Say which owns what.

**Checks:** `npx prettier reference/data-dictionary.md --check`. No test suite is implicated
(`docs` route: no mutation pass, no hermetic-tier run, security skipped).

## Approach as reviewed (frozen before the design gate) — write-once, do not edit

**Files to touch:** `reference/data-dictionary.md` only. No fixture, no tooling, no post.

**Step 1 — `hookAdditionalContext` (line 283).** Replace the trailing `Rare.` with a count-based
statement: 2,981 `system` lines carry it, against 3,964 carrying the seven-key hook-execution family
and 10,429 `system` lines in the corpus. **Compare counts; do not assert a ratio or a subset.** All
three are line-weighted and therefore directly comparable, but equal-or-lesser aggregates cannot
prove the 2,981 sit inside the 3,964 — the scanner counts keys per line and never joins them.

Supporting figure for the family denominator, re-derived: `hookCount`, `hookInfos`, `hookErrors`,
`hasOutput`, `preventedContinuation`, `stopReason` and `toolUseID` all sit at **exactly 3,964** on
`system`.

**Step 2 — new `toolDenialKind` row.** Add it to the **`### user` top-level sibling table**
(line ~143), beside `toolUseResult` — *not* to the `### tool_result` block table at line 402.
Rationale: `toolDenialKind` is a **top-level** key on the `user` line, the same structural position
as `toolUseResult`; the `tool_result` table documents keys *inside* the block. AC-2's "on the `user`
/ tool-result side of the doc, not under `system`" is satisfied by the `user` table, and placing it
in the block table would misstate where a parser finds it.

Row content:
- Type: string.
- Semantics: present on a `user` line whose `tool_result` reports a denial. **Mark the value
  vocabulary unobserved** — the scanner counts the key and never reads the value, so whether it
  discriminates a hook block from a user rejection at a permission prompt from an auto-mode
  classifier denial is **not established**. Point at #244, which folds it.
- Prevalence: 227 distinct `user` lines (see the AC-3 reinterpretation above), of 107,267.

**Step 3 — provenance, not a banner bump.** Attach a row-scoped provenance sentence to the
hook-execution subsection naming the artifact, the corpus size, and the version *range*. Leave both
section banners (`system` v2.1.170, `user` v2.1.150) untouched and let **#231** own the re-verify
sweep. This is a deliberate deviation from AC-4's literal wording, recorded here rather than
absorbed.

**Step 4 — traceability.** Cite `tooling/format-scan/scan-2026-09-19.json` by path and name the
counter each figure comes from (`keys_by_type.system.*`, `keys_by_type.user.toolDenialKind`,
`top_level_types.*`), so a reader can re-derive rather than trust. Use a full GitHub URL for the
in-repo reference, per the Pages-portability convention.

**Checks:** `npx prettier reference/data-dictionary.md --check`. No test suite is implicated
(`docs` route: no mutation pass, no hermetic-tier run, architect per the trigger below, security
skipped).

## Architect triggers hit

**One fires.** `loop.config.md` §2: *"A new reference-doc contract that AgentFluent or CodeFluent
will link to (a field definition's meaning, a format-version-history entry) — these are cross-repo
interfaces."* The `toolDenialKind` row is a new field definition on exactly that surface.

The §2 skip list covers "`reference/` prose that documents an already-verified field", which fits
Step 1 (rewording an existing row) but **not** Step 2 (a field with no row anywhere). The list is
marked "SUFFICIENT, NOT EXHAUSTIVE" with a bias toward calling the agent, and the catch-all
("the orchestrator is unsure") also applies — placement and the two AC deviations are live design
questions. Invoking.

## Risks / open questions for human

1. **AC-3 reinterpretation** — exact line count vs the "upper bound" framing the issue and this
   invocation both specify. Ruling wanted.
2. **AC-4 deviation** — row-scoped provenance instead of a "Verified against v2.1.278" banner, to
   avoid manufacturing the defect #231 is open to fix. Ruling wanted.
3. **Guardrails: one PR at a time.** PR #245 is open and was positively attributed to the human
   (step 0.3), so the orphan scan did not halt — but this iteration would open a second PR at
   step 7. Merge #245 first, accept two concurrent PRs, or hold this row?
