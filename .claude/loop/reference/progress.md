# Loop journal: reference

Append-only. One block per gate decision, plus an open record (step 7) and a close record
(step 12) per iteration. Never rewritten. The ledger is gitignored and never committed.

---

## 2026-09-12T00:40:43Z — init

- BACKLOG_SOURCE: label `reference` on frederick-douglas-pearce/claude-code-sessions
  (`gh issue list --label reference --state open`). Human chose it explicitly over
  `epic:reference-migration` (semantically wrong — that epic is W3 *migration* into `reference/`,
  these are ongoing maintenance) and over a hand-scoped two-issue run.
- **Second run dir, alongside `epic-sanitizer`.** `epic-sanitizer` is the only prior run and carries
  no run-state sentinel; its non-terminal rows are #192/#32 (`routed`) and #201/#202/#203
  (`queued`), plus #42 `parked`. None is a *pipeline* status past `routed`, so none is interrupted
  and nothing there is mid-flight. It stays resumable exactly as it is. The human is the backlog
  authority (step 0.1) and directed this source in the invocation.
- Step 0.3 orphan scan: **zero open PRs** (`gh pr list --state open` empty), so no PR lacks a row.
- Resume (a), the unfinished-mutation check: `git worktree list` shows only the primary tree at
  `main`; no `mutate-verify-*` directory under the system temp dir. Working tree clean.
- `origin/HEAD` resolves to `1476b8d` — the `/security-review` precondition in loop.config.md §4 is
  met (no repair needed).
- Enumerated 5 open issues: #226, #229, #231 (documentation/reference, priority:medium),
  #137, #138 (question/research/reference, no priority label).
- Mode: `calibration` — no prior route graduation is recorded in `.claude/specs/decisions.md`
  (it holds D001 and O001, neither about graduation). `plan-gate: always` set on the same branch.
  Both caps `none`.
- Routing:
  - #229 → `docs` / `routed`. Label `documentation`, change confined to `reference/` per
    SOURCE_LAYOUT §3. No dependencies.
  - #226 → `docs` / `blocked` on #229. **Not an inference from issue-number order:** both issue
    bodies state the pair lands together (#229: "These two issues should probably land together";
    #226's 2026-09-10 comment: "the same widening #229 asks for on `reference/data-dictionary.md`,
    which is the concrete reason those two issues should land together"). The *direction* is the
    repo's own layering — `reference/tool-invocation.md` opens by deferring field-level definitions
    to `reference/data-dictionary.md`, so the `stop_reason` enum is #229's to define and #226's to
    cite. Taking #226 first would restate enum semantics in the doc that defers on them.
  - #231 → `docs` / `blocked` on #226, from its own body: "#226 — backfilling Part 5's scan
    statistics into `reference/`. Same corpus, and any re-scan should land after it, not before."
    Flagged for a size-guard re-check at selection: its scope spans a cadence policy decision, a
    scan run, stamp updates across ~8 posts and 4 reference docs, a post footer, and a new CI gate.
  - #137, #138 → `research` / `routed`. Label `research`, and both are external-API verification
    questions feeding Open verification item #5 in `reference/subagent-traces.md`. Neither carries a
    priority label, so both rank below `priority:low`.
- Selection order therefore: #229 → #226 → #231 → #137 → #138.

---

## 2026-09-12T00:52:00Z — #229 (docs) — plan gate

- Selected: #229 (highest-priority unblocked; #226/#231 blocked on the dependency chain recorded at
  init, #137/#138 carry no priority label and rank below it).
- Route: docs. Size guard: three table rows plus one section note in one file — fits.
- Plan: issue-229.plan.md written.
- Architect: skipped. `ARCHITECT_TRIGGERS`' "new reference-doc contract (a field definition's
  meaning)" is arguably in play, and the skip list's "`reference/` prose that documents an
  already-verified field" clearly is. Skipped because the risk on this row is factual rather than
  architectural, and the factual check is the one that ran (below). Recorded in the plan rather than
  left implicit.
- Plan-gate: n/a: architect skipped (docs route; risk is factual, discharged by the source-fidelity
  pass instead).
- Source-fidelity check (step 3): DISCHARGED, and it FIRED. #229 cites no scan — its whole rationale
  is the Messages API contract — so every claim was checked against primary Anthropic docs before
  being written into the source-of-truth doc. Result: the central correction is confirmed verbatim
  ("`stop_details` itself is `null` for every stop reason other than `refusal`", stated on two
  independent doc pages), and **three of the issue's own claims are wrong or incomplete**:
  (1) the enum is SEVEN values, not six — #229 omits `model_context_window_exceeded`;
  (2) `stop_details` has FOUR sub-fields, not three — it omits `recommended_model`;
  (3) FIVE named refusal categories, not four — it omits `"general_harms"`.
  One claim could not be verified in primary docs at all: the `stop_sequence` "matched string is
  excluded from the generated content" behavior (AC-3). Third-party sources assert it; Anthropic's
  do not.
- Human gate: STOPPED for plan approval (plan-gate: always), and additionally on AC-3 — delivering
  it as written would assert a contract past what its source establishes, and reducing an AC's
  intent is an issue amendment, not something this gate absorbs.
- Human gate resolved: **plan APPROVED** (plan-gate: always). Two rulings:
  - **AC-3 → verify empirically.** Human declined both the partial-delivery and the
    third-party-citation options; the exclusion behavior gets an observed result or nothing.
  - **#229's body → comment the corrections**, leave the original body intact as the record of what
    was believed at filing time.
- **AC-3 BLOCKED on credentials.** No `ant` CLI on PATH, `ANTHROPIC_API_KEY` and
  `ANTHROPIC_AUTH_TOKEN` both unset, no `~/.config/anthropic` profile. The probe cannot run from
  this environment. Not a gate error — the gate has not run yet; it is an input the orchestrator
  cannot supply. Proceeding with every part of the plan that does not depend on it (rows 1, 3, 4 and
  the verified half of row 2); the exclusion clause is the single held item and the probe command is
  handed to the human.
- Row advanced to `plan-approved`.

---

## 2026-09-12T01:15:00Z — #229 (docs) — iteration open

- Issue: #229 — docs(reference): stop_details is populated only on stop_reason "refusal", not "when available"
- Route: docs
- Branch: fix/229-stop-details-refusal-only
- PR: #233
- Status: in-pr

## 2026-09-12T01:20:00Z — #229 (docs) — CI

- CI: green. prettier pass, build + twine check pass, pytest 3.11/3.12/3.13 pass, and the required
  aggregate `sanitizer-ci` pass.
- Lint: `npx prettier . --check` clean repo-wide (local) and in CI.
- Type: n/a: no separate type step; no mypy/pyright/tsc config exists in this repo (config binding is
  `—` with that reason).
- Hermetic: n/a: docs route.
- Row advanced to `in-review`.

## 2026-09-12T01:30:00Z — #229 (docs) — code review

- Code-review: `/code-review medium` (lens: factual-accuracy/claim-resolution, the right angle for a
  prose deliverable). 4 findings. Both empirical ones were re-verified by the orchestrator against
  the primary source and the fixtures before acting — the reviewer was right on both.
  - **F1 (medium, fixed).** `stop_sequence` row asserted the value is the caller-supplied sequence
    from the request's `stop_sequences` array and "the only thing that says which one fired". True
    of the API, unsupported here: the ONLY `stop_reason: "stop_sequence"` line in fixtures
    (`fixtures/sanitized/sanitizer-development.jsonl:206`) carries `stop_sequence: ""` on a
    `model: <synthetic>` line. Verified independently: 604 assistant lines carry the key as literal
    `null`, 12 omit it, 1 carries `""`. API-layer meaning now labeled as such and separated from
    observed Claude Code data.
  - **F2 (medium, fixed).** `stop_details` row claimed a refusal is always `content: []` /
    `output_tokens: 0`. Verified against the primary page: "A refusal can arrive before any output,
    or mid-stream after partial output", and "A mid-stream refusal bills the input tokens and the
    output already streamed at normal rates." The unconditional claim told cost code to zero out the
    refusals that actually cost money — the worst possible error in the doc AgentFluent/CodeFluent
    link for token accounting. Both shapes now documented.
  - **F3 (low, fixed).** The new upstream-source note said Claude Code "writes through whatever the
    Messages API returns"; synthesized lines are the counterexample and are the ones carrying the
    anomalous `stop_*` values in F1. Note now says a session scan is not a clean instrument either.
  - **F4 (low, out of diff scope, FILED as #234).** Part 5 and `data-dictionary.md` now disagree on
    the enum count (six vs seven), and the scan's 212 `stop_sequence` occurrences may be counting
    synthesized harness lines. Recorded as a hypothesis, not a finding — one fixture line is not
    evidence about 212 in a 289,773-line scan. Routed to #226's scope rather than this PR.
- Fixes committed as `78e36ae` and pushed BEFORE spawning the re-check, so the checker reads them.
- Round 2 = fresh instance (Fresh-re-check invariant): a new general-purpose spawn, not the
  orchestrator and not the round-1 reviewer, given the change + the claimed fixes + licence to
  object, and none of the orchestrator's conclusions. IN FLIGHT.

## 2026-09-12T01:42:00Z — #229 (docs) — code review round 2 (fresh re-check)

- Round 2 = fresh general-purpose spawn. **All three claimed fixes CONFIRMED done** at
  `data-dictionary.md:99`, `:98`, `:85`, each verified against the primary pages rather than against
  the orchestrator's account of them.
- **Round 2 came back DIRTY with new findings.** Two re-verified by the orchestrator:
  - **`stop_reason` is typed `string` but is `null` on 18 real-model lines.** Confirmed by parsing
    fixtures: `retry-rate-parameter-shape.jsonl` carries 18 assistant lines with
    `stop_reason: null` on `claude-haiku-4-5-20251001` (NOT synthesized). They are non-final
    streaming snapshots — `msg_0147ByYnVKuciyHf3nxUy9Wc` repeats at lines 5/6/7 with
    `output_tokens: 4`, then line 9 with `tool_use` and `output_tokens: 275`. The two sibling rows
    were upgraded to `| null` in this same diff; this one was not. It directly serves the token
    accounting audience the doc already tells (pitfall at `:499`) to dedupe by `message.id`:
    `stop_reason: null` is the marker of a snapshot to discard.
  - **The `stop_details` sub-field list reads exhaustive and is not.** Confirmed verbatim on the
    refusals page: "batch refusals don't mint fallback credits, so `stop_details` on a batch result
    never includes a `fallback_credit_token`" — so `fallback_credit_token` is a sub-field the row
    omits (reviewer also cites `fallback_has_prefill_claim` from the fallback-credit page).
  - Also real, unverified-by-me but quoted verbatim off the page: the row drops the docs'
    instruction "In either case, treat any partial output as incomplete and discard it."
  - Citation-scope: `:85` stamps the whole block "Verified against" two pages, but the open-enum
    framing and the `stop_sequence` non-null rule come from the Messages API reference, not those
    two; and "re-confirm against those pages rather than against a session scan" is backwards for
    the harness-specific half (only a scan can establish `stop_reason: null` on streaming chunks).
  - Quality: the doc already names `<synthetic>` at pitfall 12 (`:516`) and the new text does not
    cross-link it; the inline example at `:113`-`:131` omits both keys; **8 em-dashes added, 0
    removed**, against the standing repo preference; no CI covers `reference/` at all.
- **2-round cap SPENT. Per the Fresh-re-check invariant there is no round 3 — ESCALATED to the
  human.** Not fixed unilaterally. Row stays `in-review`; no merge on these verdicts.

## 2026-09-12T01:58:00Z — #229 (docs) — round 3 (human-authorized)

- **Round 3 exists because the human directed it.** The 2-round cap was reported spent and the
  decision put to them; they authorized a bounded round scoped to the correctness items plus the
  em-dash trim. Not opened on the orchestrator's own judgment.
- Fixes, each re-verified before acting:
  - `stop_reason` → `string | null`, with the non-final-streaming-snapshot meaning and a link to this
    file's existing snapshot-dedup pitfall. Verified by parsing fixtures (18 null lines, real model
    id `claude-haiku-4-5-20251001`, repeated `message.id`, partial `output_tokens`).
  - `stop_details` sub-field list relabeled **non-exhaustive** and extended with
    `fallback_credit_token` + `fallback_has_prefill_claim`. Verified verbatim on the Fallback credit
    page: "On a refusal, `stop_details` includes two fields ... Both are `null` when no credit is
    available for the refusal."
  - Added the docs' "treat any partial output as incomplete and discard it" instruction, which the
    mid-stream refusal shape made load-bearing.
  - Upstream-source note rewritten: four sources named (adding Fallback credit + the Messages API
    reference), and the two-instruments distinction stated — docs answer what the values mean, only
    a scan answers what Claude Code writes. The previous "re-confirm against those pages rather than
    against a session scan" was backwards for the two scan-only claims the rows now make.
  - `<synthetic>` cross-linked to pitfall 12, so the claim resolves inside this file.
  - Em-dashes in the change: 8 → 0.
- Lint: `npx prettier reference/data-dictionary.md --check` clean. Committed `49c44ce`, pushed.
- Filed **#235** — nothing in `.github/workflows/` gates `reference/` at all (Prettier is posts-only),
  so a wrong field definition has no mechanical check between it and `main`. This iteration is the
  evidence: five substantive problems, every one caught by a reader, none catchable by anything
  automated because nothing automated exists. Verified `reference/` is Prettier-clean today before
  claiming it in the issue.
- Round-3 re-check: fresh general-purpose spawn (not the orchestrator, not either prior reviewer),
  given the change + the claimed fixes + licence to object. Committed before spawning. IN FLIGHT.

## 2026-09-12T02:12:00Z — #229 (docs) — round 3 re-check: DIRTY, regression introduced by my own fix

- Fixes A/B/D/E confirmed done. **Fix A introduced a worse defect than the one it corrected, and
  fix C introduced a false provenance claim.** Both re-verified by the orchestrator:
- **BLOCKING — the dedup rule I invented at `:99` is wrong, and conflicts with this file's own.**
  I wrote "group by `message.id` and keep the line that has a non-`null` `stop_reason`" and
  presented it as if it WERE the file's established rule. The file's actual rule (`:501`,
  § `usage` is per-request) is "keep the record with the **greatest `output_tokens`**". Mine fails
  on real fixture data in BOTH directions:
  - **Selects nothing** on 2 of 17 groups in `retry-rate-parameter-shape.jsonl` — every line null.
    `msg_01Xw9V8HPY1nMPZ9o4aZMCkS` carries `cache_creation_input_tokens: 20817`;
    `msg_01EmJcV8GskEgYb8dhZoNVa6` carries `cache_read_input_tokens: 43956`. Applying my rule drops
    ~65k tokens on one fixture. The greatest-output_tokens rule keeps them.
  - **Selects everything** on 34/34 multi-line groups in `retry-rate-mixed-tools.jsonl` and 129/129
    in `sanitizer-development.jsonl`, where every line carries a non-null `stop_reason` with
    IDENTICAL `output_tokens`. That is the ~2x double-count the usage section exists to warn about.
  An undercount-and-overcount bug, published as guidance, in the doc whose audience is token
  accounting. Strictly worse than the `string` type it was fixing.
- **Also wrong: the anchor.** `:99` points the dedup rule at `#common-pitfalls-in-cost-computation`.
  The anchor resolves but the rule is not there — it is in
  `#usage-is-per-request-context-recurs-every-turn`. Nothing in CI catches a mis-aimed anchor (#235).
- **Also wrong: "no API page could establish `stop_reason: null`" (`:87`).** Verified false against
  the cited page, verbatim: "When using streaming, `stop_reason` is: `null` in the initial
  `message_start` event". The API docs DO establish it; what only a scan establishes is that Claude
  Code PERSISTS those events as separate JSONL lines. A false provenance claim inside the paragraph
  whose entire job is provenance precision.
- **Also unsupported: "New values have been added over time" (`:99`).** Confirmed the cited page
  presents a fixed table with no extensibility statement, while `:87` stamps the value sets as
  verified against those pages. The claim is true historically but is not carried by the citation.
- Minor: "both gated on the fallback-credit beta" is narrow (the server-side-fallback header also
  grants them); `fallback_has_prefill_claim` can be ABSENT, not null, on Bedrock/Google/Foundry.
- **Cannot tell:** the re-checker could not load the Messages API reference response schema (page
  truncated on both hosts), so the fourth source `:87` cites is itself unverified.
- **ESCALATED to the human.** Round 3 was human-authorized; its re-check is dirty, and the dirt is a
  regression I authored. Not opening round 4 unilaterally. Row stays `in-review`; nothing merges on
  these verdicts.

## 2026-09-12T02:25:00Z — #229 (docs) — round 4 (human-directed: subtract, don't add)

- Human ruling: **subtract, don't add.** Remove what the evidence does not carry rather than write
  new prescriptive text in the place already gotten wrong once.
- Removed:
  - The invented dedup rule on the `stop_reason` row. The row now records `stop_reason: null` as an
    observation and points at `#usage-is-per-request-context-recurs-every-turn`, noting that the
    rule there keys on `output_tokens` rather than on this field. No rule restated locally.
  - The false "no API page could establish" clause. Replaced with the correct attribution: the API
    returns `null` in `message_start` and fills it on `message_delta`; what only a scan establishes
    is that Claude Code persists those events as separate JSONL lines.
  - "New values have been added over time" as a sourced claim. The open-enum advice remains as this
    document's own recommendation to parsers, not as a citation-backed statement about the API.
  - The Messages API reference from the citation list (its response schema could not be loaded, so
    the citation was unverifiable).
  - The over-narrow "gated on the fallback-credit beta" (two headers grant those fields).
- Checks: prettier clean; **both anchors the diff adds verified to resolve** against real headings by
  slugging every heading in the file; em-dashes added still 0. Committed `6f82bd9`, pushed.
- Round-4 re-check: fresh spawn (third distinct reviewer instance this iteration), scoped to
  confirming the REMOVALS landed and that no new overreach replaced them. IN FLIGHT.
- Pattern worth carrying to the dev-loop memo: three consecutive rounds fixed the stated finding and
  introduced a new overreaching claim while doing it. The failure is not carelessness about the
  finding, it is that writing *more* prose to fix a prose defect enlarges the claim surface each
  time. Subtraction converged it; addition had not.

## 2026-09-12T02:40:00Z — #229 (docs) — round 4 re-check, round 5, security, acceptance

- Round-4 re-check: **all three removals confirmed landed and correct**, and it independently
  re-derived the fixture arithmetic behind the removed dedup rule. It also corroborated the anchor
  repair from two other files: `tool-invocation.md:52` and `subagent-traces.md:422` already treat
  `#usage-is-per-request-context-recurs-every-turn` as the rule's canonical home. Also noted the
  broadened beta-gating was NECESSARY, not merely safe: **three** headers grant those fields, so
  naming any one would have been wrong.
- Three new findings, same species as the removals. Applied under the human's **standing** "subtract,
  don't add" ruling rather than re-asking an identical question a third time; the human was told and
  given the chance to stop it.
  - Dropped "Claude Code persists those as their own lines". The fixtures do not show one line per
    streaming event: 13 affected groups carry one null line, one carries two, one carries three
    whose content blocks differ in type. The row now states the sourced API fact and the checkable
    fixture observation, and explains nothing about how one follows from the other.
  - Dropped the dangling "The Messages API documents seven values" attribution, left over after the
    previous commit removed that reference from the citation list as unverifiable.
  - Un-bolded the `stop_sequence` coupling and marked it as inference: no cited page states it for
    that field. Re-verified: 605/605 assistant lines consistent, **0 violations**.
  - Closed the trap the re-check flagged: the 2 turns recorded ONLY by null-`stop_reason` lines carry
    real `cache_creation_input_tokens` (20,817 and 161), so the row now says they are not safe to
    discard. Verified by parsing.
  - Noted but NOT acted on (would be additions): the "against sessions" vs "fixtures" framing nit.
  - Commit-message arithmetic in `6f82bd9` is off by 161 (says 20,817, the two-group sum is 20,978).
    File text unaffected; not rewriting pushed history for a commit body.
- Cross-doc finding appended to **#234**: the post asserts "that list has grown over time", the exact
  unsourced claim removed from the reference here. Post is now out of step on two counts in one
  sentence, which makes it a single edit for #226.
- `1985a97` pushed. **CI green on the final commit** (prettier, build+twine, pytest 3.11/3.12/3.13,
  and the required `sanitizer-ci`).
- Security: **skipped, per loop.config.md §4** "Skip for docs/no-surface changes (a post typo, a
  reference wording fix)". The diff is one file under `reference/`, prose plus documentation links.
  It touches none of the §4 trigger surfaces (`tooling/sanitizer/`, `.claude/hooks/`, `fixtures/`,
  `tooling/publish-to-pages.py`, path/JSONL parsing, `.github/workflows/`). Diff-level invariants
  confirmed: no raw session JSONL, no secrets.
- Acceptance gate: row → `in-acceptance`. `$BASE` resolved to `1476b8d` as ONE command and quoted.
  Tree clean, zero untracked, only the primary worktree, no mutation snapshots. Fresh AC-verifier
  spawned with ONLY the four ACs verbatim, the base SHA, and the Verifier-runs commands, and
  instructed to judge AC-3's two halves separately rather than rounding up. IN FLIGHT.
- Class B (mutation pass): **not due** — Route is `docs` (AC-verifier Part 2, question 1).

## 2026-09-12T02:52:00Z — #229 (docs) — acceptance gate

- AC-verify, Class A: **3 of 4 criteria MET, 1 half-met. Overall NOT DONE.**
  - AC-1 `stop_details` rewritten around the iff rule, six sub-fields named — MET (`:101`).
  - AC-2 `stop_reason` widened to seven values, framed open — MET (`:99`).
  - AC-3 — **NOT FULLY MET.** 3a (the `stop_reason` coupling) present at `:100`; 3b (the
    excluded-string behavior) absent. The verifier judged the halves separately as instructed and
    declined to round up, which is the right call.
  - AC-4 v2.1.170 note re-checked — MET (`:85`, `:87`).
  - It independently confirmed the fixture claims, that all three anchors resolve, and that the
    "no scan work" exclusion is honored.
- **The Class A finding is the known AC-3b scope decision, not a new gap**, and no fix round can
  close it: the human ruled "verify empirically" at the plan gate, and this environment has no
  Anthropic credentials. So the 2-round cap is not engaged here; there is nothing to re-verify.
- One nit raised OUTSIDE the criteria and **declined, with reasoning**: the verifier read
  `category`'s five values as a closed set where upstream is open. Checked against the primary
  table: `general_harms` is defined as "The request falls under a usage-policy area outside the four
  named categories", i.e. it IS the residual, which makes five-plus-`null` exhaustive. The verifier
  was reasoning from the `claude-api` skill, a secondary source that hedges the set as open. Primary
  source wins; text unchanged. Recorded rather than silently dropped.
- Class B: `mutation-survivors=n/a: docs route` (Part 2, question 1).
- Restore: n/a: no mutation applied.
- **Merge gate: STOPPED for the human.** `mode: calibration` makes every row human-approved, and
  independently the row carries an unmet AC. Row stays `in-acceptance`. Nothing merged.

## 2026-09-12T03:00:00Z — #229 (docs) — iteration complete

- Selected: #229 (highest-priority unblocked).
- Route: docs (light review; no architect, no security, no mutation pass).
- Plan: issue-229.plan.md written. Value framing + source-fidelity check discharged at plan time.
- Architect: skipped (docs route; the risk was factual and the source-fidelity pass covered it).
- Plan-gate: n/a: architect skipped (docs route; risk factual, discharged by source-fidelity).
- Human gate: plan approved by the human (plan-gate: always), with two rulings — AC-3 to be settled
  empirically, and #229's stale counts to be corrected by comment rather than body edit.
- Implemented: `reference/data-dictionary.md` rows `:99`/`:100`/`:101` plus the upstream-source note
  at `:85`-`:87`. Five commits.
- Lint: prettier clean repo-wide, local and in CI. Type: n/a: no type step exists in this repo.
- Hermetic: n/a: docs route.
- PR: #233 (fix scope). CI: green on the final commit, incl. the required `sanitizer-ci`.
- Code-review: 4 findings round 1, 3 round 2, 3 round 3, 3 round 4. Rounds 3-5 were human-directed
  after the 2-round cap was reported spent. Security: n/a (docs/no-surface, §4).
- Restore: n/a: no mutation applied.
- AC-verify: Class A 3/4 criteria met, AC-3 half-met (3a present, 3b absent by human ruling — needs
  an API probe this environment cannot run). Class B: mutation pass not due (docs route).
- Budget: subagent-runs=5 (1 code-review skill + 3 fresh re-checks + 1 AC-verifier) · gate-rounds=architect=0,code-review=4(factual-accuracy/claim-resolution),ac-verify=1 · justification=three human-directed rounds past the cap; each round's fix introduced a new overreaching claim, and the convergence came from subtracting rather than adding · ac-findings=1 · mutation-survivors=n/a: docs route · post-gate-survivors=0 · wall-clock=≈2h20m · tokens=deferred
- Merged: squash #233 as `a19752a`, branch deleted. **Issue #229 left OPEN** by human ruling, for the
  excluded-string half.
- Filed: #234 (post/reference drift: enum count + the unsourced "list has grown over time"), #235
  (nothing in CI gates `reference/`), #236 (does the hook's session-JSONL denial cover
  `tool-results/` spill files?).
- Next: **#226 is now unblocked** (`blocked` → `routed`). #231 remains blocked on #226.

### Iteration finding, carried to the dev-loop memo

**Three consecutive review rounds fixed the stated finding and introduced a new overreaching claim
while doing it.** Round 2's fix for a wrong billing claim added an unsupported request-side claim.
Round 3's fix for a wrong type added a dedup rule that was wrong in both directions on the repo's own
fixtures. Round 4's fix for that added a mechanism claim the fixtures contradict. The defect is not
carelessness about the finding — each finding was correctly addressed. It is that **writing more
prose to repair a prose defect enlarges the claim surface**, and a prose deliverable has no compiler
to bound the new surface. What converged it was the human's "subtract, don't add" instruction, at
which point the next round found only attribution nits.

**The loop's own cap behaved correctly and was the reason this was caught.** The 2-round cap fired,
the escalation surfaced a regression the orchestrator had authored, and the human's ruling changed
the *strategy* rather than authorizing another identical round. That is the cap working as designed:
"the decision is frequently not 'run another round'."

**A prose route needs a different default lens.** `docs` is specified as a "light review", and a
light pass would have merged the billing error. The lens that paid was claim-resolution: does every
sentence resolve to a source or a fixture? Worth considering whether the `docs` route should default
to that lens at a higher effort rather than to a lighter generic pass.

---

## 2026-09-19T00:00:00Z — curation

Step-1 roster reconciliation. Live `BACKLOG_SOURCE` roster (`gh issue list --label reference
--state open`) returns 7 issues; `queue.md` holds 5 rows. Deduped against a FULL-file scan of
`progress.md` for prior `- surfaced-join:` / `- surfaced-leave:` lines — none exist, so both
deltas below are first-time surfaces.

- **surfaced-join: #234** — "docs: Part 5's stop_reason enum count and the 212 stop_sequence
  occurrences need reconciling with reference/" (priority:low). Filed by the #229 iteration on
  2026-09-12, i.e. after this run's init. **Not auto-added.** Its scope overlaps #226's
  materially (it names #226 as "the natural home for both items"), so the human's answer changes
  what #226 delivers.
- **surfaced-join: #235** — "chore(ci): nothing gates reference/ — extend the Prettier workflow
  and add link/version-note checks" (priority:medium). Also filed by the #229 iteration. **Not
  auto-added.** Note it would route `code`, not `docs` — it touches `.github/workflows/`, so it
  carries the full pipeline plus a PR, unlike every other row in this run.
- **Leavers: none.** All four non-terminal rows (#226, #231, #137, #138) are still in the roster.
  #229 is `done` and still open by human ruling; terminal rows are not leave-tested.

Budget caps: `iteration-cap: none`, `subagent-cap: none` — inert, no breach possible.

---

## 2026-09-19T00:05:00Z — #226 (docs) — selection + source-fidelity

- Step 0.3 orphan scan: `gh pr list --state open` returns `[]`. **Zero open PRs**, so no PR lacks
  a row. No interrupted rows either — #229 is `done` (terminal), #231 is `blocked`, and #226,
  #137, #138 are `routed`, none of which is a pipeline status past `routed`.
- Resume (a), the unfinished-mutation check: `git worktree list` shows only the primary tree at
  `main`; no `mutate-verify-*` directory under the system temp dir; working tree clean. Nothing
  to recover, so (b) is not reached.
- Selected: **#226** — the only selectable row carrying a priority label. #231 stays `blocked`
  on #226; #137/#138 are `routed` but carry no priority label and rank below `priority:low`.
- Route: `docs`, retained from init. Size guard: five backfill sites in one 571-line reference
  doc, plus a possible one-paragraph post edit under AC-3/AC-5. Fits one context window — not
  `too-large`.
- Row advanced to `planning`. Plan written to `issue-226.plan.md`.
- **Source-fidelity check (step 3): DISCHARGED, and it FIRED.** #226's stated rationale — "All
  five come from the same 2026-08-25 scan behind #210, so the provenance exists" — does not hold
  as written. Verified three ways: all ten figures grepped against #210's fetched body return
  **zero hits**; a repo-wide grep finds them only in `posts/2026-09-10-the-tool-call-completely.md`;
  and `.claude/specs/` retains no scan output. Second-order confirmation: `scan.py` does not
  compute these families at all (it reports key names, taxonomy enums, value types, version
  buckets), so the 2026-08-25 pass was ad hoc and unretained.
- **Consequence for the deliverable, not just a caveat.** AC-1 asks for the counts "with the scan
  provenance". Citing #210 for numbers it does not contain would manufacture provenance and make
  `reference/` depend on `posts/` — the exact inversion #226 was filed to correct.
- Escalated the fork to `SCOPE_AGENT` (`pm`) before the human, per step 5. Options put to it:
  **A** re-run the scan (fresh numbers, real provenance, settles #234 item 2, pulls in the
  architect + security gates); **B** carry the figures labeled as post-reported; **C** split off
  the count-free half now.
- Architect: **not run**, and deliberately so — the approach is unsettled pending the fork, and
  the trigger set differs by option. No freeze is owed yet; it is taken at whichever step first
  consults `DESIGN_AGENT`. `## Approach as reviewed` is therefore legitimately absent (step 5:
  "where the architect was skipped, the block is legitimately absent and the condition is not
  due at all").

## 2026-09-19T00:20:00Z — #226 (docs) — plan gate

- `SCOPE_AGENT` (`pm`) ruled: **Option A**, reject B, hold C as fallback only. Its reasoning I
  independently confirmed: B would make `reference/` cite `posts/` as upstream, and since
  `posts/` syncs to a separate Pages repo, the authoritative doc would depend on a downstream,
  scan-less repo. It also noted AC-4's "Verified against Claude Code v<X>" note is a *claim of
  verification*, so carrying post-sourced digits under it would be false. Both hold.
- **One of `pm`'s load-bearing claims is wrong, and correcting it makes Option A slightly more
  expensive than it argued.** It claimed `scan.py` "already emits `stop_reason` as a public
  taxonomy enum", and used that to characterize the work as extending a reviewed tool rather
  than opening a new surface. Verified against the source: `EMITTABLE_VALUE_FIELDS =
  frozenset({"type", "version"})` (`scan.py:90`) — **`stop_reason` is not on it.** The
  2026-08-25 figures came from an ad hoc pass, not from `scan.py`, which is consistent with
  nothing being retained. So A1 requires *adding to the emittable-values whitelist* — the exact
  surface the SECURITY CONTRACT guards. Legitimate (all seven `stop_reason` values are published
  in `reference/data-dictionary.md`, so it meets the file's own bar of "a taxonomy enum that
  `reference/` already publishes"), but it is a security-contract change, not a free extension.
- Confirmed the rest of `pm`'s mechanism note: `__version__ = "0.2.0"` (`scan.py:80`) under a
  documented bump policy — "Bump `__version__` (semver) on ANY change that alters `--json`
  output shape or semantics; CCDC gates on it" (`:78-79`) — with a cross-repo contract to CCDC's
  locked `SCHEMA.md` (`:71-76`). So A1 carries a `scan_version` bump plus CCDC coordination.
- **`pm`'s R3 is right and the source states it more strongly than `pm` knew.** For #234's
  cross-tab, `model` is named explicitly among the fields that do NOT qualify for emission
  (`scan.py:102`). So the synthetic-vs-real distinction may only ever be emitted as a derived
  boolean bucket, never as a model-id string.
- Also verified `pm`'s citation of the "starting hypothesis, not a contract" bar —
  `reference/tool-invocation.md:185`, verbatim.
- Architect: **not run** — no `DESIGN_AGENT` pass at step 4 or at step 5. The consult that ran
  was `SCOPE_AGENT`, on a scope/value question, which is a different gate. The approach is
  unsettled pending the fork, so no freeze is owed and `## Approach as reviewed` is legitimately
  absent.
- Plan-gate: n/a: architect skipped (docs route; the fork is a scope question, routed to
  SCOPE_AGENT, and no architect pass ran at step 4 or step 5).
- Human gate: **STOPPED for plan approval** (plan-gate: always), and independently on the
  source-fidelity finding — #226's stated provenance does not hold, which changes what the
  deliverable is rather than adding a caveat. Row stays `planning`.

## 2026-09-19T00:35:00Z — #226 (docs→code?) — human gate resolved

- **Plan APPROVED** (plan-gate: always). Three rulings:
  - **Fork → Option A1**, extend `tooling/format-scan/scan.py`. The human took the durable
    mechanism over the one-off counter, accepting the `scan_version` bump and the CCDC
    `SCHEMA.md` coordination that comes with it.
  - **#234 pulled in**, both deltas folded into this pass — the `stop_reason` × synthetic-vs-real
    cross-tab (item 2) and the `model_context_window_exceeded` addition to Part 5's line-38
    sentence (item 1). This is an explicit human curation decision, per the curated-subset
    invariant; it was surfaced, not auto-added.
  - **#235 left out** of this run. Stays open and selectable later. Rationale recorded at the
    surface: it routes `code` via `.github/workflows/` and carries a different pipeline shape
    from every other row here.
- **Routing consequence flagged to the human at the gate:** A1 makes the diff touch `tooling/`,
  which `SOURCE_LAYOUT` §3 puts on the `code` route — turning on the architect gate,
  `/security-review`, the hermetic tier (the change adds tests) and the acceptance gate's Class B
  mutation pass. The row was routed `docs` at init when #226 read as a pure reference edit.
  **Re-route deferred until the architect answers the split question** (below), since a split
  would put the scan half and the reference half on different routes anyway.
- **Size guard re-opened.** The A1 scope — `scan.py` + new tests + CHANGELOG + a retained
  artifact + five reference sites + a post edit — is materially larger than the docs-only
  estimate that passed the guard at selection. Not unilaterally marking `blocked: too-large`;
  the natural seam (scan extension vs reference backfill) is put to `DESIGN_AGENT` as an
  explicit question rather than decided here.
- Step 4, in the engine's mandated order: **(a) froze `## Approach` verbatim** into the
  write-once `## Approach as reviewed (frozen before the design gate)` block BEFORE invoking —
  the pre-image step 5's materiality diff reads. **(b) Invoked `DESIGN_AGENT` (`architect`)**,
  read-only, with seven questions: the `EMITTABLE_VALUE_FIELDS` addition, whether the derived
  synthetic-vs-real boolean leaks by inference, whether orphan-`tool_result` detection breaks
  `scan.py`'s streaming design, the split question, where the retained artifact lives, whether
  the CCDC coupling needs more than a minor bump, and an open catch-all. **(c)** Its outcome
  gets written into `## Approach` before step 5 re-runs. IN FLIGHT.
- Architect triggers that fired: "a new reference-doc contract that AgentFluent or CodeFluent
  will link to"; the CCDC cross-repo contract and the emittable-values whitelist are both
  design-sensitive surfaces; and "the orchestrator is unsure".

## 2026-09-19T00:55:00Z — #226 (code) — architect gate + plan gate, round 2

- `DESIGN_AGENT` (`architect`) returned: 1 blocking, 4 important, 3 suggestions. **Verified its
  two sharpest claims against the source before acting; both hold.**
  - **`EMITTABLE_VALUE_FIELDS` is advisory, not enforced.** `scan.py:239-240` is literally
    `if isinstance(line_type, str) and "type" in EMITTABLE_VALUE_FIELDS: pass`, and `version` is
    emitted at `:242-244` with no membership check at all. So adding `stop_reason` to the
    frozenset declares intent and changes no behavior — which makes the sentinel test the only
    real leak gate.
  - **B1: that gate does not cover a single new surface.** `planted_root`
    (`test_content_free_contract.py:40-93`) plants sentinels in prompt text, `cwd`, `uuid`,
    `requestId`, `tool_use.input.command`, `tool_result.content`, the `meta.json` values and the
    tool-results bytes — and none in `stop_reason`, `stop_sequence`, `stop_details`, an `Edit`
    `toolUseResult`, an `Agent` `prompt`, or a string-shaped `user` `message.content`. Against a
    real-corpus-derived committed artifact, that is the one way this change could leak.
  - Also verified verbatim: the MINOR-bump verdict (`CHANGELOG.md:36-38`, "a new top-level key
    or probe surface; additive") and the determinism basis for I4 (`:26-28`, CCDC
    "content-addresses each contribution by `sha256(scan.json)` (`sort_keys=True`, so
    deterministic)").
- Dispositions written into `## Approach`, per step 4(c), BEFORE step 5 re-ran: **B1, I1, I2,
  I3, I4 and S1 adopted; S3 declined** (drift-detection on the value set expands past #226+#234,
  against R6's scope brake — filed as a follow-up instead); the architect's offer to post its
  review to #226 declined (posting to a public issue is the human's call).
- **Plan-gate: material (a step was added — B1's sentinel extension now precedes implementation;
  the five families reordered into two architectural classes per I1; the files-to-touch set
  changed — `test_content_free_contract.py` added and the artifact moved from
  `.claude/specs/research/` to committed `--json` under `tooling/format-scan/`; and AC-1 was
  reinterpreted per I3, which makes the denominator definition part of what "with counts and the
  scan provenance" requires) → STOPPED.**
- This **supersedes** the `- Plan-gate: n/a: architect skipped` line written at the
  2026-09-19T00:20:00Z stop. That line was accurate when written — no architect pass had run and
  the iteration stopped at the fork. A pass has now run, so the `n/a` spelling is no longer
  available. The journal is append-only and the earlier line stands as the record of that
  moment.
- Row stays `planning`. Not advanced to `plan-approved`: the architect materially redirected the
  plan and the human has not seen the redirect, and S2 (the two-PR split) is an unresolved scope
  question the design gate explicitly handed back.

## 2026-09-19T01:10:00Z — #226 (docs) — plan gate resolved: SPLIT

- **Plan APPROVED with a split** (plan-gate: always, round 2). Two human rulings:
  - **Split into two issues**, adopting the architect's S2. The scanner half is filed as **#237**
    (`feat(format-scan): re-derive Part 5's five statistic families and retain the output as a
    committed artifact`, labels `enhancement` / `priority:medium` / `reference`). #226 keeps the
    reference-backfill half and depends on it. PR2 branches off post-merge main, never stacked —
    the known squash-merge child-auto-close gotcha.
  - **PII gate on the artifact is the human's.** When #237's scan output exists, the loop stops
    and hands it over; it is not committed on the sentinel test alone. The test proves the
    scanner does not emit *planted* values; it cannot prove the real corpus held nothing
    unanticipated. Recorded as an AC on #237.
- #237's body carries the architect's design verbatim so the next iteration does not re-derive
  it: B1 (sentinel test lands before any counter), I1 (two family classes, join-requiring ones
  into a probe on `probe_nesting`'s precedent), I3 (denominator definitions), I4 (no timestamp in
  the attested body), S1 (fixed `SYNTHETIC_MODEL_MARKER` + `absent` bucket), and the
  `stop_reason`-only whitelist rule.
- **#226 → Status `blocked` on #237, Route restored to `docs`.** The `code` surface that forced
  the re-route has moved to #237, so the docs routing is correct again. Per step 2, a row whose
  Status is `blocked` is journaled and returned to selection rather than implemented.
- **#234 → row added, Status `blocked` on #226**, both deltas folded into #226's pass. This is
  the human's curation decision on a surfaced joiner, not an auto-add.
- **#235 → left out**, recorded on the queue so it does not re-surface.
- Writes-none path: this iteration ended before step 7, so it owes **neither** an open record nor
  a close record (Ledger format → progress.md). The gate blocks above are the whole journal.
- Budget: subagent-runs=2 (1 SCOPE_AGENT + 1 DESIGN_AGENT) · gate-rounds=architect=1,code-review=0,ac-verify=0 · wall-clock=≈70m · tokens=deferred
- **STOPPING here rather than selecting #237 in the same invocation.** One issue per invocation:
  #226 was this one, and it terminated at `blocked` with its reason recorded. #237 is a full
  `code`-route pipeline — architect, implement, hermetic tier, review, security, mutation pass,
  merge — and it wants a clean context window, which is exactly what a fresh invocation gives it.
- Next: **#237 is selectable** (`routed`, `priority:medium`, no unmet deps) and is what the next
  invocation picks up. #226, #234 and #231 unblock behind it in that order.

## 2026-09-19T01:25:00Z — #226 — correction comment posted

- Correction comment posted to #226 at the human's direction:
  https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/226#issuecomment-5740664408
- **This is write-once. Do NOT re-post it on resume** — check for this line first. Same
  discipline the architect freeze and the recorded architect outcome are under.
- Body left intact as the record of what was believed at filing time, following the #229
  precedent rather than editing the issue in place.
- Contents: the three-way verification that the "#210 contains the provenance" premise is false;
  the corroborating detail that `scan.py` does not compute these families; the replacement
  sentence and the Scope-bullet fix; the #237 split with an explicit statement that **no AC is
  reduced** (the derivation moved upstream, which is sequencing, not a scope cut); the two
  recommended AC additions (AC-6 retained artifact, AC-5 sharpening); and the expected divergence
  from Part 5's figures.
- Nothing was written to #237 or #234 in this action, and the issue body was not edited.

## 2026-09-19T02:40:00Z — #237 (code) — selected, planned, architect gate in flight

- **Selected #237** (`routed`, `priority:medium`, no unmet deps). Step-0 state was clean: no
  run-state sentinel, no interrupted row (every row terminal, `routed`, or `blocked`), **no open
  PRs at all** so the orphan scan found nothing, working tree clean, `git worktree list` shows
  only the main tree, and no `mutate-verify-*` snapshot directory in the system temp dir.
- **Roster reconciliation:** live `BACKLOG_SOURCE` (`gh issue list --label reference --state
  open`) = {137, 138, 226, 229, 231, 234, 235, 237}. Every non-terminal `queue.md` row is present
  in it, and the one roster member with no row (#235) was already surfaced as a joiner and left
  out by human ruling. **No drift to surface.**
- **Budget caps** both `none` — the retrospective check is inert.
- **Size guard: passes.** Nine ACs, but one coherent cluster (extend the scanner) across ~5 files.
  This issue is already the product of a human-ruled split; re-splitting would contradict it.
- Plan written to `issue-237.plan.md`.
- **Falsifier DISCHARGED at plan time, not merely stated** (step 3). Ran a content-free probe over
  a 60-file sample of the local corpus — counts against fixed strings only, the same argument that
  makes `PERSISTED_MARKERS` content-free. **It does not fire**: 1,342 tool cycles, 2,455 assistant
  lines, 976 `toolUseResult` dicts, `Edit`×138, `Agent`×13. Every family has real instances.
- **Three findings the prior architect pass did not have, all bearing on its own I3 ruling:**
  1. **658 of 2,455 assistant lines carry no `stop_reason`** (27%). Family 1's denominator cannot
     be "assistant lines" without the distribution silently renormalizing.
  2. **`structuredPatch` appears on 146 results against 138 `Edit` tool_uses** — it is not
     `Edit`-exclusive, so a naive key count over-counts against an `Edit` denominator. Direct
     evidence for I3.
  3. **All 3 `stop_sequence` occurrences coincide with the 3 `<synthetic>` model lines** — an
     early signal for #234 item 2, not asserted as the answer (60 files is not the corpus).
- **Source-fidelity check:** the issue's rationale rests on #226's false "the provenance exists"
  premise. That was verified false and corrected on #226 already (write-once, posted). The check
  resolves toward "re-derive", which is what this issue is.
- Step 4, in the engine's mandated order: **(a) froze `## Approach` verbatim** into the write-once
  `## Approach as reviewed (frozen before the design gate)` block BEFORE invoking. **(b) Invoked
  `DESIGN_AGENT` (`architect`)**, read-only, on a deliberately NARROW brief — the prior pass's
  rulings (B1/I1/I3/I4/S1) are human-approved and were marked settled, not up for re-litigation.
  Four questions: the probe-vs-`scan()` placement collision with AC-7, the three new findings
  against I3, whether any surface the new counters read is still uncovered by the sentinel test,
  and a catch-all. **(c)** Its outcome gets written into `## Approach` before step 5. IN FLIGHT.
- Architect triggers that fired: the `--json` shape is the CCDC cross-repo interface keyed by
  `(tool, scan_version)` and this change moves it; and "the orchestrator is unsure" — the
  placement question is unresolved and AC-7 makes it load-bearing.

## 2026-09-19T03:05:00Z — #237 (code) — architect gate returned; plan gate STOPPED

- `DESIGN_AGENT` (`architect`) returned: **3 blocking, 9 important, 2 suggestions**, and
  **changed its own prior I1 placement ruling**. Every `file:line` claim it made was
  **re-verified against the source before acting; all hold.** Notably:
  - **(f) `tooling/format-scan/tests/` is in NO CI workflow** — grep for `format-scan`/`scan.py`
    across `.github/` returns zero matches. B1, the single enforcing leak gate for this change,
    runs only when someone remembers to type the command.
  - **(g) `.gitignore` has no rule under `tooling/format-scan/`** (full file read) — so Step 5 as
    originally written would drop an unreviewed corpus-derived JSON into the tree as an untracked
    file, one `git add -A` from being committed.
  - **(2.2) `structuredPatch` is documented under BOTH envelopes** — `tool-invocation.md:236`
    (Write) and `:247` (Edit). The 146-vs-138 finding was already documented; the scan's job is to
    confirm which set carries it.
  - **(d) sharper than the architect stated:** `tool-invocation.md:195` records **240 bare-string
    `Edit` `toolUseResult`s**. The plan's dict-only denominator for family 3 would have silently
    dropped all 240 — finding 2's lesson repeating on a second axis.
  - **(c) the AC-1 blocker:** `scan.py:86-89` sets the whitelist bar at "a **closed**, content-free
    vocabulary"; `data-dictionary.md:99` says of `stop_reason` "**treat this as an open enum**".
    Both verified. Planting a sentinel *in* `stop_reason` would make the sentinel test fail by
    design, so the one newly-promoted field is the one B1 structurally cannot gate.
- Dispositions written into `## Approach` per step 4(c) **BEFORE** this gate ran: **Q1(c), Q2.1,
  Q2.2, Q2.3, Q3-a, Q3-b, Q3-c, Q3-d, Q3-e, Q4-g, Q4-h, Q4-i, Q4-j adopted; Step 6 adapted;
  architect (f) DECLINED and escalated** rather than absorbed — adopting it would touch
  `.github/workflows/`, outside all nine ACs, and would quietly reverse the human's own
  2026-09-19 curation ruling that left #235 out of this run for exactly that reason.
- **Plan-gate: material (a fork was re-chosen — class-2 families move from a probe to a per-file
  join inside `scan()`; steps added — Step 0 placement resolution and family 1b's `stop_sequence`
  state table; the files-to-touch set changed — `test_statistic_families.py` added, `README.md`
  confirmed, and the artifact restaged from the working tree to the scratchpad; and AC-1 was
  reinterpreted — three surfaces it did not previously cover, one of which makes it unsatisfiable
  as literally written) → STOPPED.**
- **No acceptance criterion was reduced.** AC-1 widened; AC-3 keeps `stop_reason` on the whitelist
  and changes only how it is emitted; AC-7's artifact is still committed, just staged outside the
  tree until AC-8 clears; AC-9 gains a second table. The one interpretive call that touches what
  #226 will cite — folding unrecognized `stop_reason` values to `<other>` — is put to the human
  explicitly rather than absorbed.
- Row stays `planning`. Not advanced to `plan-approved`: the architect materially redirected the
  plan and the human has not seen the redirect.

## 2026-09-19T03:20:00Z — #237 (code) — plan gate resolved: APPROVED

- **Plan APPROVED** (plan-gate: always, round 2 after the architect's material redirect). Three
  human rulings:
  - **Architect (f) → follow-up issue.** The CI gap is real and stays real; it does not get
    smuggled into #237. The human's #235 curation ruling stands, and the workflow work lands as
    one coherent change rather than as a rider on a scanner PR.
  - **`stop_reason` → fold to `<other>`.** Seven documented values verbatim from a fixed
    constant, plus `null`/`absent`; anything unrecognized folds to `<other>`. The artifact becomes
    a reviewable closed set, drift still surfaces as `<other>` > 0, and the field becomes
    sentinel-testable — which is what discharges AC-1 for it.
  - **Plan approved, proceed to implement.**
- Row advanced `planning` → `plan-approved`.
- Implementation order is fixed by B1 and is not negotiable under time pressure: the sentinel test
  lands **alone**, against the **unmodified** scanner, before any counter is written.

## 2026-09-19T04:10:00Z — #237 (code) — iteration open

- Issue: #237 — feat(format-scan): re-derive Part 5's five statistic families and retain the
  output as a committed artifact
- Route: code
- Branch: feature/237-format-scan-statistic-families
- PR: #239
- Status: in-pr
- Commits so far: `0804494` (sentinel gate, landed ALONE against the unmodified scanner per B1)
  and `14bc389` (the counters).
- Also filed: **#238** (`tooling/format-scan/` runs in no CI workflow) — the architect's finding
  (f), which the human ruled into its own issue rather than into this PR.

## 2026-09-19T04:55:00Z — #237 (code) — CI green; code-review gate round 1

- **CI green on #239**, all six checks including the required `sanitizer-ci` aggregate: prettier,
  pytest py3.11/3.12/3.13, build + twine check.
- **`CODE_REVIEW` (the `/code-review` skill, effort `high`) run with the issue's acceptance
  criteria supplied**, per `loop.config.md`'s binding note — a reviewer holding the ACs catches
  "this does not actually do AC-N", which the diff alone cannot reveal.
- **Leak audit came back clean** and was independently checked: no path found by which a
  session-derived value reaches stdout. It also confirmed `0804494` passes standalone against the
  unmodified scanner, which is AC-1's actual requirement.
- **9 findings (2 medium, 7 low). All verified against source before acting; all fixed** in
  `f3dfe0b`. The two that mattered:
  - **A line's single `toolUseResult` was credited to EVERY `tool_result` block on it.**
    `tool-invocation.md:526` documents multi-block lines, so this would inflate conditional-key
    counts and cross-attribute between tools. **Measured before fixing: latent, not active** —
    the local corpus has 96,416 tool_result lines and 96,416 blocks, i.e. every line carries
    exactly one. So the artifact's numbers were never wrong, and nothing but a test would ever
    have caught the regression. Now recorded as `ambiguous_multi_block` with no key credit.
  - **The mid-read `OSError` path left the report internally inconsistent** with nothing in the
    artifact to explain it. Added `files_dropped_mid_read` plus a denominator clause.
  - Also: `message_shape` silently pooled sidechain with parent traffic (now stated AND
    quantified); a comment miscited `tool-invocation.md:539` for a claim the doc contradicts
    (`toolStats` is keyed by CATEGORY — `data-dictionary.md:224`, and `:243` calls the tool-name
    form "a documentation error rather than a variant"), which is the step-6 authoring-rule
    violation exactly; a hand-derived markdown separator width; unbackticked `<other>`/`<null>`/
    `<absent>` headers that markdown ate; `non_string` folded into `non_empty_string`; explicit
    nulls collapsed into catch-alls on two families; and one untested counter.
- **Round 2 is a FRESH spawn** (Fresh-re-check invariant) — not this thread re-reading its own
  diff, and not the round-1 reviewer re-contacted. Fixes were committed BEFORE spawning it, since
  it reads `main...HEAD` and an uncommitted fix would have it certify the pre-fix code.
- **The artifact is being regenerated from the post-fix code.** The first run was made at
  `14bc389`, and the fixes changed the report shape — a retained artifact produced by superseded
  code is exactly the provenance defect this issue exists to remove.

## 2026-09-19T05:30:00Z — #237 (code) — code-review round 2 DIRTY → ESCALATED

- **Round 2 (fresh spawn, per the Fresh-re-check invariant) came back DIRTY.** 8 of 9 round-1
  fixes confirmed with `file:line`; item 2 **partially done**; and **8 new defects (D1-D8)** that
  only the fixes introduced. The checker also fuzzed 300 randomized corpora (0 identity failures)
  and found **no new leak path**.
- **Per the invariant, this STOPS and goes to the human. No round 3 opened, nothing fixed.** The
  cap is 2 and round 2 was the re-check; a round invented to fit is a cap that does not bind.
- Substantive residue, in the order it matters:
  - **D1 (moderate) — the `files_dropped_mid_read` denominator clause makes a FALSE claim in the
    retained artifact.** It asserts the figure is lower than `content_block_types.tool_result`
    whenever the counter is non-zero; that is untrue when the drop happened before any
    `tool_result` was ingested, including every *open* failure. The checker reproduced it. A
    denominator that lies is precisely the defect #237 exists to remove.
  - **D3 — `ambiguous_multi_block` is tested before `_MISSING`**, so a multi-block line carrying
    NO envelope is labelled ambiguous rather than `absent`. Nothing is ambiguous about it. Zero
    local impact (no multi-block lines exist here), but it is a wrong label the artifact cannot
    distinguish.
  - **D7 — the new classifier labels are undefined in the artifact's own `denominators`.**
    `stop_sequence_state` has no clause at all; `user_content_shape`'s does not distinguish
    `null`/`absent`/`other`; `toolUseResult_null` is described nowhere. "Denominators carried in
    the artifact, not just in code" is the stated point of the change.
  - **D4 — items 2, 5 and 6 landed with ZERO test coverage.** The `print_human` path has no test
    at all, so the column-count invariant fix 5 exists to protect would regress silently.
  - D2 (counter name conflates open-failure with mid-read death; CHANGELOG repeats it), D6
    (`tool_cycle` is pooled the same way and says nothing), D8 (CHANGELOG nesting) — minor.
- **D5 was "cannot tell" and I settled it by measurement rather than leaving it open**, so the
  human's decision is informed: across 289,122 lines the line-level `isSidechain` flag and the
  file container agree **perfectly** — trace-container lines are 100% `flag=True`, parent-container
  lines 100% `flag=False`, zero disagreement. So the proxy is exact on this corpus; the
  prose-vs-measure mismatch is a latent documentation imprecision, not a miscount.
- Checker also flagged, explicitly as **pre-existing and not introduced here**: `spawnDepth` is
  `str()`-formatted at the meta-whitelist emission with no `isinstance(int)` guard, unlike
  `probe_nesting`'s. It is the one whitelist entry whose guard is weaker than its own
  justification. Not this PR's to fix; worth its own issue.
- AC-7/8/9 remain outstanding. The artifact is regenerated from post-fix code and sits in the
  scratchpad, uncommitted, awaiting the human's PII gate.

## 2026-09-19T06:05:00Z — #237 (code) — round 3 (human-directed), security gate CLEAN

- **Round 3 was directed by the human**, not opened by the loop. Scope as ruled: D1, D3, D7, D4
  fixed in `ce2b4d2`; D2, D6, D8 filed as **#240** rather than folded in.
  - **D1 mattered most: the fix round had introduced a FALSE claim into the artifact's own
    denominators.** Correcting one honesty defect by creating another is worth naming plainly, and
    it is the reason the re-check earned its keep.
  - D3 (ambiguity now requires a body to misattribute), D7 (every new label defined in the
    artifact, not only in code), D4 (the `print_human` path had NO test at all — the column-count
    invariant and the backticking would both have regressed silently).
- **No round 4, and no self-certification of round 3.** The fresh-instance principle is discharged
  structurally by step 10, whose verifier is a fresh spawn reading the whole diff against the ACs,
  rather than by inventing a round the cap does not allow.
- **`SECURITY_REVIEW` (local `/security-review`) run. Precondition checked FIRST** per
  `loop.config.md`: `origin/HEAD` resolves to `refs/remotes/origin/main`, so the gate diffed real
  content rather than dying on `fatal: ambiguous argument` and being mistaken for clean.
- **Verdict: no HIGH or MEDIUM findings.** Evidence, not just a verdict: a full data-flow trace
  from all nine newly-read fields to both sinks; confirmation that no classifier can return
  corpus-controlled text; that the raw-id-keyed join dict is never iterated or serialized; that
  `build_report` contains no f-string; and an adversarial synthetic corpus planting sentinels in
  every new position with hostile types (non-str, near-miss, MCP-shaped, multi-block) run across
  all eight scanner modes — **0 sentinel hits in stdout+stderr**, with the sections still
  populating non-vacuously.
- Diff-level repo invariants confirmed: no raw session JSONL (every fixture synthetic via
  `_helpers.make_session`), no secrets, and the corpus-derived artifact deliberately NOT in the
  diff.
- CI green on `ce2b4d2`, all six checks.
- **Artifact regenerated a third time**, from the round-3 code. A retained artifact produced by
  superseded code is the provenance defect this issue exists to remove, so it is regenerated after
  every change to the report shape rather than once at the end.

## 2026-09-19T06:45:00Z — #237 (code) — AC-8 human PII gate FOUND A REAL LEAK

- **The human PII gate caught what no automated gate could**, which is the
  justification for having it rather than a formality discharged.
- **Method:** rather than eyeballing 56KB of JSON, enumerated every distinct string in the
  artifact. Result: **14 distinct string VALUES** — 2 real (`"0.3.0"`, `"ccs-format-scan"`) and 12
  blocks of authored denominator prose. Everything else is an integer count or an envelope key
  name. `meta_json_keys` emits names only; the sole whitelisted values are `spawnDepth=1/2/3`.
- **One section failed: `tool_results.name_prefixes` — 466 distinct values, 4 of them tool-kind
  labels.** The rest: ~430 per-invocation ids (one file each, so the section enumerated individual
  tool invocations), 30 `webfetch-<epoch_ms>-<token>` stems whose timestamps **decode to precise
  wall-clock activity times** (verified: 1781334765589 → 2026-06-13 07:12:45 UTC), and at least
  one fetched document's own filename.
- **Why no sentinel test could have caught it.** The fixture planted exactly one tool-results
  file, `toolu_<S_CRED>.txt`. The probe splits at the first `_`, so it yielded the literal `toolu`
  and the sentinel never reached the counter. **The gate passed because the fixture happened to
  use the one filename shape that is safe.** Real filenames mostly have no underscore and come
  back whole. This is the precise shape of a vacuous gate, and it is the standing argument for why
  AC-8 is a human gate at all: the sentinel test proves the scanner does not emit *planted* values
  and cannot prove the corpus held nothing unanticipated.
- **Pre-existing since 0.2.0; `git diff main...HEAD` does not touch that logic.** #237 did not
  introduce it — #237 is what would have published it.
- **Human ruled: fold it in this PR**, as the same pattern the change already establishes.
  Implemented in `dbfdb9e`. Note `mcp-github-list` could NOT simply be allowlisted — the server
  name is inside the string, the same author-controlled vocabulary `TOOL_NAME_ALLOWLIST` exists to
  exclude — so the MCP family folds to a fixed `mcp` label, countable without naming a server.
- **This is the one part of 0.3.0 that narrows an EXISTING key's value space** rather than adding
  one. Shape is unchanged (`{str: int}`) so a prior-shape consumer does not break and the bump
  stays MINOR, but anything reading the prefix strings loses them, and 0.2.0-attested profiles
  carry the unfolded values. Called out explicitly in the CHANGELOG for CCDC.
- Sentinel fixture now plants the three shapes a real corpus holds: no underscore, a
  `webfetch-<epoch_ms>-` stem, and an MCP name with the server inside it.

## 2026-09-19T07:30:00Z — #237 (code) — AC-7/8/9 discharged; acceptance gate Class A

- **AC-8 signed off by the human** after the prefix fold; artifact committed as `a5e4d56`
  (`tooling/format-scan/scan-2026-09-19.json`, 3,500 files / 436,010 lines, sha256 `810ae38f…`).
  Confirmed the repo's `.prettierignore` scopes the gate to `posts/`, so the artifact's bytes are
  never reformatted and the hash CCDC content-addresses stays stable.
- **AC-9 posted to #234** (`issuecomment-5746681916`), answering item 2 with both tables.
- **Acceptance gate Part 1 (Class A) — fresh verifier, ran the commands itself, given none of my
  claims. Verdict: all 9 ACs MET, overall DONE. `ac-findings=0`.** It verified AC-1's
  "lands before the counters" the hard way — extracted the tree at `0804494` and ran the suite
  against the byte-identical base `scan.py` (17 passed), rather than taking the commit order as
  proof.
- **It also caught a real defect no AC covers, and it is the ironic one.** The figures I posted to
  #234, and two in `a5e4d56`'s commit message, came from a scan run ~20 minutes older than the
  artifact the comment tells readers to check them against: 127,810/8,598/45,277/181,685 against
  the committed 127,991/8,620/45,362/181,973. **That is precisely the defect #237 exists to
  remove — a published figure that cannot be re-derived from its stated source — recurring inside
  the change built to prevent it.** What caught it was a reader reconciling prose against data,
  not any automated gate.
  - #234 comment **corrected in place, with the correction stated visibly** rather than silently.
  - The commit message cannot be corrected without a force-push, which is forbidden, so an
    **erratum comment** on #239 is the correction of record.
  - **Source-free fix** (a GitHub comment and a PR comment), so per step 10 it re-arms no gate and
    needs no escalation. Every ratio and qualitative claim survived unchanged; only four absolute
    counts moved.
- Two lesser notes the verifier raised, neither an AC gap: the `toolStats` key-name sentinel was
  removed from the fixture (safe, since counting is presence-only and `data-dictionary.md:224`
  says the keys are category-keyed — but it is a coverage reduction); and `0804494`'s message
  claimed coverage of "every surface #237 reads" while missing the filename-prefix surface, which
  only got covered in `dbfdb9e` after the human review found the leak. Both recorded here rather
  than fixed, since the first is deliberate and the second is honestly documented downstream.
- Class B (mutation pass) is DUE — route `code`, behavior altered, tests added — and is running
  under worktree isolation via the plugin's harness. Not improvised.

## 2026-09-19T08:00:00Z — #237 (code) — acceptance gate Class B: DIRTY, fixed, round 2 running

- **Class B was DUE** (route `code`, behavior altered, tests added) and ran via the plugin's
  harness under worktree isolation. Not improvised.
- **Round 1: one SURVIVOR out of 14 real mutations across two specs**, with a control surviving in
  both runs so the pipeline demonstrably reports survivors (exit 0 then exit 1).
- **The survivor:** making `stop_reason_label()` return `<absent>` for an explicit JSON null left
  **all 75 tests green**. The test that should have caught it is literally named
  `test_null_is_distinct_from_absent_in_every_classifier` — and covered `user_content_shape` and
  `toolUseResult` but **not `stop_reason`, the case the `_MISSING` rationale was written for**. It
  generalized a rule without applying it to the originating case.
- **Why the suite could not catch it, which is the textbook part.** `<null>` appears elsewhere in
  the tests only inside the human-report assertions, which check that a `<null>` COLUMN exists and
  is backticked. That column is emitted from a literal set, independent of anything the classifier
  returns — so under the mutation it still renders, still backticked, permanently all-zeros, and
  those tests pass. **Outcome asserted, mechanism unasserted: the atomic-write shape exactly.**
  The three tests that do exercise the histogram each happen to use a fixture with no null in it.
- **Not cosmetic.** Under the mutation the committed artifact contradicts itself:
  `stop_reason_presence.present_null` reports N while `stop_reason_by_model_bucket["<null>"]`
  reports 0 — and on this corpus that is **45,362 lines, 100% of the bucket**, mislabelled three
  keys away from the correct number in the same file.
- **Not a leak.** All three fold-removal mutations that WOULD emit a session value were killed,
  two by the content-free gate. This is an accuracy defect in a published artifact.
- **Fix (`e70ac2a`), two guards, the second asserting the mechanism:** extend the "every
  classifier" test to actually mean every; and assert that `stop_reason_presence` and
  `stop_reason_by_model_bucket` **RECONCILE** — they classify the same raw value through two
  independent paths, so either output alone is reachable by a broken implementation and their
  agreement is not. No cross-check existed before.
- Hermetic tier re-armed by the added test and re-run: **exit 0, 76 passed**.
- **Round 2 is a FRESH spawn re-running the harness on the same spec entry with its control
  retained** — a re-read is not sufficient for a surviving mutant, since the survivor was
  established by running. Fix committed BEFORE spawning it.
- **Cleanup duty discharged:** the round-1 worktree landed INSIDE the repo at
  `.claude/worktrees/agent-…` and showed as untracked — the gitlink hazard. Removed, with its
  branch, before any staging. `git worktree list` now shows only the parent; no snapshot
  directory retained.
- **Plugin defect recorded for upstream:** round 1's worktree was provisioned at the BASE commit,
  not the feature tip. Had the agent trusted the empty diff it would have mutated pristine base
  code and reported a clean pass certifying nothing. The engine's second precondition is the only
  thing that caught it, and it caught the *silent* failure shape.

## 2026-09-19T09:00:00Z — #237 (code) — Class B round 2 CLEAN; security RE-RUN on currency

- **Class B round 2 (fresh spawn): harness exit 0 — the mutation came back KILLED and the control
  SURVIVED.** Both halves of the proof present. The checker also verified the fix is honest by
  reading: no mutation weakened, no guard moved out of the pass's reach, and the commit is
  `1 file changed, 55 insertions(+), 0 deletions` — pure addition, so no pre-existing assertion was
  relaxed. It confirmed the mechanism claim against the source rather than the docstring:
  `stop_reason_presence` does its own inline `_MISSING`/`None` discrimination and **never calls
  `stop_reason_label`**, so the two surfaces really are independent and their agreement is not
  reachable by an implementation broken on either side. **`mutation-survivors=1`, resolved.**
- **Both mutation worktrees landed INSIDE the repo and were removed with their branches before any
  staging.** No snapshot directory retained on either run. `git worktree list` shows only the
  parent.
- **Round 2's worktree was ALSO provisioned at the base commit — two for two.** Recorded upstream;
  not a one-off.
- **CURRENCY: code review and security review had both certified `ce2b4d2`, and three commits
  landed after it** — `dbfdb9e` (a SOURCE change on the emission path), `a5e4d56` (commits
  corpus-derived data), `e70ac2a` (test-only). Per the Gate-outcome invariant a verdict is bound to
  the commit it ran on, so both were re-armed. **Step 9 carries no round cap, so security was
  re-run rather than waived.**
- **Security re-run verdict: no HIGH or MEDIUM.** Two MEDIUM candidates were raised and **both
  dropped by independent false-positive filtering** (2/10 and DROP-at-8/10) as pre-existing `main`
  code outside the review's stated scope. The artifact was audited exhaustively rather than
  sampled — all 390 distinct strings categorized, **all 1,662 dict keys walked separately from
  values**, and all 1,209 numeric leaves checked to confirm none falls in epoch range. Clean.
- **Filed #242** for the dropped-but-real finding: `persist_anchored_tags` emits verbatim
  tool-result content (a filesystem path was demonstrated reaching output), its comment claims the
  opposite, and **the sentinel gate passes vacuously because no fixture tool_result contains angle
  brackets**. That is the SAME blind-spot class as the prefix leak — a transform that destroys the
  sentinel before the counter sees it — now the second instance, which is why the issue names the
  general shape rather than just the instance.
- **Still outstanding at the merge gate: the code-review re-arm.** Step 8's budget is spent (round
  1, a fresh re-check, plus a human-directed round 3), so nothing remains to certify `dbfdb9e`
  onward. Per the currency clause that is an **unowned re-arm, which escalates to the human** — it
  is not something the loop may absorb, and a human decision to merge is recorded as a human
  decision, never as a gate pass.

## 2026-09-19T09:15:00Z — #237 (code) — merge gate presented; human directed a delta review

- **Gate roll-call presented with the commit each verdict certifies**, not as a flat "all green".
  Ten gates current on `e70ac2a`; one stale.
- **The stale one was surfaced, not absorbed:** code review certified `ce2b4d2`, and `dbfdb9e` (a
  source change on the emission path), `a5e4d56` (the artifact) and `e70ac2a` (tests) landed after
  it. Step 8's budget was spent — round 1, the fresh re-check, and the human-directed round 3 — so
  nothing remained inside the pipeline to certify the delta. Per the currency clause that is an
  **unowned re-arm, which escalates.**
- **Human ruled: one focused review of `ce2b4d2..HEAD`, then merge.** That round exists because
  they directed it; the loop did not open it. Running now, with the ACs supplied and angles picked
  for the delta's own risk surface rather than a fixed list.
- Also disclosed at the gate rather than glossed: **Class A certified `a5e4d56`**, and the only
  change since is test-only and strengthens AC-6's own evidence. Flagged as a judgment call for
  the human rather than silently counted as covered.
- Budget as it stands: `subagent-runs=10` · `gate-rounds=architect=1,code-review=3,ac-verify=2` ·
  `ac-findings=0` · `mutation-survivors=1 (resolved)` · `post-gate-survivors=0`.

## 2026-09-19T09:45:00Z — #237 (code) — directed delta review: CLEAN on correctness, 1 MEDIUM doc defect

- **Human-directed review of `ce2b4d2..HEAD` returned: the delta is functionally correct.** No
  count wrong, no assertion inert, every AC met. It verified rather than asserted:
  - **Confirmed the new test's claims by MUTATION, not by reading** — built scratch trees at
    `ce2b4d2` and at HEAD and showed the null-collapse mutation is green pre-delta (74 passed) and
    red at HEAD, and that **neither later assertion is inert**: each is the sole detector for a
    distinct mutation.
  - **Audited the artifact against HEAD's own serializer**: key set exactly identical, all twelve
    denominator blocks byte-for-byte, every internal identity holding
    (`tool_result_blocks 96,608 == resolved 96,604 + orphaned 4`; per-tool shapes summing to
    `results`; `<null>` 45,362 reconciling against `present_null` 45,362), file byte-identical to
    `json.dumps(…, sort_keys=True)`.
  - **Numerically verified the corrected #234 comment** against the committed file — every figure
    matches. The correction landed right.
- **One MEDIUM, and it is this repo's recurring defect class:** `dbfdb9e` updated the README's
  fold list but NOT `scan.py`'s SECURITY CONTRACT docstring, **which `README.md` designates as
  "the full contract"**. Secondary doc corrected, primary one missed — the identical mechanism
  that produced the leak `dbfdb9e` fixed.
- **Two false claims in prose I wrote**, both corrected in `408b221`:
  - "anything outside those fixed sets is counted as `<other>`" — false for the MCP fold, stated
    in the same sentence that lists it.
  - "the corpus fingerprint is `summary` … plus the `versions` histogram" — `versions` is
    top-level, not inside `summary`. **This one would have propagated**: #234's comment and #226
    are both told to cite "the artifact's `summary` fingerprint".
- Also fixed: the SECURITY CONTRACT now names the new constants AND states plainly that
  `file EXTENSION` / `DIRECTORY name` are **not** folded and rest on the same unverified
  assumption the prefix violated — so the contract does not read as though that question were
  settled. And the README's own emit-summary, stale since 0.2.0.
- **Deliberately NOT changed after the review that cleared the delta:** the MCP double-underscore
  coverage gap (documented instead) and the missing no-timestamp regression test. Both added to
  **#240** so the merge candidate's source and tests are exactly what was reviewed. `408b221` is
  docs and comments only — no source behavior, no test change — so it re-arms nothing.

## 2026-09-19T23:30:00Z — #237 (code) — iteration complete

- Selected: #237 (highest-priority unblocked; `priority:medium`).
- Route: code (full pipeline, all gates).
- Plan: issue-237.plan.md written; falsifier DISCHARGED at plan time, not merely stated — a
  content-free corpus probe that produced three findings which changed the design.
- Architect: invoked on a narrow brief; returned 3 blocking / 9 important / 2 suggestions and
  **reversed its own prior I1 placement ruling** once shown the join is intra-file.
- Plan-gate: material (a fork was re-chosen, steps added, files-to-touch changed, AC-1 reinterpreted) → STOPPED.
- Human gate: plan approved by the human (plan-gate: always), with three rulings.
- Implemented: sentinel gate first and ALONE against the unmodified scanner (B1); then the
  counters; then four fix rounds. `tooling/format-scan/{scan.py,README.md,CHANGELOG.md}`,
  two test modules, and the retained artifact.
- Hermetic: pass — re-run after every commit that added a test, block re-verified socket-level each time.
- PR: #239 (feat scope). CI: green, 6/6 including the required `sanitizer-ci`, on every commit.
- Code-review: 4 rounds. Round 1: 9 findings. Round 2 (fresh): DIRTY, 8 new defects — escalated, human directed round 3. Round 4 (human-directed, on the post-review delta): 1 medium doc defect. Security: no HIGH/MEDIUM, re-run on currency; 2 candidates dropped by FP filtering.
- Restore: n/a: no mutation applied to the parent tree (both passes ran under worktree isolation; both copies removed, no snapshot directory retained).
- AC-verify: Class A 9/9 acceptance criteria met. Class B: 1 survivor found, fixed, and re-killed by a fresh instance (harness exit 0, control survived).
- Budget: subagent-runs=11 (architect + code-review skill + fresh re-check + 2 security ident + 2 FP filters + AC-verifier + 2 mutation pass + delta review) · gate-rounds=architect=1,code-review=4(correctness,robustness,security-contract,doc-consistency),ac-verify=2 · justification=blast radius: a scanner reading unsanitized transcripts whose output is now committed to a public repo; two of the extra rounds were human-directed and one found a live PII leak · ac-findings=0 · mutation-survivors=1 (found and resolved) · post-gate-survivors=1 (the SECURITY CONTRACT docstring defect in dbfdb9e survived both the security re-run and the acceptance gate; caught only by the directed delta review) · wall-clock=≈21h (includes three human gate stops) · tokens=deferred
- Merged: squash #239 as `e29c4e7`. Issue #237 closed. Branch deleted local and remote.

**What this iteration actually bought, beyond the feature:**

- **A live PII leak fixed** — `tool_results.name_prefixes` was emitting 466 corpus-derived
  strings including 30 decodable activity timestamps. Pre-existing since 0.2.0, and this iteration
  is what would have published it.
- **Two vacuous gates identified.** The sentinel fixture passed for the prefix surface because it
  used `toolu_<sentinel>.txt`, the one filename shape that splits safely; and
  `persist_anchored_tags` (#242) passes today because no fixture tool_result contains angle
  brackets. **Both are the same shape: a transform that destroys the sentinel before the counter
  sees it.** That generalization is the durable finding.
- **A mutation survivor in a test named for the very property it failed to assert.**
- **The irony worth recording:** a published figure that could not be re-derived from its stated
  source recurred *inside* the change built to eliminate that defect, in the #234 comment and one
  commit message. Corrected in place and by erratum. What caught it was a reader reconciling prose
  against data — no automated gate did.

- Next: **#226 is now unblocked** (its only dependency, #237, is `done`) and is the highest-priority
  selectable row at `priority:medium`. #234 and #231 remain blocked behind #226. #137/#138 are
  selectable but rank below `priority:low`. New this run and NOT in the queue: #238, #240, #242 —
  surface them as joiners at the next iteration's roster reconciliation rather than auto-adding.

## 2026-09-20T00:00:00Z — curation + selection (#243)

- **Run-state sentinel scan (step 0.1, FULL file):** no `RUN COMPLETE` / `RUN PARKED` / `RUN RESUMED`
  sentinel anywhere in this journal. Run continues normally.
- **Resume row scan (step 0.3):** no interrupted row. Statuses are `done`/`done`/`blocked`×3/
  `routed`×2 — no pipeline status past `routed`. Nothing to finish before selecting.
- **Resume (a), unfinished-mutation check:** `git worktree list` shows only the primary tree at
  `main` (`e29c4e7`); no `mutate-verify-*` directory under the system temp dir. Working tree clean.
- **`origin/HEAD` precondition (loop.config.md §4):** resolves to `refs/remotes/origin/main` at
  `e29c4e7`. Met; no repair needed.

### Orphan scan (step 0.3) — one open PR, classified NOT an interruption

`gh pr list --state open` returns **PR #245** (`feature/68-what-hooks-leave-behind`, "feat(posts):
draft Part 6"). It has no row in this run's `queue.md`, and none in `epic-sanitizer`'s.

**Positively attributed to a human, not to this loop.** It was authored by hand earlier in this same
session at the human's direct request, outside the pipeline: no plan file, no open record in either
ledger, no gate ever ran on it. Its issue (#68) does not carry the `reference` label and is not in
this run's `BACKLOG_SOURCE`. Per step 0.3's default-deny test this is the "positively attribute to a
human" exemption, not the "cannot tell ⇒ interruption" branch — so the scan does not halt.

**But Guardrails' `One PR at a time (no stacked PRs)` is still live**, and this iteration would open
a second PR at step 7. That is **carried to the plan gate as an open question for the human** rather
than absorbed here. Nothing irreversible happens before then: under `plan-gate: always` this
iteration stops at step 5, before any branch or PR exists.

### Roster reconciliation (step 1)

Live roster (`gh issue list --label reference --state open`): #137, #138, #226, #229, #231, #234,
#235, #243. Deduped against a FULL-file scan for prior `- surfaced-join:` / `- surfaced-leave:`
lines (found: #234, #235).

- **surfaced-join: #243** — in the roster, no `queue.md` row, not previously surfaced. **Human ruled
  "pull in" in this invocation**, so a `queued`→`routed` row was added (row 8).
- **#235** — already carries `- surfaced-join: #235` from 2026-09-19 and was left out by human
  ruling. Self-dedups; **not re-surfaced**, per that ruling and this invocation's instruction.
- **Left:** none. #237 is absent from the live roster (closed, and never carried the `reference`
  label — it was split out by human ruling), but its row is terminal (`done`), so the leave-surfacing
  rule does not apply.
- **#238 / #240 / #242 — disposition recorded, NOT joiners for this run.** The 2026-09-19 close
  record flagged them for a joiner decision. None carries the `reference` label, so none is in this
  run's `BACKLOG_SOURCE` roster and the reconciliation above never sees them. All three were labelled
  `epic:format-watch` on 2026-09-20 and assigned to a **new, separate `format-scan` run** (not yet
  initialised). They do not enter this queue.

### Budget cap check (step 1)

`iteration-cap: none` / `subagent-cap: none` — both inert. Prior iteration (#237) journaled
`subagent-runs=11`; no cap to breach.

### Selection — HUMAN OVERRIDE of `PRIORITY_LABELS`, recorded as such

**The engine would have selected #226.** Both #226 and #243 are `priority:medium`; the tiebreak is
issue-number ascending, and #226 became selectable when #237 merged (the 2026-09-19 close record says
so explicitly). **The human overrode that and selected #243.**

**Correction to the rationale as the human received it.** It was put to them as "Part 6 shipped
2026-09-24, so `reference/` contradicts a published post". **That is wrong and is corrected here:**
Part 6 is *not* published. It sits on unmerged PR #245 carrying a future `date: 2026-09-24`. The
ordering argument survives in a different and stronger form — landing #243 **before** PR #245 merges
means Part 6 never ships contradicting the reference doc it defers to — but the premise as stated was
false and is not what the ledger should record.

#226 keeps its place as the next selectable row and still blocks #231 and #234.

### Size guard (step 1)

Two table rows in one file (`reference/data-dictionary.md`, 607 lines). Single AC cluster. Fits one
context window. Pass.

### Route (step 2)

**`docs`.** Router step 2: label `documentation` + change confined to `reference/`, which
`SOURCE_LAYOUT` §3 lists under the docs label/path. Not `stub-defer` (title begins with neither
`Epic:` nor `Coordinating PR:`). Status `routed` — no external gate, no unmet `Depends on`.

Per `loop.config.md` §3's warning, the repo's docs-may-go-direct-to-main policy governs **humans**,
not the loop: this row still goes through the engine's commit + PR step.

## 2026-09-20T00:30:00Z — #243 (docs) — architect gate

**Trigger fired** despite the `docs` route: `loop.config.md` §2, *"A new reference-doc contract that
AgentFluent or CodeFluent will link to (a field definition's meaning) — these are cross-repo
interfaces."* The §2 skip list covers "`reference/` prose that documents an already-verified field"
(true of Step 1) but not a field with no row anywhere (Step 2). The list is marked SUFFICIENT, NOT
EXHAUSTIVE with a bias toward calling the agent, and the "orchestrator is unsure" catch-all also
applied.

`## Approach` was **frozen verbatim before the agent was invoked** (step 4a), heading exact,
write-once. Verified byte-identical after the outcome was applied.

**Outcome recorded here, in the journal + the queue row Notes — NOT as an issue comment.** The agent
was explicitly barred from any outward write this time (the prior double-post defect), and it
complied: no file edits, no issue or PR comment.

**Four findings — three important, one suggestion. All four ADOPTED:**

1. *(important)* Placement in the `### user` top-level sibling table is correct, and the agent
   confirmed it on **independent evidence** rather than agreeing: both counters reporting the key
   iterate `obj.keys()` (`scan.py:497`, `scan.py:575-577`), so `toolDenialKind` is provably a
   top-level line key. **But add a see-also from the `### tool_result` section** (line ~415, which
   already carries the doc's precedent for exactly this structural-vs-semantic split), and reword the
   line-142 lead-in, which says "One optional top-level sibling key is significant" and goes stale at
   two. Do not make `toolDenialKind` a peer of `toolUseResult` — the doc calls that envelope "one of
   the highest-information surfaces in the format" (line 218).
2. *(important)* **Do not splice the row into the `hookAdditionalContext` ↔ Hook-response-schema
   chain.** That chain is `additionalContext` injection on `Stop`/`SubagentStop`, a different
   contract; wiring a denial marker in would assert a denial-is-a-hook-artifact join the scan cannot
   support. Instead name three **candidate** denial sources, each labelled a candidate.
3. *(important)* **Provenance must reach both rows in both sections.** The pre-review plan anchored
   it to the `system` hook subsection only, which would have shipped the `user`-side row with a bare
   count under a v2.1.150 banner. State the corpus facts once by extending line 258; have the
   user-side row cite artifact + counter and point there.
4. *(suggestion)* **Lead the row with the unhedged 227/107,267.** The exactness rests entirely on
   `keys_by_type.user.toolDenialKind` and does not depend on the block-weighted counter at all; a
   hedge-heavy row bleeds uncertainty onto the one certain fact. Epistemics stay in the plan and PR.

**Agent ruling on Q2 (the AC-3 reinterpretation): SOUND**, and to be framed as *strengthening* AC-3
rather than reducing it — the issue reasoned "upper bound" from the block-weighted counter when a
line-weighted instrument was available. It also confirmed the hedge is *logically* correct
(225×1 + 1×0 + 1×2 = 227 blocks over 227 lines) while noting it qualifies a secondary claim the
exact count never rested on.

**Agent ruling on Q3 (the AC-4 deviation): row-scoped provenance is the RIGHT call, and is the
doc's existing convention** — so AC-4's "consistent with the section convention" clause is
*satisfied*; only its literal "Verified against v2.1.278" string is not, and that string is the part
that would be false.

**One citation of the agent's was wrong and is corrected rather than relayed.** It placed the
"SDK 0.2.106 / CLI 2.1.185" claim-scoped pin at line 193 (`resolvedModel`). It is at **line 69**
(`entrypoint`). Every other citation it gave — lines 83, 85, 142, 218, 258, 415, 562 and both
`scan.py` sites — was verified against the files and holds. Its argument does not depend on the
misattributed line.

- Plan-gate: material (a step was ADDED — Step 2b, the `tool_result` see-also + line-142 lead-in reword; Step 3's scope widened from one section to two; the row's content changed from a hedged count to an unhedged lead plus three labelled candidate sources) → STOPPED

## 2026-09-21T02:35:00Z — #243 (docs) — human gate + merge of the blocking PR

**Timestamp correction (append-only, prior entries not rewritten):** the two blocks above are
stamped `2026-09-20T00:00:00Z` and `2026-09-20T00:30:00Z`. Real wall-clock at the time was
2026-09-21T02:2x–02:3xZ; the session's local date had not yet rolled over to UTC 09-21. The
ordering is correct, the absolute stamps on those two blocks are ~26h early. Corrected from here on.

- **Human gate: plan approved by the human (plan-gate: always), as revised by the architect.** All
  four architect findings adopted, and both AC amendments ratified.
- **AC amendments recorded on the issue** (issuecomment on #243 — write-once, the issue had **zero**
  comments before this; do not re-post). AC-3 strengthened to an exact distinct-line count with the
  block-weighted epistemics moved to the PR body; AC-4's literal `Verified against v2.1.278` string
  dropped for claim-scoped provenance, with the #231 hand-off stated. Neither removes scope.

### Guardrails: one-PR-at-a-time resolved by merging the human's own PR first

The human ruled **merge #245 first** rather than waive the guardrail or hold this row.

- Currency checked before merging, not assumed: all 8 checks green **on `dac910a`, the current
  head** — no commit landed after CI ran, so no verdict was stale.
- Squashed as `48ebe38` with an explicit `--subject` carrying the `feat(posts):` scope and the
  `(#68) (#245)` suffix per `COMMIT_CONV`; `--delete-branch` removed the branch local and remote.
- Issue #68 CLOSED by the PR body's `Closes #68`.
- **`gh pr list --state open` now returns 0.** The guardrail is satisfied outright rather than
  waived — this iteration opens into a clean single-PR state.

**Note for a later reader:** #68 was never in this run's `BACKLOG_SOURCE` and has no row here. The
merge is recorded in this ledger because the Guardrails resolution is part of *this* iteration's
history, not because the loop owned that work. It did not — see the 0.3 orphan-scan attribution.

**Stale local branch observed, not touched:** `worktree-agent-a23ba24262454a290` (leftover ref from
an earlier agent worktree; `git worktree list` shows no corresponding tree) and
`draft/cost-levers-aside`. Neither belongs to this iteration and the hard limits scope branch
deletion to the PR's own branch, so both are left for the human.

## 2026-09-21T02:55:00Z — #243 (docs) — iteration open

- Issue: #243 — docs(reference): Part 6 scan contradicts two hook rows
- Route: docs
- Branch: fix/243-hook-rows-data-dictionary
- PR: #246
- Status: in-pr

## 2026-09-21T02:44:01Z — #243 (docs) — code review round 1

- **`CODE_REVIEW` ran as bound**: the `code-review` skill, bare name, effort `medium` (docs-adjacent
  diff on a cross-repo source-of-truth doc). Invocable; no `- gate-fallback:` owed.
- **3 findings (2 medium, 1 low) + 1 non-blocking note. All 4 adopted**, fixed in `786bd06`.
- **Two of the three are the same defect class this change exists to correct, reproduced inside the
  correction** — the pattern #237's close record already flagged as this repo's recurring shape:
  1. *(medium)* The `toolDenialKind` Type column asserted `string` on no evidence, in a row whose own
     prose says the scanner never reads values. Verified deeper than the finding stated:
     `scan.py:737` captures a JSON type **only** for subagent `meta.json` manifest keys, and
     `scan-2026-09-19.json` has no per-key type map for session lines at all.
  2. *(medium)* The non-restamping caveat guarded the `system` banner but never reached the `user`
     section, which the same paragraph names in its own scope line.
  3. *(low)* "recorded at the top level **rather than** in this block" is an absence claim a
     content-free scan cannot support, contradicting the `is_error` row three lines above.
- Round 1's reviewer independently re-derived every figure and confirmed all of them, plus the
  per-line-exactness argument and the `PermissionDenied` citation.

## 2026-09-21T02:44:01Z — #243 (docs) — MERGE BY HUMAN, and the squash missed the fix commit

**This is recorded as a human decision, never as a gate pass** (Gate-outcome invariant: "a human
deciding to merge is not a gate certifying the code").

- **Merged: squash #246 as `bed92f7`.** Issue #243 closed by the merge, then **REOPENED** — see below.
- **The human reviewed the diff as it then stood and merged it. That review was real and is not
  disputed.** What it could not cover is code that did not exist yet.

### The currency failure, with the margin

```
PR #246 merged at:       2026-09-21T02:44:01Z  (19:44:01 PDT)
PR head at merge time:   17bbb16               <- commit 1 ONLY
786bd06 authored:        19:44:34 PDT          <- the round-1 fixes, 33 SECONDS LATER
```

`bed92f7` is `17bbb16` alone — 8 insertions / 3 deletions, where the branch carries 12/5. **All three
round-1 findings are therefore live on `main`** in the doc AgentFluent and CodeFluent link to.

**Root cause is ordering, not judgement.** The engine requires the fix committed *and pushed* before
the fresh re-check is spawned, and that was done — but nothing in the pipeline tells a human watching
the PR that a gate is mid-flight. The PR page showed a green, reviewable diff at `17bbb16` with no
signal that round 2 existed. **Worth reporting upstream:** a gate in flight is invisible on the
surface the human actually merges from.

### Gate state, stated plainly

- **Code review round 1:** ran, 3 findings, all fixed in `786bd06`. Verdict bound to `786bd06`, which
  is **not** in `main`.
- **Code review round 2 (fresh re-check):** spawned against `786bd06`, **in flight at merge time, no
  verdict**. It governs the follow-up PR, not the merged commit.
- **Acceptance gate (step 10, AC-verify):** **never ran.** Not skipped by route — docs does not scope
  step 10 out, only the Class B mutation pass within it. It is simply owed and unrun.
- **Security (step 9):** `n/a: docs route`, per the Routing table. The diff touches none of the six
  sensitive surfaces and the PR recorded that as reviewed-and-not-applicable.
- **`- Hermetic:` n/a: docs route.**
- **`- Restore:` n/a: no mutation applied** (Class B not due, question 1: route is `docs`).

**No close record is written for this iteration and the row is NOT set `done`.** The work on `main`
is incomplete and #243 is reopened; writing a close record would assert an iteration that converged.

### Cleanup deliberately deferred

`git switch main` + branch deletion is **held** while the round-2 checker reads this working tree.
Switching now would hand it `main...HEAD` = empty and let it return a clean verdict certifying
nothing — the manufactured-confidence shape the acceptance gate's own preconditions exist to refuse.
Branch `fix/243-hook-rows-data-dictionary` stays local and remote until round 2 returns.

## 2026-09-21T03:20:00Z — #243 (docs) — code review round 2 (fresh re-check): DIRTY → ESCALATED

**Round 2 of the 2-round cap. A fresh spawn, not round 1 re-contacted, not the parent.** It confirmed
all four round-1 fixes actually landed, and independently re-verified every figure, both `scan.py`
citations, all six anchors and all four issue links. Then it found five more.

**Verified by me before escalating — all three load-bearing ones hold:**

- **MEDIUM, `:280` — "The scanner emits key names and counts only and never reads a field value" is
  FALSE, and the sentence containing it depends on the falsehood.** `scan.py:111` defines
  `EMITTABLE_VALUE_FIELDS = frozenset({"type", "version", "stop_reason"})`; the artifact's `versions`
  dict holds emitted version **values**. So "130 versions, v2.1.4 through v2.1.278" — in that same
  sentence — is derivable only by reading values the sentence says are never read. **This is my
  sentence.** The pre-existing cousin at `:263` carries the same overstatement.
- **MEDIUM, `:278` vs `:290` — the doc now contradicts itself one paragraph apart, and contradicts
  the published post.** My new row text says aggregate counts cannot prove co-occurrence. The
  untouched section intro at `:278` still says the hook fields are "present as a family on the same
  lines" — a co-presence claim no counter in `scan.py` can support for `system` lines. Part 6, now on
  `main`, states the correct position at `posts/2026-09-24-what-hooks-leave-behind.md:49`: "Aggregate
  key counts cannot prove co-occurrence, though: two disjoint sets of 3,964 lines would produce the
  same table."
- **LOW, `:280` — wrong denominator.** "1,303 of the 436,010 lines" is not a share of a partition:
  the 130 version counts sum to **350,954**, and 85,056 scanned lines carry no `version` key at all.
  0.2988% where the meaningful figure is 0.3713%. **Third instance of this class in this repo**, after
  #237/#239 shipped under the title "with stated denominators."

Two more, both mine, both from the round-1 fix: `:422`'s "which a denied call is expected to set" is
an unsourced behavioural claim in mild tension with `is_error`'s own definition one line up; and
`:142`'s lead-in calls `toolDenialKind` "a narrow marker on denied calls", stating flatly the
semantics `:147` spends a sentence saying are name-inferred and not established.

Plus INFO: 12 em-dashes across 10 added lines, against the maintainer's standing preference.

### Diagnosis — name the pattern, because it is the change's own subject

Three rounds, and in every one the prose claimed slightly more than the evidence supports. **That is
precisely the defect this change exists to correct** — the doc said "Rare" where the data said 2,981.
The mechanism is visible in the artifact: the row grew from ~120 words to ~250, and **each hedge
added a new claim that could itself be wrong.** Fixing an over-claim by adding a qualifying sentence
raises the surface area rather than lowering it.

This is the same shape #237's close record already named: "a published figure that could not be
re-derived from its stated source recurred *inside* the change built to eliminate that defect."

### Escalation

**Fresh-re-check invariant: one re-check, then escalate; there is no ladder. No round 3 is opened on
my own authority.** Reaching the cap is a handoff, not a terminal state, and the engine is explicit
that "run another round" is frequently *not* the right answer — narrowing or splitting are live.

Four of the five findings are in text I wrote. Only `:263`'s overstatement and `:278`'s co-presence
claim pre-date this change. Scoped the pattern across `reference/`: it is **localized to lines 263,
278 and 280**, not doc-wide.

Row stays `in-review`. No close record. #243 remains reopened.

## 2026-09-21T03:35:00Z — #243 (docs) — human ruling on the cap: NARROW + SPLIT

**Human directed: narrow the row, split the pre-existing defects out.** Not a third round — the
engine's own named alternative to one ("narrowing the change, splitting it... are all live answers").

- **Branch cut fresh from `origin/main`** (`fix/243-narrow-tooldenialkind-row` off `bed92f7`), not
  continued on `fix/243-hook-rows-data-dictionary`. That branch's merge-base is `48ebe38`, pre-squash,
  so a PR from it would re-propose commit 1's already-merged content. This is the
  `feedback_branch_off_origin_main` trap in a new shape, and round 2 flagged it unprompted.
- **Row cut ~250 words → ~90.** Five claims, each established: top-level key; 227 of 107,267; type
  never inspected; type and meaning both name-derived; #244 settles it.
- **Moved to the PR body** rather than deleted: the block-weighted counter caveat, the
  exact-not-a-ceiling argument, the three candidate denial sources. Reviewer-facing, not
  reader-facing, and each was a claim the doc would have had to defend.
- **Two factual corrections** to text merged in `bed92f7`: the false "never reads a field value"
  (`scan.py:111` whitelists three fields, and the same sentence's version range depends on reading
  them), and the non-partition denominator (versions sum to 350,954; 85,056 scanned lines carry no
  `version` key).
- **Em-dashes in added prose: 12 → 3**, per the maintainer's standing preference.
- **PR #249** opened. **Issue #248** filed for the two split-out pre-existing defects (`:263`'s
  overstatement + unsupported carrier-type claim, `:278`'s co-presence claim), with ACs that require
  the discipline claim be stated **once** in wording that survives #244 adding folds.

### Gate state on PR #249

Round 1 and round 2 both ran on the **predecessor** branch and their verdicts are bound to commits
not in this PR. Per the currency clause those verdicts **do not reach `61b1898`**. This PR therefore
enters the review gate with a **fresh budget**, and that is recorded rather than assumed: nothing
here is journalled as review-passed on the strength of the earlier rounds.

The acceptance gate (step 10) has still never run on any commit of this issue.

## 2026-09-21T03:45:00Z — #243 (docs) — code review on PR #249: first attempt produced NO VERDICT

**Not journalled as a pass.** `CODE_REVIEW` (the `code-review` skill, bare name, effort `low`) was
invoked on `61b1898` and returned an **empty result**: no findings, no verdict text, no report.

**Why this reads as "ran and produced no verdict" rather than "ran and found nothing":** the same
binding, in this same session, on comparably sized diffs, spent 129s / 18 tool calls (round 1,
`medium`) and 287s / 30 tool calls (the round-2 fresh re-check). This attempt spent **3.9s / 1 tool
call**. One tool call cannot retrieve a diff, load the scan artifact, and resolve citations. A clean
verdict from that budget would be a verdict about nothing.

Per the Gate-outcome invariant this is the **dynamic** branch — the binding is present and
demonstrably invocable (it worked twice already), so it is not the static "cannot run" case and
**inline composition is not the licensed fallback here**. The rule is: do not substitute a
home-composed check, do not journal it as passed, escalate.

**One retry issued before escalating**, to separate a transient fork failure from a reproducible one.
A retry of an attempt that yielded no verdict is not a second gate *round* — round 1 never produced
one, so no budget is consumed. If the retry also returns empty, that is a reproducible binding
failure: `- gate-error:` stands and it goes to the human, with PR #249 held unmerged.

**The temptation being refused, stated for the record:** an empty result on a 6-line prose diff that
was deliberately narrowed is exactly the shape where "nothing to find" feels plausible. That
plausibility is the hazard. The diff being small is not evidence the reviewer read it.

## 2026-09-21T03:50:00Z — #243 (docs) — code review on PR #249: REPRODUCIBLE no-verdict → BLOCKED

- gate-error: code-review — Skill(code-review) effort low on a 6-line docs diff — returned empty result, no findings and no report, 1 tool call

**Two attempts, identical signature:**

| attempt | duration | tool calls | subagent tokens | result |
|---|---|---|---|---|
| 1 | 3.94s | 1 | 37,933 | empty |
| 2 | 3.46s | 1 | 37,937 | empty |

Against the same binding's earlier behaviour **in this same session**: 129s / 18 tool calls (round 1,
`medium`) and 287s / 30 tool calls (the fresh re-check). The token counts say the skill body *loaded*
(~38k both times) and then the agent exited without doing the work. This is not a reviewer finding
nothing; it is a reviewer that never looked.

**Guardrails: the same error signature recurred, so this is `stuck`.** Row marked `blocked` with
Notes `gate-error: code-review`. Per the engine, a stuck row with an **open PR** does **not** hand off
to another issue — "one PR at a time still binds; report and STOP." So #226 is NOT selected, and this
invocation ends here rather than starting new work.

**PR #249 is held unmerged**, CI green, `MERGEABLE / CLEAN`. It is not merged on my authority, and it
is not journalled as review-passed.

**What is NOT being done, and why.** The engine licenses inline finder composition only on the
**static** branch (a binding absent from the toolset). This binding is present and was demonstrably
invocable twice today, so this is the **dynamic** branch: "do not substitute a home-composed check,
do not journal it as passed, escalate." A human may direct a substitute round — and if they do it
exists because they directed it, and is journalled under its real identity, not as `code-review`.

**Worth reporting upstream** (dev-loop v0.2 corpus + Claude Code product): a gate binding that fails
by *succeeding instantly and silently* is the worst available failure mode. A non-zero exit would
have been caught by any exit-status check. This one returns a well-formed empty result that an
orchestrator reading only "did it come back?" would journal as clean — and the diff being small and
deliberately narrowed makes "nothing to find" feel plausible, which is precisely the hazard.

## 2026-09-21T03:55:00Z — #243 (docs) — HUMAN-DIRECTED substitute review (not `CODE_REVIEW`)

**The human directed this round after the bound gate failed twice.** It exists because they directed
it; the loop did not open it, and the engine does not license it on the dynamic branch.

**Journalled under its real identity.** This is a directly-spawned general-purpose reviewer, **not**
`CODE_REVIEW`, and the distinction is recorded rather than smoothed over — a later reader comparing
rounds must not see one verdict whose provenance differs from the others without being told. That is
the provenance defect this ledger already recorded once, when an unrunnable binding was replaced by
inline composition. It is **not** a `- gate-fallback:` line either: that shape is for a *binding*
defect with a substitution the engine licenses, and Guardrails excludes it from the repeat check.
The `- gate-error:` above stands unretracted.

**Precondition repaired first.** Local `main` was stale at `48ebe38` (pre-squash), so `main...HEAD`
would have shown a merge-base diff re-proposing commit 1's already-merged content — the trap round 2
caught unprompted. Ran `git fetch origin main:main`; local `main` is now `bed92f7` and the delta is a
true **6 insertions / 4 deletions**.

**Brief given to the reviewer**, so the verdict can be read against what it was actually asked:

- Retrieve the diff itself and state what it retrieved before answering. None of my conclusions.
- **The central question is inverted from a normal review:** the row was deliberately *shrunk* across
  two prior rounds, so the question is whether it now claims exactly what the evidence supports.
  **Under-claiming is named as a defect too** — a reference row that refuses to say anything useful
  has failed differently, and a reviewer told only "check for over-claims" would ratify that.
- All five of #243's acceptance criteria verbatim, **plus both recorded amendments**, plus the fact
  that AC-1 and part of AC-4 were satisfied by `bed92f7` and not by this diff — so it judges the file
  as it stands and can report a defect in the merged state.
- Verify every figure against the artifact **including the arithmetic relationships**, every
  `file:line` citation against `scan.py`, every anchor against the headings.
- Four specific suspicions, including the one the narrowing could have broken: does anything removed
  leave a reader worse off?
- "If you cannot verify something, say so — that is a dirty result, not a clean one. Do not hedge
  your way to a pass."

PR #249 stays held until this returns.

## 2026-09-21T04:20:00Z — #243 (docs) — substitute review returned DIRTY BOTH WAYS; fixed in 4da01da

**4 medium, 5 low, 4 notes.** Every load-bearing finding verified by me against the files before
acting on it — a subagent's findings carry its evidence, its recommendations do not.

**The direction flipped, and that is the signal.** Rounds 1-2 found over-claiming. Round 3 found
**under**-claiming in three places, plus one **new** over-claim authored in the very sentence that
was fixing the old one.

- **M1 (new over-claim).** "The scanner reads values for only three whitelisted fields" is wrong on
  both axes. `scan.py:104`: "The ONLY **message fields** whose *values* may be **emitted**" — emitted
  not read, message fields not all keys. Four whitelists exist, not one (`:111`, `:147`, `:165`,
  `:212`), and the artifact carries values from them (`Agent`, `Edit`, `json`, `pdf`, `txt`, `mcp`,
  `toolu`). Verified directly.
- **M2/M3/M4 (under-claims).** Dropped: the counter name that **amended AC-3 explicitly required**;
  the `tool_result` linkage that three other surfaces still assert, including this file's own inbound
  cross-reference; and the v2.1.193 CHANGELOG anchor (format-watch F-025), the only evidence for the
  denial reading from outside the key name. All three restored.

### Root cause, finally legible after four rounds

**Every one of these was a PARAPHRASE of what the scanner does.** `scan.py:17` already carries a
`SECURITY CONTRACT` docstring stating it authoritatively. Four rounds re-derived it in prose and got
it wrong four different ways. `4da01da` stops paraphrasing and cites it, then states only the one
fact the figures rest on. That is a structural fix, not another hedge.

### My own verification tooling had a false clean

The anchor check I ran and reported all session was wrong on **both** sides, and the errors cancelled:

- the regex `\]\(#([a-z0-9-]+)\)` **silently skipped** `#tool_use` and `#tool_result` (no `_` in the class);
- the heading slugger stripped `_` with the backticks, so `` ### `tool_use` `` became `tooluse`.

The two anchors the regex dropped were exactly the two the slugger would have failed on. Output:
a confident `unresolved: none`. Corrected script: **42 occurrences, 23 distinct, all resolve, no
duplicate slugs**, identical on `main`. The doc was always fine; the check was worthless.

**This is the session's own defect class, committed by the instrument built to detect it** — the same
shape as #237's vacuous sentinel fixture and #242's `persist_anchored_tags` gate, one layer up. The
PR body's "all 21 internal anchors resolve" was corrected to 23 rather than quietly amended.

### Status

- `4da01da` pushed; **CI green 6/6** on PR #249, required `sanitizer-ci` included.
- Row stays `blocked` with `gate-error: code-review` — the bound gate is still broken; this round was
  a **human-directed substitute** and does not retract that.
- **Acceptance gate (step 10) has still never run** on any commit of this issue.
- **Not merged.** Held for the human.
- Post corrections recorded on **#247** (line 70's superseded "upper bound", line 68's unsourced
  `is_error: true`), where the branch is already open and the 2026-09-24 build date applies.

## 2026-09-21T04:20:00Z — #243 (docs) — acceptance gate opened (step 10)

Human directed: continue to the acceptance gate. Row advanced `blocked` → `in-acceptance`. The
`gate-error: code-review` stays in the record unretracted — step 10 running does not repair step 8.

### Base resolution — an orchestrator deviation, recorded as such

The engine's literal command is `BASE=$(git merge-base main HEAD)`. Run here it returns **`bed92f7`**,
which is the squash of PR #246 — **this issue's own first commit**, already on `main` because of the
partial merge. Diffing from there would show the verifier 6 insertions / 4 deletions and hide the
`hookAdditionalContext` correction entirely, so AC-1 would read not-met against work that is already
shipped.

Base set instead to **`48ebe38`** — the last commit before any #243 work. Checks run before choosing it:

- `48ebe38` is an ancestor of both `HEAD` and `origin/main`;
- `git diff 48ebe38 --stat` touches **only** `reference/data-dictionary.md` (10 insertions, 3
  deletions), so the wider base pulls in no unrelated edit;
- everything in `48ebe38..HEAD` lands in `main` when #249 merges, so every `file:line` the verifier
  can cite is in the merge candidate — the engine's actual requirement behind the merge-base command.

The verifier was told this fact about its input and nothing about what the change does.

### Gate scope

- **Class A** (AC-satisfaction) — due, running. Fresh spawn; no prior gate agent re-contacted.
- **Class B** (mutation survivors) — **not due**: `mutation-survivors=n/a: docs route`. Question 1 of
  the three-question scope test answers no at the Route.
- Working tree clean, `git worktree list` shows one entry (no stray isolated copy),
  `git ls-files --others --exclude-standard` empty.

## 2026-09-21T04:35:00Z — #243 (docs) — acceptance gate round 1: DONE (Class A 5/5)

- **AC-verify: Class A 5/5 acceptance criteria met** (3 unamended as written, 2 against the plan-gate
  amendments). Class B: `mutation-survivors=n/a: docs route`.
- Verifier ran its own commands against base `48ebe38`: 1 file, 10 insertions, 3 deletions, no
  untracked files, nothing unrelated in the diff.
- **Every figure re-derived independently from the artifact.** All 13 match, including the six
  separate `3964` counters checked one at a time, and `sum(versions.values())` = 350,954 confirming
  the corrected denominator. No numerator paired with a differently-weighted denominator.
- It read `scan.py:17-56` itself and checked the `stopReason` trap that `:280`'s "none of the keys
  counted below has its value read" could have fallen into: `EMITTABLE_VALUE_FIELDS` contains
  `stop_reason`, but the scanner reads `message.stop_reason` on `assistant` lines (`scan.py:521`)
  only. The hook table's top-level camelCase `stopReason` is a different key and is never read. The
  sentence is true as scoped.
- **No under-claims found.** The three restored in `4da01da` all check out, including F-025's
  v2.1.193 CHANGELOG quote against `.claude/specs/research/jsonl-format-watch.md:449-459`.

### Two residual over-claims — NOT Class A findings, and recorded as such

Both are below the AC bar (no criterion depends on either) so the gate returned done. Both are the
defect class this issue exists to remove, which is why they are written down rather than dropped:

1. **`:147` sentence 1** asserts `toolDenialKind` appears "on `user` lines that **also carry a
   `tool_result` block**" flatly. `tool_result_line_keys.toolDenialKind` = 227 is a **sum of blocks
   over those lines**, so it establishes a mean of exactly 1, not that every line has one — by the
   amendment's own `225x1 + 1x0 + 1x2` argument. The row then hedges the same linkage two sentences
   later, so it disagrees with itself.
2. **`:422`** asserts "**A denial is *also* marked at the top level**" flatly, while `:147` calls the
   denial reading "likely, not verified". This is the identical sentence shape the PR body claims to
   have removed from the lead-in; it survived at the cross-reference.

### PR body corrected (not the merge candidate — re-arms nothing)

The verifier caught the body describing a head it no longer has. "What moved out of the doc and into
this PR" still listed the block-weighted caveat and "exact rather than a ceiling" as removed; both
were **restored by `4da01da`**. Marked superseded in place. Also `Em-dashes in added prose: 12 to 3`
was never re-measured after round 3 — the real figure is 8 on added lines, 6 newly authored.

### Gate ledger

- `gate-rounds=ac-verify=1` · `ac-findings=0` (Class A) · `mutation-survivors=n/a: docs route`
- Round 2 of this gate's 2-round cap is **unspent**.
- Held at step 11. `gate-error: code-review` still stands; step 10 passing does not repair step 8.

## 2026-09-21T04:50:00Z — #243 (docs) — acceptance gate round 2 (human-directed)

Human directed: make the two minor doc fixes, then round 2. Round 1 returned **done**, so neither
fix was mandated by a Class A finding — but both changed the merge candidate, and a verdict is bound
to the commit it ran on, so the round-1 certification no longer reaches HEAD. Round 2 is the gate's
**last** round under the 2-round cap; a dirty result escalates rather than iterating.

### `338bb57` — the two fixes

- **`:147`** dropped "on `user` lines that **also carry a `tool_result` block**" from the opening
  clause and replaced the hedge downstream with the identity the counter actually pins:
  `tool_result_line_keys` sums **blocks over the lines carrying the key**, so 227 fixes the mean at
  exactly one, not one apiece. The row now says "227 `tool_result` blocks across those same 227
  lines, an average of one apiece that is consistent with, but does not establish, one apiece
  exactly." **Strictly more informative than the claim it replaces** — this is not a narrowing.
- **`:422`** replaced "**A denial is *also* marked at the top level**" with "**Some `user` lines
  carrying this block also carry a top-level `toolDenialKind` key**". The cross-reference was
  asserting the denial semantics that the row it points at calls name-inferred and unverified. Same
  sentence shape this branch already removed from the lead-in; it had survived at the pointer.

Staged by explicit path; `git diff --cached` read before committing: 2 insertions, 2 deletions, no
stray file. No mutation copy exists to remove (`docs` route, so Part 2 never ran); `git worktree
list` shows one entry.

### Sourceless, so nothing downstream is re-armed

Step 10's rule: a fix that changes **no** source (a citation, a doc line) re-arms neither step 8 nor
step 9 and needs no escalation on that ground. This repo's whole deliverable here is a doc line, so
the distinction is worth stating explicitly rather than assumed: nothing executable moved,
`git diff --cached` touched `reference/` only, and no test exists to re-arm step 6's hermetic
trigger. The merge gate remains the human's for the ordinary reasons (`mode: calibration`, plus the
unretracted `gate-error: code-review`).

### Round 2 brief

Same five criteria, same two amendments, same base `48ebe38`, fresh spawn — **not** the round-1
agent re-contacted and not the author of the fix (Fresh-re-check invariant). One addition to the
brief: it is asked to derive for itself, from `scan.py`, what `tool_result_line_keys` does and does
not establish, and to judge under-claiming with the same weight as over-claiming. It was told
nothing about what round 1 found or what changed since.

Anchors re-checked after the edit: 42 occurrences, 23 distinct, all resolve, no duplicate slugs.

## 2026-09-21T05:05:00Z — #243 (docs) — acceptance gate round 2: DONE. Held at the merge gate.

- **AC-verify: Class A 5/5 on `338bb57`** (3 unamended, 2 against the plan-gate amendments).
  `ac-findings=0`. `mutation-survivors=n/a: docs route`.
- **No over-claim and no under-claim in the changed prose.** Round 2 was briefed to weigh the two
  equally and to derive `tool_result_line_keys`'s meaning from `scan.py` itself rather than from any
  citation. It confirmed the restored sentence is "precisely the strongest true statement" — the
  first time in five rounds that both directions came back clean.
- It re-derived all 11 figure families independently, re-checked both banner lines as absent from the
  diff, and confirmed `top_level_keys.version` = 350,954 counts key **presence**, which is what makes
  "85,056 lines carrying no `version` key at all" exact rather than arithmetic.
- It also caught a `stop_reason` trap on its own: `EMITTABLE_VALUE_FIELDS` contains `stop_reason`,
  but that is `message.stop_reason` on `assistant` lines (`scan.py:521`); the hook table's top-level
  camelCase `stopReason` is a different key and is never read. `:280` is true as scoped.
- **CI green 6/6 on `338bb57`**, required `sanitizer-ci` SUCCESS. PR #249 `OPEN / MERGEABLE / CLEAN`.

### One deviation, ruled rather than left open

Both rounds flagged that amended AC-3 said the block-weighted caveat "moves out of the doc row and
into the PR body", and it now sits in **both**. That placement instruction was **superseded by the
human's round-3 ruling** ("stop paraphrasing, restore 3 clauses"), one of which was the `tool_result`
linkage. The amendment's substance — exact count, named counter, value vocabulary unobserved — is
fully met, and both verifiers independently judged the restored sentence accurate. Recorded as a
superseded instruction, not an open gap. The human can overrule.

### Third instance of the `:278` defect class, filed not fixed

Round 2 found `:292` ("These lines are **frequently accompanied** by a top-level `toolUseID`
**linking the hook run to the tool call that triggered it**"). Two claims the scan cannot reach: the
per-line accompaniment (`keys_by_type.system.toolUseID` = 3,964 = the family count, no cross-key
join) and the linkage semantics (`toolUseID` is on none of the four emit whitelists, so no value was
read; it also appears on 2,747 `progress` lines, which the sentence omits). Verified against the
artifact and **posted to #248** with a suggested AC, because #248's AC-4 asks for the discipline
claim to be stated once and that only works if the enumeration is complete. Confirmed pre-existing:
absent from every added and removed line of `git diff 48ebe38`.

### Gate ledger — final for this issue

- `gate-rounds=architect=1,code-review=gate-error(+1 human-directed substitute),ac-verify=2`
- `ac-findings=0` · `mutation-survivors=n/a: docs route` · `post-gate-survivors=0`
- **Held at step 11.** The merge gate escalates for two standing reasons: `mode: calibration` with no
  graduated routes, and the **unretracted `gate-error: code-review`**. Step 10 passing twice does not
  repair step 8. Both acceptance-gate fixes were sourceless (doc lines), so neither re-armed step 8
  or step 9 on its own account.
- **Not merged.** Awaiting the human.

## 2026-09-21T08:07:26Z — #243 (docs) — MERGED as `a1e25d3`. Iteration complete.

Human merged at the gate. Squash-merged via `gh pr merge --squash --delete-branch`.

### The #246 check, run this time

The partial merge earlier in this run happened because the PR head at merge time was not the head the
gates had certified, and nothing checked. So before merging:

- PR head `338bb571d581c9ddb57d5d00296a3b64f6a7cddd` compared character-for-character against the
  commit the acceptance gate certified. Identical.
- `origin/fix/243-narrow-tooldenialkind-row` == local `HEAD` == PR head. No unpushed commit, no
  33-second window.
- Working tree clean. All 6 checks SUCCESS, required `sanitizer-ci` included.

And **after** merging, the check that would have caught #246 within a minute:

```
git diff 338bb57 origin/main -- reference/data-dictionary.md   ->   EMPTY
```

The squash captured the whole certified tree. This belongs in the run's standing procedure, not just
in this row — a squash is silent about what it dropped, and the only cheap proof is diffing the
merged result against the certified head.

### Final state

- `a1e25d3` on `main`. Issue **#243 CLOSED** at 08:07:27Z by `Closes #243` in the squash body.
- PR #249 MERGED; its branch auto-deleted.
- **`fix/243-hook-rows-data-dictionary` deleted** (local + remote, was `786bd06`). Checked first that
  it held nothing `main` lacks: its only file is `reference/data-dictionary.md` and the delta is the
  superseded round-1 wording, not orphaned work.

### Gate ledger — closed

- `gate-rounds=architect=1,code-review=gate-error(+1 human-directed substitute),ac-verify=2`
- `ac-findings=0` · `mutation-survivors=n/a: docs route` · `post-gate-survivors=0`
- `subagent-runs=~14` · PRs=2 (one partially merged, one superseding)

### What this row cost, and why

Two PRs, five review rounds, four of them finding the same defect class. The root cause was legible
only at round 4: **every finding was a paraphrase of what the scanner does**, re-derived in prose
each time instead of citing `scan.py:17`'s `SECURITY CONTRACT`. A two-row doc edit consumed an entire
iteration because the thing being documented was the documentation tool's own discipline claim, and
nothing mechanically checks that claim (**#238** — `tooling/format-scan/` runs in no CI workflow).

### Open, downstream of this row

- **#248** — three pre-existing sites making claims the scanner cannot support (`:263`, `:278`,
  `:292`). `:292` was found by this row's acceptance gate and posted with figures.
- **#247** — Part 6 `:70` says "227 is an upper bound" and now contradicts `main`. Build date
  **2026-09-24**; the human holds that branch.
- **#244** — folds the values, removes the "type not inspected" qualifier. Assigned to the separate
  `format-scan` run, not this one.
- **`gate-error: code-review` stands unretracted** for the run. The binding failed twice and was never
  observed working again in this session. Next iteration should expect it and escalate on first
  failure rather than retrying.
