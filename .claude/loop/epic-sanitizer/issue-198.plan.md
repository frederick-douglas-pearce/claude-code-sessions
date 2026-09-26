# Plan: #198 — sanitizer: regex path/identifier rules get no output-side verification

**Route:** code  **Branch:** `fix/198-regex-output-side-oracle`

## Value framing (route-scaled — see step 3)

**Kind: `fix:`** (issue is labeled `bug`). One line, then the discharged falsifier.

**Who hits it / how often / what breaks.** An operator who hand-authors a `re:` rule in
`paths` or `identifiers` gets **no output-side verification at all** for that rule. For
regex-matched PII the two traversal gaps the oracle was built to close stay live as **silent
leaks with an affirmatively clean sidecar** — exit 0, output written, value present,
`residual_scan: clean`. That last part is what makes it more than a coverage gap: the
`.scrubbed` sidecar is the artifact the README asks a human to read before publishing, so the
review step that is supposed to catch this actively reports the file as clean. Reproduced on
merged `main` (`91adca1`) in the issue's own comment, with a positive control.

**Prevalence — the falsifier, and it was RUN at plan time rather than stated.**

- Falsifier: *"~0 real configs use `re:` rules, so this fixes nothing anyone hits."*
- Check 1 — the shipped template (`_templates/ccs-sanitize.example.yaml`): **5 rules, all
  literal, zero `re:`**. Verified by grep. This is the half that supports the falsifier: a
  default-config operator is not exposed.
- Check 2 — the PRD's own teaching material (§7, lines 441 and 464): **two worked `re:`
  examples**, `match: "re:-home-fdpearce-([a-z0-9-]+)"` (project slug) and a catch-all email
  regex. Verified by grep.
- **Verdict: falsifier NOT hit.** Reachability is opt-in, but regex rules are the pattern the
  project's own specification teaches, and the project-slug example is the maintainer's own
  shape. An operator who follows PRD §7 lands squarely in the unverified path. Stated honestly:
  this is a *documented-and-encouraged* opt-in, not a hypothetical one — but it **is** opt-in,
  and the plan should not oversell it as affecting every run.

**Source fidelity.** The rationale is internal (the issue, its comment, and #195's merged
code), not an external citation, so the source-fidelity check reduces to: does the code still
behave as the issue claims? Confirmed by reading `residual.py:300-321` — the rule tuple is
built with `if not rule.is_regex`, so regex rules are filtered out of the oracle entirely.

## Acceptance criteria (verbatim from issue)

- [ ] A decision recorded (design 1, design 2, or explicitly neither) for regex output-side
      verification.
- [ ] If implemented: zero-width guard and `finditer` semantics both covered by tests.
- [ ] The sidecar and PRD §10 wording updated to match whatever guarantee results — the current
      text is correct for literal-only and must not drift.
- [ ] `scan_residual`'s decoded/serialized blind spot either fixed or documented as a known limit.

### Suggested acceptance vectors (from the issue's comment — treated as AC-2 test material)

- A regex `paths` rule whose match appears as a **dict key** must abort, exactly as the literal
  form does today.
- The same regex rule against the same value in a **string leaf** must still redact — the
  positive control, which is what stops a brick implementation passing by aborting on everything.
- `test_adversarial_placement.py` has **no regex payload family**; its four payloads
  (`pii-home`, `pii-email`, `pii-name`, `secret`) are literals, so the existing matrix cannot
  observe this class in any cell.

## Approach

**Fork ruled by the architect (step 4): design 1, with a mandatory correction.** The ratified
name is **"skip-predicate-aware regex scan on the `remap_uuids=False` predicate."** Design 2
(`verify_output: true` per-rule opt-in) is rejected; a third option I asked the architect to
consider — verify regex but downgrade abort to a sidecar warning — is **rejected as fail-open**
and recorded here so it is not re-litigated: it would write the output with the value present,
re-creating the rubber-stamp risk PRD §5 exists to prevent, and it incurs the same
sidecar-shape change design 2 does while buying nothing.

**The correction, and why the plan as first written was unsound (architect F1, BLOCKING —
verified independently against the code before adoption).** My original step 4 said to pass the
orchestrator's own `skip_predicate` to the oracle, "so the oracle's notion of reach is the same
object the scrub used rather than a re-derived copy that could drift." That instinct is the
defect, not the safeguard:

- `pipeline.py:392` — `allowed = _FORMAT_PATHS if remap_uuids else _FORMAT_PATHS | _UUID_PATHS`.
  Under `remap_uuids: true` the UUID-graph paths are **dropped from the skip set**, so
  `("uuid",)`, `("parentUuid",)`, `("sessionId",)`, `("agentId",)` and
  `("toolUseResult","agentId")` are **reached**.
- `identifiers.py:225-248` — at those reached positions the identifier layer **mints** a value:
  `_remap_uuid` returns `str(uuid.UUID(bytes=sha256(seed + b"\x00" + original)[:16]))`, a
  canonical 36-char dash-formatted UUID.
- I-3 (`config.py` `_check_replacement_leak`) vets only the **literal** `replace` template plus
  the fixed gitBranch and `<REDACTED:kind>` placeholders. It never sees a runtime
  `match.expand()` / `_remap_uuid` value.

So under design 1 as first written, a UUID-shaped `re:` identifier rule matches the sanitizer's
**own synthesized output** at a reached position and aborts. Nothing leaked. Exit 2, no output,
**every run, deterministically**, with no override. That is the exact category error the
`scan_residual_rules` docstring holds up as the reason regex was scoped out of #195 — my plan
cited that docstring as its safety argument while relocating the failure from the
`remap_uuids: false` skipped case (which I handled) to the `remap_uuids: true` visited case
(which I missed).

**This is not hypothetical, and #202 is why.** The natural reason to pair `remap_uuids: true`
with a catch-all UUID regex is to sweep the UUID-graph edges the built-in set is known to
miss — `sourceToolAssistantUUID` / `leafUuid`, which is **#202, row 10 of this very run's
queue**. An operator acting on #202 would brick every run. The carve-out must land before
anyone acts on #202.

**The fix is positional, and it must never be value-based (architect F3, IMPORTANT).** The
regex scan runs under `make_skip_predicate(remap_uuids=False)` (== `default_skip_predicate`)
**regardless of the run's setting**, which exempts `_UUID_PATHS` from the regex oracle
unconditionally. That is safe and auditable: `_UUID_PATHS` is a fixed five-element set known at
load time, and it is the only position class where the sanitizer writes a runtime-synthesized
value I-3 cannot vet, which is provably non-PII (SHA-256 of `(seed, original)`) yet matches any
UUID-shaped regex by construction.

**Negative requirement, stated because the tempting fix is the forbidden one.** The exemption
MUST NOT be implemented by comparing a match span against synthesized values or the
substitution table. That is the allow-set verbatim — dynamic, value-based — and it is the exact
mechanism that leaked `/home/realuser` in #195's review. Positional exemption cannot excuse
that leak, because a normal path leaf is not a UUID position. A test pins this (step 5c).

**What the oracle asserts, precisely.**

- A regex match at a **reached, non-UUID-synthesis** position is a leak → abort.
- A regex match at a **skipped** position is not a leak (the value is preserved on purpose so
  the parent/subagent graph stays linkable) → no abort.
- A regex match at a **UUID-synthesis** position is not a leak (the sanitizer wrote it) → no
  abort.
- **Dict keys — and the justification is a proxy, not the leaf equivalence (architect F2).**
  For a string *leaf*, "the walk would have reached this" is exactly `not skip_predicate(path)`;
  `walk_strings` applies `transform` iff that holds (`pipeline.py:429-433`). For a *key* it is
  not: `walk_strings` rebuilds `{key: _walk(sub, path + (key,))}` and **structurally cannot
  address a key at any path**. The key is attributed its value's path, and the real reason to
  abort is that **the sibling value-position is user-writable territory rather than a preserved
  format position**. Keep the attribution; state the reason correctly, so the next reader does
  not re-derive the leaf equivalence and conclude keys and leaves are the same case.
- Consequence, stated rather than hidden: **#194's residual stays open for regex.** Skip-listed
  positions remain exempt, so the five allow-listed paths under `toolUseResult` keep their
  documented residual. This closes #190 for regex and does **not** close #194 for regex. That
  asymmetry lands in the docs (AC-3), not just here.

**Note what the correction does to the design-selection argument (architect F4).** Design 2's
one genuine merit is that it avoids the false-abort surface entirely, which is exactly design
1's F1 liability. So "design 1 over design 2" holds *only* once the carve-out is in. The
carve-out is load-bearing for the choice, not an incidental detail.

**Steps.**

1. **`residual.py` — give the decoded walk a path.** Replace `_iter_decoded_strings(node)` with
   a path-aware iterator yielding `(text, path)`, mirroring `walk_strings`' path discipline
   exactly: dict keys extend the path (`path + (key,)`), **list indices are elided** (the
   allow-list depends on elision — `pipeline.py:437-449`). Keep the existing key-yielding
   behavior, which is the whole of the #190 coverage.
2. **`residual.py` — scan regex rules, exempting the synthesis positions.** Extend
   `scan_residual_rules` to scan regex rules at positions where
   `not default_skip_predicate(path)` — the `remap_uuids=False` predicate, **not** the run's.
   Record the justification inline. Literal-rule behavior is **unchanged**: literals stay
   position-agnostic and are not filtered by any predicate, because "presence is a leak,
   unconditionally" is still true of a literal and narrowing it would regress #195's guarantee.
3. **`residual.py` — the two guards the literal path does not need** (AC-2):
   - **Zero-width guard.** Skip empty subjects and zero-width match spans.
     `_reject_zero_width_pattern` only tests `compiled.match("")`, so an input-dependent
     zero-width pattern (`re:(?=hello)`, `\b`) still reaches here — the same reason
     `rules/_engine.apply_rule` carries its own `if not original` guard.
   - **`finditer`, not `search`.** For a regex the spans vary, so an exempted first match must
     not excuse a genuine survivor later in the same string.
4. **`orchestrator.py` — do NOT pass the run's predicate to the regex path.** The call at
   `orchestrator.py:169` keeps feeding the run's `skip_predicate` to the *literal* path's
   existing behavior; the regex path uses `default_skip_predicate`, constructed inside
   `residual.py` so the divergence is a property of the module rather than of a call site
   someone could later "fix". Document that the oracle **deliberately diverges** from the
   scrub's predicate at the UUID positions, and why — otherwise the divergence reads as a bug
   and gets removed.
5. **Tests — `test_residual_rules.py`** (AC-2). The issue comment's vectors, plus the three
   cells the architect requires:
   - regex rule matching a **dict key** aborts;
   - the same rule against the same value in a **string leaf** still redacts (positive control,
     which stops a brick implementation passing by aborting on everything);
   - a **skipped** position under `remap_uuids: false` does not abort;
   - zero-width (`re:(?=...)`, `\b`) and a `finditer` case where an exempt-looking first match
     precedes a genuine survivor in one string;
   - **(a) F1 regression guard** — `remap_uuids: true` + a UUID-shaped `re:` identifier rule +
     input carrying a real `uuid`/`sessionId` → run **succeeds**, no `ResidualRuleError`;
   - **(b) carve-out is positional** — the same UUID-shaped rule matching a UUID-shaped value
     planted in a **dict key** (a non-UUID position) → still aborts;
   - **(c) no allow-set crept in** — the PRD §5 `/home/realuser` layer-order leak still aborts
     through the new regex path.
   Cells (a) and (b) together are what prove the carve-out is a position exemption and not a
   blanket "UUID regexes never abort"; (a) alone would pass a too-broad implementation.
6. **Tests — `test_adversarial_placement.py`**: add a **regex payload family** to the matrix.
   Its four payloads are all literals, so the matrix cannot observe this class in any cell today.
7. **Docs (AC-3 + AC-4).** PRD §5 and §10, the sidecar note, and the `scan_residual_rules`
   docstring (which currently says regex rules "are **not** re-verified here"): state the
   guarantee exactly — regex rules are verified at reachable positions **except the UUID-graph
   synthesis positions**; literals stay position-agnostic; #194's skip-list residual stays open
   for regex. Record explicitly that the exemption is **positional, not the forbidden
   value-based allow-set**, and why. CHANGELOG entry.
8. **AC-4 — `scan_residual`'s decoded/serialized blind spot: DOCUMENT, do not fix**, and audit
   the built-in set. The issue argues this itself: the code fix "changes the semantics of the D-1
   security floor, so it wants its own change and its own test matrix rather than riding along".
   AC-4's wording (`either fixed or documented as a known limit`) permits documenting. The
   **audit** is in scope and bounded — 12 built-in patterns (8 `VENDORED_PATTERNS` + 4
   `BATCH_PATTERNS`) — so walk all 12 for escaped-byte divergence and record the result. Known
   going in: `bearer-token` diverges (`\s` matches newline/tab, which JSON escapes);
   `conn-string-pw` and `pem-private-key` were checked in the issue and do not.

   **AMENDED at the plan gate (human, 2026-08-30): the audit's findings must land DURABLY.** An
   audit whose result lives only in a PR body or in this gitignored plan file is not tracked. So
   the per-pattern result goes into a **doc file** (the PRD's own limits section, beside the
   existing `residual_scan: clean` caveats) **and** a **follow-up issue** carries the code fix,
   quoting the audit table so the next person does not re-derive it. Doc file and issue, not one
   or the other: the doc states the standing limit for a reader of the guarantee, the issue
   tracks the work.
9. **Version bump — DEFERRED to the merge gate by human ruling (2026-08-30).** Do **not** bump
   `__version__` in this change. The determinism contract still applies — a config that used to
   exit 0 can now exit 2 — but the human's direction is to **review the magnitude of the actual
   landed diff once it has passed review, then decide**. So: implement without touching
   `__init__.py`, and surface the magnitude at the merge gate as an explicit decision, alongside
   whether landing this releases the `0.4.0` publish hold that #190 left open. Recorded here so
   the acceptance gate does not read the missing bump as an omission.

**Order of operations is unchanged (architect F7).** `scan_residual` (secrets) stays strictly
before `scan_residual_rules` (rules) at `orchestrator.py:150`/`169`, so a genuine surviving
secret still reports as `ResidualSecretError` rather than as a rule match. Both map to exit 2;
only the diagnostic differs.

**Files to touch:** `tooling/sanitizer/src/ccs_sanitize/residual.py`,
`tooling/sanitizer/src/ccs_sanitize/orchestrator.py`,
`tooling/sanitizer/tests/test_residual_rules.py`,
`tooling/sanitizer/tests/test_adversarial_placement.py`,
`.claude/specs/prd-sanitizer.md` (§5 **and** §10), `tooling/sanitizer/CHANGELOG.md`,
`tooling/sanitizer/README.md`. **`src/ccs_sanitize/__init__.py` is NOT touched** — the version
decision is deferred to the merge gate per the human's ruling (step 9).

**Deliberately OUT of scope — with one item MOVED IN by the architect (F5).** Each deferral
wants its own issue; listed so you can overrule at the plan gate rather than discover the
omission at the acceptance gate.

- **MOVED IN — the regex analog of the synthesized-value false-abort.** I had filed this under
  the deferred "substring of a synthesized value" bullet. The architect separated them, and the
  separation is right: **the literal case is pre-existing and deferrable; the regex case is
  created by this change**, so it cannot be deferred. It is also strictly worse — a UUID-shaped
  regex is not narrowable, because it matches all UUIDs by construction, including synthesized
  ones. This is F1, now step 2/4 above.
- Still deferred: **literal** rule that is a substring of a synthesized value false-aborts under
  `remap_uuids: true`. Availability-only, never a leak, deterministic, recoverable by narrowing
  the rule.
- **Load-time contradiction guard** (`remap_uuids: false` + a canonical-UUID-shaped regex rule).
  A new rejection path that could break existing configs; the issue says it was deliberately not
  landed in #195 and wants its own tests.
- **JSON-number invisibility** (`{"account_id": 1004728391}`). Blocks #126; needs a false-abort
  trade-off analysis on ordinary numeric fields (token counts, timestamps).
- **Nested JSON-in-a-string.** Pre-existing limit of the scrub itself, not of the oracle.
- The **code** fix for `scan_residual`'s decoded-domain scan (step 8 documents it instead).

**AMENDED at the plan gate (human, 2026-08-30): every deferral is FILED, not just named.** "Defer
but capture in follow-up issue(s) so they're still tracked." A deferral recorded only in a
gitignored plan file is untracked work, so each item above gets a GitHub issue before this PR
opens, and the PR body links them. Two notes on the mapping, since it is not one-issue-per-bullet:
**#126 already exists** and is the numeric-id scrubbing work — check whether it already records
the JSON-number *blind spot* as its blocker and extend it if not, rather than filing a duplicate;
and the `scan_residual` decoded-domain code fix is the same follow-up step 8 already owes, so it
is one issue, not two. Filing happens at step 6 (implement), so the issue numbers are real by the
time the PR body cites them.

## Approach as reviewed (frozen before the design gate) — write-once, do not edit

<!-- Verbatim copy of `## Approach` taken BEFORE the architect pass was consulted (step 4). -->

**Fork chosen: design 1 (skip-predicate-aware regex scan).** Recorded here as the plan's
proposal; AC-1 makes the *recorded decision* itself a deliverable, and the architect gate
(step 4) is what ratifies or redirects it before any code is written.

Why design 1 over design 2 (`verify_output: true` per-rule opt-in), stated so the architect has
something falsifiable to push against:

- Design 2 makes the safety property **opt-in on top of an opt-in**. The operator already had to
  hand-author the regex rule; asking them to also know that regex rules are unverified and to
  set a second flag means the default for a hand-authored rule stays silently unverified. The
  people most exposed are the ones least likely to set it.
- Design 2 needs a **sidecar marker** so the review gate can see which rules were verified —
  that is a sidecar-shape change, which is a determinism-contract surface and a second
  ARCHITECT_TRIGGER.
- Design 1 needs no config-schema change and no sidecar-shape change, and it closes the #190
  dict-key position for regex, which is the reproduced leak.

**What design 1 asserts, precisely.** Abort on a regex match only at a position the scrub walk
**would have reached**. The walk's reach is exactly `not skip_predicate(path)`. So:

- A regex match at a **non-skipped** path is a leak: the walk reached that position, so a
  surviving match means the scrub failed there (or, for a dict key, could never have run —
  `walk_strings` rebuilds `{key: _walk(sub, ...)}` and copies keys verbatim). Abort.
- A regex match at a **skipped** path is **not** a leak: the value was preserved on purpose
  (`remap_uuids: false` keeps the UUID graph linkable). Do not abort. This is what stops the
  category error #195 hit, where a UUID-shaped identifier rule aborted every session with
  nothing mis-scrubbed.
- Consequence, stated rather than hidden: **#194's residual stays open for regex.** A
  skip-listed position remains exempt, so the five allow-listed paths under `toolUseResult`
  keep their documented residual. Design 1 closes #190 for regex and does **not** close #194
  for regex. That asymmetry must land in the docs (AC-3), not just here.

**Steps.**

1. **`residual.py` — give the decoded walk a path.** Replace `_iter_decoded_strings(node)` with
   a path-aware iterator yielding `(text, path)`, mirroring `walk_strings`' path discipline
   exactly: dict keys extend the path (`path + (key,)`), **list indices are elided** (the
   allow-list depends on elision — `pipeline.py:437-449`). A dict key is attributed the same
   path as its value, since that is the position the walk reached and declined to scrub.
   Keep the existing key-yielding behavior, which is the whole of the #190 coverage.
2. **`residual.py` — scan regex rules under the skip predicate.** Extend `scan_residual_rules`
   to take a `skip_predicate` argument and scan regex rules at non-skipped positions only.
   Literal-rule behavior is **unchanged** — literals stay position-agnostic and are not
   filtered by the predicate, because "presence is a leak, unconditionally" is still true of a
   literal and narrowing that would be a regression in #195's guarantee.
3. **`residual.py` — the two guards the literal path does not need** (AC-2):
   - **Zero-width guard.** `if not text: continue` before matching, and skip zero-width match
     spans. `_reject_zero_width_pattern` only tests `compiled.match("")`, so an
     input-dependent zero-width pattern (`re:(?=hello)`, `\b`) still reaches here — the same
     reason `rules/_engine.apply_rule` carries its own `if not original` guard.
   - **`finditer`, not `search`.** For a regex the spans vary, so an excused first match must
     not excuse a genuine survivor later in the same string.
4. **`orchestrator.py` — pass the predicate.** `scan_residual_rules` is called at
   `orchestrator.py:169`; the `skip_predicate` already exists at line 114 and is already
   threaded into `run_pipeline`. Pass the same one, so the oracle's notion of reach is the
   *same object* the scrub used rather than a re-derived copy that could drift from it.
5. **Tests — `test_residual_rules.py`** (AC-2): the issue comment's three vectors (regex rule
   in a dict key aborts; same rule in a string leaf still redacts — the positive control; and
   the skipped-position case does **not** abort under `remap_uuids: false`), plus zero-width
   (`re:(?=...)`, `\b`) and a `finditer` case where an allow-listed-looking first match precedes
   a genuine survivor in one string.
6. **Tests — `test_adversarial_placement.py`**: add a **regex payload family** to the matrix.
   The issue comment is explicit that the four existing payloads are all literals, so the
   matrix cannot observe this class in any cell today.
7. **Docs (AC-3 + AC-4).** PRD §10 and the sidecar note: state the resulting guarantee exactly —
   regex rules are now verified **at reachable positions**, literals stay position-agnostic,
   and #194's skip-list residual remains open for regex. Update `scan_residual_rules`' docstring,
   which currently says regex rules "are **not** re-verified here". CHANGELOG entry.
8. **AC-4 — `scan_residual`'s decoded/serialized blind spot: DOCUMENT, do not fix**, and audit
   the built-in set. The issue argues this itself: the code fix "changes the semantics of the D-1
   security floor, so it wants its own change and its own test matrix rather than riding along".
   AC-4's wording (`either fixed or documented as a known limit`) permits documenting. The
   **audit** is in scope and is bounded — 12 built-in patterns (8 `VENDORED_PATTERNS` + 4
   `BATCH_PATTERNS`) — so walk all 12 for escaped-byte divergence and record the result. Known
   going in: `bearer-token` diverges (`\s` matches newline/tab, which JSON escapes);
   `conn-string-pw` and `pem-private-key` were checked in the issue and do **not**. File a
   follow-up issue for the code fix.
9. **Version bump.** `__version__` carries a determinism contract: this changes produced output
   (a config that used to exit 0 can now exit 2), so a bump is **required** — not a no-bump
   merge. Currently `0.4.0`; this is a behavior change on an unreleased-to-PyPI version, so
   confirm at the merge gate whether it rides `0.4.0` (still gated on the #190 publish hold) or
   takes its own bump.

**Files to touch:** `tooling/sanitizer/src/ccs_sanitize/residual.py`,
`tooling/sanitizer/src/ccs_sanitize/orchestrator.py`,
`tooling/sanitizer/tests/test_residual_rules.py`,
`tooling/sanitizer/tests/test_adversarial_placement.py`,
`.claude/specs/prd-sanitizer.md` (§10), `tooling/sanitizer/CHANGELOG.md`,
`tooling/sanitizer/README.md` (if it states the guarantee), and possibly
`src/ccs_sanitize/__init__.py` (version).

**Deliberately OUT of scope — the issue's "Also in scope" items that carry no acceptance
criterion.** Listed so the human can overrule at the plan gate rather than discover the
omission at the acceptance gate. Each wants its own issue:

- Literal rule that is a **substring of a synthesized value** false-aborts under
  `remap_uuids: true`. Availability-only, never a leak, deterministic, recoverable by narrowing
  the rule. Any guard here risks re-introducing the allow-set mechanism that produced a real
  leak in #195's review.
- **Load-time contradiction guard** (`remap_uuids: false` + a canonical-UUID-shaped regex rule).
  A new rejection path that could break existing configs; the issue itself says it was
  deliberately not landed in #195 and wants its own tests.
- **JSON-number invisibility** (`{"account_id": 1004728391}`). Blocks #126; needs a
  false-abort trade-off analysis on ordinary numeric fields (token counts, timestamps).
- **Nested JSON-in-a-string.** Pre-existing limit of the scrub itself, not of the oracle.
- The **code** fix for `scan_residual`'s decoded-domain scan (step 8 documents it instead).

**AMENDED at the plan gate (human, 2026-08-30): every deferral is FILED, not just named.** "Defer
but capture in follow-up issue(s) so they're still tracked." A deferral recorded only in a
gitignored plan file is untracked work, so each item above gets a GitHub issue before this PR
opens, and the PR body links them. Two notes on the mapping, since it is not one-issue-per-bullet:
**#126 already exists** and is the numeric-id scrubbing work — check whether it already records
the JSON-number *blind spot* as its blocker and extend it if not, rather than filing a duplicate;
and the `scan_residual` decoded-domain code fix is the same follow-up step 8 already owes, so it
is one issue, not two. Filing happens at step 6 (implement), so the issue numbers are real by the
time the PR body cites them.

## Architect triggers hit

Three, and any one of them alone would fire the gate:

1. **"Any change to the sanitizer's scrubbing behavior"** — this changes `residual.py`'s
   scan semantics and the pipeline's abort conditions. Carries a published determinism contract
   and a PyPI audience.
2. **"Anything that changes what a `.scrubbed` sidecar records"** — design 2 explicitly needs a
   sidecar marker. Design 1 as planned does not, but the fork itself is live until the architect
   rules, so the trigger is hit on the fork rather than on the chosen branch.
3. **"The orchestrator is unsure"** — AC-1 makes the design decision itself the deliverable, and
   the issue deliberately presents two candidates without choosing. That is the definition of a
   design question, and it is the architect's to answer, not the implementer's.

## Risks / open questions for human

1. **The fork is the whole of AC-1.** If the architect redirects to design 2 or to "neither",
   the plan changes materially and step 5's always-on condition stops for you regardless.
2. **Design 1 closes #190-for-regex but NOT #194-for-regex.** The skip-listed positions stay
   exempt. That is a deliberate, documented residual, and it needs to be stated in the PRD in
   the same edit — otherwise the docs imply a guarantee wider than the code makes.
3. **AC-4 is being read as "document", not "fix".** The issue's own text argues for this, and
   the AC's wording permits it, but it is a judgment call and it is yours to overrule. The
   12-pattern audit is in scope either way.
4. **The `0.4.0` publish hold interacts with this.** #190's iteration left the PyPI publish hold
   open pending #198. This change alters produced output, so it forces a version decision at the
   merge gate. Worth deciding whether landing this is what releases the hold.
5. **Scope discipline.** Five "Also in scope" items are being deferred to follow-up issues. If
   you want any of them in this change, say so now — the acceptance gate will otherwise certify
   only the four ACs.
