# Loop journal: epic-sanitizer

Append-only. One block per gate decision, plus an open record (step 7) and a close record
(step 12) per iteration. Never rewritten. The ledger is gitignored and never committed.

---

## 2026-08-21T22:46:05Z — init

- BACKLOG_SOURCE: label `epic:sanitizer` on frederick-douglas-pearce/claude-code-sessions
  (no milestones exist in this repo). Human chose it over `epic:pages-sync`,
  `epic:format-watch`, and the whole open backlog.
- Enumerated 7 open issues: #1, #32, #42, #190, #192, #194, #195.
- Mode: `calibration` — no prior route graduation is recorded in `.claude/specs/decisions.md`
  (it holds D001 and O001, neither about graduation), so this is the default branch.
  `plan-gate: always` set on the same branch. Both caps `none`.
- Routing:
  - #1 → `stub-defer` / `deferred` (terminal). Title begins `Epic:`, the stub-defer marker in
    loop.config.md §3. The loop does not close epics.
  - #195 → `code` / `routed`. No dependencies.
  - #190, #194 → `code` / `blocked` on #195. **Not an inference:** #195's body states the
    sequencing outright — "this issue lands first as its own PR. #190 and #194 land together
    as a second PR. One 0.4.0 release covers both." #195 also explains why: it converts both
    from silent-leak gates into coverage work.
  - #192 → `code` / `routed`. No dependencies.
  - #32 → `code` / `routed`. Carries no priority label, so it ranks below `priority:low`.
  - #42 → `code` / `parked`, `awaiting: user demand for human-readable sidecar placeholders`.
    The issue is explicitly a track-demand placeholder ("No action is required until someone
    actually asks"), which is an external event, not an in-run dependency.
- Orphan scan (step 0.3): zero open PRs, working tree clean, `git worktree list` shows only
  the primary tree, local `main` level with `origin/main`. No unattributed state.

## 2026-08-21T22:58Z — #195 (code) — plan gate

- Architect: invoked (`DESIGN_AGENT` = `architect`). Triggers hit: sanitizer scrubbing behavior
  (new fail-closed exit path); CI/workflow structure (edits the required `sanitizer-ci` suite
  list); published-artifact blast radius (0.4.0 ships to PyPI).
- Architect outcome recorded as a comment on issue #195 (the agent posted it directly). Verdict:
  architecturally sound, ONE `blocking` change, plus `important`/`suggestion` refinements.
- Blocking finding applied: the plan's preferred Q2 fix (mask recorded replacement strings out of
  each line before scanning) is withdrawn. Blind string-deletion can manufacture a FALSE NEGATIVE
  — rule `match: abc123` / `replace: abc` passes I-3, so deleting every `abc` turns a genuine
  `abc123` leak into `123`, which the rule no longer matches, and the leak ships clean. Replaced
  with exact-membership exclusion: scan with `rule.compiled`, abort unless the exact matched span
  is a member of the run's recorded-replacement set. No text mutation, no false negatives.
- One architect suggestion DECLINED with rationale: appending the rule's replacement string to the
  diagnostic. Replacement text is user-authored and nothing structurally forbids PII in it, so
  "non-sensitive by construction" overstates the guarantee. Diagnostic stays `section[index]`.
- Plan-gate: material (a different fork was chosen at step 5 — masking replaced by exact-membership
  exclusion; `scan_residual_rules` signature gained the allow-set; two steps added (follow-up issue
  for config.py's ConfigError messages, release-coordination checks); three tests added to step 7)
  → STOPPED
- Human gate: pending — `plan-gate: always`, and the always-on architect-materiality condition
  fired independently. Awaiting the human.
- Human gate: plan approved by the human (plan-gate: always). Two decisions recorded:
  (1) HOLD the PyPI publish after this lands — bump `__version__` to 0.4.0 on this PR, but do not
      release until #190/#194 land, so the first version a `pip` user sees carries coverage and
      not merely refusal (architect item 6b);
  (2) FILE the config.py ConfigError follow-up (step 8) rather than fixing it in this PR.
  Row advanced to `plan-approved`.

## 2026-08-21T23:20Z — #195 (code) — iteration open

- Issue: #195 — feat(sanitizer): total output-side oracle for path/identifier rules
- Route: code
- Branch: feature/195-output-side-oracle
- PR: #197
- Status: in-pr
- Hermetic: pass — trigger fired (Route `code`, the change adds `test_residual_rules.py`).
  All four suites re-run inside `unshare -rn` with loopback up; green. Block confirmed
  socket-level: a direct-IP connect fails inside the wrapper and succeeds outside it.
- Lint: `npx prettier . --check` exit 0. Type: n/a: no separate type step (no mypy/pyright
  config in the repo and no CI job runs one).
- Follow-up #196 filed per the approved plan (step 8).

## 2026-08-21T23:35Z — #195 (code) — code review (round 1)

- Gate: `CODE_REVIEW` = `/code-review high` on PR #197. Six findings: 1 HIGH, 4 MEDIUM, 1 LOW.
- Independently reproduced three of them against the branch before acting (agent findings are
  not taken at face value):
  - **#1 HIGH — CONFIRMED. The oracle does not close the class it claims to.** Rules are
    authored against DECODED leaf values; the scan runs over the SERIALIZED line. Any value
    containing a backslash, quote or control char is therefore invisible to it. Reproduced
    end-to-end with a Windows home dir (`C:\Users\realuser`) in a dict key — the canonical
    `paths` case in the #190 position: exit 0, output written verbatim, sidecar
    `residual_scan: clean`. That is the exact silent leak this PR claims to have closed.
  - **#2 MEDIUM — CONFIRMED.** A zero-width match (`re:(?=hello)`) aborts a clean run with no
    PII present. My own code comment asserts this is impossible because
    `_reject_zero_width_pattern` covers it; that guard only tests `compiled.match("")` and
    does not cover input-dependent zero-width patterns. `rules/_engine.apply_rule` has the
    guard the oracle lacks. The comment is false and sits directly on the gap.
  - **#4 MEDIUM — CONFIRMED, and it falsifies the basis of an approved decision.** Under the
    DEFAULT `remap_uuids: false`, `sessionId` is skip-listed deliberately. A UUID-shaped
    identifier rule then aborts EVERY session though nothing was mis-scrubbed. The human
    approved shipping with no escape hatch on the architect's stated basis that "with
    exact-membership the realistic false-positive rate is ~zero". That basis is now falsified
    by reproduction on a default config.
- Not yet fixed. Findings #3/#4 are one design tension the plan flagged as a risk and the
  human ruled on; the ruling's premise no longer holds, so fixing round 1 against a design
  that may change would spend this gate's only remaining round on superseded code.
- Round 1 of 2 consumed. ESCALATING to the human before the fix round (Escalation rubric: a
  contested finding, and a design decision whose stated basis is falsified).
- Gate NOT journalled as passed — it returned findings.
- Human disposition on the escalation: leans Option 2 (scope the oracle to literal rules) or
  Option 3 (keep it total, ship an escape hatch); directed `DESIGN_AGENT` to determine which
  is the better detection/false-positive balance. Narrowing scope now and filing a follow-up
  for the edge cases is explicitly acceptable to the human.
- Second architect consultation invoked at the code-review gate. No plan freeze is owed: this
  is a step-8 design consultation, not the step-4/5 architect pass, and the pipeline offers no
  path back to the plan gate from `in-review` (the plan-currency case the engine scopes out).
  Agent instructed NOT to write anywhere this time — the first pass posted its review to the
  issue itself, which the engine's tool surface does not cover.

## 2026-08-21T23:55Z — #195 (code) — code review (round 2: fixes)

- Architect determination (second consultation): **Option 2** — scope the unconditional oracle to
  LITERAL rules, with finding A fixed as decoded-tree scanning. Explicitly NOT Option 3: a global
  escape hatch recreates the silent-leak path #195 exists to close and contradicts the repo's
  settled `--no-check` stance. The architect retracted its own earlier "false-positive rate ~zero"
  basis, which is what the human's no-escape-hatch approval rested on.
- Applied: decoded-tree walk over leaves AND dict keys (A); literal-only scope, which also
  dissolves B and C; corrected the false CLI catch-all comment (E); simplified to `search()` since
  a literal's every match shares a span.
- One architect recommendation DECLINED with rationale: a load-time guard rejecting regex rules
  that match the canonical UUID shape when `remap_uuids` is false. It is a new exit-3 rejection
  path that could break existing configs, it fixes no confirmed finding once regex is out of the
  oracle's scope, and it wants its own tests. Moved to #198. The human authorized narrowing scope
  with a follow-up.
- Docs treated as BLOCKING per the architect, not cleanup: PRD sections 5/10/11, CHANGELOG and
  README now state exactly what `residual_scan: clean` covers. A narrowed guarantee wearing a
  total-sounding attestation is the rubber-stamp failure the issue is about.
- Follow-ups filed: #198 (regex gap + the two guards a regex treatment needs + `scan_residual`'s
  own decoded/serialized blind spot). #196 already covers the message-side leaks.
- All four reproductions re-run against the fix: A now aborts, B and C no longer false-abort, the
  original literal case still aborts. Suites 413+4x / 64 / 16 OK. Prettier clean. Hermetic re-armed
  (tests changed) and green.
- PR #197 body rewritten — it claimed a total guarantee that no longer ships.
- Fresh re-check spawned (round 2 of the 2-round cap; a new instance, not the round-1 reviewer).
- Round 2 (fresh re-check) came back DIRTY. Verdicts: findings 1, 2, 4 confirmed fixed; 3 and 5
  half-fixed; 6 unfixed and now shown to be load-bearing. Nine new items, two of them reproduced
  silent leaks. I reproduced both of those myself:
  - **N1 MEDIUM — a silent leak the allow-set CREATED, and my change introduced it.** Regex-rule
    replacements are synthesized at runtime by `match.expand()` and are never vetted by I-3, which
    checks only the literal `replace` template. They land in the subtable, hence in the allow-set.
    Config `paths: /home/realuser -> /home/user` + `identifiers: re:HOME_(\w+) -> /home/\1` on
    input "see HOME_realuser here": the identifiers layer mints `/home/realuser`, records it as a
    replacement, and the oracle then EXCUSES the paths rule's own match value. Result: exit 0,
    output containing the operator's real home directory, `residual_scan: clean`, and a sidecar
    printing `replacement: /home/realuser`. Without the allow-set the oracle would have caught it.
    This is round-1 finding 6 (the unsound transitivity claim) manifesting as a live leak — I had
    declined to fix it as a docs-only nit, and that judgment was wrong.
  - **N2 MEDIUM — the decoded walk decodes one level only.** A value inside a JSON-encoded string
    leaf carries its own escaping. Reproduced: exit 0, `residual_scan: clean`, value recoverable by
    a double decode. Pre-existing (the scrub misses it too, and #198 already records it), but the
    new docstring claims the scan runs "in the domain the rules were authored in", which overclaims.
  - N4: the CLI catch-all's OWN comment still asserts every typed exception is span-free, ten lines
    below the correction I added. The false claim sits in the handler it describes.
  - N5: three "total" overclaims remain (CHANGELOG heading + the #191 entry,
    test_adversarial_placement.py module docstring). N3/N6/N7/N8/N9: smaller claim/doc drift.
- 2-round cap reached and round 2 is dirty. ESCALATING to the human per the Fresh-re-check
  invariant: no round 3 on my own initiative. Gate NOT journalled as passed.
- Recommendation carried to the human: DELETE the allow-set. With regex rules out of the oracle's
  scope its only non-vacuous effect is to excuse regex-expanded replacements, which is precisely
  N1; every other category it could excuse is already barred by I-3 from tripping the oracle. Cost
  is a contrived false abort (a literal whose match equals a synthesized UUID).

## 2026-08-22T00:20Z — #195 (code) — code review (round 3, human-authorized)

- Human authorized a third round rather than splitting or reverting, and confirmed the load-time
  guard stays in #198. Standing instruction: if the gate still fails, send the remaining items to
  `DESIGN_AGENT` to scope the fixes so it passes.
- Applied: allow-set REMOVED entirely (N1). Signature is now
  `scan_residual_rules(lines, paths, identifiers)`; the orchestrator no longer builds a frozenset
  from the subtable. N1's config aborts at `paths[0]` and writes nothing.
- Also: the CLI catch-all's own comment corrected (N4) — last round I fixed the handler above it
  and left the false claim in the handler it described; three surviving "total" overclaims (N5);
  stale module/exception/PRD docstrings (N6); the substring claim (N3) gone with the allow-set;
  the one-level-decode limit (N2) documented and pointed at #198 instead of implied away; the
  "three"/"four" nit and the undocumented `json.JSONDecodeError` (N8/N9).
- All five reproductions re-run: A aborts, B and C pass, N1 aborts, the original literal case
  aborts. Suites 412+4x / 64 / 16 OK. Prettier clean. Hermetic re-armed and green. A repo-wide
  grep for the "total output-side" phrasing returns nothing.
- Round 3 fresh re-check spawned (new instance again, not either prior reviewer).
- Round 3 re-check: DIRTY, but **no code defect**. The checker independently verified the allow-set
  removal is complete (no vestigial parameter, single caller, `AbstractSet` import gone), the
  decoded walk correct over keys/lists/nesting, and the I-3 reasoning true against
  `config.py:489-547`. Every remaining item is documentation still describing the removed
  mechanism, plus three scope questions.
- **The repeated error is mine and it has a shape:** I fix the mechanism and leave the claims about
  it standing. Round 2 left the false CLI catch-all comment ten lines below its own correction;
  round 3 removed the allow-set from the code and left it described as load-bearing in PRD section
  5 and in the CHANGELOG of the version being shipped, unsound transitivity sentence included. In a
  repo whose whole subject is that an attestation must not outrun what was verified, that is the
  defect class, not an untidiness.
- Two findings the checker reproduced that are NOT stale-doc items: a literal rule that is a
  SUBSTRING of a synthesized UUID false-aborts under `remap_uuids: true` (removal covered only the
  exact-equality variant); and the escaped-value-inside-JSON-in-a-string leak is real and absent
  from the PRD's list of what `residual_scan: clean` does not attest to.
- Per the human's standing instruction, remaining items routed to `DESIGN_AGENT` to scope rather
  than fixed ad hoc: whether the substring false-abort needs a guard or a sentence, how to rewrite
  the now-inverted v1 jitter forward constraint, and whether the secret scan's own "total" claim is
  fixed here or deferred to #198.

## 2026-08-22T01:05Z — #195 (code) — architect scoping + round 4

- `DESIGN_AGENT` scoping determination: **nothing left requires new code before merge**; the gate
  can pass on wording. It corrected two conclusions I had accepted from the re-check:
  - **The substring false-abort is PRE-EXISTING, not a cost of removing the allow-set.** That
    allow-set tested *exact span membership*, so a literal like `dd9cca` inside a synthesized UUID
    was never in it and false-aborted before removal too. Removal changed only the exact-equality
    case, which genuinely is contrived. My docstring called the whole residual cost contrived,
    which understated the case that matters; it now separates the two. Deferred to #198, because
    any guard excusing a match for falling inside a synthesized value re-introduces the shape that
    leaked.
  - **"Position-agnostic" is accurate for the secret scan and is kept.** Only "total" overclaimed,
    by implying encoding-completeness. Built-in credential patterns are alphanumeric so serialized
    and decoded forms coincide (D-1 floor complete); the gap is an *extra* user pattern matching an
    escapable byte.
  - The v1 jitter forward constraint was INVERTED rather than stale — with no allow-set, jitter's
    values get no exemption and are scanned like any other content, so the live risk flips from
    leak to false-abort. Rewritten, not dropped.
- Applied the must-land pile: PRD section 5 now states the no-exemption requirement positively with
  the reproduction, so the threat model records the lesson instead of inviting the mistake; PRD
  section 10 enumerates the three things `residual_scan: clean` does NOT attest to; CHANGELOG
  allow-set note and jitter constraint rewritten; `ResidualRuleError` summary, the `Raises:`
  wording, and three stale test comments corrected; the secret-scan claim qualified in five places.
- #198's body corrected: it rested on "the PRD says so today", written from an intended edit rather
  than a checked one. It now records the substring false-abort and the corrected secret-scan story.
- Suites 412+4x / 64 / 16 OK. Prettier clean. Hermetic green. All five probes correct.
- Round 4 fresh re-check spawned. Note this exceeds the engine's 2-round cap; rounds 3 and 4 exist
  because the human explicitly authorized continuing and then directed the architect scoping.
- Round 4 re-check: code confirmed correct for the second consecutive round; two REPRODUCED
  findings, both about claims rather than behavior:
  - **The completeness claim I wrote in the doc pass was false.** "Every built-in credential
    pattern is alphanumeric so the D-1 floor is complete" -- `bearer-token` is
    `(?i)authorization:\s*bearer\s+...` and `\s` matches a newline, which JSON escapes. A bearer
    token with a newline separator, in a dict key, survives with `residual_scan: clean`. I wrote
    that sentence in the commit whose purpose was removing overclaims, without checking it against
    `rules/secrets.py`. Narrowed; folded into #198.
  - **The decode switch created a numeric-leaf gap.** `_iter_decoded_strings` yields strings, so a
    configured value appearing as a JSON number is invisible to it. The serialized-text scan this
    branch replaced WOULD have matched it: moving to the decoded domain closed the escaped-byte
    blind spot and opened a non-string-leaf one. Not a regression against `main` (no rule scan
    existed), but it is live here -- #126 is "scrub GitHub-noreply numeric user ids", exactly that
    shape. Listed in PRD section 10 and cross-referenced from #198 to #126.
  - Also: PRD section 10's list is now four items and says explicitly that it is NOT closed; a
    lazy-continuation indent that folded a paragraph into a bullet; a broken fixture-validator
    anchor (section 13, not 11) including the twin predating this branch; the jitter claim narrowed
    because token counts are numbers; three over-long lines rewrapped.
- All gates green. CI green on all six checks at `2258f9d`.
- **Standing observation about my own error rate on this row, recorded because it is the useful
  signal:** three consecutive rounds found no code defect and a claim defect every time. The code
  was right after round 3; what kept failing was prose asserting things about the code that I had
  not verified. On a tool whose subject is exactly that, that is the finding.
- STOPPING for the human rather than spawning round 5 unprompted. Rounds 3 and 4 were
  human-authorized; a fifth is the human's call.

## 2026-08-22T02:10Z — #195 (code) — targeted claim audit (human-authorized)

- Human chose the narrow option: audit every factual assertion in the diff rather than another
  general review. Correct call — it found a FOURTH instance of the same class, which a general
  review had just missed.
- Audit verified ~70 claims and independently re-ran all five reproductions the docs assert (the
  `HOME_realuser` allow-set leak, the `C:\Users\realuser` dict key, the numeric `account_id`, the
  newline-separated bearer token, the `dd9cca` substring false-abort), plus both regex regressions
  and the `SubstitutionConflictError` catch-all leak. All behaved exactly as written. It also
  verified the "pre-existing" and "not a regression" claims against `main` and against the
  intermediate commits rather than taking them on trust.
- Five failures, none behavioral:
  1. PRD's "the pattern *bodies* of the built-ins are alphanumeric" is false — `conn-string-pw`
     uses negated classes accepting quotes and backslashes, `pem-private-key` is a literal with
     spaces and dashes. **Third revision of the same sentence across three commits, each written
     to correct the last and each introducing a new unverified assertion.**
  2. README still said "three things" after the list grew to four; #198 carried the stale count
     AND the superseded completeness bullet its own later text contradicted.
  3. A test comment named `axbQ` as the discriminator for raw-vs-escaped compilation. It matches
     under neither reading, so the assertion proved nothing and **the test was passing for the
     wrong reason** — the Class B shape, found by reading rather than mutation. Now `axb0`.
  4. The parametrized skip-name set was described as #195's set; it is neither subset nor superset.
  5. The module docstring credited RFC-2606 fixtures the module does not contain.
- All fixed. Suites 412+4x / 64 / 16 OK, prettier clean, hermetic green.

## 2026-08-22T02:45Z — #195 (code) — security review (step 9)

- **Pipeline-position error caught before it cost anything.** The parent told the human "next is
  the merge gate" while steps 9 and 10 had never run, and the human's "merge it" was given on that
  belief. The ledger was correct throughout — no block existed for either gate. Caught by re-reading
  `progress.md` before acting on the approval. Recorded upstream as dev-loop v0.2 finding 9: a
  compaction event inside one invocation is context loss that never re-arms step 0's ledger read,
  and the Gate-outcome invariant is a journalling rule with no precondition at step 11 to enforce it.
- `SECURITY_REVIEW` = local `/security-review` skill (§4 binding). Due: the diff touches
  `tooling/sanitizer/` and `.github/workflows/`. Precondition verified — `origin/HEAD` resolves to
  `refs/remotes/origin/main`.
- Ran at `8788b4a`, the merge candidate. **Verdict: no HIGH or MEDIUM findings.**
- Verified: `ResidualRuleError` carries only `section`/`index`, never `Rule.pattern`, `Rule.replace`
  or the matched span; the raise site does not carry `text`/`rule` onto the exception and the CLI
  prints no tracebacks. Abort precedes `build_sidecar` and `_atomic_write_pair`, so neither output
  nor sidecar exists on the exit-2 path. `json.JSONDecodeError` and `RecursionError` land in the
  catch-all at exit 2 with nothing written — fails closed. Index arithmetic correct: `enumerate`
  runs over the full section before the regex filter, so `section[index]` names the right config
  line. Diff grepped for real PII (`fdpearce`, `fpearce@`, `@gmail.com`, real home paths): zero hits.
- Two observations recorded, neither blocking:
  - **Confirmation oracle.** Someone who can inject content into a session and observe the exit code
    can plant a candidate string in an unreachable position and learn from exit 2 that it matches a
    config literal. Confirms guesses rather than extracting values, needs repeated observed runs, and
    the pre-#195 behavior was strictly worse (the value shipped). Matters only if this repo ever runs
    the sanitizer over third-party fixtures in CI where exit codes are public.
  - **Real sessions with file paths as `toolUseResult` dict keys now abort at exit 2** and are
    unscrubbable until #190 lands. Fail-closed and correct, and it raises #190's urgency — it is
    already queue row 2, unblocked by this merge.
- `SubstitutionConflictError` leaking an original via the catch-all was considered and excluded as
  pre-existing and unchanged here; this branch only corrects the comment that falsely called the
  catch-all span-free, and files #196.

## 2026-08-22T05:25Z — #195 (code) — acceptance gate (step 10)

- Fresh AC-verifier spawn against `8788b4a`. #195 carries no `## Acceptance criteria` block, so the
  gate ran against the 11 criteria derived in the plan from its Test plan / Proposed change /
  Versioning sections, with the human-approved narrowings stated up front.
- **BLOCKERS: none.** A/B/C/E/F/G/I/K MET; D/H/J SUPERSEDED-AND-MET against the narrowed scope.
- The verifier probed rather than read wherever a criterion asserts runtime behavior. Notable:
  - Byte-neutrality proved cross-version, not just by the golden suite: it extracted `origin/main`'s
    `src/` to scratch and ran both builds on the same clean input, `cmp`-clean across all five
    synthetic fixtures, sidecar identical modulo `sanitizer_version`.
  - Position-agnosticism proved on a position **no test names** — a dict key nested inside a list
    inside an MCP `tool_use.input`, plus an `embedding_tokens` suffix-skipped key.
  - It reproduced the allow-set leak against `origin/main`'s code to confirm the prose is not
    invented: `main` writes `/home/realuser` at exit 0, this branch aborts at exit 2.
  - It verified the three uncovered classes behave exactly as documented — regex+dict-key, numeric
    leaf, JSON-in-string leaf all exit 0 with `residual_scan: clean` — rather than better or worse.
- Three notes carried forward, none blocking:
  1. **`residual_scan: clean` is an unqualified string in the sidecar.** PRD §10 enumerates the four
     non-attestations, but a downstream reader who never opens the PRD reads "clean" as total.
     Candidate for a machine-readable scope marker; belongs in #198.
  2. **README semver table (`README.md:174`) is now stale.** MINOR promises "your existing config
     keeps working, output may scrub *more*"; there is no "refuses more" clause, which is in tension
     with the deterministic-abort hazard this branch documents at `residual.py:247-261`. NOT fixed
     pre-merge: a commit would re-arm both gates and CI for a one-line doc edit the gate called
     non-blocking. **Carry into the #190/#194 PR**, which touches the same README.
  3. ~~`TEST_CMD` suite 3 in `loop.config.md` is wrong.~~ **RETRACTED 2026-08-22 — it is correct.**
     The config says `python -m pytest tooling/tests -q`, path-scoped from the repo root, which is
     the working form. The orchestrator paraphrased it as `cd tooling && python3 -m pytest -q` when
     writing the AC-verifier's brief, dropping the path argument; the verifier accurately reported
     "suite 3's invocation **in the brief** is wrong" and speculated the config needed the fix. The
     orchestrator relayed the speculation as fact without opening `loop.config.md`. Same
     unverified-claim shape this row spent five rounds on, committed in the report about it.
     Human caught it. Dev-loop finding 10.

## 2026-08-22T05:28Z — #195 (code) — merge + close (steps 11-12)

- Merge-gate roll-call, all bound to `8788b4a` = the merged tree: plan gate human-approved; code
  review clean after 5 rounds + a targeted claim audit; security review no HIGH/MEDIUM; acceptance
  gate no blockers; CI green on all six checks; human merge approval given.
- **Squash subject corrected at merge time.** The PR title still read "total output-side oracle";
  the guarantee was narrowed to literal rules in round 1. Merged as "output-side oracle for
  **literal** path/identifier rules" so `main`'s history does not carry the overclaim the branch
  spent five rounds removing. Message-only, so it re-armed nothing.
- Squash-merged as `91adca1`, branch deleted local + remote, #195 closed, local `main` fast-forwarded,
  tree clean.
- Row 1 → `done`. Rows 2 (#190) and 3 (#194) unblocked; they land together as one PR and the PyPI
  0.4.0 publish is gated on them.
- **Row retrospective.** Six commits, five review rounds plus an audit. Every round after the first
  found zero code defects and at least one false claim about the code. The code was right after
  round 3; what kept failing was prose asserting properties nobody had checked, on a tool whose
  entire subject is that an attestation must not outrun what was verified.
- STOP. One issue per invocation.

## 2026-08-22T14:05Z — curation (step 1 roster reconciliation)

- Live `epic:sanitizer` roster (8): #1, #32, #42, #190, #192, #194, #196, #198.
  `queue.md` rows (7): #1, #32, #42, #190, #192, #194, #195.
- **Joined since init** — surfaced once each, never auto-added:
  - `- surfaced-join: #196` — `fix(sanitizer): ConfigError messages print rule match values,
    which are the literal PII`. Filed after init. No priority label.
  - `- surfaced-join: #198` — `sanitizer: regex path/identifier rules get no output-side
    verification (#195 scoped to literals)`. Filed as the carve-out when #195's guarantee was
    narrowed to literal rules in review round 1. No priority label.
- **Left:** #195 is no longer in the open roster because it closed on merge. Its row is terminal
  (`done`), so the leave rule does not apply and nothing is surfaced.
- Neither joiner changes this iteration's selection: both are unlabeled, which ranks below
  `priority:low`, and two `priority:high` rows are already selectable.

## 2026-08-22T14:40Z — #190 (code) — plan gate (step 5) — STOPPED

- Selected #190 mechanically: `priority:high`, tiebreak issue-number ascending (#190 < #194).
  Row set `planning`. Budget caps both `none`, so the step-1 check is inert.
- Baseline before any change, all four suites green: sanitizer 412 passed + 4 xfailed
  (the four are the `13-dict-key-not-value` strict xfails this issue must flip);
  format-scan 49; tooling root 15; hooks 16 OK. **This also settles the retracted
  `TEST_CMD` suite-3 claim from the #195 row: `python -m pytest tooling/tests -q` from the
  repo root is correct as written in `loop.config.md`.** Verified by running it.
- **Falsifier discharged by running, not asserting** (step 3). Probed merged `main` `91adca1`
  with a positive control. Literal rule + value in a dict key → exit 2, nothing written.
  **Regex rule + same key → exit 0, value present in output, sidecar `residual_scan: clean`.**
  Control: same regex rule, same value in a string leaf → correctly redacted. So the rule
  works and the key position is the defect.
- **Finding: the "usability only" reframe on #190/#194 is wrong for regex configs.** The
  issues, both "Rescoped under #195" comments, and the CHANGELOG all state the remaining work
  is making the position scrubbable rather than refused. True for literal rules only. For a
  `re:` rule the oracle deliberately does not re-verify (`residual.py:189-206`) and the walk
  never visits keys, so the original silent leak is unchanged on `main` today. Recorded
  nowhere before this row.
- **AC audit corrected a claim of my own before it shipped.** I first wrote that ACs 1/3/5 were
  already satisfied by #195. Reading the tests showed AC-3 is **not**: the nearest test
  (`test_residual_rules.py:299`) plants `input.usage.x`, a nested *value* under a skip-listed
  name — #194's shape, not a nested key. Every key-position test in the suite plants the key
  one level deep. AC-3 is a real coverage gap.
- **Design hazard found and verified, for the architect gate.** Naive key transformation is not
  just a shape change, it **silently destroys records**: two keys mapping to one placeholder
  collapse to a single entry, last writer wins, no error and no sidecar trace. Any key-scrubbing
  design needs a fail-closed collision check.
- **SCOPE_AGENT (`pm`) consulted** on the one-PR-vs-two question (step 3 → Escalation rubric).
  Ruling: **override the "land together as one PR" note — two separate sequential PRs**, both
  under one `sanitizer-v0.4.0`; a release covers merged commits, not a single PR, and the two
  fixes touch distinct code with distinct test matrices. **Order: #194 first, then #190**, on
  risk/confidence grounds (#194 is decided and bounded; #190 carries the open design question).
  It also ruled #198 mis-labeled (recommends `priority:high` + `bug`) and scoped #190 to a hard
  enumerated known-data allow-list with everything else staying fail-closed, plus a pre-blessed
  fallback of closing #190 as "refusal is the contract for keys" if the allow-list cannot be
  enumerated defensibly. It listed the split confirmation as blocked on the human.
- **Architect gate (step 4): NOT RUN.** `## Approach` was frozen in anticipation, but
  `DESIGN_AGENT` was not consulted — the sequencing ruling may re-point this iteration to #194,
  which would make an architect pass on #190's mechanism wasted. Stated plainly rather than
  journalled as skipped-for-route.
- Plan-gate: n/a: architect skipped (not consulted at step 4 or step 5; sequencing unresolved).
- Human gate: STOPPED for plan approval (plan-gate: always). Row stays `planning` — a
  `planning` row is by definition unapproved and re-enters at step 5.
- Open decisions put to the human: (1) confirm the two-PR split; (2) confirm #194-before-#190,
  which overrides the engine's mechanical tiebreak; (3) whether to relabel #198; (4) whether to
  post the regex reproduction to #198 and cross-link #190/#194.
- STOP. One issue per invocation.

## 2026-08-22T14:55Z — human decisions on the #190 plan gate

- **Sequencing: #194 first, two separate PRs.** Human took the `SCOPE_AGENT` ruling, overriding
  both the "land together as one PR" note in #195/#190/#194 and the engine's mechanical
  issue-number tiebreak that had selected #190. Row 2 (#190) reverted `planning` → `routed`;
  its plan file is retained, unapproved. Row 3 (#194) is next up.
- **Tracker writes, all human-authorized, all completed:**
  - Reproduction + positive control posted to #198 (`issuecomment-5379152940`), with the
    suggested acceptance vectors and the note that `test_adversarial_placement.py` has no regex
    payload family, so no cell in the existing matrix can observe this class.
  - Corrective cross-links posted to #190 (`issuecomment-5379155073`) and #194
    (`issuecomment-5379155292`), fixing the "usability only" framing in place. #190's carries
    the two planning findings (key-collision record loss; the uncovered nested-key criterion).
  - #198 relabeled: `+priority:high`, `+bug`, `-enhancement`. Now `bug, epic:sanitizer,
    priority:high`. **`enhancement` was removed, not just supplemented** — flagging the removal
    explicitly since the question offered "relabel" and that is the reading taken.
- **Joiners #196 and #198 remain surfaced-but-not-added**, per the curation rule that a bare
  surface never adds a row. Relabeling #198 is not the same as pulling it into the run; it stays
  out of `queue.md` until the human says pull in.
- **`issue-190.plan.md` retained** with its frozen `## Approach` block and a provenance note: no
  architect pass ran, the block is a genuine pre-image, and part of a future step-5 diff will be
  non-architect change from this ruling. Recorded so that diff is not misread as an architect
  redirect.
- Iteration ends here. #190 reached the plan gate and was re-pointed; no PR opened, so no open
  record is owed and none was written. Next invocation selects **#194**.
- STOP. One issue per invocation.

## 2026-08-22T16:20Z — #194 (code) — plan gate (step 5) — STOPPED

- Resumed clean: no interrupted rows, **zero open PRs** (orphan scan clean), no stray worktrees,
  no retained `mutate-verify-*` snapshot dir. Roster reconciliation: joiners #196/#198 already
  surfaced at 14:05Z, deduped, not re-surfaced. #195 left the roster but its row is terminal.
- Selected **#194**, not the mechanical tiebreak. `priority:high` ties with #190; the human's
  14:55Z ruling puts #194 first. Row 3 → `planning`. Budget caps both `none`, check inert.
- Baseline all four suites green on `91adca1`: sanitizer **412 passed + 4 xfailed**,
  format-scan 49, tooling root 15, hooks 16 OK. **Gotcha recorded:** the sanitizer suite reports
  411+1 skipped unless `.venv/bin` is on `PATH` — `test_cli_smoke.py:45` skips with
  "ccs-sanitize entry point not on PATH". A silently-skipped CLI smoke test is the
  gate-that-did-not-run shape; the run command needs the PATH prefix. **Config finding for the
  human — I did not edit `loop.config.md`.**
- Hermetic wrapper pre-verified socket-level on this host: direct-IP connect fails under
  `unshare -rn` + `ip link set lo up`, succeeds without it.

- **Falsifier discharged by RUNNING (step 3), and it was refuted.** Probe A, 16 positions inside
  `tool_use.input`, one synthetic value, on merged `main`: **literal rule 16/16 FAIL-CLOSED**
  (exit 2), **regex rule 16/16 LEAKED** (exit 0, value present). Positive control
  `input.plain_control` REDACTED under both, so the rules work and the position is the defect.
  The "usability-only after #195" framing in three separate comments is wrong for regex configs.
- **New finding not in the issue, its two corrections, or the prior architect review.** Probe B:
  `build_identifier_transform` matches bare names at any depth too, so
  `input.gitBranch: "release/2026-q3-payments"` → `"feature/example"` under **default** options.
  Silent corruption of a tool parameter. (`input.sessionId` → synthesized UUID under
  `remap_uuids: true` was known, one line, in the Rescoped comment.)
- **Prevalence: NULL RESULT, reported rather than buried.** Full key-path survey of `fixtures/`
  (8 files, 1,494 records, v2.1.150-2.1.185): **zero** occurrences of any skip-listed name inside
  a `tool_use.input` subtree. Does not refute the bug — the probe proves the mechanism and MCP
  schemas are open — but it is the honest number and it sits in tension with `priority:high`.
- **AC provenance flagged:** #194 has **no explicit AC block**. AC-1..AC-7 are derived from its
  Test plan + the Rescoped comment, quoting where possible. Posting them to #194 is a plan-gate
  ask, not something done unasked — otherwise step 10 would certify criteria I wrote myself.

- **Architect gate (step 4): RAN.** Freeze taken first and verified byte-identical to the live
  `## Approach` before `DESIGN_AGENT` was invoked; outcome applied to the plan text before step 5.
- **Architect verdict: endorse the mechanism, two blocking/three important on the execution.**
  - **C1 (blocking)** — the frozen plan's `**` subtree prefixes reintroduce the deleted
    skip-anywhere pattern; `error.**` regresses a scrubbed leaf to skipped.
    **I verified C1 rather than adopting it, and it is understated:** enumerating `error.*`
    string leaves returns `error.headers.set-cookie` (`_cfuvid=…`),
    `error.headers.anthropic-organization-id` (a real org UUID), `error.error.request_id`,
    `error.error.error.message`. `error.**` would have skipped every one. **Went one step past
    C1: dropped prefixes entirely** — proved both `usage` subtrees hold exactly four string
    leaves each, all closed enums, so eight exact entries replace the last two prefixes.
  - **C2** — separate "no-op to visit" from "must preserve"; three tiers now. Dropped
    `message.content.content.type`. Proved `message.diagnostics` has exactly one string leaf.
  - **C3** — the UUID transform couples to this change and
    `test_uuid_fields_match_pipeline_skip_list` would stay **green while its invariant breaks**.
    Pulled into this PR as AC-8.
  - **C4** — `gitBranch` must not ship untracked → AC-9. **C5** — drift test now → AC-10.
  - Architect **reconciled its own prior claim**: "`toolUseResult` is arbitrary MCP output" was
    too strong; it is a mixed envelope, which strengthens rather than weakens the allow-list.
- **Plan-gate: material (a fork re-chosen: subtree prefixes → exact paths, ruled a blocking
  regression; steps added: UUID transform + gitBranch + drift test; files-to-touch changed:
  rules/identifiers.py and PRD §13 added; an AC split into AC-8/AC-9/AC-10) → STOPPED.**
  Frozen-vs-live diff taken: 87 → 128 lines, +106/-65.
- Human gate: STOPPED for plan approval (plan-gate: always). Row stays `planning` — a
  `planning` row is by definition unapproved and re-enters at step 5.

- **Process deviation, surfaced not hidden.** The `architect` subagent posted its full review to
  #194 on its own initiative as `issuecomment-5379462629`. My prompt said not to write to the
  tree; it has `mcp__github__*` and treated the issue as the recording surface — which is where
  this project does record architect decisions, but the engine says that record is written by
  the orchestrator, not the agent. Not double-posting. Two questions for the human: leave it, and
  should that agent's tool grant be narrowed.
- **Observation, not scope.** `fixtures/sanitized/` contains `anthropic-organization-id`
  (`c86124b6-…`) and `set-cookie: _cfuvid=…` values at currently-scrubbable positions. Found
  while verifying C1. Not this issue's job; flagged because committed-fixture content is a
  standing CLAUDE.md concern and that judgement is not mine to make alone.
- No PR opened, so no open record is owed and none was written.
- STOP. One issue per invocation.

## 2026-08-22T17:30Z — #194 (code) — iteration open

- Issue: #194 — fix(sanitizer): bare-name skip-list exempts user data inside tool inputs
- Route: code
- Branch: fix/194-anchor-skip-list
- PR: #200
- Status: in-pr

## 2026-08-22T17:45Z — #194 (code) — CI green (step 7 tail)

- PR #200, commit `d9a2bd0`. All six checks pass: prettier, pytest py3.11/3.12/3.13,
  build + twine check, and the required `sanitizer-ci` aggregate. **No CI fix was needed, so
  no gate verdict is re-armed** and the review below binds the merge candidate.
- Row → `in-review`.

## 2026-08-22T18:40Z — #194 (code) — code review round 1 (step 8)

- `/code-review high` on the branch diff, given the ten acceptance criteria. **10 findings, 2 high.**
  Nine implemented, one contested and escalated. Both high findings were **verified by ablation
  before being accepted**, not taken on trust.
- **F1 (high) — the stated safety net did not exist.** `pipeline.py`, PRD §6b and the CHANGELOG all
  claimed a forgotten allow-list entry would turn `test_golden_determinism.py` red. Reviewer
  ablated all 30 entries: 0/30 caught. I reproduced it by dropping
  `("message","usage","speed")` — golden suite: **14 passed**. The claim is false and was the whole
  safety argument for choosing over-scrub as the failure direction. Removed rather than softened,
  and replaced with guards that actually work: the allow-list contents are now **pinned literally**,
  and each entry is ablation-tested against a config whose rule matches the value at that position.
  **The per-entry test alone was not sufficient and I checked that too** — it parametrizes over the
  allow-list, so deleting an entry deletes its own case; the literal pin is what closes it, verified
  by dropping BOTH `speed` entries (the case the reviewer flagged as escaping the collision test).
- **F2 (high) — AC-9 shipped with zero regression coverage.** Reviewer reverted both #199 guards to
  bare-name and the full suite stayed green. Reproduced. Two tests added; confirmed to fail against
  the reverted guards and pass against the fix, with `identifiers.py` restored to HEAD afterwards.
  This is the same green-over-a-live-corruption-path shape the CHANGELOG criticises the OLD uuid
  test for, reproduced in the fix for that very issue.
- **F3 (medium) — my evidence was wrong, the decision was right.** "`toolUseResult.agentId` carries
  the same value as line-level `agentId` (25 records)" conflated an occurrence count with a match
  count. Verified: 2 distinct line-level values, 25 distinct `toolUseResult` ones, **zero same-file
  overlap in all six files**, one cross-file match. The link is cross-FILE, which is exactly why a
  shared `uuid_seed` matters, so the placement stands and the reasoning is now reproducible.
- **F5** CI presence + did-it-run guard for the drift suite (the workflow already had this pattern
  for two other self-skipping suites). **F6** tier test now checks four tiers pairwise + partition.
  **F7** the `attachment.type` counterexample recorded — I had noticed it while planning and then
  wrote a CHANGELOG claim that ignored it. **F8** `_REGEX_CONFIG` now carries both rules so the
  regex half exercises the identifiers layer. **F9** `thinking.signature` rationale was inverted;
  verified `residual.py` has no positional exemption. **F10** stale present-tense #194-is-open
  claims fixed in `residual.py` and two test modules.
- **F4 CONTESTED, not decided by me.** Whether `message.content.content.type` /
  `toolUseResult.content.type` belong on the allow-list: the **architect** ruled drop them as
  arbitrary tool output; the **reviewer** argues they are Anthropic content-block discriminators
  (values only `text`/`tool_reference`) and that the tool controls `text`, not `type`. Two agents
  disagree → human. This is also an always-escalate merge condition.
- Gates re-run after the fixes: all four suites **498 passed + 4 xfailed** / 49 / 15 / 16 OK,
  prettier clean, and the **hermetic tier re-run** because adding tests re-armed its trigger.
- `- Hermetic: pass` (re-armed by the round-1 test additions; final state recorded here).
- Fixes committed as `0a78bcc` and pushed **before** spawning the re-check, so the checker reads the
  fixed head rather than certifying pre-fix code.
- Round 2 = one fresh checker, a new spawn (not me, not the round-1 reviewer).

## 2026-08-22T19:25Z — #194 (code) — code review round 2 (fresh re-check) — DIRTY, ESCALATED

- Round 2 was a **fresh spawn**, not me and not the round-1 reviewer, reading commit `0a78bcc`
  (pushed before the spawn so it read the fixed head). It re-derived the evidence rather than
  trusting the claims: it re-ablated all 30 allow-list entries under BOTH golden configs (60 runs),
  re-reverted the #199 guards, and recomputed the `agentId` corpus counts.
- **The three substantive fixes hold, independently verified.** F1's claim is accurate and no stale
  "turns red" text remains; F2's two tests fail for the right reason and exactly those two fail;
  F3's numbers are right to the digit. F6, F7, F9, F10-in-the-three-named-files also confirmed.
- **But round 2 returned four findings, three of them introduced by MY fix commit:**
  - **My F8 fix is a false claim and made the cells WEAKER.** Adding
    `identifiers: re:realuser` to `_REGEX_CONFIG` does not make the regex cells exercise the
    identifiers layer: the paths layer runs first and rewrites `/home/realuser/app` to
    `/home/user/app`, after which `re:realuser` cannot match. Instrumenting the substitution table
    shows only `paths` labels. Deleting the rule leaves the module green. Worse, the rule produces
    byte-identical output to the paths rule, so it would now **mask a paths-layer regression** in
    those cells. The original F8 finding stands unfixed and diagnostic power went down.
  - **My CI error message overstates, which is F1's defect in miniature.** "If it skipped,
    fixtures/ was not found and the scrub boundary is unguarded" is false: without `fixtures/`,
    32 of 35 tests still run, including the literal pin and all 30 ablation cells — the two guards
    the same comment calls load-bearing. I wrote an unsupported claim **inside the commit whose
    subject was correcting unsupported claims.**
  - **The new CI step was inserted in the wrong place**, orphaning the placement-matrix comment
    above it and leaving the placement-matrix step with no comment.
  - **Four more present-tense "#194 is open" statements** survive in PRD §5 (`:134`, `:153`) and
    CHANGELOG (`:170`, `:195`), now directly contradicting text the fix commit added a few lines
    away — including inside the same unreleased `[0.4.0]` section.
- **F4 (contested) refined, still not mine to settle.** Round 2's read: `toolUseResult.content.type`
  is clearly right to leave off; `message.content.content.type` has the better *technical* case for
  inclusion (it is an API content-block discriminator, values `text`/`tool_reference`) and the
  better *safety* case for exclusion; and either way the code comment's stated reason is wrong,
  because it calls the `type` KEY arbitrary tool output when the arbitrary part is the sibling
  `text`. It also notes the internal inconsistency: `message.content.type` IS allow-listed as a
  content-block discriminator while the identical discriminator one level in is not.
- **Also flagged, and I am not resolving it:** the cross-file `agentId` design claim is evidenced
  only by a **synthetic** fixture pair this repo authored; no sanitized real-derived file shows a
  cross-file match. The counts are right; the design claim should be sourced to `reference/` rather
  than to the corpus.
- **Gate outcome: round 2 DIRTY → escalate, no round 3** (Fresh-re-check invariant, 2-round cap).
  Not fixing these on my own judgement. The row stays `in-review`; steps 9 (security) and 10
  (acceptance) have NOT run, and nothing is merged.
- CI on `0a78bcc`: 6/6 green, and the new drift guard verified to actually execute in CI (35 passed
  in the py3.11 job log), not silently skip.

## 2026-08-22T19:40Z — #194 (code) — human directed round 3 (step 8, re-opened)

- **Round 3 exists because the human directed it**, not on my judgement: "have the architect review
  the code review findings and make a recommendation on each ... then invoke a third code review".
  The 2-round cap had been reached and escalated; the human's answer was to continue.
- `DESIGN_AGENT` invoked on the four round-2 findings plus the contested F4 and the synthetic-
  evidence flag, asked for a disposition + concrete replacement wording per finding, and explicitly
  told **not** to write to the tree or post to the tracker (it posted unprompted last time).
- **Pre-emptive evidence gathered on R2-1, and the finding is BROADER than round 2 stated.**
  Instrumented the substitution table: at the #194 positions, `_BASE_CONFIG`'s **literal** config
  fires only `paths` labels too, not just the regex one. The paths rule consumes
  `/home/realuser/app` before the identifiers rule ever sees it, so **no #194 cell in either
  parametrization has ever exercised the identifiers layer.** Round 1 called this a regex-config
  gap; it is a both-configs gap. An identifier-shaped payload with no path prefix
  (`realuser-workspace`) does fire `identifiers` and redacts to `user-workspace`.

## 2026-08-22T20:15Z — #194 (code) — architect rulings applied, round 3 review running

- **Architect ruled on all six items** (four round-2 findings + contested F4 + the synthetic-
  evidence flag), with replacement wording per item. It did **not** post to the tracker this time.
- **Headline: no approach change and no scrub-boundary movement.** F4 was the only item that could
  have moved the boundary; the architect DECLINED the addition. `_ENUM_PATHS`, the literal pin and
  `_KNOWN_NAME_COLLISIONS` are untouched. So nothing here needed a fresh plan-gate escalation —
  recorded explicitly because a post-plan-gate design consultation is exactly where that question
  arises.
- **R2-1 FIX** — reverted the inert identifiers rule. The architect's ruling matches the evidence I
  had already gathered, and the finding was broader than round 2 reported: under the LITERAL config
  too, only `paths` labels fire. Comment now states the real scope rather than claiming coverage it
  does not have. Architect flagged a genuine identifiers-under-regex cell as OPTIONAL; not taken.
- **R2-2 FIX** — the CI overclaim corrected and the step renamed to what it actually asserts
  (corpus-drift checks, not the boundary). Verified the underlying fact: 3 of 35 tests take the
  corpus fixture; the pin and all 30 ablation cells do not.
- **R2-3 FIX** — steps reordered so each comment sits above its own step. First rebuild attempt
  double-inserted the step; caught by parsing the YAML and listing step names rather than eyeballing
  the diff, then rebuilt from a clean `git checkout`.
- **F4 DECLINE + comment FIX** — the exclusion stands, the justification was false in two places.
  New reason is the **format boundary, not nesting depth**: `message.content.type` discriminates the
  rigid Anthropic-API block and is listed; these two exist only inside a `tool_result` payload, on
  the tool-controlled side of the boundary this fix polices.
- **R2-5 FIX** — `toolUseResult.agentId` justification re-anchored to `reference/` rather than to a
  corpus whose only cross-file match is a synthetic fixture pair this repo authored.
- **R2-4 FIX** — five stale present-tense "#194 is open" claims reworded, not deleted, since the
  #198 regex-oracle argument around them is still live. The fifth was found by my own sweep, not
  reported by either reviewer: the publish-hold note said the release waits for #190 **and #194**.
- Gates re-run: all four suites 498+4x / 49 / 15 / 16 OK, prettier clean, hermetic tier green.
  `- Hermetic: pass`.
- Committed `657424e`, pushed. **Round 3 review invoked** per the human's direction.
- Note for the budget line: round 3 exists by human direction after the 2-round cap was reached and
  escalated, not by the loop re-opening a gate on its own judgement.

## 2026-08-22T21:30Z — #194 (code) — code review round 3 — 5 fixed, 1 ESCALATED (boundary)

- Round 3 (human-directed) **verified the load-bearing claims independently**: re-ablated all 30
  allow-list entries against BOTH golden configs (60/60 byte-identical, so the golden test genuinely
  cannot see a dropped entry); confirmed every corpus number; confirmed the `reference/` citations
  added for `toolUseResult.agentId` actually say what is claimed; and confirmed the `_REGEX_CONFIG`
  revert argument is sound with **no real AC-5 gap** (the orchestrator applies
  `identifier_transform(path_transform(...))` and the cells hold one `realuser` leaf, so an
  identifiers rule provably cannot fire there under either config).
- **Six findings. Five fixed, all mine, all prose or diagnostics:**
  - The retracted golden-test claim **survived in a second CHANGELOG location** — retracted at
    length in one paragraph, re-asserted 40 lines later. Third round in a row this defect class has
    appeared, and this time it survived inside the commit that removed its twin.
  - **The monotonicity claim was wrong for #199, and it matters on upgrade.** "Both are
    monotonically safer: more values get scrubbed" is true of #194/#195 but **false for #199**,
    which scrubs LESS at its anchored positions: 0.3.x blanket-replaced `input.gitBranch` with the
    placeholder; 0.4.0 emits it verbatim if no rule matches. The PR's own test asserts that. The
    removal is still right (it was corruption of a value the config never asked to touch), but an
    upgrader will see a value 0.3.x had overwritten. Release note now says so explicitly.
  - The F4 defence said "the exempt list stops here and everything under a tool result
    over-scrubs" — **twenty lines above six allow-list entries under `toolUseResult`**. That wording
    came from the architect's ruling and **I applied it without checking it against the list.**
  - Two more stale claims in the same unreleased section (#191 entry: "14 structural positions" when
    the module now has 19; "its cells ... never collide with a skip-listed name" when cells 15-19,
    added by this PR, do). I had updated the module docstring and not its changelog entry.
  - Inverted failure diagnostic in `test_pipeline.py` — printed the payloads that WERE visited under
    the heading "not visited". Fixed to print the difference; **verified by re-introducing a
    usage-parent skip** and confirming it names `PAYLOAD-usage-child` alone.
- **ESCALATED, not decided: `("toolUseResult","type")` may be a residual #194-shaped exemption.**
  New evidence found while checking it, which strengthens the finding beyond what the reviewer had:
  the corpus shows **three** distinct values there (`text` 41, `create` 29, `update` 9), so it is
  **not a closed enum** — it varies by tool, matching the data dictionary's "Tool-specific subtype
  indicator" and "the shape is tool-dependent". By contrast `message.content.caller.type` is a
  single value (`direct`, 342). Removing it would change the pinned allow-list, so it is a
  scrub-boundary decision and belongs to the human.
- Also from that finding: **AC-6 is incomplete** — PRD §6b B's enum-tier enumeration omits
  `toolUseResult.type` and `message.content.caller.type`, the two entries most needing justification.
  Held with the boundary decision since the PRD text depends on it.
- Gates re-run: 498+4x / 49 / 15 / 16 OK, prettier clean, hermetic green. `- Hermetic: pass`.
- Committed `987cbd8`, pushed. **Currency note for the merge gate: these fixes land DOWNSTREAM of
  round 3's verdict, so no review has certified `987cbd8`.** That is stated plainly rather than
  carried as a clean verdict.

### 2026-08-22 — #194 boundary decision applied, architect re-audit in flight

- **Human ruled on the escalated finding: remove `("toolUseResult","type")`.** Applied in `0a8361d`,
  pushed. That position is now visited and scrubbable. Touched `_ENUM_PATHS`, the literal pin
  `_EXPECTED_ALLOW_LIST`, and `_KNOWN_NAME_COLLISIONS` (the entry moves from allow-listed to a
  pinned, deliberately-rejected collision, so the decision is recorded where a future reader hits it).
- **AC-6 closed with it.** PRD §6b B's enum tier now enumerates `message.content.caller.type` and
  states the deciding rule plus both rulings.
- Verified by running, not asserting:
  - Per-entry golden ablation re-run at the new size: **blind to 29/29**, so the "golden cannot see a
    dropped entry" claim in the PRD and CHANGELOG still holds *at the number they now state*. Both
    documents were updated 30 → 29 before this was re-run, not after.
  - The same 29 ablations against `test_skip_allow_list_corpus.py`: **0/29 blind, all caught.** The
    guard is where those documents say it is.
  - Direct predicate probe: `toolUseResult.type` visited and redacted; `caller.type` and both `usage`
    subtrees still exempt.
- Gates: 497+4x / 49 / 15 / 16 OK, prettier clean, hermetic green. The 498 → 497 delta is exactly the
  removed entry's own ablation cell.
- **Architect invoked on a design question the removal creates, before review round 4.** The removal
  generalized into a written rule ("who chooses the value, not whether the key is named `type`"), and
  that rule was *derived from one entry and applied to one entry*. My own read is the only thing
  backing that the other 29 survive it. Asked for: (1) does any remaining entry fail the rule,
  (2) is `message.content.caller.type` genuinely format-side or is "one value observed" too weak,
  (3) is the rule worth writing down given it has no mechanical check, (4) scope completeness.
  Instructed explicitly not to post to GitHub — the round-1 invocation did that unprompted.
- **Currency: `0a8361d` is uncertified.** No review has run on it. Round 4 is next, after the
  architect's rulings land.

### 2026-08-22 — architect re-audit returned, applied in `82876aa`

- **Ruling: no blocking findings.** It walked all 29 remaining entries against the ownership rule
  and found none that fails it — nothing else comes off. It scrutinized the four
  `toolUseResult.usage.*` entries and `toolUseResult.agentId` hardest (they sit in the
  tool-dependent envelope) and kept all five: `usage` is the runtime's billing rollup, `agentId` is
  runtime-generated. It did NOT post to GitHub this time.
- **Two real findings, both mine, both applied:**
  - **The recorded rule invited the wrong test.** I wrote "who chooses the value" and then led every
    explanation with the value COUNT. The corpus refutes that reading: `version` takes **4** distinct
    values and `message.model` takes **4** — *more* than the entry I removed — and both correctly
    stay exempt. Cardinality cannot be the test. Both counterexamples are now named in the tier
    comment and PRD §6b B. This matters because the wrong rule, left written down, would have
    mis-classified the next candidate.
  - **The `caller.type` exemption rested on its weakest evidence** ("one value, 342"). Verified the
    structural argument instead: `caller` appears **342/342** as a sibling of `input` on a
    `tool_use` block, key set `{type,id,name,input,caller}`, on no other block kind. A tool controls
    the contents of `input` and nothing else, so it cannot reach `caller`. Holds regardless of
    future caller kinds.
- **Checked the architect's one testable claim rather than accepting it.** It asserted the committed
  sanitized fixtures need no re-scrub. Ran all **79** `toolUseResult.type` occurrences across both
  through the full pipeline under the shipped PII-free template: **zero moved.** Scope stated in the
  commit and PR body, since the live config is read-denied: verified under the template, reasoned
  for the live config.
- **Recorded the rule's weakness rather than papering over it:** ownership is human judgment read
  off format docs that are themselves incomplete. Declined the mechanical proxy (pinning observed
  value-sets) on the architect's reasoning — it would fire constantly on `version`/`model`.
- **Follow-up, NOT filed (no authorization for a new tracker write):** `caller` is undocumented in
  `reference/data-dictionary.md`, so that exemption's "format-owned" premise lives only in sanitizer
  comments. Surface at the merge gate for the human to decide.
- Gates re-run: 497+4x / 49 / 15 / 16 OK, prettier clean, hermetic green. Allow-list byte-identical
  to `0a8361d` — this commit is comments, spec and changelog only.
- PR body corrected too: it was carrying the round-1-**retracted** golden-test claim in **two**
  places, plus the wrong monotonicity framing and a stale suite count (465).
- **Currency: `82876aa` is uncertified.** Round 4 next.

### 2026-08-22 — review round 4 (5 reviewers) + architect; fixes in `b21a4cf`

- **`/code-review` binding is UNINVOCABLE in this session** — the plugin is marketplace-only, not
  enabled, and `Skill(code-review:code-review)` errors. Per the engine that is not permission to
  skip the gate, so round 4 was composed INLINE: five fresh reviewers with distinct lenses
  (conventions/security, correctness, claim-audit, test-efficacy/mutation, history+comments).
  Fresh spawns, so the re-check invariant holds. **Journal this as an inline composition, not as a
  `/code-review` verdict.**
- **Round 4 did NOT pass.** 2 BLOCKING + ~12 SHOULD-FIX/NIT. Per the human's standing instruction
  ("if the next code review round doesn't pass, then we definitely need an architect review"), the
  architect was invoked on the four design/scope questions.
- **Both BLOCKING findings were in the PR body**, and both were claims the diff itself retracts:
  - The golden-fixture claim, **third recurrence**. `987cbd8`'s own message says "the retracted
    claim survived in a second place" — it fixed the CHANGELOG twin and left the PR body's. Verified
    false myself: `attachment.type` is the counterexample, in the golden fixture.
  - The `agentId` "(25 records)" citation, retracted by name in `82876aa`'s own `pipeline.py` edit.
- **Three unguarded invariants found by mutation testing** — the PR's thesis turned on itself. All
  three now guarded and each verified red by re-running its mutant with bytecode purged.
- **Hit the stale-`.pyc` trap the mutation reviewer warned about**: my docstring mutation swapped
  `19`→`14`→`19`, byte-length-identical, so a cached `.pyc` was served and a passing test showed
  red. Purged and re-verified; also re-ran the earlier prefix mutations with purging since I had
  reported those results.
- **Architect rulings:** Q1 UUID-graph edges → FOLLOW-UP (opt-in mode only, distinct third defect),
  but prose must not claim completeness → done. Q2 residual accept → one clause, done. Q3 all three
  guards → SHOULD-FIX-HERE, not over-scoping, done. Q4 AC-10 → **genuinely half-met**; the human
  process is "papering over the gap"; comments fixed, issue still owed.
- **The architect caught two overclaims in MY framing of Q1**: containment unblocks the fix but does
  not *guard* the defect class, and "the reverse direction is harmless" has a silent-no-op edge case.
  Both fair; neither shipped.
- **Caught myself mid-edit**: I wrote that the UUID-edge defect "is tracked separately" when no issue
  exists. Corrected to "awaiting one" before commit.
- Gates: 500+4x / 49 / 15 / 16 OK, prettier clean, hermetic green. CI green on the pushed head.
- **THREE ITEMS NEED THE HUMAN — all require tracker writes I am not authorized for:**
  1. **AC-10's `format-scan` drift-check fast-follow.** The architect calls this a merge condition:
     AC-10 is not satisfiable by what shipped. Q1's UUID edges are the motivating example.
  2. The pre-existing org-UUID + `_cfuvid` cookie values in `fixtures/sanitized/`.
  3. The literal-rule/oracle interaction found in round 1, and now the Q1 UUID-edge defect.
- **Currency: `b21a4cf` is uncertified.** No review has run on it. Round 5 is required by the
  Fresh-re-check invariant before the merge gate.

### 2026-08-22 — follow-ups filed; round 5 via the real `/code-review` binding

- **Human authorized the tracker writes.** Filed #201 (AC-10 `format-scan` drift check), #202
  (`sourceToolAssistantUUID`/`leafUuid` never remapped under `remap_uuids`), #203 (sanitized fixture
  carrying an org identifier + Cloudflare cookie at `error.headers.*`), #204 (literal rule matching a
  skipped format-marker value can never produce output). All four linked from the PR body under a
  new "Follow-ups filed" section.
- **Comments now name the issues.** `d5011a0` replaces "owed"/"awaiting an issue" with #201 and #202.
  #202's note also carries WHY the fix belongs in `UUID_PATHS` alone. Comments only; the allow-list
  and both UUID sets are byte-identical to `b21a4cf`.
- **CORRECTION to the round-4 entry: the `CODE_REVIEW` binding was NOT uninvocable.** I invoked it as
  `code-review:code-review` (unknown skill) and concluded from that single failure plus the plugin's
  absence from `plugins/config.json` that it was unavailable. The correct name is the bare
  `code-review`, which works. Round 4's five-reviewer inline composition was therefore a substitution
  that was not actually due. It found real defects (2 BLOCKING, 3 unguarded invariants), so this is a
  provenance problem rather than a quality one, but round 4 must stay journalled as an inline
  composition and NOT as a `/code-review` verdict. Recorded as finding 11 in the dev-loop memo; Fred
  is investigating whether the root cause is local config.
- **Round 5 running through the real binding**, on `d5011a0`.
- Human's standing rule for this round: proceed to the next round unless the review finds
  **significant issues with the core implementation**. Docs and testing nits do not block and are to
  be documented at the end as potential follow-ups.

### 2026-08-22 — round 5 (real `/code-review` binding) — core CLEARED

- **Ran through the real binding this time** (`Skill(skill="code-review")`, bare name). Note the skill
  reported no `ReportFindings` tool available in this environment and returned findings as text.
- **Core implementation cleared, and verified empirically rather than read**: the reviewer diffed the
  OLD bare-name predicate against the NEW allow-list across all 8 fixtures (1494 records) and found
  the new allowed set is a **strict subset** of the old skipped set — no position previously scrubbed
  is now skipped. Only three positions moved skipped→scrubbed in the corpus
  (`message.content.content.type` 30, `toolUseResult.content.type` 3, `toolUseResult.type` 79), all
  enum-valued. Two-sided UUID pin sound.
- It also cleared two things it checked rather than flagged: the `set +e` placements swallow no
  earlier command's failure, and the `_record_with` `("type",)` ablation cell still survives
  `DEFAULT_STRIP_TYPES` so that cell is meaningful.
- **Three findings, all documentation.** Per the human's standing bar (docs/testing nits do not
  block), none blocks. Two were fixed anyway in `f09146f` because they were false statements:
  - **MEDIUM — "#194 is closed" was unqualified in `residual.py`, PRD §5/§13 and the CHANGELOG.**
    Five of the 29 entries sit inside `toolUseResult`, a tool-shaped envelope by this PR's own
    argument. `pipeline.py` documented the residual honestly; the other three asserted closure
    without it. Now say the bare-name MECHANISM is closed, not the class.
  - **LOW — the retracted "human review covers that" wording was still in PRD §6b B. FOURTH
    recurrence.** Retracted in `pipeline.py` and the corpus test earlier in this same PR. The spec is
    the authority those comments defer to, so it was the worst of the three places to leave it.
  - **LOW — NOT fixed, carried as a follow-up candidate:** `test_every_allow_list_entry_exists_in_the_corpus`
    makes the allow-list unextendable ahead of a fixture, so allow-listing a newly discovered format
    position needs a synthetic fixture authored first. Pressure is toward over-scrub (safe direction)
    but it is friction on exactly the maintenance path #201 feeds. Candidate: an `_UNVERIFIED` bucket
    exempt from the dead-entry check, or a docstring note.
- Gates: 500+4x / 49 / 15 / 16 OK, prettier clean.
- **Currency: `f09146f` post-dates round 5's verdict.** Docs-only (allow-list, both UUID sets and the
  predicate byte-identical to `d5011a0`), and the human's standing rule says docs nits do not warrant
  another round — recorded plainly rather than carried as a clean verdict on `f09146f`.
- **Step 9 (SECURITY_REVIEW) now running** on `f09146f`.

### 2026-08-22 — step 9 SECURITY_REVIEW: PASS (no findings) on `f09146f`

- Ran `/security-review` per the `SECURITY_REVIEW` binding. **No vulnerabilities at HIGH or MEDIUM.**
  Step 2 of the skill (parallel false-positive filtering) was vacuous — zero candidates to filter.
- Verdict is grounded in verification, not reading. The reviewer independently:
  - reimplemented `main`'s five-mechanism predicate and diffed it against the 29 allow-list entries in
    BOTH modes: **empty in both directions**, so no path skipped today was visited on `main`;
  - confirmed the previously-leaking positions are now visited in both `remap_uuids` modes;
  - established root-anchoring is sound because `walk_strings` has **exactly one call site** and always
    enters at the tree root — a second subtree caller would silently re-root every entry;
  - confirmed the four `set +e` additions open no green-on-failure path (each captures `status=$?`
    and fails closed on it);
  - confirmed each removed test is replaced by a strictly stronger assertion.
- **Sub-bar observation worth carrying forward:** `gitBranch` anchoring is the ONE place in this PR
  where scrub coverage got *narrower* (any-depth blanket redaction → field-anchored), and PRD §4 calls
  out branch names as carrying ticket IDs. Not raised as a finding because the position is still
  visited and rule-covered, the corpus has zero non-root occurrences, and the any-depth behavior was
  itself #199's corruption defect firing under a default config. Already disclosed in the CHANGELOG's
  upgrade note. **Recorded here because it is the kind of thing a future reader should not have to
  rediscover.**
- Also flagged sub-bar: the new corpus-drift CI step omits the `grep -qE '[0-9]+ passed'` positive
  assertion its two sibling steps carry. Exit 5 is still caught by the `status -ne 0` branch, so
  partial deselection is the only uncovered shape. Candidate follow-up, not a gate hole.
- **Step 10 (AC-verify) now running** against AC-1..AC-10 on `f09146f`.

### 2026-08-22 — step 10 AC-verify: FIRST ATTEMPT DIED, no verdict; re-run in flight

- The AC-verifier terminated on an API session limit partway through, with its last output being
  "Scratch copy is isolated. Now let me run mutations against it." **It produced NO verdict.**
- **Per the gate-outcome invariant, that is NOT a pass and is not journalled as one.** Step 10 is
  outstanding.
- Confirmed the failed agent left nothing behind: `git status --short` empty, HEAD still `f09146f`,
  suite 500 passed + 4 xfailed.
- Re-spawned with an explicit budget instruction: return a complete ten-criterion verdict FIRST from
  reading + the existing suite, and only then deepen with mutation testing if budget remains. The
  first attempt spent its whole budget setting up scratch-copy mutation work and returned nothing,
  which is worse than a shallow verdict. Worth carrying to the dev-loop memo: the engine tells a
  gate agent what to check but never how to sequence its work against a budget, so a thorough agent
  can fail the gate by being thorough in the wrong order.

### 2026-08-22 — step 10 AC-verify: PASS on `f09146f` — AC-1..AC-10 all MET

- Re-run returned a complete ten-criterion verdict. **All ten MET**, and the verdict is
  mutation-backed rather than assertion-backed: 9 targeted mutants in a scratch copy, each killing
  the specific test claimed to discharge its criterion.
  - AC-1: 5 mutants restoring each old mechanism independently — killed 42/10/10/13/1 tests.
  - AC-3: mutating the predicate to silently stop honoring a tier (list unchanged) reddened 19/29
    ablation cells — so that test is not one that passes with the feature absent.
  - **AC-8: the equality pin does NOT discharge it, and the verifier proved that.** Reverting the
    transform to bare-name matching left `test_uuid_transform_positions_match_pipeline_allow_list`
    GREEN and killed exactly one test — the behavioral
    `test_uuid_named_tool_input_is_not_remapped_under_remap_uuids`. The corruption reproduced in the
    mutant's output. The behavioral test is the real guard.
  - AC-9: mutant killed exactly the #199 regression test and nothing else.
  - AC-10 first clause: dropping BOTH `usage.speed` entries — the case the module docstring says the
    ablation control cannot see — was caught by the literal pin, so the removal blind spot is
    genuinely closed.
  - AC-6 judged against runtime values (29 entries, exact paths) and the golden-ablation retraction
    spot-checked, not judged by whether the file was edited.
- **#201 and #202 assessed as documented, correctly-filed deferrals rather than blockers.** #202
  does not affect AC-8: AC-8 asks for anchoring plus a real guard test, both delivered; #202 is a
  distinct graph-*completeness* defect under an opt-in flag.
- **One doc gap found, NOT fixed, carried as a follow-up candidate:** PRD §8 (`:434`, `:444`) still
  describes the identifiers layer as replacing "`gitBranch` values" without stating the path
  anchoring. Outside AC-6's scope (which names §6b B), but §8 is where #199's fix logically lives.
  Held under the human's standing rule that docs nits do not block and are collected at the end.
- Working tree verified clean by the verifier at finish.

### Gate roll-call for the merge gate (step 11)

| gate | verdict | commit certified |
|---|---|---|
| 8 code review (round 5, real binding) | core CLEARED, 3 doc findings | `d5011a0` |
| 9 security review | PASS, no HIGH/MEDIUM | `f09146f` |
| 10 AC-verify | PASS, AC-1..AC-10 MET | `f09146f` |
| CI | 6/6 green | `f09146f` |

- **Currency, stated plainly rather than glossed:** the code-review verdict is bound to `d5011a0`,
  not to the merge candidate `f09146f`. The delta is `f09146f` alone, which is docs-only — the two
  false-statement fixes round 5 itself asked for — with the allow-list, both UUID sets and the
  predicate byte-identical to `d5011a0`. The human's standing rule is that docs nits do not warrant
  another round. **This is surfaced AT the merge gate for the human to weigh; it is NOT recorded as
  a clean code-review verdict on `f09146f`.**
- **Step 11 requires human approval (`mode: calibration`). Nothing is merged.**

### 2026-08-22 — step 11 MERGE: DONE. #194 + #199 closed.

- Human approved at the merge gate after the roll-call, having been told plainly that the
  code-review verdict was bound to `d5011a0` and the candidate was `f09146f` (docs-only delta).
- Re-verified preconditions immediately before merging: HEAD `f09146f`, tree clean, PR `MERGEABLE`
  / `CLEAN`, **6/6 checks pass**. Then `gh pr merge 200 --squash --delete-branch`.
- Squashed to **`b8c2b0c`** on `main`. 12 files, +1716 / -195. #194 CLOSED, #199 CLOSED, PR MERGED
  at 2026-08-23T00:45:29Z. Branch deleted locally and remotely.
- **Post-merge verification on `main`** (not assumed from the branch): 500 passed + 4 xfailed / 49 /
  15 / 16 OK, prettier clean.
- Follow-ups filed before merge, all linked from the PR: **#201** (format-scan drift check, AC-10's
  second clause), **#202** (`sourceToolAssistantUUID`/`leafUuid` unremapped under `remap_uuids`),
  **#203** (org identifier + Cloudflare cookie in a sanitized fixture), **#204** (literal rule vs a
  skipped format-marker value), **#205** (PRD §8 stale on bare-name matching), **#206** (dead-entry
  test blocks allow-listing ahead of a fixture), **#207** (corpus-drift CI step missing its
  positive assertion).

## Row #194 CLOSED — iteration complete

**What shipped.** The bare-name traversal skip-list, a `*_tokens` suffix rule, a `parent == "usage"`
rule and a mis-described "anchored" pair set all replaced by a 29-entry root-anchored path
allow-list: an unlisted position is now visited and scrubbed. The identifier transform anchored the
same way (#199). 88 net new tests.

**What the run cost and why.** Five code-review rounds, three architect passes, one scrub-boundary
escalation to the human. The dominant defect class across every round was **prose asserting
properties nobody had checked** — it appeared in rounds 1, 3, 4 and 5, and twice inside the very
commit whose purpose was removing such claims. What finally caught the last of it was mutation
testing, not reading.

**Carried to the dev-loop memo:** finding 11 (a single failed skill-name invocation was enough to
declare a binding dead and substitute five self-authored reviewers on the one gate whose value is
independence) and the budget-sequencing gap that made the first AC-verifier return no verdict at all.

## 2026-08-24T01:07Z — resume reconciliation + #194 close (step 0.3, step 12)

- **Row #194 was stale at `in-review`; live state settled it.** PR #200 `MERGED` 2026-08-23T00:45:29Z
  as `b8c2b0c`; issue #194 `CLOSED`. The spending invocation journaled the merge and a narrative
  close block ("Row #194 CLOSED") but never advanced the `queue.md` Status. Reconciled to `done` per
  Resume — live git/PR state wins over a stale row.
- **Orphan scan (step 0.3): clean.** `gh pr list --state open` returns none, so no open PR lacks a
  row. `git worktree list` shows the primary tree only. Working tree clean on `main` at `685eede`.
- **Unfinished-mutation check (Resume (a)): clean.** No `mutate-verify-*` directory under the system
  temp dir, and no leftover isolated copy.
- **The `- Budget:` line #194 owed was never written** — nor was #195's. Reconstructed below from
  that iteration's own journal blocks and labelled as such rather than left absent; `subagent-runs`
  is a **floor**, since the invocation that spent them did not count. Both caps are `none`, so
  nothing was gated on the number. Carried to the dev-loop findings memo as a journaling gap.
- Budget: subagent-runs=15 (floor, reconstructed at resume from the journal) · gate-rounds=architect=3,code-review=5(correctness,robustness,conventions/security,claim-audit,test-efficacy/mutation,history+comments),ac-verify=2(attempt 1 died mid-run with no verdict; attempt 2 returned it) · ac-findings=0 · mutation-survivors=0 (9 targeted mutants in a scratch copy, all killed; the journal records no declared control) · justification=rounds 3-5 and two of the three architect passes were human-directed after round 2 came back dirty; the dominant defect class was prose asserting unchecked properties, which only mutation caught · wall-clock=≈7h15m (17:30Z to 00:45Z, includes gate-wait) · tokens=deferred
- Row #194 → `done`. Newly unblocked: none (no row declares a dependency on #194); PyPI 0.4.0
  publish remains gated on #190.

## 2026-08-24T01:07Z — curation (step 1 roster reconciliation)

Live `epic:sanitizer` roster vs `queue.md`. Seven issues joined the epic after init and after the
last curation pass — all of them follow-ups filed during the #194 iteration. **Surfaced once, not
auto-added.**

- `- surfaced-join: #201` — sanitizer: format-scan drift check for corpus positions the allow-list does not cover (priority:medium)
- `- surfaced-join: #202` — sanitizer: sourceToolAssistantUUID and leafUuid are never remapped under remap_uuids (priority:medium)
- `- surfaced-join: #203` — fixtures: sanitized fixture carries an org identifier and a Cloudflare cookie (priority:medium)
- `- surfaced-join: #204` — sanitizer: a literal rule matching a skipped format-marker value can never produce a finding (priority:low)
- `- surfaced-join: #205` — docs(prd): section 8 still describes gitBranch and UUID scrubbing as bare-name matching (priority:low)
- `- surfaced-join: #206` — sanitizer: the dead-entry test blocks allow-listing a new format position until a fixture exists (priority:low)
- `- surfaced-join: #207` — ci: the corpus-drift guard step omits the positive pass-count assertion (priority:low)

No leavers: every non-terminal row is still in the roster.

**#196 and #198 were surfaced in an earlier pass and remain out of the queue** — no new surface owed,
and #198 (`priority:high`) is therefore **not selectable** despite outranking #190 on label, per the
curated-subset invariant. Worth the human's attention when deciding what to pull in.

## 2026-08-24T01:32Z — #190 (code) — steps 3-5, STOPPED at the plan gate

- Selected #190 (`priority:high`, highest-priority selectable row). Budget caps are `none`, so the
  step-1 check is inert.
- **Plan refreshed against `685eede` before the design gate.** The existing plan was written
  against `91adca1` (pre-#194). Re-probed both populations via `sanitize_session`, synthetic values
  only: literal rule + key → abort exit 2 (both 1-deep and nested); **regex rule + key → exit 0 with
  the value present in the output** (1-deep and nested); control (same value as a string value) →
  redacted under both. The record-loss hazard re-reproduced: 2 keys → 1 entry, first entry gone.
- Three findings resolved without the human: #198's body already records population 2 by name (plan
  risk 3 closed); AC-3 is a **test-coverage** gap, not a behavior gap (nested key already aborts for
  literals); and three stale test citations in the plan's own AC table corrected
  (`:236`→`:273`, `:323`→`:483`, `test_nested_value_under_tool_input_aborts :299` →
  `test_nested_value_under_tool_input_is_redacted :354`).
- Baseline on `main`: 500 passed + 4 xfailed / 49 / 15 / 16 OK, all four suites green.
  **`test_cli_smoke.py:45` silently skips unless the venv `bin` is on `PATH`** (499 + 1 skipped) —
  flagged, not filed.
- **Architect ran (step 4) and MATERIALLY REDIRECTED the plan.** Freeze was already taken as a
  genuine pre-image in a prior invocation and was left untouched (write-once). Rulings recorded in
  `issue-190.plan.md` with adopt/adapt/decline: Q2 `blocking` (the collision check is **inline** and
  cannot be delegated to the oracle — a collision deletes its own evidence, so the output-side scan
  reads clean); Q1 `important` (polarity right, but `_FORMAT_PATHS` allow-lists format-owned
  *values*, not key *names*, so "reuse `make_skip_predicate` unchanged" is wrong and over-scrub
  renames a structural key — the key/value failure calculus is not symmetric); Q4 `important` (the
  (e)-vs-(b′) fork is a human scope call, architect leans (e) with #198 first); Q5 `important`
  (no join contract broken; document the tail); Q3 `suggestion` (no D-2/§10 violation, no marker
  needed); Q6 `optional` (0.4.0 suffices; byte-neutrality verified against the golden fixture) plus
  two under-specification gaps (secret-in-key composed-transform question; AC-3 coverage).
- **All four load-bearing architect citations verified before adoption**, not taken on trust:
  `_iter_decoded_strings` yields dict keys (`residual.py:144-163`, docstring says so explicitly);
  regex rules skipped at `residual.py:301`; `test_residual_rules.py:273` and `:354` resolve as named.
- Architect review **not** posted to #190 as an issue comment — the project's recording surface is
  issue comments, but the plan is unapproved and that is a public write. Held for the human's
  go-ahead; the review is recorded in the plan regardless.
- Plan-gate: material (a different fork chosen — (e) promoted from named-for-completeness to the architect's preferred path and (b) demoted; steps reordered into two forked lists; the files-to-touch set changes under (e), which touches no pipeline source at all; and AC-3 reinterpreted from a behavior gap to a test-coverage gap) → STOPPED
- **AC-reduction hazard surfaced, NOT absorbed:** under fork (e) the "make the position scrubbable"
  ACs (the Rescoped-comment bar, and AC-5's cell-13 flip to REDACTED) would not be delivered at all.
  Per step 5 that is an **issue amendment**, not a gate interpretation — if the human picks (e) it
  gets recorded on #190 and the removed scope filed before implementation.
- Row #190 → `planning`. Nothing implemented, no branch, no PR.

## 2026-08-24T01:48Z — #190 (code) — plan gate RESOLVED, fork (e) approved

- **Human gate: plan approved by the human (plan-gate: always), on fork `(e)` detect-only.** The
  architect's redirect was presented with the frozen-vs-live diff; the human chose `(e)`, pulled in
  #198 + #201-#203, and authorized posting the architect review to the issue.
- **Architect outcome recorded on #190** as an issue comment (`#issuecomment-5389742006`) — this
  project's recording surface, held until the human approved the public write.
- **AC reduction handled as an issue amendment, NOT absorbed by the gate.** `(e)` does not deliver
  the "make the position scrubbable" criteria. Narrowing recorded on #190
  (`#issuecomment-5389748039`); removed scope filed as **#208**
  (`feat(sanitizer): make a rule-matching dict key scrubbable so the session is publishable`),
  carrying the architect's three ruled constraints so #208 does not rediscover them.
- Plan ACs rewritten to the narrowed set (AC-1..AC-6). The acceptance gate judges against those.
- **Curation applied on the human's ruling:** rows added for #198 (`priority:high`), #201, #202,
  #203 (`priority:medium`), all Status `queued`, Route `code`. #204-#207 left out as surfaced.
  **#208 is a new joiner created by this iteration** — recorded here as surfaced, NOT auto-added.
  - `- surfaced-join: #208` — split out of #190 at the plan gate; option `(b′)` publishability work
- Row #190 → `plan-approved`. Proceeding to step 6 (implement).

## 2026-08-24T02:14Z — #190 (code) — iteration open

- Issue: #190 — fix(sanitizer): dict keys are never transformed
- Route: code
- Branch: fix/190-nested-key-coverage-and-prd
- PR: #209
- Status: in-pr

### Step 6 detail (implement)

- Commit `672bdfc`. Four files, +290 / -37: `test_residual_rules.py`,
  `test_adversarial_placement.py`, `prd-sanitizer.md`, `CHANGELOG.md`. **No file under
  `src/ccs_sanitize/` touched** — fork `(e)` makes no behavior change.
- Gates: 507 / 49 / 15 / 16 OK; `npx prettier . --check` clean. (507 = 500 passed + 4 xfailed
  before, minus the 4 xfail params now excluded, plus 7 new: 2 residual + 4 fail-closed params +
  1 partition guard.)
- `- Hermetic: pass` — due (Route `code`, tests added). All four suites green inside
  `unshare -rn -- sh -c 'ip link set lo up && …'`; block confirmed socket-level by a direct-IP
  connect failing `OSError: [Errno 101] Network is unreachable`.
- **Two authoring-rule corrections caught before commit, both claims I had written and then
  checked:**
  1. A docstring claimed "a change that yielded only top-level keys would leave every existing test
     in this module green." **False** — the sibling one-deep test plants at depth 2, so that
     mutation killed it too. Re-measured with a depth-limited mutation that isolates the property:
     1 failed, 501 passed. Docstring now states the measured result.
  2. The PRD amendment cited "Step D's output-side oracle". **There is no Step D** — the PRD has
     only Steps A and B. Corrected to §5, which is where the residual scan is specified and which
     already states the re-run covers "every string leaf *and every dict key*".
- AC walk (step-6 tripwire, not a gate): AC-1 `test_residual_rules.py:285` + `:328`; AC-2
  `test_adversarial_placement.py:173`, `:682`, `:722`; AC-3 `prd-sanitizer.md:284`; AC-4
  `prd-sanitizer.md:291` + `CHANGELOG.md:154`; AC-5 golden determinism green within suite 1; AC-6
  `CHANGELOG.md:154` states the bump trigger does not fire.
- Staged four explicit paths; `git diff --cached` read before committing; `git worktree list` shows
  the primary tree only.
- **Surfaced on the PR, not resolved:** the CHANGELOG's publish hold ("both traversal gaps carry
  coverage rather than only refusal") **can no longer be met by this release** under fork `(e)` —
  the dict-key position is refusal-only until #208. Maintainer decision at the merge gate.

## 2026-08-24T02:22Z — #190 (code) — CI green (step 7 tail)

- PR #209, commit `672bdfc`. **6/6 pass**: prettier, pytest py3.11/3.12/3.13, build + twine check,
  and the required `sanitizer-ci` aggregate. **No CI fix was needed, so no gate verdict is
  re-armed** and the review below binds the merge candidate.
- Row → `in-review`.

## 2026-08-24T03:05Z — #190 (code) — code review round 2 (fresh re-check) — DIRTY, ESCALATED

- Round 1: `/code-review high` (the real binding) on `672bdfc`. **5 findings, all accepted, all
  independently verified before fixing.** The two that mattered were against this PR's own
  headline measurement: the docstring and CHANGELOG both claimed the depth-2 mutation killed
  "this test and nothing else -- 1 failed, 501 passed, 4 xfailed". **Wrong.** That came from an
  IN-PROCESS monkeypatch, which never reaches the placement matrix because the matrix drives the
  console script as a subprocess. Re-measured at source level: **4 failed, 503 passed**. The
  "4 xfailed" half was impossible too -- this PR removes the last xfails in the repo.
- Fixes committed as `2a102fb` and **pushed before spawning the re-check**, so the checker read the
  fixed head.
- Round 2 = one fresh spawn, not me and not the round-1 reviewer. It **confirmed all five fixes are
  really in the tree**, re-derived the `4 failed, 503 passed` figure itself, verified the other
  measured table (`1 failed, 75 passed, 4 xfailed` pre / `5 failed` post -- both exact), and
  confirmed the narrowed `label == "paths"` assertion is a real guard and not vacuous
  (`rules/paths.py:109` passes `label="paths"`).
- **It came back DIRTY. Round 2 is the last round of the 2-round cap, so this ESCALATES to the
  human. No round 3 is opened on my own judgement.**
- **Finding B is the serious one, and it is mine, introduced by the fix commit itself.**
  `test_residual_rules.py:317-320` now claims "no monotonic depth cutoff can separate this test
  from cell 13 in the other direction either -- cell 13 plants its key deeper still". That is
  **backwards and false**: because cell 13 is deeper, a cutoff at depth 3 kills cell 13 and spares
  this test. Measured by the checker: `3 failed, 504 passed`. It is verifiable by reading alone.
  **This is an unverified measurement-shaped claim introduced by the very commit whose purpose was
  removing an unverified measurement-shaped claim** -- the same shape the #194 retrospective
  recorded as the dominant defect class of that iteration.
- Findings A, C, D: the #190-vs-#198/#208 renumber was applied to PRD §5 but **not swept** --
  `CHANGELOG.md:291` still says "#190 stays open" 155 lines below line 136 saying it landed;
  `CHANGELOG.md:374-377` still describes the four cells as strict xfails against #190; and
  `src/ccs_sanitize/residual.py:183-185` -- **the copy a `pip` user reads** -- still names #190 as
  the open gap. The PR's security review said "no `src/` file modified", which is true and is
  exactly why that one went unswept.
- Finding E: the narrowing is right but its stated justification is not -- neither cited example
  (`remap_uuids` default, §9b jitter) actually bites that line, which carries no uuid-graph field
  and no `timestamp`.
- Finding F/G: minor -- a stale test name, dead `xfail` branch in `_params`, a conditionally-wrong
  failure message for the `secret` payload, a run-on sentence at `prd-sanitizer.md:285`, plus the
  **PR #209 body still carrying the retracted figure** and **#208's body citing now-stale line
  numbers**.
- **Tree verified after the checker's in-tree mutation:** HEAD `2a102fb`, `git status` empty,
  `residual.py` byte-exact vs HEAD, one worktree, no retained snapshot dir, 507 passed.
  **Process deviation, self-reported:** that checker mutated the working tree and should have been
  given worktree isolation under the Execution policy. It was not. No harm resulted and it was
  verified rather than trusted, but the isolation duty was mine and I skipped it.
- `- Hermetic: pass` (re-armed by the round-1 test edit; re-run on `2a102fb`).
- Row stays `in-review`. Not `blocked` -- this waits on a human answer about THIS gate.

## 2026-08-24T03:40Z — #190 (code) — human directed NARROWING (step 8 disposition)

- **Round 2 was the cap. The human's disposition was to NARROW, not to open a round 3** — the
  engine's own point that "the decision is frequently not 'run another round'". Commit `8e5d368`.
- **The measurement prose is deleted rather than re-measured.** That retires finding B outright:
  the false claim ("no monotonic depth cutoff can separate this test from cell 13") is gone with
  the block that carried it, instead of being corrected and re-checked. The same counts came out
  of `test_adversarial_placement.py` and the CHANGELOG. **The logical arguments stay in all three**,
  because they are verifiable by reading rather than by running: FAIL-CLOSED and LEAKED both fail
  `== "REDACTED"`, so a strict xfail could not tell a safe abort from a leak.
- **Rationale, recorded because it is the finding of this iteration:** 3 of 3 defects here were
  prose asserting a measurement; 0 were in code. Removing the surface beats re-checking it.
- Findings A, C, D swept — the `#190 → #198/#208` renumber landed in the CHANGELOG's #195 entry,
  its #191 entry, and `residual.py`'s `scan_residual_rules` docstring. **A full grep of every
  `#190` mention across `src/`, `tests/`, the CHANGELOG and the PRD** confirms no remaining
  contradiction; what is left describes the defect historically, not its status.
- Finding E fixed (the justification cited two examples that do not bite that line). F minors
  fixed: a pre-existing false claim that nothing re-scans the output for config-driven payloads
  (#195 does, for literals), the stale `test_known_deviations_reference_real_cells` name, and a
  failure message that promised the `secret` payload moves with the PII ones when #208 leaves that
  undecided.
- **`residual.py` is now modified — docstring only, no executable line.** Noted explicitly because
  the previous security-review line said no `src/` file was touched, which is exactly why that
  attribution went unswept. The PR body's Closer-read row is updated to match.
- Records outside the diff corrected: **PR #209's body** (it still carried the retracted figure)
  and **#208's body citations** (`KNOWN_DEVIATIONS` / `test_adversarial_placement.py:164-171`, both
  stale after this merge) via `#issuecomment-5391899510`.
- Gates on `8e5d368`: 507 / 49 / 15 / 16 OK, prettier clean, `- Hermetic: pass` (re-armed again by
  the test edits). **CI 6/6 green.**
- **CURRENCY, stated plainly and NOT glossed:** round 1 certified `672bdfc`, round 2 read
  `2a102fb`. **`8e5d368` has been reviewed by nobody, and step 8's round budget is spent**, so per
  the Gate-outcome invariant this is an **unowned re-arm** — it escalates to the human at the merge
  gate rather than being absorbed. It is NOT recorded as a clean code-review verdict on `8e5d368`.

## 2026-08-24T03:55Z — #190 (code) — step 9 security review: PASS

- Local `/security-review` on `8e5d368`. **No HIGH or MEDIUM findings.**
- Due because the diff touches `tooling/sanitizer/` (config §4). `origin/HEAD` precondition checked
  first and resolves, so the gate ran rather than dying on `fatal: ambiguous argument`.
- **The load-bearing claim was proved mechanically, not read:** `residual.py`'s AST is **identical
  once docstrings are stripped** and differs only with them included, so the one `src/` edit changes
  no executable semantics. Also verified: no real-identity strings anywhere in the diff, every
  planted value reuses the pre-existing synthetic `_REAL_USER_HOME = "/home/realuser"` with its
  definition unmodified, and no `fixtures/` or `*.jsonl` path is touched.
- **No guard is weakened; coverage strictly increases.** Removing the four cells from
  `test_placement_is_redacted` and asserting `== "FAIL-CLOSED"` positively catches the LEAKED
  direction that the strict xfail reported as an expected failure, and still forces an update when
  #208 makes the cells REDACTED.
- **Disclosure posture considered and cleared.** The PR states an unfixed scrubbing gap in a
  docstring that ships to PyPI. Not an advisory case: the gap is already public (#190, #198), it is
  not live exposure (D-7 strips the one real shape), and documenting it is the safer direction —
  suppressing it would leave a user trusting `residual_scan: clean`.
- **Method deviation, self-reported:** the skill prescribes fan-out sub-tasks; I analysed directly
  with mechanical verification instead. Recorded so the verdict is not read as having come from
  that procedure.
- Row → `in-acceptance`.

## 2026-08-24T04:10Z — #190 (code) — step 10 Part 1 (Class A): PASS, AC-1..AC-6 all MET

- Fresh verifier, given ONLY the criteria verbatim, the resolved `$BASE`
  (`685eede`) and the commands to run — none of my narrative or conclusions. It ran them itself and
  stated its retrieved input first: 5 files, **329 insertions / 69 deletions**, no untracked files,
  tree clean before and after.
- **AC-1 met** — `test_residual_rules.py:285` plants the payload key inside `outer`'s value, and the
  verifier confirmed the abort is attributable to the KEY position rather than an incidental match
  by probing the same value at the same depth in a VALUE position (redacts cleanly) against the key
  position (raises `ResidualRuleError(section='paths', index=0)`).
- **AC-2 met** — `KNOWN_DEVIATIONS` empty, four cells in `FAIL_CLOSED_BY_DESIGN`, `_params`
  `continue`s past them, asserted positively with exact equality so `LEAKED` / `ERROR-<rc>` /
  `NO-OUTPUT` / `REDACTED` all fail. It checked the `(label, cell)` vs `(cell, label)` key order
  against the fixture and confirmed nothing still exempts those cells.
- **AC-3, AC-4 met** — and it verified the quoted §5 phrase resolves verbatim rather than taking the
  citation on trust.
- **AC-5 met, not on trust:** `git diff --name-only -- fixtures tooling/sanitizer/tests/golden`
  returns **0 files**, and `test_golden_determinism.py` drives the shipped CLI against committed
  golden output AND sidecar under two pinned configs, including the generative `remap_uuids: true`
  path. 507 passed.
- **AC-6 met, independently re-derived:** it parsed base and HEAD with docstrings stripped and got
  **identical ASTs** — the same check the security gate ran, reached separately.
- Class A findings: **0**.
- **Two non-blocking observations from the verifier, both accepted:**
  1. The CHANGELOG deliberately leaves the release-hold decision open. Already carried to the merge
     gate as a human decision; not a defect.
  2. **The new prose uses em-dashes freely, against the recorded "fewer em-dashes" preference.**
     Real, and mine: 14 added lines carry one, all in `prd-sanitizer.md` (6) and `CHANGELOG.md` (8).
     The Python files use ASCII `--` already. Markdown-only, so fixing it touches no source and no
     test and re-arms nothing. **Deferred until the Part 2 copy is removed** — the engine forbids
     committing while a writing subagent's isolated copy is live.

## 2026-08-24T04:35Z — #190 (code) — step 10 Part 2 (Class B): CLEAN, exit 0

- Ran via the harness in an **isolated worktree outside the repository**, with its own venv
  editable-installed **from the worktree**. That last detail was checked rather than assumed:
  `ccs_sanitize` and the `ccs-sanitize` console script both resolve INTO the copy, so a mutation is
  actually seen by the placement matrix, which drives the CLI as a subprocess. A venv still bound
  to the parent would have produced a pass that measured nothing. **This is the same trap that
  produced this iteration's first false measurement**, met a second time and caught in advance.
- Both envelope preconditions verified before mutating: suite green IN THE COPY (507), and the copy
  contains the change (same 5 files / same counts as the parent's diff against `$BASE`).
- **Exit 0.** 6 real mutations, all killed; 1 control, survived. `applied: 7, restored: 7`.
- The verifier did attribution work beyond the verdict, with narrowed `--test-cmd` probes: with the
  new tests deselected, the depth-2 and depth-4 traversal regressions **both survive** (499 passed),
  so **neither is visible to any pre-existing test**. With only the AC-2 test deselected, depth-2 is
  killed by exactly one test (the new nested-key cell) and depth-4 still survives. **Each new test
  is the sole guard for a distinct real regression.**
- The depth-4 kill printed `cell 13-dict-key-not-value with pii-name returned LEAKED, expected
  FAIL-CLOSED` — the AC-2 argument reproduced empirically. Worth noting: this is the **verified**
  form of the claim I deleted earlier for being unverified. The right move was to delete the
  unverified prose and let the mutation pass establish it instead.
- **Limits the verifier stated plainly, and I am not glossing them:** no `src/` mutation can
  exercise `test_no_cell_is_both_a_deviation_and_fail_closed_by_design` or
  `test_deviation_mappings_reference_real_cells`, since those assert over the test module's own data
  structures; mutation says nothing about the docstring's accuracy; and the now-dead `_params` xfail
  branch was not exercised.
- Restore: 7 mutations applied, 7 restored, git status clean. Copy verified byte-exact at HEAD and
  free of retained snapshots BEFORE removal, then removed; `git worktree list` shows one tree.
- AC-verify: Class A 6/6 acceptance criteria met. Class B: 0 survivors (6 killed, control held).

## 2026-08-24T04:40Z — #190 (code) — em-dash pass (post-gate, prose only)

- Commit `4d7125d`. The Class A verifier's second observation, accepted: 14 added lines carried
  em-dashes against the standing preference. Rewritten to periods and commas.
- **Prose only — no source, no tests, no executable line**, so per the currency clause this
  re-arms nothing. AC-3 and AC-4 substance re-checked after the edit and preserved verbatim in
  content.
- **Disclosed rather than glossed: the acceptance and security verdicts were taken on `8e5d368`,
  and the merge candidate is now `4d7125d`.** The delta is repunctuation of two markdown files.
  This is surfaced AT the merge gate for the human to weigh; it is NOT recorded as a gate verdict
  on `4d7125d`.
- Gates re-run: 507 passed, prettier clean.

## 2026-08-24T04:50Z — #190 (code) — step 11 merge gate: STOPPED for the human

### Gate roll-call

| gate | verdict | commit certified |
|---|---|---|
| 8 code review (round 1, real binding) | 5 findings, all fixed | `672bdfc` |
| 8 code review (round 2, fresh re-check) | **DIRTY** -> cap reached -> human directed a narrowing | `2a102fb` |
| 9 security review | PASS, no HIGH/MEDIUM | `8e5d368` |
| 10 AC-verify Class A | PASS, AC-1..AC-6 MET | `8e5d368` |
| 10 AC-verify Class B | CLEAN, exit 0 (6 killed, control held) | `8e5d368` |
| CI | 6/6 green | `4d7125d` |

- PR #209 `MERGEABLE` / `CLEAN`, head `4d7125d`, four commits, working tree clean, one worktree,
  `__version__` still `0.4.0`.
- **`mode: calibration`, so no row is auto-merge-eligible. Nothing is merged without the human.**

### Two currency gaps, surfaced not glossed

1. **Code review never certified the merge candidate.** Round 1 saw `672bdfc`, round 2 saw
   `2a102fb`. `8e5d368` (the narrowing) and `4d7125d` (the em-dash pass) have been reviewed by
   nobody, and **step 8's 2-round budget is spent**, so nothing in the pipeline can certify them.
   Per the Gate-outcome invariant this is an **unowned re-arm**: it escalates, and the human's
   disposition is what releases the row. **It is NOT recorded as a clean code-review verdict.**
   Mitigating facts for the human to weigh, not a substitute for the gate: `8e5d368` is a
   deletion-and-renumber commit the human themselves directed, and its content was subsequently
   read by three independent agents (security, Class A, Class B) none of which raised anything
   against it; `4d7125d` is repunctuation of two markdown files.
2. **Security and acceptance certified `8e5d368`, not `4d7125d`.** The delta is prose only, no
   source and no tests, which the currency clause says re-arms nothing. Stated anyway.

### Always-escalate conditions

- `feat:`/breaking change: **no** (no behavior change; AST identical modulo docstrings).
- Risky/irreversible: **no**.
- Touched security surface: **yes** (`tooling/sanitizer/`), and the security gate ran clean on
  `8e5d368`. The `4d7125d` delta is markdown.
- Contested review finding: **no** contested finding, but see currency gap 1.
- Unresolved Class B mutation survivor: **no** (0 survivors).
- Unresolved hermetic-tier finding: **no** (`- Hermetic: pass`).

### The open decision that is not about this PR's correctness

The CHANGELOG's publish hold read "wait for both known traversal gaps to carry *coverage* rather
than only *refusal*". Scoping #190 to detect-only means **no release can now meet that wording** --
the dict-key position is refusal-only until #208. The CHANGELOG records the two readings rather
than picking one. This does not block the merge; it blocks the PyPI publish, and it is the human's.

## 2026-08-24T08:15Z — #190 (code) — iteration complete

- Selected: #190 (highest-priority selectable row, `priority:high`).
- Route: code (full pipeline, all gates).
- Plan: issue-190.plan.md refreshed against `685eede` before the design gate; ACs amended at the
  plan gate and the narrowed set recorded.
- Architect: RAN, and materially redirected the plan onto an `(e)`-vs-`(b')` fork.
- Plan-gate: material (a different fork chosen: `(e)` promoted from named-for-completeness to the architect's preferred path and `(b)` demoted; steps reordered into two forked lists; the files-to-touch set changes under `(e)`, which touches no pipeline source at all; and AC-3 reinterpreted from a behavior gap to a test-coverage gap) -> STOPPED
- Human gate: plan approved by the human (plan-gate: always), on fork `(e)`.
- Implemented: nested key-in-key coverage in `test_residual_rules.py`; `FAIL_CLOSED_BY_DESIGN` +
  positive FAIL-CLOSED assertions in `test_adversarial_placement.py`; PRD 6b Step B amendment;
  CHANGELOG entry; one docstring in `residual.py`.
- Hermetic: pass.
- PR: #209 (test scope). CI: green 6/6 on every head.
- Code-review: 5 findings round 1 (all fixed); round 2 fresh re-check DIRTY -> cap -> human
  directed a narrowing rather than a round 3. Security: PASS, no HIGH/MEDIUM.
- Restore: 7 mutations applied, 7 restored, git status clean.
- AC-verify: Class A 6/6 acceptance criteria met. Class B: 0 survivors (6 killed, control held).
- Budget: subagent-runs=5 (architect + code-review skill + fresh re-check + AC-verify Class A + Class B mutation) · gate-rounds=architect=1,code-review=2(correctness,robustness,accuracy-of-stated-measurements,issue-attribution,test-efficacy),ac-verify=1 · ac-findings=0 · mutation-survivors=0 (6 real mutations killed, 1 control held, exit 0) · post-gate-survivors=0 · justification=code-review ran 2 rounds because round 1 found the PR's own headline measurement was false; round 2 then found a second false measurement introduced by the fix commit, which hit the cap and produced the narrowing decision · wall-clock=≈7h05m (01:07Z to 08:15Z, includes gate-wait) · tokens=deferred
- Merged: squash #209 as `f8f0c96`. Issue #190 closed. Branch deleted local and remote.
- **Post-merge verification ON MAIN** (not assumed from the branch): 507 / 49 / 15 / 16 OK,
  prettier clean, one worktree, no stray branch.
- Merge released by **human decision**, not by a gate: code review's verdict covered `672bdfc` and
  `2a102fb` only, and its round budget was spent, so `8e5d368` and `4d7125d` were merged uncertified
  by that gate. Recorded here as a human decision naming the gate and the commits its verdict does
  not cover, per the Gate-outcome invariant.
- Publish hold: left OPEN by human ruling. Revisit after #198 lands; the CHANGELOG's two readings
  stand unresolved deliberately.
- Next: #198 (`priority:high`) is now the highest-priority selectable row.

### Iteration finding, carried to the dev-loop memo

**Every defect in this iteration was prose asserting a measurement; none was in code.** Three
instances: a docstring measurement taken with an in-process monkeypatch that never reached the
subprocess under test; a PRD cross-reference to a "Step D" that does not exist; and a
direction-reversed claim about depth cutoffs introduced by the very commit that was fixing the
first. All three were caught by a different reader, never by the author re-reading. The disposition
that worked was **deleting the claim surface** rather than re-verifying it, and letting the Class B
mutation pass establish the same property by running instead of by asserting.

## 2026-08-30T04:58Z — orphan-PR scan (step 0.3)

Open PR with no `queue.md` row, resolved by the human before any new work was selected.

- **PR #214** — `feat(posts): draft Part 5 — "The tool call, completely"`, branch
  `feature/67-part-5-tool-call-completely`, opened 2026-08-28, CI green 7/7.
- **Classified NOT an interruption**, on positive attribution to the human rather than on absence
  of evidence. Three independent grounds: issue #67 carries `documentation` + `priority:medium`
  and **no `epic:sanitizer` label**, so it is outside this run's `BACKLOG_SOURCE` and the loop
  could not have selected it; `progress.md` holds no record of #214 or #67 while the ledger is
  present and internally current (last entry 2026-08-24, four days before the PR was opened), so
  step 7's open record would exist had the loop opened it; and a sibling in the same posts
  workstream (#211) merged to `main` with no ledger trace either.
- **Human confirmed 2026-08-30: "Mine — proceed with #198."** The attribution is the human's
  ruling, not the orchestrator's inference.
- One-PR-at-a-time is unaffected: #214 is not this loop's PR, and the next loop PR branches from
  `origin/main` rather than stacking on it.

## 2026-08-30T04:58Z — curation (step 1 roster reconciliation)

Live `epic:sanitizer` roster (14 open) vs `queue.md` (11 rows). **No new drift; nothing surfaced
this pass.**

- **Joined:** none new. #196, #204, #205, #206, #207, #208 are all in the roster with no row, and
  every one of them carries a prior `- surfaced-join:` line (2026-08-22 for #196; 2026-08-24 for
  #204–#207; 2026-08-24 for #208). A bare surface never adds a row, so surfaced-but-not-added is
  their correct resting state and re-surfacing them would violate the surface-once rule.
- **Left:** none. Every non-terminal row (#192, #32, #42, #198, #201, #202, #203, #1) is still in
  the live roster. #195 / #190 / #194 are absent from the open roster only because they are closed,
  and all three are terminal (`done`), which the leave test does not cover.

## 2026-08-30T05:15Z — #198 (code) — plan gate (step 5)

- Selected: #198 (`priority:high`, the only high-priority selectable row).
- Route: code (full pipeline, all gates).
- Plan: issue-198.plan.md written; `## Approach` frozen BEFORE `DESIGN_AGENT` was consulted, so
  the materiality test has a real pre-image rather than a self-assessment.
- Architect: RAN (three triggers: sanitizer scrubbing behavior; sidecar shape, live on the fork;
  orchestrator unsure — AC-1 makes the design decision itself the deliverable). Returned one
  **blocking** finding, three **important**, two **minor**. Outcome recorded as an issue comment
  on #198 (this project's architect-decision surface), and applied to `## Approach` at step 4c
  before this gate was evaluated.
- Plan-gate: material (a different fork chosen: the ratified design is design 1 **corrected** — "skip-predicate-aware regex scan on the `remap_uuids=False` predicate" — and step 4's core instruction was INVERTED, from "pass the run's skip_predicate so the oracle cannot drift from the scrub" to "do NOT pass it; the oracle must deliberately diverge at the UUID-synthesis positions"; steps 2 and 4 rewritten; step 5 gained three required test cells (F1 regression, positional-not-blanket, no-allow-set); the files-to-touch set changed, adding PRD §5 and promoting README.md and __init__.py from conditional to definite; and one scope item moved OUT of the deferred list and INTO this change, the regex analog of the synthesized-value false-abort, on the ground that this change creates it) -> STOPPED
- Human gate: PENDING — stopped for the human (plan-gate: always, and the always-on architect
  materiality condition fired independently of it).
- Row left at Status `planning`, which is what an unapproved row reads as; resume re-enters at
  step 5, never past it.

### Why the architect's finding is load-bearing, in one paragraph

The plan's inference was "a regex match at a position the walk reached is therefore a leak".
Verified false at the synthesis positions: `pipeline.py:392` drops `_UUID_PATHS` from the skip set
under `remap_uuids: true`, so those five paths are reached, and `identifiers.py:225-248` mints a
canonical UUID there that I-3 never vets. A UUID-shaped `re:` rule would match the sanitizer's own
output and abort every run, deterministically, with nothing mis-scrubbed. The orchestrator
confirmed all three facts against the source before adopting the correction rather than taking the
agent at its word.

## 2026-08-30T05:30Z — #198 (code) — plan gate RESOLVED (step 5)

- Human gate: **plan APPROVED by the human** (plan-gate: always), with three amendments, each
  answering one of the plan's own open questions. The amendments are the human's own, so they
  need no second materiality stop — this gate exists to show the human what changed, and they
  authored these.
  1. **AC-4 findings must land durably** — "either in a follow up fix issue, or doc file". Read
     as **both**: the per-pattern audit result goes in a doc file (PRD limits section) for a
     reader of the guarantee, and a follow-up issue carries the code fix quoting the audit table.
  2. **Version bump DEFERRED to the merge gate** — "review the magnitude of the change once the
     actual implementation lands and passes review, then determine whether to version bump".
     `__init__.py` is dropped from the files-to-touch set; the magnitude is surfaced at step 11
     as an explicit decision, alongside whether landing this releases #190's `0.4.0` publish hold.
  3. **Deferred scope items must be FILED** — "defer but capture in follow up issue(s) so they're
     still tracked". Issues are filed at step 6 so the PR body can cite real numbers. #126 is
     checked for extension rather than duplicated, and the `scan_residual` code fix is the same
     issue step 8 already owed.
- Row advanced `planning` -> `plan-approved`. Resume now re-enters at implement (step 6); the
  architect and human gates are NOT re-run.

## 2026-08-30T06:05Z — #198 (code) — iteration open

- Issue: #198 — sanitizer: regex path/identifier rules get no output-side verification
- Route: code
- Branch: fix/198-regex-output-side-oracle (cut from origin/main at `0976f8c`)
- PR: #221
- Status: in-pr

## 2026-08-30T06:12Z — #198 (code) — CI + gates so far

- CI: **green 6/6** on `0d2334e` (build+twine, prettier, pytest 3.11/3.12/3.13, and the required
  `sanitizer-ci` aggregate).
- Lint: `npx prettier . --check` clean.
- Type: n/a: no type step — no mypy/pyright/tsc config exists in the repo and no CI job runs one
  (`TYPE_CMD` is `—` with that reason in loop.config.md).
- Test: four suites green — 533 / 49 / 15 / 16 OK.
- Hermetic: pass. Tier run under `unshare -rn` with the block verified socket-level first (direct-IP
  connect succeeds unwrapped, fails `OSError: [Errno 101] Network is unreachable` inside). 533
  passed, exit 0. Trigger fired: Route `code` and the change modifies tests.

## 2026-08-30T06:30Z — #198 (code) — code review round 1 (step 8)

`CODE_REVIEW` = the `code-review` skill at `high`, given the issue's four ACs plus four directed
questions (false-clear paths, the path-mirror, tests passing for the wrong reason, and unnamed or
misdescribing comments per the step-6 authoring rule).

**8 findings: 1 HIGH, 4 MEDIUM, 3 LOW.** AC verdict from the reviewer: AC-1 met, AC-2 met, AC-3
mostly met (three stale spots), AC-4 met.

**F1 (HIGH) — the regex oracle fires on the format's own dict key names. CONFIRMED by the
orchestrator against the repo's `fixtures/` corpus, and worse than reported:**

- `re:[a-z]{3,}_[a-z]{3,}` aborts **8/8** fixture files (reviewer measured 6/6 on a subset).
- `re:[a-z]{4,}[A-Z][a-z]{2,}` (camelCase) aborts **6/8**.
- **Every tripping string is a dict KEY**, all format schema names: `input_tokens` (617
  occurrences), `output_tokens`, `cache_read_input_tokens`, `stop_reason`, `stop_sequence`,
  `cache_creation`, `ephemeral_1h_input_tokens`. Values are ints, null or dicts — never PII.
  52 of 1149 distinct matches were keys; only keys abort.

**Root cause, and it is the same class as the architect's F1.** `_FORMAT_PATHS` enumerates *string
leaves the walk must not rewrite*. A format key whose value is a non-string never needed an entry,
because `walk_strings` never transforms a non-string leaf. Attributing a key its value's path and
gating on that allow-list therefore scans key names with nothing to exempt them. Exit 2, no
override, and **unfixable by the scrub** since a key cannot be addressed. That is "aborted every
session with nothing mis-scrubbed" relocated from values to keys.

The docstring justification is also false for exactly those keys: `("message","stop_reason")` IS a
preserved format position. "Not skip-listed" is not "user-writable".

**F2 (MEDIUM) — zero-width false clear. CONFIRMED.** `apply_rule` returns `""` for a zero-width
match so the scrub no-ops, and the new zero-width skip means the oracle is silent too. Probe:
`paths: [{match: "re:(?=/home/realuser)"}]` -> exit 0, `/home/realuser` verbatim in the output,
empty substitution table, `residual_scan: clean`. A real leak, not just an availability issue.

**F8 (LOW) — CONFIRMED, and it is the defect class this orchestrator asked the reviewer to hunt.**
The finditer cell's docstring claims "the engine's post-empty-match advance would end the scan".
False: `re.finditer(r'(?=alpha)', 'alpha then /home/realuser xalpha')` yields spans at **(0,0) and
(27,27)**. A comment that misdescribes the code it sits on, written by the same orchestrator that
put the standing check in the reviewer's prompt.

**Escalated to `DESIGN_AGENT` rather than fixed here.** F1's remedy is a design fork (do not scan
keys for regex / value-shape exemption / load-time I-3 analog / per-rule key opt-in), each with a
different false-clear-vs-false-abort profile and a different consequence for #208. The orchestrator
has already been redirected once on this exact class, so picking a fourth design unaided is the
move that produced the defect. Round 2 of this gate's 2-round cap is reserved for the fresh
re-check of whatever fix is ratified.

**Not yet fixed, pending the ruling:** F1, F2, F6 (the false key justification), F7 (the
"where the scrub could have acted" wording, which is self-contradictory for keys). **Independent of
the ruling:** F3 (no test pins the `_iter_decoded_strings` <-> `walk_strings` path mirror, though
the codebase has the precedent `test_uuid_transform_positions_match_pipeline_allow_list`), F4
(stale `pipeline.py:78` comment), F5 (stale docstring in `test_residual_rules.py`), F8.

## 2026-08-30T07:20Z — #198 (code) — code review round 2 (fresh re-check) — DIRTY, CAP REACHED

Fresh instance (a new spawn, not the round-1 reviewer and not the parent), given the change as it
stands plus the list of claimed fixes and none of the orchestrator's conclusions.

**All 9 claimed fixes CONFIRMED**, and the checker verified the motivating measurement itself
rather than taking it on trust (it re-simulated the reverted key-gating and reproduced 8/8 aborts).
`is_key` correctness confirmed exhaustively at both yield sites. Suite 535 passed + 1 xfailed.

**But 10 NEW findings, one HIGH — so round 2 is dirty and the 2-round cap is spent.**

**NEW-1 (HIGH) — CONFIRMED by the orchestrator. A third false-abort class, introduced by this
branch.** A regex rule whose **runtime-expanded replacement re-matches its own pattern** now aborts
at a reachable value position. Probe:

```
identifiers: [{match: "re:(user)_[0-9]+", replace: "\1_0000"}]
```

over `{"message":{"content":"hello user_1234 bye"}}` -> the scrub writes `user_0000`, which the
rule re-matches -> `ResidualRuleError identifiers[0]`, exit 2, no output. **On `main` this config
ran clean**, because the oracle filtered `if not rule.is_regex`. Load-time I-3 cannot catch it: it
vets the literal template `\1_0000`, which does not match the pattern; the *expansion* is produced
at runtime and no load-time check sees it.

**The CHANGELOG actively denies this**: "It does not fire on the sanitizer's own output" is written
as an absolute and justified only for the UUID-graph case. A shipping doc asserting a property the
code does not have is the defect class this iteration has now produced three times.

**NEW-9 (MEDIUM) — a test of mine passes without exercising what it names.**
`test_layer_order_leak_still_aborts_under_the_regex_path` never invokes `_regex_rule_survives`: the
literal `paths[0]` is evaluated first and raises. Its docstring claims it "goes red the moment
someone optimizes the exemption into a comparison against synthesized values" -- true only for the
*literal* check; a value-based exemption inside the regex path would leave it green. Also a
near-duplicate of the pre-existing `test_regex_expanded_replacement_does_not_excuse_a_literal_leak`.

**NEW-10 (LOW) — CONFIRMED, a number I wrote is ambiguous.** The docstring says "input_tokens (617
occurrences)". 617 is correct for `message.usage.input_tokens` **specifically**; the total across
all four paths is **1211** (`message.usage.iterations.input_tokens` adds 586). Unqualified it reads
as the total.

**Remaining findings, all documentation/comment defects of the same family:** NEW-2 (a
cross-reference added this commit half-resolves -- `scan_residual_rules` has no zero-width note),
NEW-3 (names `test_dict_key_is_scanned`, which does not exist), NEW-4 (three stale claims in the
same unreleased CHANGELOG section, one now contradicted by the new test), NEW-5 (a comment saying
"four payloads" where the cell now has five), NEW-6 (the `pii-regex` matrix entry under-asserts:
`KNOWN_DEVIATIONS` is a strict xfail on `!= REDACTED`, which cannot distinguish LEAKED from
FAIL-CLOSED -- the exact critique that module makes of itself), NEW-7 (PRD says "four things" over
five bullets), NEW-8 (a test *outside* the diff, `test_skip_allow_list_corpus.py:255`, is now
explained by a reason that is no longer true and is silently coupled to the new positional gate).

### Cap reached — ESCALATED to the human, no round 3

Per the Fresh-re-check invariant the cap ends the round, not the issue. The orchestrator does not
open round 3 on its own. Escalating with the observation that matters more than any single finding:

**This design has now produced three false-abort classes, each caught by a different reader, never
by the author.** (1) UUID-synthesis positions, caught by the architect at the plan gate. (2)
Format-owned dict keys, caught by code review round 1. (3) Self-rematching expanded replacements,
caught by the fresh re-check. Each fix was correct and each left the next one standing. That is a
property of the approach, not a run of bad luck, and it is the thing to weigh -- not the ten
findings individually.

Row stays `in-review`. Nothing merged. Security and acceptance gates NOT run: the merge candidate
is unsettled, and a verdict taken now would not survive whatever the human decides.

## 2026-08-30T07:55Z — #198 (code) — fix round 3 (human-authorized), re-check in flight

The 2-round cap was reached and escalated; the human authorized one further fix round plus a
re-check. That round is **not** a gate round the orchestrator opened on its own, and it is recorded
as the human's decision rather than as a cap that did not bind.

**All ten round-2 findings addressed** in `ba90026`.

**NEW-1 (HIGH), reproduced by the orchestrator before acting.** A regex rule whose runtime-expanded
replacement re-matches its own pattern aborts at a reachable value position. Probe:
`re:(user)_[0-9]+` -> `\1_0000` scrubs `user_1234` to `user_0000`, which the rule matches again ->
exit 2, nothing written; on `main` the same config ran clean. I-3 cannot reach it, since it vets the
literal template and the expansion exists only at runtime.

**Disposition: keep the behavior, document it honestly, pin it with a test.** The CHANGELOG's
absolute claim ("It does not fire on the sanitizer's own output") is narrowed to the UUID case it
actually justified. The class is argued **both ways** in the CHANGELOG and PRD §5 rather than
assumed: by the operator's own declaration the output still matches what they called sensitive,
which is the class I-3 rejects outright for static replacements; against that, nothing leaked. The
failure profile settles the disposition — availability-only, deterministic, surfaced on the first
run, fixed by rewriting the rule.

**NEW-9 was the most instructive.** A test of the orchestrator's own writing passed **without ever
invoking the function it was named for**: the literal `paths` rule was evaluated first and raised,
so `_regex_rule_survives` was never called and a value-based exemption added inside it would have
left the cell green. That is a test asserting an outcome rather than the mechanism — the Class B
shape, found by reading rather than by mutation. Its `paths` rule is now a regex and it is renamed.

**NEW-6 closed a gap of the same family:** the `pii-regex` matrix cell was pinned only by a strict
xfail on `!= REDACTED`, which FAIL-CLOSED and ERROR-<rc> also satisfy. `KNOWN_LEAK_VERDICTS` plus a
positive `== "LEAKED"` assertion now makes three futures visible — fixed, degraded, or made
safe-but-unscrubbable.

**NEW-8** was a comment *outside* the original diff that this branch made false; corrected, and the
real coupling (those cells now pass because the oracle's positional gate agrees with the allow-list
under test) is named rather than left implicit.

Remaining seven were documentation defects of the same family: a half-resolving cross-reference, a
named test that does not exist, three stale CHANGELOG claims, stale payload counts, a numbered list
that went stale (now de-numbered so it cannot again), and an ambiguous figure (617 is
`message.usage.input_tokens`; 1211 across all four paths).

**Process note carried to the dev-loop memo.** One edit in this round removed three unrelated tests
by overshooting a slice boundary; caught immediately because the test count fell 67 -> 36, and
reverted via `git checkout` of that single file against the committed baseline (safe here: the file
had no other uncommitted work, and this was the orchestrator's own bad edit rather than a mutation
artifact, so the AC-verifier prohibition on `git restore` did not apply). The lesson is that a
regex boundary over source is not a safe replacement primitive; the count check is what caught it.

Gates re-run: 537 passed + 1 xfailed, four suites green, prettier clean, hermetic tier re-run under
the block. Row stays `in-review` pending the fresh re-check.

## 2026-08-30T08:20Z — #198 (code) — round-3 re-check DIRTY, but the code is settled

Fresh instance (third distinct spawn; not round 1's reviewer, not round 2's checker).

**All 10 claimed fixes CONFIRMED, several verified by measurement rather than by reading:** the
checker instrumented both branch functions to prove the renamed test now calls
`_regex_rule_survives` **1x** and `_literal_rule_survives` **0x** (and that the old literal form did
the reverse), re-measured the 8/8 corpus abort independently, and re-counted the `input_tokens`
figures (617 / 1211) exactly.

**Zero new FUNCTIONAL defects.** Round 3's only source change was a docstring; nothing functional
moved, and the checker states no test now passes for a wrong reason that it did not already.

**11 new findings, all prose or test-quality.** The one with teeth is NEW-6: the round-3 test
`test_a_regex_rule_whose_expansion_rematches_itself_aborts` **asserts the outcome, not the
mechanism** -- `scan_residual_rules` raises identically on the scrubbed and unscrubbed strings, so
the cell stays green if the identifiers scrub ever stops reaching `message.content`, while its
docstring's story goes silently false. A control config (`replace: "\1_XXXX"` must exit clean) closes
it. That is the Class B shape again, this time in a test written *to pin* a class -- the third
distinct instance of assert-the-outcome in this iteration.

The other ten are stale cross-references and counts: a CHANGELOG line still saying `clean` does not
attest to regex rules (false since this branch, and it is release copy about a safety attestation),
the last surviving "four things" count, three `tracked in #198` forward-refs in `residual.py` that
should now read #217 / #220+#126 / #218, one more `re: is not re-verified` comment in the file this
branch edited most, the module docstring still describing two mapping forms where round 3 added a
third, and a consistency test not extended to the new mapping.

### Why this round is different from the two before it

The orchestrator ran a **mechanical sweep** rather than reacting to the reviewer's sample:
`grep` over the whole repo for the three invalidated claim patterns (`not re-verif` / `scrub-only`,
`in #198`, `four things|four payload`). The result is a **complete, bounded list of ~12 items**, and
every hit is accounted for -- the remaining `scrub-only` hits are `cli.py`'s unrelated
"scrub-only argument" sense, and `reference/subagent-traces.md`'s "four" is unrelated.

That is the difference the previous two rounds lacked. Rounds 1-3 fixed instances a reviewer
happened to find, which is why a new reviewer kept finding more; the surface was never enumerated.
It now is.

**Escalated to the human rather than opening a fourth round unilaterally.** The prior authorization
covered one round plus its re-check, and that is spent.

## 2026-08-31T09:05Z — #198 (code) — security gate (step 9): PASS

`SECURITY_REVIEW` = the local `/security-review` skill. Due: the diff touches
`tooling/sanitizer/`, which is on the PR template's closer-read list. `origin/HEAD` verified to
resolve first, so the gate diffed rather than erroring (loop.config.md §4's precondition).

**No findings at or above the confidence bar, in either direction.**

Evidence, which is stronger than a read-through and worth recording because a clean security
verdict is otherwise indistinguishable from a shallow one:

- With comments and docstrings stripped, the change is **~600 lines of prose and 25 lines of
  code**. `orchestrator.py` and `pipeline.py` have **zero** code changes; `config.py` and
  `rules/identifiers.py` are untouched, so I-3 and the UUID minting are exactly as on `main`.
- **Literal-rule coverage unchanged, confirmed three independent ways.** Structurally
  (`_literal_rule_survives` consumes every entry, ignoring `path` and `is_key`); **empirically by
  the orchestrator** (replayed `main`'s generator against HEAD's over all 1,494 fixture records --
  the yielded string multiset is identical, 0 differing records, and the literal check still sees
  dict keys in 627/619/349 records for `input_tokens`/`stop_reason`/`toolUseResult`); and
  **differentially by the reviewer** (3,441 rule-config combinations over 8 adversarial records:
  2,333 identical, 1,108 where HEAD aborts and `main` did not, **0 regressions**). There is no
  config for which `main` aborts and HEAD does not.
- **Skip-predicate polarity verified**, the one way this could have silently inverted:
  `make_skip_predicate` returns `path in allowed` where `allowed` is the *do-not-scrub* set, so the
  `continue` skips exempt positions rather than the inverse. `default_skip_predicate`
  (`remap_uuids=False`) is always a **superset** of the run's own skip set, so the check can only
  under-report, never claim coverage of a position the walk never visited.
- **D-2 intact.** `_regex_rule_survives` binds `match` as a loop local and discards it;
  `ResidualRuleError` still formats only `section[index]`; `residual.py` has no print, no logging,
  no file I/O; `sidecar.py` untouched.

Two behavior changes recorded as **non-findings** so they are not re-litigated: a regex rule can
now win the `section[index]` race against a later literal (diagnostic-only -- both exit 2, nothing
written), and an over-broad regex config can false-abort (availability, the safe direction by
design). Dict keys under a `re:` config remain a silent leak: `main`'s status quo carried forward,
documented in-code and tracked on #208, not a regression this branch introduces.

## 2026-08-31T09:20Z — #198 (code) — acceptance gate Part 1 (Class A): 4/4 MET

Fresh verifier, given only the ACs verbatim, the resolved `$BASE` and the commands to run. It
retrieved its own input and reported it before answering: base `0976f8c`, HEAD `13ebf91`, 10 files,
1230 insertions / 207 deletions, working tree clean, **no untracked files**, suite 539 passed +
1 xfailed. It judged nothing in the diff unrelated to the criteria.

| AC | Verdict |
|---|---|
| 1 — a decision recorded for regex output-side verification | **met** (architect ruling + scope-amendment comments on #198; implemented at `residual.py:381-385`, `:409-491`) |
| 2 — zero-width guard and `finditer` covered by tests | **met**, and the verifier **traced both cells as discriminating**: the zero-width cell raises without the guard, and the finditer cell's alternation puts a zero-width match *before* the survivor, so a `search`-based check reports clean |
| 3 — sidecar + PRD §10 wording matches the resulting guarantee | **met**; it grepped repo-wide for stale present-tense claims and found **zero** — the only survivors are explicitly historical |
| 4 — `scan_residual`'s blind spot fixed or documented | **met (documented)** — 12-row audit table, #217 filed, pinned by two new tests |

**Overall DONE. Class A findings: 0.**

### The amendment was audited, not accepted

This is the question the orchestrator could not answer about its own work, so it was put to the
verifier explicitly: is the mid-review narrowing a legitimate re-scope, or a reduction of AC-1's
intent dressed as satisfaction? It checked all three legs and **independently reproduced the
forcing evidence** — 8/8 and 6/8 aborts against `fixtures/`, matching the claimed numbers — rather
than taking them from the record. Verdict: legitimate. Recorded on #198 twice before verification;
#208's body genuinely carries the removed scope in its own voice with a dedicated regex-key AC;
the five spun-off issues are real and open.

**Its reservation is recorded here rather than smoothed over**, because it is the honest shape of
what shipped: the narrowing is large. #198's body advertised "closes #190 dict keys for regex" and
its first acceptance vector was "a regex `paths` rule whose match appears as a dict key must
abort". **That vector is not met, and its inverse is now a passing test.** What keeps it from being
a hollowed AC is that nothing is claimed that is not delivered and the residual is asserted
*positively* (`KNOWN_LEAK_VERDICTS` pins the cell as LEAKED and goes red if it silently becomes
anything else) rather than hidden behind an xfail that cannot tell a leak from a refusal.

### Three advisory flags (verifier: none block)

1. **Discoverability** — #198's body advertised a promise a later comment retracts. **Fixed
   immediately**, outside the merge candidate: a scope-narrowed banner now heads the issue body,
   naming the unmet acceptance vector explicitly and pointing at #208.
2. **The self-rematch false-abort class** is a genuine upgrade-behavior change. Already disclosed
   in PRD §5, the CHANGELOG and a pinned test. No action.
3. **The new AC-4 audit probe embeds an unsplit PEM banner literal**, which trips this repo's own
   `detect_secrets_in_output.py` hook. **Confirmed the hard way: the hook fired on the
   orchestrator's own grep while checking the flag.** No key material is involved, but the same
   file already splits that literal across a concatenation 138 lines above precisely to avoid this,
   so the fix is to follow the file's existing convention. Deferred until the Class B worktree is
   removed -- committing inside a live isolated-copy window is forbidden (Execution policy).

## 2026-08-31T09:45Z — #198 (code) — acceptance gate Part 2 (Class B): CLEAN, 0 survivors

Mutation pass run via the plugin harness in an **isolated worktree**; the agent owned all three
roles (select / apply / judge) because the tree at risk was its own copy. Improvised procedures are
forbidden and none was used.

**Harness exit 0.** `applied: 9`, `restored: 9`, `errors: []`, `survivor_groups: []`,
`snapshot_dir: null`. **7 real mutations KILLED, 2 controls SURVIVED**, so the clean verdict is
proven rather than vacuous — the pipeline demonstrably *can* report a survivor and declined to
seven times.

| mutation | verdict | caught by |
|---|---|---|
| drop the `is_key` skip in `_regex_rule_survives` | killed (4) | the two key-exclusion guards + the adversarial cell |
| neuter the `default_skip_predicate` gate | killed (35) | skip-list corpus + UUID-exemption cells |
| remove the zero-width span skip | killed (2) | both zero-width cells |
| `finditer` -> first match only | killed (1) | `test_regex_scan_uses_finditer_...` — exactly the named guard, exactly one test |
| kill the `is_regex` dispatch | killed (41) | corpus + UUID/format-key cells |
| **make `_literal_rule_survives` skip keys** | killed (10) | **the load-bearing one**: this branch *claims* it did not narrow #195/#190's literal-key guarantee, and the suite enforces that claim rather than the docstring merely asserting it |
| append the list index in `_iter_decoded_strings` | killed (1) | the new path-mirror test, with a precise tuple diff — the mirror is genuinely pinned |

### Two things the agent did that the gate depends on

1. **It caught its own precondition failure.** Its worktree was cut at the **base** commit, so
   `git diff <base> --stat` came back empty and the change was absent. It checked for the target
   functions rather than reading the empty diff as "no local edits", then checked out `13ebf91`
   before mutating. That is exactly the silent failure the envelope names: mutating a tree without
   the change, killing nothing, and reporting absences as survivors — a clean verdict that
   certifies the old code. It flagged the provisioning issue explicitly.
2. **It declined an equivalent mutation.** It did not spec removal of the `not text` half of
   `if is_key or not text:` because a match against `""` is necessarily zero-width and already
   dropped downstream — mutating it would have surfaced a *fake* survivor. Judgment the harness
   cannot supply.

Its one judgment note, recorded: mutations 2 and 5 kill very loudly (35 and 41 failures), mostly
via the `test_skip_allow_list_corpus` parametrization rather than a test named for those guards.
Coverage holds either way; the signal is coarse there relative to the others.

- Restore: 9 mutations applied, 9 restored, git status clean. Under isolation the counts describe
  the agent's copy, restored by discarding it; the clean status describes the **parent**, which was
  never mutated. Worktree removed by the parent (it materialized INSIDE the repo as
  `?? .claude/worktrees/`, the gitlink hazard — explicit-path staging is what covered it), and
  `/tmp/mutate-verify-*` is absent, so no snapshot was retained. Spec collected before removal and
  saved to `issue-198.mutation-spec.json` beside this plan, where interrupted-pass recovery needs
  it.

## 2026-08-31T09:50Z — #198 (code) — advisory fix + gate-currency note

Class A's third advisory flag was fixed on the merge candidate: the AC-4 audit probe wrote the PEM
banner as one contiguous literal, tripping this repo's own `detect_secrets_in_output.py` hook on any
tool read of the file. Confirmed the hard way — the hook fired on the orchestrator's own grep. The
same module already splits that literal for exactly this reason, so the fix follows its convention.
The **assertion is unchanged**: Python concatenates adjacent literals at runtime, so the value is
identical and only the source representation differs. Detector now finds zero matches in the file.

**Gate currency, stated precisely rather than assumed away.** Class A and Class B both certified
`13ebf91`. The merge candidate is now `c5711c4`, which the acceptance gate has **not** seen. What
changed: one line of test source, a literal split, identical runtime value, no assertion altered,
in a file Class B never mutated (it mutated `residual.py` only). Full suites and the hermetic tier —
re-armed by the test-only change — are green on the new head. This is a change no gate certified,
so it goes to the human at the merge gate rather than being absorbed. Under `mode: calibration`
every merge stops there regardless.

## 2026-09-01T08:00Z — #198 (code) — iteration complete

- Selected: #198 (`priority:high`, the only high-priority selectable row).
- Route: code (full pipeline, all gates).
- Plan: issue-198.plan.md; `## Approach` frozen before the design gate, so the materiality test had
  a real pre-image.
- Architect: RAN twice. At the plan gate it materially redirected the approach (blocking F1: the
  gate must NOT use the run's own skip predicate, or the oracle aborts on the sanitizer's own
  minted UUIDs). At the code-review gate it was consulted again on the key-position fork and ruled
  Option A, narrowing the issue's scope.
- Plan-gate: material (a different fork chosen: design 1 CORRECTED; step 4's core instruction inverted from "pass the run's skip_predicate so the oracle cannot drift" to "do NOT pass it, the oracle must deliberately diverge at the UUID-synthesis positions"; steps 2 and 4 rewritten; step 5 gained three required test cells; the files-to-touch set changed, adding PRD §5 and promoting README.md and __init__.py from conditional to definite; and one deferred scope item moved INTO the change) -> STOPPED
- Human gate: plan approved by the human (plan-gate: always), with three amendments — AC-4 findings
  must land durably, the version bump deferred to the merge gate, and every deferral filed as an
  issue.
- Implemented: position-gated regex oracle in `residual.py` (`_iter_decoded_strings` now yields
  `(text, path, is_key)`; `_literal_rule_survives` / `_regex_rule_survives` split); PRD §5/§6b/§10/
  §11/§13, README, CHANGELOG; new cells in `test_residual_rules.py`, `test_residual.py`, a
  `pii-regex` family plus `KNOWN_LEAK_VERDICTS` in `test_adversarial_placement.py`.
- Hermetic: pass. Re-run on every head that changed a test, with the block verified socket-level
  first (direct-IP connect succeeds unwrapped, `Errno 101` inside).
- PR: #221 (fix scope). CI: green 6/6 on every head.
- Code-review: **4 rounds** — round 1 (8 findings, one HIGH), round 2 fresh re-check (10 findings,
  one HIGH; **cap reached, escalated**), then two further rounds the human authorized: a fix round
  plus re-check (11 findings, none functional), and a final mechanical sweep. Security: PASS, no
  findings.
- Restore: 9 mutations applied, 9 restored, git status clean.
- AC-verify: Class A 4/4 acceptance criteria met, 0 findings, and the verifier separately audited
  whether the mid-review narrowing hollowed out AC-1 — reproducing the forcing evidence itself
  before ruling it legitimate. Class B: 0 survivors (7 real mutations killed, 2 controls held,
  exit 0).
- Budget: subagent-runs=8 (architect ×2 + code-review skill + 2 fresh re-checks + security + AC Class A + Class B mutation) · gate-rounds=architect=2,code-review=4(correctness,robustness,false-clear-paths,path-mirror-fidelity,test-efficacy,claim-resolvability),ac-verify=1 · ac-findings=0 · mutation-survivors=0 (7 real mutations killed, 2 controls held, exit 0) · post-gate-survivors=0 · justification=code-review ran 4 rounds because rounds 1 and 2 each found a HIGH functional defect of the same class (a false-abort the design did not anticipate); the 2-round cap was reached and the human authorized rounds 3 and 4, the last being a mechanical sweep that enumerated the remaining surface instead of sampling it · wall-clock=≈51h (2026-08-30T04:58Z to 2026-09-01T08:00Z, mostly gate-wait across three human decisions) · tokens=deferred
- Merged: squash #221 as `92d7ae1`. Issue #198 closed. Branch deleted local and remote.
- **Post-merge verification ON MAIN** (not assumed from the branch): 539+1x / 49 / 15 / 16 OK,
  prettier clean, working tree clean, one worktree, no retained snapshots, no stray branch.
- Version: **no bump**, by human ruling — 0.4.0 is unreleased, so the determinism contract has no
  downstream consumer to break. The `0.4.0` PyPI publish hold from #190 remains the human's, and is
  now unblocked by #198 landing.
- Next: no `priority:high` work remains in the epic (#1 is the epic tracker, terminal). Highest
  selectable is `priority:medium` — #192, #201, #202, #203.

### Iteration finding, carried to the dev-loop memo

**Three false-abort classes, from one design, each caught by a different reader and never by the
author.** (1) UUID-synthesis positions — architect, at the plan gate. (2) Format-owned dict keys —
code review round 1, reproduced at 8/8 fixture files. (3) Self-rematching expanded replacements —
the round-2 fresh re-check. Each fix was correct and each left the next one standing, which is a
property of the approach rather than a run of bad luck.

**What actually converged it was enumeration, not iteration.** Rounds 1–3 fixed the instances a
reviewer happened to sample, so every new reviewer found more. Round 4 grepped the repo for the
three claim patterns the change invalidated and accounted for every hit; the surface went to zero
and stayed there. The lesson for the loop: when a change invalidates a *class* of prose claim,
sampling review cannot close it — only a mechanical sweep can.

**Assert-the-outcome appeared three times, twice in tests written to pin a class.** A test that
never called the function it was named for; a matrix entry pinned by an xfail that could not tell a
leak from a refusal; and a cell that would have stayed green if the scrub stopped running. All
three were caught by reading, not by mutation — and the Class B pass then came back clean, which is
the right order: the cheap reader finds the assertion-shaped defects, the harness proves the rest.

**One process failure worth carrying:** a regex slice boundary over source silently removed three
unrelated tests. Caught only because the test count fell 67 -> 36. A count check after any
programmatic edit to a test file is cheap insurance; a regex boundary is not a safe replacement
primitive.
