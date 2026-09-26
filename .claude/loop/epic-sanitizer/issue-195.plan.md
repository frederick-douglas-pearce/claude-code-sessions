# Plan: #195 — feat(sanitizer): total output-side oracle for path/identifier rules

**Route:** code  **Branch:** `feature/195-output-side-oracle`

## Value framing (route-scaled — see step 3)

`feat:` — backbone activity: **publish a session transcript without leaking the author's
identity or filesystem.**

**Story 1 — the sidecar must not certify what it did not verify.**
_As a maintainer publishing a sanitized fixture, I want the sanitizer to refuse to write output
that still contains a configured path or identifier, so that `residual_scan: clean` cannot appear
on a file that still holds my home directory or my name._

- **Who benefits:** this repo (every `fixtures/sanitized/` artifact), CCDC contributors (#75),
  and any `pip install claude-code-sessions-sanitizer` user. The README makes sidecar review the
  human gate, so a false clean converts that review into a rubber stamp.
- **Prevalence:** two confirmed instances found by two different methods (#190 dict keys, via the
  placement harness against the PyPI wheel; #194 skip-list names, via manual probing). #195's
  argument is that the position space is open-ended — tool inputs are tool-defined and MCP servers
  define their own schemas — so instance count is expected to keep growing.
- **Falsifier:** _"the paths/identifiers layers already have an output-side check, or every
  traversal gap already fails closed via the secret residual scan."_ **DISCHARGED — false.**
  `orchestrator.py:135` is the only post-pipeline pass: `scan_residual(out,
  config.extra_secret_patterns)`. It takes secret patterns only. A repo-wide grep for any other
  re-scan of `config.paths` / `config.identifiers` over output returns nothing.

**Story 2 — the leak is silent today, not merely theoretical.**
_As a reviewer, I want a traversal gap to abort the run, so that "exit 0 plus a clean sidecar" is
evidence rather than an assumption._

- **Falsifier:** _"the two reported instances do not actually reproduce against the shipped
  0.3.0."_ **DISCHARGED — they reproduce.** Ran the installed 0.3.0 console script over a
  three-cell synthetic session with a two-rule config (`/home/probeuser` → `/home/user`,
  `probeuser` → `user`):

  | Cell                                     | Result                     |
  | ---------------------------------------- | -------------------------- |
  | value as a **dict key** (#190)            | LEAKED verbatim, exit 0    |
  | value at `tool_use.input.version` (#194)  | LEAKED verbatim, exit 0    |
  | value as an ordinary string leaf (control)| redacted correctly         |

  The sidecar for that run reports `residual_scan: clean`, `paths: {substitutions: 1}`, and a
  populated `substitutions:` list — it looks like a healthy run. Two of three planted values
  survive in the output bytes.

**Source-fidelity note.** The rationale is internal (this repo's own issues #190/#193/#194 and the
sanitizer PRD), not an external citation, so there is no external generalization to check. The
one upstream-ish claim — that the wheel published to PyPI carries the defect — was verified
directly by running the installed console script rather than a source checkout.

## Acceptance criteria (verbatim from issue)

**Note:** #195 carries no `## Acceptance criteria` block. The criteria below are its **Test plan**
section, quoted verbatim, plus the three properties its **Proposed change** section commits to.
Flagging the substitution because the acceptance gate (step 10) will be run against this list.

From **## Test plan**:

- [ ] A configured value planted in a dict key aborts rather than writing (currently #190's silent leak).
- [ ] A configured value at `tool_use.input.version` / `.type` / `.sessionId` / `.max_tokens` / `.usage.x` aborts rather than writing (currently #194's silent leak).
- [ ] A normal scrub of an already-clean session still exits 0, and its output and sidecar bytes are unchanged. The golden fixtures must not move.
- [ ] A regex rule is scanned via its compiled form, not its literal source.
- [ ] The abort names the rule and never prints the matched value (D-2).
- [ ] The sidecar records `residual_scan: clean` only when both scans pass.
- [ ] Confirm no legitimate config trips the oracle on its own replacements, leaning on the I-3 invariant above.

From **## Proposed change** (properties committed to):

- [ ] Position-agnostic. Covers #190, #194, and the next traversal gap without anyone naming it first.
- [ ] Byte-neutral on the happy path. Output that is already clean is unchanged.
- [ ] Converts every future silent leak into a loud abort.

From **## Versioning**:

- [ ] Target **0.4.0** (from 0.3.0). MINOR, not PATCH.

## Approach

_Revised after the architect pass (review recorded as a comment on issue #195). One `blocking`
finding changed step 5's mechanism outright; the rest are `important`/`suggestion` refinements.
Changes are marked **[architect]**._

1. **`residual.py` — add the oracle beside the secret scan.** New `ResidualRuleError` and
   `scan_residual_rules(lines, paths, identifiers, allowed_replacements)`. **[architect]** The
   signature gains the run's recorded-replacement allow-set (step 5); the plan previously passed
   only the rules. Iterates per line like `scan_residual` (first match wins), matching with
   `rule.compiled` — which satisfies the regex criterion for free, since `_compile_rule` stores
   literals as `re.escape`d patterns. **[architect]** Pin a deterministic iteration order — paths
   then identifiers, ascending index — so the reported `section[index]` is stable to assert on.

2. **Name the rule without printing it.** `ResidualRuleError` carries `section` and `index`
   (`paths[0]`), never `rule.pattern` and never the matched span. The architect endorsed this and
   sharpened the reasoning: the oracle fires on *successful-looking* runs, which are exactly the
   ones that execute in CI and inside Claude Code sessions, so printing the span would write real
   PII into the artifact class this repo exists to sanitize.
   **Declined, with rationale:** the architect offered appending the rule's *replacement* string as
   a safe enrichment. Omitting it. Replacement text is user-authored and nothing structurally
   forbids PII there — I-3 constrains only whether a replacement *matches a rule*, not whether it
   is sensitive — so "non-sensitive by construction" is really "non-sensitive by convention". The
   diagnostic stays strictly `section[index]`.

3. **`orchestrator.py` — call it after the secret scan, before returning**, threading in the
   subtable's recorded replacements. Precedence endorsed by the architect: a surviving secret
   should still report as a secret (D-1 floor), and both map to exit 2, so the only observable
   difference is which diagnostic prints. **[architect]** Update the docstring at lines 63-70 and
   88-96 — it currently promises "if this function returns, the residual scan passed", and there
   are now two scans.

4. **`cli.py` — map the new exception to exit 2.** **[architect]** Three concrete edits, not one:
   add the type to the actual `except (PipelineError, ResidualSecretError, SidecarLeakError)`
   tuple at line 790 with its import; update the module docstring exit-code list at lines 5-13;
   and confirm `str(exc)` is span-free so the catch-all `except Exception` at 795 cannot print PII.

5. **[architect — BLOCKING, mechanism replaced] Exact-membership exclusion, not masking.** The
   plan's original fix (delete recorded replacement strings from each line before scanning) is
   unsafe and is withdrawn: blind string-deletion can manufacture a **false negative**, the one
   failure direction a security tool cannot tolerate. Construction — rule `match: abc123` /
   `replace: abc` passes I-3; if `abc123` genuinely leaks, deleting every `abc` first leaves `123`,
   the rule no longer matches, and the leak ships with a clean sidecar.

   Instead: scan with `rule.compiled` and, on a match, **abort unless the exact matched span is a
   member of the recorded-replacement set** — no text mutation. Why this has no false negatives: a
   genuine leak is an *original*, and I-3's full cross-product (config.py:491) already guarantees
   no rule matches any configured replacement, hence transitively that no replacement equals any
   original. So a real leak's span is never in the allow-set. It excuses exactly the synthesized-
   UUID gap and nothing else, and costs O(1) per match. Residual false positives are only in the
   safe direction (a regex matching *part* of a synthesized UUID still aborts).

   The architect also rejected the alternative I had listed (extend I-3 to reject UUID-shaped rules
   under `remap_uuids`): it is UUID-specific and undecidable at load time, since the synthesized
   values cannot be enumerated before the run.

6. **Version + docs.** `__version__` 0.3.0 → 0.4.0 (MINOR confirmed: new refusal surface, no
   sidecar field removed or retyped, no config break). **[architect]** Two things to state
   explicitly: `test_golden_determinism` stays **green** because clean bytes are unchanged, so the
   bump is a deliberate hand-recorded MINOR rather than a trigger-fired regeneration — say so in
   the CHANGELOG so a reviewer does not expect the golden to move; and confirm
   `sidecar_schema_version` stays `1`. Update PRD §5, §11, and **[architect]** generalize the §10
   note at line 428 (`residual_scan: clean`) to cover rules, not only secrets. Update the
   `residual.py` module docstring.

7. **Tests** — `tooling/sanitizer/tests/test_residual_rules.py`, one case per Test-plan bullet,
   plus **[architect]** three the issue's plan omits:
   (a) `remap_uuids: true` with a broad UUID identifier rule does **not** false-abort — the Q2
   regression, and the single most important new test;
   (b) a genuine leak whose span is *not* a recorded replacement still aborts, guarding the
   exclusion from over-excusing;
   (c) a configured value on a strip-types-dropped line does **not** abort, since it is never
   written.
   Scanning only written output is correct as planned — `run_pipeline` `continue`s on strip-types,
   so `out` is exactly the bytes written. Add the new file to the security-critical suite list in
   `.github/workflows/sanitizer-ci.yml`.

8. **[architect — new] File a follow-up issue** to change `_check_replacement_leak`'s ConfigError
   messages (config.py:494-532) to use `section[index]` instead of `rule.pattern!r`. That is the
   same leak class on the exit-3 path, and the architect's judgment is that it is a latent leak
   rather than a precedent to emulate. Out of scope for #195; the issue gets filed with this PR.

9. **[architect — new] Release coordination, before publishing.** (a) Run the oracle against this
   repo's own real scrub inputs and the CCDC (#75) workflow to confirm nothing that scrubs today
   now refuses. (b) Resolve the bundling: bump `__version__` here but **do not publish to PyPI
   until #190/#194 land**, so the first version a `pip` user sees carries coverage and not merely
   refusal. Both paths are safe (refuse beats leak); this is a UX call.

**No escape hatch.** The architect explicitly recommends shipping without `--no-oracle`: with
exact-membership the realistic false-positive rate is ~zero, and an override would recreate the
silent-leak path this issue closes. This matches the established stance that `--no-check` is not
the fix for exit 3. The user's escape is narrowing their rule, which the `section[index]`
diagnostic tells them how to do.

**Forward-compatibility constraint to record:** exact-membership forward-covers v1 jitter's
synthesized values **iff** jitter records them into the `SubstitutionTable`. Note that in the
jitter design (PRD §9b) — the load-time-only alternative would have silently failed to cover it.

**Explicitly not in scope:** fixing #190 or #194. #195 states the sequencing — it lands first and
alone; those two land together afterwards. After this change their positions abort instead of
leaking, which converts them from leak gates to coverage work.

## Approach as reviewed (frozen before the design gate) — write-once, do not edit

1. **`residual.py` — add the oracle beside the secret scan.** New `ResidualRuleError` and
   `scan_residual_rules(lines, paths, identifiers)`. Iterates the same way `scan_residual` does
   (per line, first match wins) and matches with `rule.compiled`, which satisfies the regex
   criterion for free — `_compile_rule` already stores literals as `re.escape`d patterns, so
   literal and regex rules scan on identical footing.

2. **Name the rule without printing it.** `ResidualRuleError` carries `section` and `index`
   (`paths[0]`, `identifiers[2]`) — never `rule.pattern`, and never the matched span. This is
   stricter than the issue's wording ("name the rule"): a paths/identifiers `match` value **is**
   the literal PII (real home dir, real name), so printing it to stderr would leak the config's
   secret into any terminal, CI log, or Claude Code transcript that captures the run. Mirrors how
   `ResidualSecretError` carries only `kind`. **Flagged for the architect** — see below.

3. **`orchestrator.py` — call it after the secret scan, before returning.** One added line plus
   docstring updates. Keeping it after `scan_residual` preserves the existing failure precedence
   (a surviving secret still reports as a secret).

4. **`cli.py` — map the new exception to exit 2** alongside `PipelineError` /
   `ResidualSecretError` / `SidecarLeakError`, with a diagnostic naming the section and index and
   pointing at the two coverage issues.

5. **Close the `remap_uuids` gap the issue flags as an open question.** Verified real:
   `identifiers.py:146-158` **early-returns** on a `UUID_FIELDS` leaf when `remap_uuids` is on, so
   user identifier rules never run on that leaf. The synthesized UUID is a runtime value that
   `_check_replacement_leak` has never seen, so a broad rule (e.g. `re:[0-9a-f-]{36}`) would not
   fire during scrub and *would* match in the output — a false abort on every run. Preferred fix:
   mask the substitution table's recorded replacement strings out of each line before scanning.
   The subtable already holds every `original → replacement` pair the run produced, including
   `identifiers:uuid` rows, so this is position-agnostic and needs no new bookkeeping.
   **Architect question** — see below.

6. **Version + docs.** `__version__` 0.3.0 → 0.4.0; CHANGELOG entry; PRD §5 and §11 updated to
   describe the second output-side gate and its exit code. The determinism contract requires the
   bump because the set of inputs the tool refuses changes.

7. **Tests** — `tooling/sanitizer/tests/test_residual_rules.py`, one case per Test-plan bullet,
   plus a golden-determinism re-run asserting existing fixtures do not move. Add the new file to
   the security-critical suite list in `.github/workflows/sanitizer-ci.yml` so a rename or
   deletion goes red.

**Explicitly not in scope:** fixing #190 or #194. #195 states the sequencing — it lands first and
alone; those two land together afterwards. After this change, their positions abort instead of
leaking, which converts them from leak gates to coverage work.

## Architect triggers hit

Three fire (loop.config.md §2):

1. **"Any change to the sanitizer's scrubbing behavior — rules, pipeline, residual scan, or
   sidecar shape."** Directly: this adds a new fail-closed exit path.
2. **"CI/workflow structure changes"** — step 7 edits the required `sanitizer-ci` gate's suite list.
3. **Published-artifact blast radius** — 0.4.0 goes to PyPI; a false-positive oracle bricks the
   tool for every user whose config happens to match its own output.

Two questions for the architect:

- **Q1 — how should the abort name the rule?** The issue says "names the rule"; a rule's `match`
  string is literal PII. Section+index (`paths[0]`) leaks nothing but is less actionable.
  Alternatives: the rule's replacement text (safe, but ambiguous across rules), or a config-load-
  assigned label. Note `_check_replacement_leak` already prints `rule.pattern!r` in ConfigError
  messages, so there is a contrary precedent to reconcile.
- **Q2 — masking vs. tightening I-3 for synthesized UUIDs.** Mask recorded replacements before
  scanning (general, handles any future runtime-synthesized value, but weakens #195's "no span
  masking needed" simplification), or extend I-3 to reject rules matching a canonical UUID shape
  when `remap_uuids` is on (keeps the scan trivially simple, but rejects some legitimate configs
  and only covers the one known synthesized value)?

## Risks / open questions for human

- **The oracle's false-positive mode is a hard failure.** If a legitimate config trips it, the
  tool refuses to scrub anything and the user has no override. The I-3 invariant is what makes
  this safe, and Q2 is a known hole in it. Worth deciding whether 0.4.0 should ship an escape
  hatch, though a `--no-oracle` flag would recreate the silent-leak path this issue exists to
  close.
- **AC substitution.** The acceptance criteria above are derived from the issue's Test plan
  rather than a formal AC block (noted in that section). If you read the scope differently, say so
  now — step 10 verifies against this list.
