# Plan: #190 — dict keys are never transformed

**Route:** code  **Branch:** `fix/190-nested-key-coverage-and-prd`  _(fork `(e)`; the old `scrub-dict-keys` name described `(b′)`, now #208)_

## Value framing (route-scaled — `fix:`)

**Who hits it, how often, what breaks without the fix.**

Two distinct populations, and the issue + the "Rescoped under #195" comments describe only the
first. The second is the reason this is not a usability-only ticket.

**(1) Literal-rule configs — a usability cliff, no leak.** Since #195 merged (`91adca1`), a
`paths`/`identifiers` rule with a **literal** `match` whose value appears as a JSON dict key is
caught by the output-side oracle: the run aborts at exit 2 and writes nothing. Safe, but the file
is now **unsanitizable** — there is no override, so the user cannot publish that session at all.
This is the population the existing comments describe.

**(2) Regex-rule configs — the original silent leak, still live on `main` today.** A rule with a
`re:` `match` is deliberately **not** re-verified by the oracle (`residual.py:189-206`: "presence
in the output is a leak" holds for a literal and not for a shape; regex re-verification is #198).
Dict keys are also never scrubbed by the walk. So for a regex rule the two layers miss the same
position and the original defect is unchanged: **exit 0, value present in the written output,
sidecar reporting `substitutions: []` and `residual_scan: clean`.**

Neither issue, neither "Rescoped" comment, nor the CHANGELOG records (2). They all state the
remaining work is "making a value in a dict key **scrubbable** rather than merely refused," which
is true only for literal rules.

**This matters for what fixes it.** #198 (regex oracle) would only make (2) fail *closed*. The
traversal fix in this issue is the only change that makes either population's file actually
publishable, and the only current remedy for (2)'s silent leak.

### Falsifier — and it was discharged by running, not by asserting

> *What single observation would show this is misdirected?* — "No real session shape puts a
> configured match value in a dict key, and no supported config reaches the key position."

**Not falsified. Both halves were checked against the merged `main` (`91adca1`):**

- **Real shape exists, and it is the format's highest-risk field.**
  `file-history-snapshot.snapshot.trackedFileBackups` is keyed by absolute path
  (PRD §4 table: "Highest-risk field in the format"; `reference/data-dictionary.md:360`). The
  golden input fixture already carries one — key `/home/goldenuser/projects/demo/notes.env`. It is
  not live exposure only because D-7 drops those lines wholesale, which the issue body itself
  argues the sanitizer must not depend on ("The sanitizer should not depend on D-7 continuing to
  cover a case D-7 was not written to cover").
- **Both config families reach the key position — probed, with a positive control.** Input
  `{"type":"user","toolUseResult":{"/home/probeuser/notes.md":{"size":42}}}`:

  | Rule | Result |
  |---|---|
  | literal `match: "/home/probeuser"` | **exit 2**, `residual rule scan matched paths[0]; output was not written` |
  | regex `match: "re:/home/probe\w+"` | **exit 0**, output written, `/home/probeuser/notes.md` **present**, sidecar `residual_scan: clean` |
  | regex, same value in a **string value** (control) | **exit 0**, output `/home/user/notes.md` — correctly redacted |

  The control is what makes the middle row a finding rather than a broken probe: the same rule
  redacts the same value one position over.

**Prevalence, stated honestly — this is not the default path.** The shipped config template
(`_templates/ccs-sanitize.example.yaml`) contains **zero** `re:` rules; all four examples are
literals. So (2) requires a user to have hand-authored a regex rule. That is a documented and
PRD-encouraged pattern — PRD §7's own worked example is
`match: "re:-home-fdpearce-([a-z0-9-]+)"` for the project slug — but it is opt-in, and a
template-only user is in population (1), not (2).

### Source-fidelity note

The rationale leans on the architect review posted to #190/#194 on 2026-08-21 and on the
"Rescoped under #195" comments. **Locus and evidence base check out** — both were written against
this codebase with verified repros. **Current relevance is where they have drifted:** they predate
#195's merge and describe the remaining work as usability-only, which the probe above contradicts
for regex configs. Treated as sound on mechanism, stale on consequence.

## Acceptance criteria (as amended at the plan gate, 2026-08-24)

#190 has no `## Acceptance criteria` heading; the original set was taken from its **Test plan** plus
the constraints its **Notes** and the "Rescoped under #195" comment impose. **The human selected
fork `(e)` detect-only at the plan gate**, which *reduces* that set. Per the engine's rule that a
reduction is an issue amendment and never a gate interpretation, the narrowing is
[recorded on #190](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/190#issuecomment-5389748039)
and the removed scope is filed as **#208**. The acceptance gate judges against the narrowed set
below.

### Delivered by #190 under `(e)`

- [ ] **AC-1** Unit: **nested** key placement (a key inside another key's value) aborts rather than
      writing. The genuine gap — every current key-position test plants the key exactly one level
      deep (`toolUseResult.<key>`), and the nearest nested test
      (`test_residual_rules.py:354` `test_nested_value_under_tool_input_is_redacted`) plants a
      nested *value*, which is #194's shape.
- [ ] **AC-2** The four `13-dict-key-not-value` `KNOWN_DEVIATIONS` entries
      (`test_adversarial_placement.py:136-171`) become explicit **FAIL-CLOSED assertions** rather
      than xfail-because-not-REDACTED, so the matrix asserts the behavior the tool actually has.
- [ ] **AC-3** **PRD §6b Step B** amended — it specifies the walk applies rules "to every
      **string-valued leaf**", which is true but misleading without stating that the key position is
      covered by the output-side oracle instead of the walk.
- [ ] **AC-4** Recorded: publishability is deliberately not delivered here (#208), and #198 is what
      closes the regex population.
- [ ] **AC-5** Regression: the existing suite stays green with no byte changes to current fixtures.
      Byte-neutral **by construction** under `(e)` — test-and-docs only, no pipeline source touched.
- [ ] **AC-6** No further version bump. `__version__` is already 0.4.0 (unreleased, bumped by #195);
      `(e)` alters no produced output, so the determinism contract is not re-engaged.

### Moved to #208, NOT read down

- ~~Cell `13-dict-key-not-value` moves to **REDACTED** for all four payload families~~ — superseded
  twice: #195 already moved these to fail-closed, and the further move to REDACTED is #208's.
- ~~"Scrubbable without corrupting document shape"~~ — `(e)` makes no traversal change at all.
- ~~A key-position value is made scrubbable so the file is publishable~~ — #208.

### Already satisfied by #195, verified by reading the tests rather than assumed

| Original AC | Covering test | Status |
|---|---|---|
| key placement aborts | `test_residual_rules.py:273` `test_value_in_a_dict_key_aborts_rather_than_writing` | **covered** (exact shape) |
| leaf still redacts, no self-trip | `test_residual_rules.py:483` `test_ordinary_leaf_still_scrubs_and_does_not_abort` | **covered** (exact shape) |
| cell 13 fails closed | `test_adversarial_placement.py:136-171`, four strict xfails | **covered** as an abort assertion; AC-2 above converts it |

## Approach

> **Refresh provenance (2026-08-24, pre-architect).** The frozen pre-image below was written
> against `91adca1` (#195 merged, #194 not). #194 has since merged as `b8c2b0c` and **changed the
> mechanism this issue has to extend**. Everything in this section marked **[re-verified]** or
> **[new post-#194]** is my own pre-architect update from re-running the probes against
> `685eede` / `__version__` 0.4.0 — **not** an architect redirect. The step-5 diff will read
> material on it; that is the anticipated over-stop, not a design gate that fired.

**Goal.** Make a rule-matching dict key **scrubbable**, so a session carrying one is publishable
again (population 1) and does not silently leak under a regex rule (population 2) — without
corrupting document shape and without silently losing records.

### Both populations re-verified on current `main` [re-verified]

Probed at `685eede`, library API (`sanitize_session`), synthetic values only:

| Config | Key placement, 1 deep | Key-in-key (nested) | Same value as a string value (control) |
|---|---|---|---|
| literal `match: "/home/probeuser"` | **abort** `ResidualRuleError: matched paths[0]` | **abort**, same | exit 0, redacted to `/home/user` |
| regex `match: "re:/home/probe[a-z]+"` | **exit 0, value present in output** | **exit 0, value present** | exit 0, redacted to `/home/user` |

The control is what makes the regex rows findings rather than a broken probe: the same rule
redacts the same value one position over. **Population 2 — the silent leak — is live on `main`
today**, unchanged by #194.

**One AC correction falls out of this [re-verified].** AC-3 (nested key placement aborts) is
already satisfied *behaviorally* for literal rules — the nested probe aborts. It remains a genuine
**test-coverage** gap (no test plants a key inside another key's value), which is what this issue
still owes on that criterion. The plan previously read this as a behavior gap.

### The hazard that constrains every option — re-verified, not predicted [re-verified]

Naive "transform keys the same way as values" **silently destroys records**. Re-run against the
real transform contract on `685eede`:

```
in : {"toolUseResult": {"/home/probealice/x.md": {"size": 1}, "/home/probebob/x.md": {"size": 2}}}
out: {"toolUseResult": {"/home/user/x.md": {"size": 2}}}
entries before: 2   after: 1
```

Two keys collapse onto one placeholder; the **first entry is gone** and the last writer wins. No
exception, no warning, no sidecar record. On a tool whose contract is that the sidecar must never
overstate what happened, a silent record deletion is a severe failure mode — arguably worse than
the leak, because the oracle catches the leak and nothing catches this.

**So any key-scrubbing design needs a collision check that fails closed**, in the same spirit as
the residual oracle: if scrubbing keys would merge two distinct keys in one object, abort rather
than write. That constraint is the main thing to put to the architect.

### What #194 changed, and why it reshapes the options [new post-#194]

#194 replaced the bare-name skip-list with `_FORMAT_PATHS` — a **root-anchored allow-list of
format-owned paths** (`_PRESERVE_PATHS | _IDENTIFIER_PATHS | _ENUM_PATHS`, plus `_UUID_PATHS`
unless `remap_uuids`). `make_skip_predicate` matches the **whole rooted path**, and
`pipeline.py`'s own docstring states the resulting polarity: **"An unlisted path is now visited and
scrubbed."**

That polarity is the opposite of the frozen plan's leaning. Option (b) below enumerates
**data** subtrees and exempts everything else — under-scrub by default — which is the same
inverse-enumeration shape #194's correction discarded, and its failure direction is population
2's silent leak rather than an abort. It should be demoted, and a new option stated in the
polarity the codebase now has.

### Options, and the fork the architect sent back to the human

**The architect ran on 2026-08-24 and materially redirected this plan.** The frozen pre-image
leans (b) and treats "transform keys" as settled, routing only sub-questions to review. The
architect's top-line ruling is that **the load-bearing choice is (e) detect-only vs (b′) transform,
and it is closer than the plan framed it** — because *the safety hole is not owned by the
traversal*. Every ruling below is recorded with adopt/adapt/decline and a rationale.

- **(a) Transform all keys everywhere, no exemptions.** Rejected — the collision result above,
  plus the standing objection that keys carry structural meaning. Architect concurred.
- **(b) Transform keys only under subtrees known to be *data*.** Demoted — enumerate-the-safe-set,
  and incompleteness under-scrubs, which is population 2's silent leak. Architect concurred:
  this is "the enumerate-an-unbounded-space failure #194 discarded for values."
- **(c) Inverse skip-list on key *names*.** Rejected. Architect concurred.
- **(d) Operator override to bypass the abort.** Rejected. Not contested.
- **(b′) Visit keys, exempt only format-owned positions.** Still the transform option, but
  **materially amended by Q1 — see below**. Polarity confirmed correct; the "reuse
  `make_skip_predicate` unchanged" formulation is **wrong** and has been struck.
- **(e) Detect-only: leave `walk_strings` alone; #198 closes population 2.** **Promoted from a
  named-for-completeness option to the architect's preferred path.**

### The architect's ruling on the fork — Q4, `important`, ADOPTED as a human decision

Verified independently before adopting: `_iter_decoded_strings` (`residual.py:144-163`) **yields
dict keys**, and its docstring says so in as many words — "Dict keys are yielded because they are
the whole of #190". `scan_residual_rules` skips regex rules at `residual.py:301`
(`if not rule.is_regex`).

So **literal-key safety is already total today**, and **regex-key safety is #198's to close, not
this issue's**. Both populations reach fail-closed with **no traversal change at all**. That is
what #190's own "Proposed fix — extend the residual scan, do not transform keys" argues.

| | (e) detect-only | (b′) transform keys |
|---|---|---|
| Population 1 (literal) | already fail-closed | fail-closed **and publishable** |
| Population 2 (regex) | fail-closed **once #198 lands** | scrubbed immediately |
| Collision hazard | **none — never transforms a key** | **mandatory inline check** (Q2, blocking) |
| Format-key over-scrub tail | none | present, must be documented (Q1) |
| Byte-neutrality | guaranteed | verified no-op on the golden fixture |
| What #190 still owns | AC-3 test coverage, cell-13 xfail flips, PRD note — a thin ticket | the full traversal change |

**The architect's net:** (e) is lower-risk and forward-compatible; (b′) buys **publishability**,
which for a dict-key-carrying real session is today **hypothetical** — the one known real shape,
`trackedFileBackups`, is D-7-stripped. Its recommended sequencing if safety is the priority:
**land #198 first as the urgent fail-closed fix, then decide (b′) for publishability at leisure.**

It also noted the tool already has an accepted unpublishable-input class of this flavor — a literal
rule whose match value equals a format-marker value aborts every session
(`test_format_markers_are_still_skipped_at_their_real_positions`, `test_residual_rules.py:431`).

**This is a scope/product call, not a design call, so it goes to the human at the plan gate.**
It is not mine to settle, and the frozen plan pre-resolved it toward transforming keys.

### Architect rulings to apply if the human picks (b′)

1. **Q2 `blocking` — the collision check is inline and cannot be delegated to the oracle. ADOPTED.**
   The sharpest finding in the review, and it corrects a real gap in the frozen plan's step 2. When
   two keys collapse onto one placeholder, **the output contains only the placeholder — both
   originals are gone — so `scan_residual_rules` scans clean. The collision deletes its own
   evidence.** It must be detected at the point of dict rebuild (`pipeline.py:434-435`), where both
   source keys are still visible. Abort at exit 2, detected per-object, failing the whole run. A
   sidecar-recorded partial refusal is wrong twice over: the unscrubbed key *is* the leak, and a
   sidecar on a file you refused to fully scrub is the rubber-stamp failure PRD §5/§10 exist to
   prevent. Diagnostic names the object's rooted path only, never the key value (D-2), mirroring
   `ResidualRuleError` (`residual.py:114-142`).
2. **Q1 `important` — the polarity is right, "reuse the predicate unchanged" is not. ADOPTED.**
   `_FORMAT_PATHS` (`pipeline.py:308-310`) allow-lists positions whose **values** are format-owned.
   It is **not** a list of format-owned **key names**. `cwd`, `gitBranch`, `stdout`, `stderr`,
   `command`, `description`, `message`, `content`, `toolUseResult`, `timestamp` are all
   format-owned *keys* deliberately absent from it because their *values* are scrubbable. So b′
   would **visit those keys**. For a value, over-scrub corrupts a field but preserves shape; **for
   a key, over-scrub renames a structural key** — the one failure #190's body calls "the wrong
   repair". The calculus is **not symmetric between keys and values**, and the frozen plan imported
   that symmetry silently.
   **Adopted resolution: ship b′ with the residual documented and bounded** (the architect's
   option 1), not a separate key-exemption set (its option 2) — that would add a second enumeration
   surface for #201 to have to cover, trading a near-zero-probability corruption tail for real
   machinery. Reachability is low: path/identifier rules are path- and email/name-shaped and do not
   match short tokens like `cwd`; it takes a pathological rule (`re:[a-z]+`) to bite. **The
   collision check does NOT cover this** — renaming a unique format key collides with nothing and
   so would rename silently.
   **Also adopted:** under `remap_uuids: true` the UUID paths are lifted from `allowed`
   (`pipeline.py:392`) to remap the UUID *value*; b′ would apply that lift to the **key** too,
   un-exempting the literal key names `uuid`/`sessionId`/`agentId`/`parentUuid`. A no-op in
   practice (the transform only matches UUID-shaped strings), but it is the same conflation and
   gets a one-line acknowledgment in the code.
3. **Q3 `suggestion` — no D-2/§10 violation; key-position marker optional. ADOPTED as "no marker".**
   The subtable records *replacements* and counts, never originals, so a scrubbed key produces an
   ordinary non-sensitive entry. No consumer contract needs key- and value-substitutions
   distinguished (D-4: the fixture-validator re-derives independently). Cheap to add, nothing
   breaks without it — so it is not in scope.
4. **Q5 `important to document` — no join contract broken; document the tail. ADOPTED.**
   The keys consumers join on are format keys, which b′ exempts; the keys b′ actually scrubs are
   tool-defined data keys under `toolUseResult` / `tool_use.input` / `tool_result.content`, which
   no documented contract joins on. `reference/data-dictionary.md:239` already tells parsers to
   read keys defensively, and `trackedFileBackups` is D-7-stripped. Add a one-line note that
   sanitized fixtures may carry scrubbed tool-side keys.
5. **Q6 `optional` — existing 0.4.0 bump suffices; byte-neutrality independently confirmed. ADOPTED.**
   The architect checked the golden fixture rather than taking the prediction on faith: the only
   rule-matching key sits on line 4, a `file-history-snapshot` line dropped by
   `DEFAULT_STRIP_TYPES` (`pipeline.py:65`); surviving lines carry no rule-matching keys. No-op on
   both golden variants.
6. **Q6 gap (a) — do keys run the *composed* transform, including secrets? ADOPTED as a decision
   the plan must make explicitly.** `KNOWN_DEVIATIONS` also carries a **secret** entry for cell 13
   (`test_adversarial_placement.py:164-171`), fail-closed today via the secret oracle. If keys run
   the composed chain, secret-in-key flips to REDACTED and that xfail must be removed too — the
   strict xfail will go red and force it. If keys run path/identifier only, it stays fail-closed.
   The frozen plan's step 5 flipped only the three PII cells and under-specified this.
7. **Q6 gap (b) — AC-3 nested-key coverage genuinely missing. ADOPTED, already independently
   confirmed** above, and the plan's three stale test citations have been corrected in the AC table.

### Steps — fork RESOLVED to `(e)` by the human at the plan gate, 2026-08-24

**Decision:** `(e)` detect-only. The removed scope is filed as **#208**, the narrowing is recorded
on #190, and **#198 + #201-#203 were pulled into the queue** in the same ruling. The `(b′)` branch
below is retained only as the record of what #208 inherits — it is **not** this issue's plan.

**THE LIVE PLAN — (e) detect-only.** A thin ticket; #190 is largely already fixed by #195:
1. Add the missing **AC-3 nested-key** test coverage in the abort direction.
2. Convert the four `13-dict-key-not-value` `KNOWN_DEVIATIONS` entries into explicit FAIL-CLOSED
   assertions rather than xfail-because-not-REDACTED.
3. Amend **PRD §6b Step B** ("to every **string-valued leaf**") to state the key position is
   covered by the oracle rather than the walk.
4. Record that publishability is deliberately not delivered, and that #198 is what closes
   population 2.

**NOT THIS ISSUE — (b′), retained as the record #208 inherits.** The frozen plan's steps, amended by rulings 1, 2, 6:
1. Extend `walk_strings` to visit dict keys under a caller-supplied policy, defaulting to today's
   behavior so no other caller moves. **Do not reuse `make_skip_predicate` as though it exempted
   key names** (ruling 2); document the format-key residual.
2. Add the **inline** collision check at the dict-rebuild site; fail closed on a merge, exit 2,
   naming the object path and never the key value (ruling 1).
3. Amend **PRD §6b Step B**.
4. Decide and document whether keys run the composed chain or path/identifier only (ruling 6),
   then update the cell-13 **secret** deviation to match.
5. Tests: **AC-3 nested-key** in both directions; the collision case; a **regex-rule key** case
   (population 2 — the placement matrix has no regex payload family, verified); byte-neutrality on
   the golden suite.
6. Flip the `13-dict-key-not-value` xfails and delete the corresponding `KNOWN_DEVIATIONS` entries.
7. CHANGELOG under the existing unreleased **0.4.0** heading — no further bump needed (ruling 5).
   **Sequence #198 onto the same release train** (architect's forward-compatibility note): shipping
   b′ without it leaves regex keys backed by traversal completeness alone.

**Under either fork, #194 has now merged, so #190 is the last gate on the held 0.4.0 PyPI publish.**

## Approach as reviewed (frozen before the design gate) — write-once, do not edit

> **Provenance note (added alongside the block, not an edit to it).** No architect pass has
> run on this issue — not at step 4, not at step 5, and not as an inline substitute. This
> block was frozen in anticipation of a step-4 consultation that the plan-gate stop
> pre-empted. It is a genuine pre-image (taken before any consultation), so it is left in
> place per the write-once rule. Expect the step-5 diff to read *material* when #190 is
> worked: the human's 2026-08-22 sequencing ruling and SCOPE_AGENT's allow-list scoping
> both post-date it, so part of that diff will be non-architect change. Over-stopping is
> the fail-safe direction; do not read it as the architect having redirected the plan.

**Goal.** Make a rule-matching dict key **scrubbable**, so a session carrying one is publishable
again (population 1) and does not silently leak under a regex rule (population 2) — without
corrupting document shape and without silently losing records.

### The hazard that constrains every option — verified, not predicted

Naive "transform keys the same way as values" is not merely a shape change. It **silently destroys
records**. Run against the real `walk_strings` transform contract:

```
in : {"toolUseResult": {"/home/alice/x.md": {"size": 1}, "/home/bob/x.md": {"size": 2}}}
out: {"toolUseResult": {"/home/user/x.md": {"size": 2}}}
entries before: 2   after: 1
```

Two keys collapse onto one placeholder; the **first entry is gone** and the last writer wins. No
exception, no warning, no sidecar record. On a tool whose contract is that the sidecar must never
overstate what happened, a silent record deletion is a severe failure mode — arguably worse than
the leak, because the oracle catches the leak and nothing catches this.

**So any key-scrubbing design needs a collision check that fails closed**, in the same spirit as
the residual oracle: if scrubbing keys would merge two distinct keys in one object, abort rather
than write. That constraint is the main thing to put to the architect.

### Options, and my leaning

- **(a) Transform all keys everywhere.** Rejected — the collision result above, plus the
  architect's standing objection that keys carry structural meaning and downstream consumers join
  on them.
- **(b) Transform keys only under subtrees known to be *data*** (`toolUseResult`,
  `tool_use.input`, `tool_result.content`), leaving envelope structure untouched. This is the bar
  the "Rescoped under #195" comment sets. Its failure direction is the safe one for literals — an
  incomplete data-list under-scrubs and the oracle then aborts — but **under-scrubbing is a silent
  leak for regex rules**, which is population (2), so "fails closed" is not a complete defense here.
- **(c) Inverse skip-list on key names.** Rejected — same unbounded enumeration over
  tool-defined names that #194's correction already showed does not close the class.
- **(d) Leave traversal alone; add an operator override to let the abort be bypassed.** Rejected —
  it makes the file publishable by making it unsafe, and does nothing for population (2).

**Leaning: (b), plus a fail-closed collision check.** Put both to the architect; the data-subtree
list and whether the collision check aborts or is a sidecar-recorded refusal are its calls.

### Steps (provisional — the architect gate may redirect)

1. Extend `walk_strings` to visit dict keys under a caller-supplied policy, defaulting to
   today's behavior so no other caller moves.
2. Add the collision check; fail closed on a merge, exit 2, naming the object path and never the
   key value (D-2).
3. Amend **PRD §6b Step B**, which currently specifies the walk applies rules "to every
   **string-valued leaf**" — the sentence that encodes the behavior being changed.
4. Tests: the missing **AC-3 nested-key** case in both directions; the collision case; a
   regex-rule key case (population 2, currently untested — the placement matrix has no regex
   payload family); byte-neutrality on the golden suite.
5. Flip the four `13-dict-key-not-value` strict xfails in `test_adversarial_placement.py` from
   FAIL-CLOSED to REDACTED, and delete the `KNOWN_DEVIATIONS` entries.
6. CHANGELOG under the existing unreleased **0.4.0** heading. `__version__` is **already 0.4.0**
   (bumped by #195) and the PyPI publish is deliberately held for #190 + #194, so this rides that
   release rather than cutting a new one.

## Architect triggers hit

- **"Any change to the sanitizer's scrubbing behavior"** — this changes what the structural walk
  visits. Fires unambiguously.
- **"Anything that changes what a `.scrubbed` sidecar records"** — a scrubbed key produces a
  subtable entry whose "original" is a structural token; the issue flags this as a reason key
  rewriting may be wrong.
- **"The orchestrator is unsure"** — the mechanism (which keys are data vs structure) is exactly
  the open design question the architect review left unresolved.

## Risks / open questions for human

**1. THE DECISION — `(e)` detect-only vs `(b′)` transform keys. OPEN, and it is yours.** The
architect materially redirected the plan onto this fork and declined to settle it, because it turns
on whether **publishability** of a dict-key-carrying session is a real near-term need or a
hypothetical one. Safety is closed either way (by #195 + #198, not by the traversal). See the fork
table in `## Approach`. The architect's own lean is **(e), with #198 landed first**.

**2. PRD §6b Step B encodes the assumption being changed. OPEN under both forks.** It specifies the
walk applies rules "to every **string-valued leaf**". Under (b′) that becomes false; under (e) it
stays true but is misleading without a note that the key position is covered by the oracle. Amended
in the same change either way.

**3. The regex/dict-key silent leak (population 2) is unrecorded anywhere. RESOLVED — no longer a
risk.** #198's body records it by name: "for regex-matched PII the two traversal gaps #195 was
written to close — #190 (dict keys are never visited) and #194 ... — remain open." Checked
2026-08-24; the frozen plan predates that reading.

**4. Byte-neutrality is a prediction, not an assumption to ship on. RESOLVED.** The architect
verified it against `golden-session.jsonl` rather than reasoning about it: the only rule-matching
key is on line 4, a `file-history-snapshot` line dropped by `DEFAULT_STRIP_TYPES`
(`pipeline.py:65`), and no surviving line carries a rule-matching key. No-op on both golden
variants.

**5. One PR or two. RESOLVED by your 2026-08-22 ruling** — #194 first, on its own PR, ahead of
#190. #194 merged as `b8c2b0c` on 2026-08-23, so #190 is now a single standalone PR and the last
gate on the held 0.4.0 PyPI publish.

**6. Recording the architect review as an issue comment — awaiting your go-ahead.** This project
records architect decisions as comments on the issue (the 2026-08-21 reviews on #190/#194 are the
precedent). I have **not** posted it: the plan is unapproved and the comment is a public write on
your repo. Say the word and I will post it to #190; the review is recorded in this plan either way.

**7. `test_cli_smoke.py:45` silently skips when `ccs-sanitize` is not on `PATH`.** Baseline reads
499 passed + 1 skipped instead of 500 + 4 xfailed. Not caused by this issue and not in its scope,
but it is a declared check that quietly does not run — the shape this repo cares about. Flagging it
rather than filing unprompted.
