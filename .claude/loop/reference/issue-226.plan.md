# Plan: #226 — docs(reference): backfill Part 5's scan statistics into reference/tool-invocation.md

**Route:** docs  **Branch:** `feature/226-backfill-scan-statistics`

## Value framing (docs route — who reads it, what it unblocks)

**Who reads it.** Two audiences, and they want different things from the same numbers.
Parser authors (AgentFluent, CodeFluent, and anyone else walking `~/.claude/projects/*.jsonl`)
read `reference/tool-invocation.md` to know which envelope keys they can rely on and how often
a conditional key actually appears. A `structuredPatch`-on-7,099-of-7,182 figure is the
difference between "branch on its presence" and "assume it". Second, readers of Part 5 who want
to check a number: the post ships to a separate Pages repo with no scan, no fixtures, and no
provenance trail, so a quoted statistic there is currently uncheckable by design.

**What it unblocks.** #231 (the re-verification cadence sweep) is queued behind this and will
re-stamp the same sections. #234 carries two post/reference deltas that land naturally in the
same pass. And the repo's own source-of-truth rule — posts are the narrative layer, `reference/`
is authoritative — is currently violated for five statistic families.

## Source-fidelity check (step 3) — RUN, and it FIRED

#226's rationale rests on one claim, quoted from its own body:

> All five come from the same 2026-08-25 scan behind [#210], so the provenance exists. It just
> was not written down in the doc.

**The second sentence is true. The first does not hold as written.** Checked three ways:

1. **Not in #210.** Fetched the issue body (188 lines) and grepped every figure: `93,832`,
   `6,724`, `212`, `68,963`, `7,441`, `7,099`, `7,182`, `1,472`, `1,029`, `102` — **zero hits
   for all ten.** #210 documents the scan's *method*, corpus (2,480 files / 289,773 lines /
   109 versions / v2.1.5–v2.1.243) and date, and carries its own numbers (Bash envelope counts,
   the `requestId` grouping table). It does not carry these five families.
2. **Not in #211** (the merged PR that applied #210's corrections), and not anywhere in
   `reference/` — a repo-wide grep for the figures returns only `posts/2026-09-10-the-tool-call-completely.md`.
3. **Not in `.claude/specs/`.** No retained scan output: `specs/` holds `decisions.md`,
   three plans, the sanitizer PRD, `roadmap-v0.md`, `series-outline.md`, and three research
   files, none carrying these counts.

**So the only extant source for all five families is the post itself.** The scan happened — its
method and corpus are documented — but its output was not retained, and these five numbers were
reported only into Part 5.

**Why that changes the deliverable rather than just adding a caveat.** AC-1 asks for the counts
"with the scan provenance". Copying the figures from the post into `reference/` and citing
"the 2026-08-25 scan (#210)" would manufacture provenance: the citation points at an issue that
does not contain the numbers, and the real upstream would be the post — inverting the exact
source-of-truth relation that is #226's stated motivation. That is the defect this issue exists
to fix, reintroduced in the file meant to fix it.

**Second-order:** `tooling/format-scan/scan.py` does not compute these families. It reports
`type` values, envelope key sets, content-block types, subdirectory shapes and version buckets —
not per-tool key frequencies, not a `stop_reason` distribution. So the 2026-08-25 figures came
from an ad-hoc pass, which is consistent with nothing being retained.

## Acceptance criteria (verbatim from issue)

- [ ] All five statistic families appear in `reference/tool-invocation.md` with counts and the scan provenance.
- [ ] `stop_sequence` is documented as a `stop_reason` value.
- [ ] The `Edit` table either carries scan counts or is explicitly marked unverified, with Part 5 adjusted to match if the latter.
- [ ] Every new or amended section carries its "Verified against Claude Code v<X>" note.
- [ ] Part 5's "everything traces back to `reference/tool-invocation.md`" is true as written.

## Approach

**Fork resolved by the human 2026-09-19: Option A1. #234 pulled in, #235 left out.**
**Architect pass applied 2026-09-19 — one blocking and four important findings, all adopted;
one suggestion declined. The dispositions below rewrote this section; see the frozen block for
the pre-architect text.**

**Routing: `docs` → `code`** (unchanged by the architect, which endorsed it). `SOURCE_LAYOUT` §3
puts `tooling/` on the `code` route, turning on the architect gate, `/security-review`, the
hermetic tier and the acceptance gate's Class B mutation pass.

### Step 0 — NEW, and it comes first (B1, adopted)

**Extend `tooling/format-scan/tests/test_content_free_contract.py` BEFORE writing any counter.**
I verified the architect's finding directly and it is correct on both halves:

- `EMITTABLE_VALUE_FIELDS` is **advisory, not enforced**. At `scan.py:239-240` the membership
  test is literally `if isinstance(line_type, str) and "type" in EMITTABLE_VALUE_FIELDS: pass`,
  and `version` is emitted at `:242-244` with no membership check at all. So adding
  `stop_reason` to the frozenset declares intent and changes no behavior.
- The sentinel test is therefore the **only** real leak gate, and it does not cover a single new
  surface. `planted_root` (`test_content_free_contract.py:40-93`) plants sentinels in prompt
  text, `cwd`, `uuid`, `requestId`, `tool_use.input.command`, `tool_result.content`, the
  `meta.json` values and the tool-results bytes — and **nothing** in `message.stop_reason`,
  `stop_sequence`, `stop_details`, an `Edit` `toolUseResult`, an `Agent` `prompt`, or a
  string-shaped `user` `message.content`.

Since the committed artifact is real-corpus-derived, shipping counters against a vacuous leak
gate is the one way this change could leak. Sentinels get planted in every new value the
counters read — `stop_sequence` and `stop_details.explanation` above all, which sit one field
away from the enum being emitted.

### Step 1 — extend `scan.py`, families placed by architectural class (I1, adopted)

The plan previously treated all five as one "add counters" task. They are two classes:

- **Line-streamable, into `ingest_line`:** (a) `stop_reason` distribution cross-tabbed against a
  derived synthetic-vs-real bucket; (b) `user` `message.content` list-vs-string shape split.
- **Join-requiring, into a probe** following `probe_nesting`'s precedent (`scan.py:523-639`),
  which already holds an in-memory per-file id map and uses the id purely as a join key it never
  emits: (c) `Edit` `structuredPatch` presence; (d) orphan `tool_result` blocks split parent vs
  sidechain; (e) `Agent` `prompt` / `toolStats` presence. These need a per-file
  `tool_use_id → tool name` join that line-scoped `ingest_line` cannot do. Keeping them in a
  probe also keeps the CCDC-attested default report smaller and more stable.

**(S1, adopted)** The synthetic-vs-real bucket uses a fixed module constant
`SYNTHETIC_MODEL_MARKER = "<synthetic>"`, mirroring the blessed `PERSISTED_MARKERS` /
`SUBAGENT_TOKENS_MARKER` pattern at `scan.py:105-111` — a string *we* supply, so testing for it
leaks nothing. Fixed bucket labels only, plus an explicit `absent` bucket for null/missing
`model` rather than defaulting the ambiguous case to "real". The observed model string never
reaches output (`scan.py:102` names `model` as non-qualifying).

Add `stop_reason` — and only `stop_reason` — to `EMITTABLE_VALUE_FIELDS`. Never `stop_sequence`
(carries the caller-supplied matched sequence, `data-dictionary.md:100`) and never
`stop_details.explanation` (free text, `:101`).

**(I3, adopted)** Each family states its **denominator definition** in both code and reference —
e.g. "`structuredPatch` on N of M `Edit` results, where an `Edit` result is a `tool_result` whose
`tool_use_id` resolves to a `name == "Edit"` `tool_use` and carries a dict `toolUseResult`".
Without the definition the reference number is exactly as uncheckable as the post's, which is
the defect #226 exists to fix. R5 said these are being *defined*, not recovered; this is what
acting on that looks like.

Bump `__version__` `0.2.0` → `0.3.0`. Verified correct against the policy: "`MINOR` — a new
top-level key or probe surface; additive, existing keys unchanged" (`CHANGELOG.md:36-38`).
CHANGELOG entry owed. CCDC coordination is a **heads-up, not a blocking dependency** — the change
is additive so nothing downstream breaks, and `SCHEMA.md` is owned by the
`claude-code-data-collective` repo and is **not edited from here**.

### Step 2 — run and retain (I4, adopted)

Run over `~/.claude/projects/`; commit the deterministic machine `--json` report as the artifact,
following the existing versioned-JSON precedent (`baseline-v2.1.150.json`) rather than a prose
note — a markdown transcription re-introduces exactly the risk that is #226's root cause.

**The run date stays OUT of the attested JSON body.** Verified: CCDC "content-addresses each
contribution by `sha256(scan.json)` (`sort_keys=True`, so deterministic)" (`CHANGELOG.md:26-28`),
so a wall-clock timestamp inside the body would make identical-corpus re-runs hash differently
and break the determinism CCDC depends on. The date lives in the filename. `files_scanned` /
`lines_scanned` already exist and the version span is derivable from the `versions` histogram, so
the date is the only fingerprint element that would pollute the body.

**A human must eyeball the artifact for PII before it is committed** — it is real-corpus-derived
and the PostToolUse detector catches credential patterns only, not arbitrary PII
(`scan.py:48-50`). This is a hand-off, not something the loop discharges.

### Step 3 — backfill `reference/tool-invocation.md` (I2, adopted)

Five sites as before. **New: a distinct 2026-09-19 provenance banner scoped to the new sections,
and the doc states which sections belong to which corpus.** The existing banner at
`tool-invocation.md:11` describes the 2026-08-25 corpus (2,480 files / 289,773 lines /
v2.1.5–v2.1.243); the fresh run is ~3,463 files, and the Read/Bash/Grep/Glob/parallel tables stay
on the old corpus. The `:11` banner must not silently umbrella numbers from a different corpus.
This is also what keeps #231 from inheriting an incoherent doc.

Both corpora labeled, with the dated Part-5 note reading as **superseded by** the fresh section
rather than co-equal. No claim that the shipped Part 5 will be retro-edited — its cadence is
governed by `claude_code_version_verified` and it lives in the separate Pages repo once synced.

### Step 4 — #234, stamps, checks

#234 item 1: add `model_context_window_exceeded` to Part 5's line-38 sentence. Item 2: record the
cross-tab result on #234; if most of the 212 are synthetic, point post and reference at
`data-dictionary.md:100`'s existing synthesized-line caveat rather than restating it. New
reference sections stamped v2.1.278. `npx prettier . --check`;
`python -m pytest tooling/format-scan/tests -q`; hermetic tier (the change adds tests).

### Declined

**S3 — making `stop_reason` a baseline-diff category** (`baseline-v*.json` + `_DIFF_CATEGORIES`,
`scan.py:409-416`) so a novel value surfaces as drift. Sound and squarely the scanner's purpose,
but it expands scope past #226 + #234 into drift-detection on the value set, which R6's scope
brake exists to prevent. **Filed as a follow-up instead.** The approach otherwise stands.

**The architect's offer to post its review to #226** — declined. Posting to a public issue is the
human's call, not something taken on an agent's suggestion.

### Resolved by the human 2026-09-19 (S2) — SPLIT

Split into two issues. The scanner half is **#237**; #226 keeps the reference backfill and is
`blocked` on it. PR2 branches off post-merge main, never stacked. The human also holds a **PII
gate** on the committed artifact: when the scan output exists the loop stops and hands it over,
rather than committing on the sentinel test alone.

**What remains in #226's own scope**, once #237 lands: the five reference sites, the distinct
2026-09-19 provenance banner (I2), the AC-5 sharpening so the dated note carries the Part-5-era
figure, the #234 deltas, v2.1.278 stamps, and the correction comment owed on #226's false
"#210 contains the provenance" premise.

## Approach as reviewed (frozen before the design gate) — write-once, do not edit

<!-- Verbatim copy of ## Approach taken BEFORE DESIGN_AGENT was consulted. -->

**Fork resolved by the human 2026-09-19: Option A1 — extend `scan.py`. #234 pulled in, both
deltas folded. #235 left out of this run.**

**Routing consequence, stated up front: this is no longer a `docs` change.** Under A1 the diff
touches `tooling/format-scan/`, which `SOURCE_LAYOUT` §3 puts squarely on the `code` route
("bug/enhancement touching `tooling/` ... full pipeline, PR required"). The row was routed
`docs` at init, when the issue read as a pure reference edit. Re-routed to `code`, which turns
on the architect gate, `/security-review`, the hermetic tier (the change adds tests), and the
acceptance gate's Class B mutation pass — none of which a `docs` row runs.

1. **Extend `tooling/format-scan/scan.py`.**
   - Add `stop_reason` to `EMITTABLE_VALUE_FIELDS` (`:90`). It meets the file's own stated bar —
     "a TAXONOMY ENUM that `reference/` already publishes as a public value" — since all seven
     values are enumerated in `reference/data-dictionary.md:99`.
   - Add counters for the five families, each with its definition written down (R5: the
     denominators are definition-dependent and the 2026-08-25 definitions were not retained, so
     these are being *defined*, not recovered):
     a. `stop_reason` distribution over assistant lines, cross-tabbed against a **derived
        synthetic-vs-real boolean**. Never the model-id string — `scan.py:102` names `model`
        among the fields that do not qualify for emission. This is #234 item 2.
     b. `user` `message.content` shape split (list-shaped vs string-shaped).
     c. `Edit` envelope: `structuredPatch` presence, numerator and denominator.
     d. Orphan `tool_result` blocks — a `tool_result` whose `tool_use_id` matches no `tool_use`
        in the same file — split parent vs sidechain on `isSidechain`.
     e. `Agent` envelope conditional keys: `prompt` and `toolStats` presence counts.
   - Bump `__version__` `0.2.0` → `0.3.0` per the in-file policy (`:78-79`), add the
     `CHANGELOG.md` entry, and note the CCDC `SCHEMA.md` coordination the contract at `:71-76`
     requires.
   - Add tests under `tooling/format-scan/tests/` for every new counter, against fixtures.
2. **Run it over `~/.claude/projects/`** and record the corpus fingerprint the way #210 does:
   file count, line count, version span, date.
3. **Retain the output as a committed artifact** so the next backfill re-derives rather than
   re-invents. This is the actual fix for #226's root cause; without it the failure recurs.
4. **Backfill five sites in `reference/tool-invocation.md`:** a new `stop_reason`-in-the-tool-cycle
   section (the doc has none today) documenting the distribution and `stop_sequence` as a value;
   the `user` content-shape split; the orphan `tool_result` mirror case into `## The pairing key`,
   which today asserts the one-to-one invariant without it; counts into the `### Edit` table,
   retiring its "starting hypothesis, not a contract" disclaimer for that row; and `prompt` /
   `toolStats` frequencies into the `### Agent` table.
5. **Both corpora, labeled.** Fresh figures are authoritative; a dated note records the
   2026-08-25 figures Part 5 quotes, marked reported-not-re-derived. AC-5 is met only if that
   note carries the Part-5-era figure, not on structural traceability alone.
6. **#234 item 1:** add `model_context_window_exceeded` to Part 5's line-38 sentence, which this
   pass is already editing. **#234 item 2:** record the cross-tab result on #234.
7. **Version stamps at v2.1.278** on every touched reference section (AC-4). Current
   `reference/` tops out at v2.1.243.
8. `npx prettier . --check`; `python -m pytest tooling/format-scan/tests -q`.

**Two ACs the scope agent recommended adding (additions, not reductions — no amendment gate):**
AC-6, the retained fingerprinted artifact; and the AC-5 sharpening in step 5 above. Also owed: a
correction comment on #226 fixing the false "#210 contains the provenance" premise, and its
Scope bullet's "cites the #210 scan" pointer.

**Open size concern for the design gate.** This now spans `scan.py` + new tests + CHANGELOG + a
retained artifact + five reference sites + a post edit. That is materially larger than the
docs-only estimate the size guard passed at selection, and there is an obvious seam: the scan
extension (code) and the reference backfill (docs) could be two issues. Put to the architect.

## Architect triggers hit

**Deferred until the fork resolves — the trigger set differs by option.**

- Under **Option A**, two fire: a new scanner that parses raw session JSONL is design-sensitive
  under the security posture (and `loop.config.md` §4 routes "path/JSONL parsing" to
  `/security-review`), and scan-backed counts that AgentFluent/CodeFluent will link to are a
  "new reference-doc contract". The orchestrator is also **unsure**, which is itself a trigger.
- Under **Option C/D**, likely none beyond the skip-list's "`reference/` prose that documents an
  already-verified field".

## Risks / open questions for human

**The fork (blocking).** The five figures have no retained provenance outside the post. Options:

- **A — re-run the scan (recommended).** Only option that makes `reference/` genuinely
  source-of-truth. Settles #234 item 2 at near-zero marginal cost. Costs a purpose-built
  no-values counter plus a run over 3,463 files, and pulls in the architect and security gates.
  Fresh numbers will differ from the post's; step 4 above is how both stay honest.
- **B — carry the numbers with honest provenance.** Write them in as "reported by Part 5 from
  the 2026-08-25 scan; output not retained". Cheap and not false, but `reference/` then
  depends on `posts/`, which is the inversion #226 was filed to correct.
- **C — split.** Deliver now the half needing no counts (`stop_sequence` as a documented value,
  the orphan `tool_result` mirror case, the `user` content-shape split qualitatively); file the
  counted half against a re-run. Keeps #231 moving; leaves AC-1 and AC-3 open.

**Secondary.** #234 and #235 joined the `reference` roster after init and have no queue row —
surfaced separately; #234's two deltas overlap this issue's scope and are not folded in
unless pulled in.
