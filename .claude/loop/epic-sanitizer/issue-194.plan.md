# Plan: #194 — fix(sanitizer): bare-name skip-list exempts user data inside tool inputs

**Route:** code  **Branch:** `fix/194-anchor-skip-list`

---

## Value framing (route-scaled — `fix:`)

**Who hits it.** Anyone sanitizing a session that used a tool whose input schema happens to
use one of ~14 reserved names. MCP servers define their own schemas, so the space is open.

**How often.** `type`, `version`, `max_tokens`, `sessionId`, `role`, `id`, `model` are among
the most common parameter names in any tool schema. Not exotic.

**What breaks without the fix — two outcomes, and only one was previously recorded:**

| Config kind | Behavior at a skip-listed position | Severity |
|---|---|---|
| **literal** rule | exit 2, no output (the #195 oracle catches it) | usability: unusable config, but safe |
| **regex** (`re:`) rule | **exit 0, value present, sidecar `residual_scan: clean`** | **silent leak** |

The regex half is the reason this is `priority:high` and not a papercut. #195's oracle
deliberately does not re-verify regex rules (`residual.py:189-206`), so for a regex-configured
scrub the original silent leak is **unchanged on `main` today**.

**Falsifier.** *"These positions are already safe after #195, so this is usability-only."* —
that is what the three "Rescoped under #195" comments asserted.

### Falsifier DISCHARGED by running (step 3), not asserted

Probed against merged `main` `91adca1` (`scratchpad/probe194.py`), 16 positions planted inside
`tool_use.input`, one value, two configs:

- **literal rule:** 16/16 FAIL-CLOSED (`ResidualRuleError`, section=paths).
- **regex rule:** **16/16 LEAKED** — exit 0, value present in output.
- **positive control** (`input.plain_control`, a name the predicate never matches): REDACTED
  under both. So the rules work; the **position** is the defect.

The falsifier is **refuted**: the leak is live. Value story holds.

### Second probe — the symmetric TRANSFORM-side surface (new finding)

`make_skip_predicate` decides *visit-or-not*. `build_identifier_transform`
(`rules/identifiers.py:132-160`) decides *what happens when visited*, and it also matches
**bare names at any depth**. Probed (`scratchpad/probe194b.py`) on merged `main`:

- **`input.gitBranch: "release/2026-q3-payments"` → `"feature/example"`**, with **default
  options** (`scrub_git_branch: true`). Any depth. Silent **corruption** of a tool parameter.
- **`input.sessionId: "customer-order-88213"` → `c65a126e-…`** under `remap_uuids: true`.

The `sessionId` case is one line in the issue's "Rescoped" comment. **The `gitBranch` case
appears nowhere** — not in the issue, not in the two corrections, not in the architect review —
and it fires under defaults. Same root cause: a bare name matched in an open position space.

**Source fidelity.** The issue's rationale is its own repro plus two self-corrections, all
internal. Both were re-verified here by running against current `main`, not taken on trust.
The one external-ish claim — "`max_tokens` is a real parameter name on a real API" — is true
of the Anthropic Messages API and needs no further sourcing.

### Prevalence check — NULL RESULT, reported squarely

A full key-path survey of every fixture (8 files, **1,494 records**, versions 2.1.150–2.1.185)
found **zero** occurrences of any skip-listed name inside a `tool_use.input` subtree. The
complete observed input-key set is ordinary tool parameters (`file_path`, `command`,
`old_string`, `prompt`, `questions`, …). **No collision has actually happened in this corpus.**

This does **not** refute the bug — the probe above proves the mechanism directly, and the
position space is open by construction (MCP servers define their own schemas). But it is the
honest prevalence number and it sits in tension with `priority:high`: the corpus is eight files
from one user with a narrow tool set. **The human should weigh this at the plan gate.** What
the survey *does* establish is that the fix has a large blast radius on the format side, which
is the finding that reshaped the approach below.

---

## Acceptance criteria

⚠ **#194 carries no explicit AC block.** These are derived from the issue's **Test plan**
section and the enumerated surface in its **"Rescoped under #195"** comment. Quoted fragments
are verbatim; the framing is mine. **This is an issue amendment and gets posted to #194 before
implementation** (engine step 5: an AC reinterpretation is recorded on the issue).

- [ ] **AC-1 — the full over-skip surface is closed, not the five names filed.** Per the
      Rescoped comment, the fix "must cover the full over-skip surface established in the
      correction above, not the five names this issue was filed with":
      `_SKIP_LEAF_NAMES` (5) **and** `_UUID_NAMES` (4, at default `remap_uuids: false`), the
      `*_tokens` suffix rule, the `parent == "usage"` rule, and `_ANCHORED_PARENT_LAST_SKIPS`,
      "which is not actually anchored".
- [ ] **AC-2 — redaction, not refusal.** "A cell per skip-listed name planted inside
      `tool_use.input`, asserting redaction." Verdict must be REDACTED (exit 0, value gone),
      **not** FAIL-CLOSED.
- [ ] **AC-3 — format markers are still skipped.** "A cell per name in its legitimate
      structural position, asserting it is still skipped, so the fix does not start scrubbing
      format markers."
- [ ] **AC-4 — anchoring is by position, not depth.** "Nested case (`input.a.type`) to pin that
      anchoring is by parent, not by depth alone."
- [ ] **AC-5 — regex configs are covered.** The positions must be REDACTED for a `re:` rule,
      not merely fail-closed — this is the half #195 does not speak for (issue comment
      2026-08-22). Directly falsifiable by re-running `probe194.py`.
- [ ] **AC-6 — PRD §6b B corrected.** "PRD §6b B encodes the bug in prose (`*.role`, bare
      `version` / `type`), so the spec needs correcting alongside the code, or the next
      implementer will re-derive the same skip-list."
- [ ] **AC-7 — version bump.** "this changes output bytes for affected inputs and needs a
      version bump." (`__version__` carries a determinism contract; `main` already sits at
      an unreleased `0.4.0`, so this rides that bump rather than adding one.)

### Added after the architect gate — scope GROWTH, not absorbed silently

The frozen plan had a single "proposed AC-8" covering the whole transform-side surface. The
architect **split it**, and added a drift criterion. All three are new scope beyond what #194
asks for, and all three need the human's yes at the plan gate:

- [ ] **AC-8 — UUID transform anchored on paths, and its guard test made real.** *(architect C3,
      ruled to belong in **this** PR.)* Moving the pipeline to paths while
      `build_identifier_transform` still matches `UUID_FIELDS` by bare name leaves
      `test_uuid_fields_match_pipeline_skip_list` (`test_identifiers.py:478-485`) **green while
      the invariant it guards is broken**, and leaves `input.sessionId` corruption live under
      `remap_uuids: true`. Rewrite the test to a path-level equivalence.
- [ ] **AC-9 — `gitBranch` corruption filed as its own bug.** *(architect C4; hard requirement
      that it not ship untracked.)* Fires under **default** options. Recommendation to confirm:
      file it **and** fix it here, because AC-8 already opens the same function.
- [ ] **AC-10 — drift detection ships with the change.** *(architect C5.)* A characterization
      test over the current corpus now; a `format-scan` drift check filed as fast-follow.

**AC-1 is unchanged in intent but its table is materially different** — see the Approach: the
`**` prefixes were ruled a blocking regression and are gone, and `message.content.content.type`
is dropped rather than allow-listed. No acceptance criterion has been *reduced*.

---

## Approach

> **Revised after the architect gate** (issue #194 `issuecomment-5379462629`, 2026-08-22).
> The pre-image below (`## Approach as reviewed`) is what was frozen *before* that review.
> Changes are attributed inline: **[C1]**–**[C5]** are the architect's; **[mine]** marks a
> change I made from my own evidence after the review.

**The fix is an inversion, not another enumeration.** Every rule in `make_skip_predicate`
(`pipeline.py:161-183`) matches **depth-agnostically** — `path[-1]` against a name set, a
`_tokens` suffix, `path[-2] == "usage"`, or a `(parent, last)` pair. Every one of them
therefore fires inside `tool_use.input`, which is arbitrary tool-defined JSON. Adding more
names, or carving out `input`, patches an enumeration over an **unbounded** space.

`walk_strings` already builds a **root-anchored path** from the line object
(`pipeline.py:213-230`), so the information needed to close the class is already in hand and is
simply not being used. The change is to match on the **whole path** instead of its tail.

Architect ruling on mechanism (Q1): **root-anchored allow-list, endorsed**; the rooted-boundary
variant is rejected because it needs its own open enumeration of uncontrolled subtrees and
cannot express the *mixed* `toolUseResult` envelope. But the tabled execution was **not safe to
build**, for the reasons now folded in below.

### 1. Exact paths only — no subtree prefixes at all **[C1, extended by mine]**

The frozen plan used `**` subtree prefixes (`error.**`, `message.diagnostics.**`,
`message.usage.**`, `toolUseResult.usage.**`). **C1 ruled these blocking**: a prefix is the
`"usage" in path` membership test the codebase already deleted (`pipeline.py:174-178`), merely
rooted, and `error.**` would regress a currently-scrubbed leaf into a skipped one.

**I verified C1 rather than adopting it, and it is understated.** Enumerating every string leaf
under `error.*` across the fixtures returns not just `error.error.error.message` ("Overloaded")
but an entire HTTP header dump:

```
error.headers.set-cookie                    '_cfuvid=ecnH1OOywlamA38dunuyPgwIaGJoImOnZ9xyrv5MzLU-…'
error.headers.anthropic-organization-id     'c86124b6-bb43-47d2-8010-971229036882'
error.headers.request-id / cf-ray / traceresponse / date / …
error.error.request_id                      'req_011CbWXJinmhYhU6bx7zww4L'
```

All are visited and scrubbed today. `error.**` would have skipped **every one**, including a
session cookie and an organization UUID. A leak introduced by the PR meant to close leaks —
exactly C1's argument, on evidence C1 did not have.

**Going one step beyond C1: drop prefixes entirely.** C1 allowed `message.usage.**` if
justified. I enumerated it instead — both `usage` subtrees contain exactly **four** string
leaves each, all closed enums:

| leaf | observed values | rec |
|---|---|---|
| `…usage.service_tier` | `standard` | 605 / 3 |
| `…usage.speed` | `standard` | 584 / 3 |
| `…usage.inference_geo` | `""`, `not_available` | 604 / 3 |
| `…usage.iterations.type` | `message` | 586 / 3 |

Eight exact entries replace two prefixes, and the allow-list ends up with **zero** prefix rules.
An unknown future string field under `usage` is then *scrubbed* (safe, visible) rather than
silently skipped — which is the whole point of the inversion, applied to itself.

### 2. Two tiers, because "no-op to visit" ≠ "must preserve" **[C2]**

`walk_strings` only mutates a leaf a configured rule *matches*, so a format enum is already a
no-op to visit and allow-listing it protects nothing. Separating the tiers keeps the
load-bearing list small and gives the tests something to aim at:

- **Tier A — load-bearing preserves** (the value could match a rule and must survive):
  the four UUID-graph fields at line level (remap-gated), and `message.content.signature`
  (base64-ish, can trip secret patterns).
- **Tier B — opaque format identifiers** preserved for graph integrity: `requestId`,
  `message.id`, `message.content.id`, `message.content.tool_use_id`, `toolUseResult.agentId`.
- **Tier C — enum discriminators**, exact entries documented *"no-op today, listed to pin
  intent"*: `type`, `message.type`, `message.content.type`, `message.role`, `message.model`,
  `version`, `error.type`, `error.error.type`, `error.error.error.type`,
  `message.diagnostics.cache_miss_reason.type`, `toolUseResult.type`,
  `message.content.caller.type`, and the four `usage` leaves above (×2 parents).

**Dropped from the frozen table [C2/Q6]:** `message.content.content.type` — it sits inside the
`tool_result` content array, which the data dictionary documents as arbitrary tool output, so
exempting it is #194 one level deeper. **`message.diagnostics` proven safe to list exactly
[mine]:** it has exactly one string leaf in the corpus,
`cache_miss_reason.type` (26 rec, four enum values); `cache_missed_input_tokens` is an int and
never reaches the transform. **`message.content.caller.type` kept as Tier C [mine]:** 342 rec,
sole value `direct`, always on a `tool_use` block — format, and an enum either way.

### 3. The UUID transform-side comes into THIS PR **[C3]**

The frozen plan left `build_identifier_transform` alone. C3 ruled that unsafe: the pipeline
would decide visit-or-not by **path** while the transform still remaps `UUID_FIELDS` by **bare
name at any depth** (`identifiers.py:146`). `test_uuid_fields_match_pipeline_skip_list`
(`test_identifiers.py:478-485`) asserts *name-set* equality — it would **stay green while the
invariant it guards breaks**, and `input.sessionId` under `remap_uuids: true` would remain
synthesized-UUID corruption *by design*. So:

- anchor the UUID transform on the same paths, and
- rewrite that test to the real invariant at the **path** level: every position the transform
  remaps is a position the pipeline visits, and vice versa.

### 4. `gitBranch` is filed, not absorbed **[C4]**

`identifiers.py:140-145` corrupts `input.gitBranch` under **default** options, independent of
the skip mechanism. C4's hard requirement is that it not ship untracked. **Ruling to confirm at
the plan gate:** file it as its own `priority:high` bug with the Probe B repro, and — since
item 3 already opens that exact function — fix it in the same PR rather than leaving a known
default-on corruption beside the lines being edited.

### 5. Drift detection ships with the change **[C5]**

Q2 ruling: drift does **not** argue against the allow-list, because the allow-list fails toward
over-scrub. Minimum to ship: a characterization test over the current corpus (allow-listed
positions pass through; representative user-data positions scrubbed). **`test_golden_determinism.py`
is already half of this [mine]** — I enumerated `golden-session.jsonl` and every string leaf it
currently skips is covered by the list above, so golden should stay byte-identical, and a
*missing* entry turns it red rather than leaking. Fast-follow, own issue: a `format-scan` check
that flags fixture string-leaf paths at format positions the allow-list does not cover.

### 6. Docs

PRD §6b B rewritten to state the allow-list as rooted paths in the two tiers (AC-6); a one-line
note in PRD §13 that the **regex**-config residual remains #198's job **[C5 forward-compat]**;
CHANGELOG. The existing 0.4.0 entry's claim that *"clean output is byte-identical … do not go
looking for a fixture that should have moved"* must be re-checked against the golden result and
corrected if it no longer holds **[mine]**.

### Files to touch

`pipeline.py`, **`rules/identifiers.py` (new — C3/C4)**, `test_pipeline.py`,
`test_residual_rules.py`, `test_identifiers.py`, `test_adversarial_placement.py`,
`.claude/specs/prd-sanitizer.md` §6b B **and §13**, `tooling/sanitizer/CHANGELOG.md`.

---

## Approach as reviewed (frozen before the design gate) — write-once, do not edit

**The fix is an inversion, not another enumeration.** Every rule in `make_skip_predicate`
(`pipeline.py:161-183`) matches **depth-agnostically** — `path[-1]` against a name set, a
`_tokens` suffix, `path[-2] == "usage"`, or a `(parent, last)` pair. Every one of them
therefore fires inside `tool_use.input`, which is arbitrary tool-defined JSON. Adding more
names, or carving out `input`, patches an enumeration over an **unbounded** space (the issue's
own correction says exactly this).

`walk_strings` already builds a **root-anchored path** from the line object
(`pipeline.py:213-230`), so the information needed to close the class is already in hand and is
simply not being used. The change is to match on the **whole path** instead of its tail:

1. **Replace the four depth-agnostic rules with a root-anchored allow-list** whose entries are
   either an **exact path** or a **path prefix** (a subtree). Everything not matched is
   **visited and scrubbed**. This is the fail-closed inversion, and it is what the PRD's own
   C-1 rationale asks for: the auditable question becomes *"which exact positions do we
   deliberately not scrub?"* — a short, reviewable list.
2. **`*_tokens` and `usage.*` collapse into (1) as prefix entries.** Both are already
   near-inert: `walk_strings` only transforms **string** leaves and token counts are integers,
   so these two rules protect `message.usage.service_tier` and little else — while exempting
   every tool parameter ending in `_tokens`. Two prefixes (`message.usage`,
   `toolUseResult.usage`) keep the real protection and drop the rest.
3. **`_ANCHORED_PARENT_LAST_SKIPS` is absorbed too.** Its own comment already reasons this bug
   through correctly ("a bare-name skip would also exempt user content like
   `tool_use.input.id`") and then ships a mechanism that does not achieve it. Root-anchoring is
   what that comment was reaching for.
4. **Keep `remap_uuids` semantics.** With `remap_uuids: false` the four UUID positions are in
   the allow-list; with `true` they are removed from it so the identifier layer visits them.
   Unchanged contract, expressed on paths instead of bare names.
5. **Tests.** Positive cells (each name inside `tool_use.input` → REDACTED, under **both** a
   literal and a `re:` config), negative cells (each name at its real structural position →
   still skipped), nested cells (`input.a.type`), and the `remap_uuids` matrix. The existing
   #194 tests in `test_residual_rules.py:267-300` **flip** from `pytest.raises(ResidualRuleError)`
   to asserting redaction — that is AC-2 landing, and it must be visible as a deliberate flip.
6. **PRD §6b B** rewritten to state the allow-list as rooted paths (AC-6), plus CHANGELOG.

**Files to touch:** `pipeline.py` (constants + `make_skip_predicate`), `test_pipeline.py`,
`test_residual_rules.py`, `test_identifiers.py`, `test_adversarial_placement.py` (add cells),
`.claude/specs/prd-sanitizer.md` §6b B, `CHANGELOG.md`.

### The allow-list, pinned against the fixture survey (not written from memory)

Full key-path survey of `fixtures/` (8 files, 1,494 records, v2.1.150–2.1.185) plus
`reference/data-dictionary.md`, `tool-invocation.md`, `subagent-traces.md`:

| entry | kind | evidence (rec count) |
|---|---|---|
| `version`, `uuid`, `parentUuid`, `sessionId`, `agentId`, `requestId`, `type` | exact, line level | 1069 / 1069 / 1069 / 1494 / 68 / 605 / 1494 |
| `message.role`, `message.type`, `message.model`, `message.id` | exact | 1026 / 614 / 617 / 614 |
| `message.content.type`, `.id`, `.tool_use_id`, `.signature` | exact | 974 / 351 / 352 / 121 |
| `message.content.caller.type` | exact | 341 (value always `direct`) |
| `message.content.content.type` | exact | 25 (`tool_result` inner array) |
| `message.usage.**` | **prefix** | 617 — absorbs 12 `_tokens` paths, `service_tier`, `iterations.type` |
| `message.diagnostics.**` | **prefix** | 26 — absorbs `cache_miss_reason.type` and `cache_missed_input_tokens`, the one `_tokens` field **not** under a `usage` object |
| `toolUseResult.usage.**` | **prefix** | 5 — a **second** `usage` parent the current `parent == "usage"` rule catches only by accident |
| `toolUseResult.agentId`, `toolUseResult.type` | exact | 25 / 79 — documented envelope fields |
| `error.**` | **prefix** | 6 — `type` nests three deep here (`error.error.error.type`) |

**`toolUseResult.task.id` is deliberately NOT in the list.** The survey found it is a TodoWrite
task id — genuine user data. Its parent pair is `("task", "id")`, which is not in
`_ANCHORED_PARENT_LAST_SKIPS`, so it is scrubbed today and must stay scrubbed. Adding it would
be a regression, and it is the concrete proof that `id` cannot be allow-listed by name.

### The hard part, and why this needs the architect

The survey found **`type` at ten distinct format paths, nesting up to four levels**
(`error.error.error.type`), and `*_tokens` at fourteen. So the allow-list is not the three-line
table the issue implies — and its failure mode inverts:

- **today:** an unlisted position → user data is **silently skipped** (leak).
- **after:** an unlisted position → a format marker is **scrubbed** (visible corruption).

The second is the right direction, but it is not free. `.claude/specs/research/jsonl-format-watch.md`
already tracks four line types (`agent-name`, `file-history-delta`, `progress`, `custom-title`)
with **zero fixture coverage**, so the format demonstrably grows positions this list would not
know about. **The allow-list is only as current as the corpus behind it**, and this repo's
corpus is 8 files from one user.

That is the design question I am not deciding alone: whether to accept a maintained position
list (with a drift-detection story), or a different mechanism entirely — e.g. keeping
name-based rules but **disabling them below a rooted uncontrolled-subtree boundary**
(`message.content.input`, `message.content.content`). Note the earlier architect review
rejected the boundary variant partly because "`toolUseResult` is arbitrary MCP output" — the
survey **contradicts** that premise: `toolUseResult.usage.*`, `.agentId` and `.type` are
documented format fields, so that envelope is mixed, not arbitrary.


---

## Architect triggers hit

- **"Any change to the sanitizer's scrubbing behavior"** — rules/pipeline. Fires directly.
- **"Anything that changes the fixture contract"** — output bytes change for affected inputs.
- The design question in (1) is a **mechanism replacement**, not a parameter tweak.
- **The orchestrator is unsure** about AC-8 scope.

`DESIGN_AGENT` is owed. Freeze taken before invoking.

---

## Risks / open questions for human

Resolved by the architect gate, no longer open: the mechanism (Q1, root-anchored allow-list),
the drift hazard (Q2, does not decide against it), the prevalence null (Q4, stays
`priority:high` — latent, not absent), and `toolUseResult` (mixed envelope; the allow-list is
the only mechanism that can preserve `usage.*`/`agentId` while scrubbing `task.id`/`stdout`).

Still open, and these are the plan-gate asks:

1. **Confirm the scope growth** — AC-8 (UUID transform, architect says *this* PR), AC-9
   (`gitBranch`: file it, and my recommendation is to fix it here too), AC-10 (drift test now,
   `format-scan` check as fast-follow). Any of these can be pushed out; AC-9's *filing* is the
   one the architect made a hard requirement.
2. **Two tracker writes need authorization** (this loop does not post to trackers unasked):
   - the derived AC-1..AC-7 list, posted to #194 as an AC amendment — #194 carries no explicit
     AC block, so the gate at step 10 would otherwise certify criteria I wrote myself;
   - the new `gitBranch` bug (AC-9), with the Probe B repro.
3. **Unauthorized tracker write already made — flagging, not hiding.** The `architect` subagent
   posted its full review to #194 as `issuecomment-5379462629` on its own initiative. I asked it
   not to write to the tree; it has `mcp__github__*` and treated the issue as the recording
   surface, which is where this project *does* record architect decisions — but the engine says
   that record is written by **me**, not the agent. The comment is useful and I will not
   double-post. Two things to decide: whether to leave it, and whether the `architect` agent's
   tool grant should be narrowed.
4. **Observation, not scope — an org identifier sits in a committed sanitized fixture.** While
   verifying the architect's C1 I enumerated `error.headers.*` and found
   `anthropic-organization-id: c86124b6-…` and `set-cookie: _cfuvid=…` values inside
   `fixtures/sanitized/`. Both are *currently scrubbable* positions (which is why C1 matters),
   but they were not scrubbed, presumably because no configured rule matches them. Not this
   issue's job. Flagging because CLAUDE.md's security posture makes committed-fixture content a
   standing concern, and a UUID tied to a real Anthropic org is a judgement call I should not
   make alone.
5. **List-index erasure** (`pipeline.py:224-228`) is *not* fixed by this change: a
   user-supplied object named `content` inside `message.content[]` still shares a path with a
   real content block. Root-anchoring shrinks the collision but does not eliminate it. The
   architect confirmed this is correctly scoped out — flagging so it is not read as closed.
