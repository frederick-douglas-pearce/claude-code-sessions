# PRD — Session JSONL Sanitizer (`ccs-sanitize`)

**Status:** v0 implemented and in use (`ccs-sanitize` v0.3.0, the first public release). This PRD remains the canonical design and is kept current; where it differs from the package READMEs, the PRD wins.
**Owner:** Fred Pearce
**Roadmap item:** [W2 — Sanitizer design + v0 implementation](roadmap-v0.md#w2--sanitizer-design--v0-implementation)
**Tracking issue:** [#1 — Epic: Sanitizer design + v0 implementation](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/1)
**Created:** 2026-05-29
**Last updated:** 2026-08-17 (ruling Q9: `sidecar_schema_version` at `0.3.0`; §13 validator note)

> This PRD is deliberately verbose. Per the epic, we are early-stage and want the
> design rationale, the alternatives considered, and the decision history recorded
> alongside the final spec — not just the spec. Sections marked **Decision** record a
> resolved question; sections marked **Alternatives** record what was rejected and why.

---

## 1. Purpose

`ccs-sanitize` is the CLI tool that scrubs raw Claude Code session JSONL files so they
can be committed to this repository (as `fixtures/sanitized/`) or shared publicly by
anyone. It is the **security boundary** of the whole project: without it, every fixture
must be synthetic, which limits which real-world phenomena the blog can illustrate
(a multi-hour real subagent trace, real token-accounting shapes, real tool-error cascades).

The tool has two audiences:

1. **This repo.** Produces the `.scrubbed` sidecar that gates `fixtures/sanitized/`
   (see [CLAUDE.md → Security posture](../../CLAUDE.md) and
   [fixtures conventions](../../CLAUDE.md)).
2. **Standalone users.** Anyone who wants to share a Claude Code session — in a bug
   report, a blog post, a gist — without leaking secrets, file paths, or personal
   identifiers. "Sanitize your Claude Code session before sharing" is a real, unmet need,
   and the tool is designed to stand on its own (see [§12 Packaging](#12-packaging)).

---

## 2. Background: what makes raw session JSONL dangerous

The [data dictionary](../../reference/data-dictionary.md) documents the format in full.
For sanitization purposes, the dangerous surfaces are:

| Surface | Where it lives | Risk |
|---|---|---|
| **Home directory & username** | `cwd`, `toolUseResult.file`/`filePath`, the project slug (`-home-USER-project`), `transcript_path` echoes | Leaks the OS username and directory layout on every line. |
| **Absolute file paths** | `cwd`, tool inputs (`file_path`, `command`), `toolUseResult` path fields, `structuredPatch` | Leaks project structure, internal names, sometimes employer/client identity. |
| **Project slug** | the directory name *and* `cwd` on every line | Encodes home dir + project path together; must be scrubbed consistently with `cwd`. |
| **Identifiers** | git author email, `gitBranch` (often `feature/JIRA-123-...`), prompt text | PII and internal ticket/project names. |
| **Secrets** | Bash `stdout`/`stderr`, file contents via `Read`, env dumps, prompt text | API keys, tokens — the catastrophic case. Patterns in [`.claude/hooks/detect_secrets_in_output.py`](../../.claude/hooks/detect_secrets_in_output.py). |
| **Whole-file backups** | `file-history-snapshot.snapshot.trackedFileBackups` — full pre-edit file contents indexed by absolute path | **Highest-risk field in the format.** Holds entire files (configs, source, possibly `.env` snapshots). v0 **drops these lines wholesale** rather than scrub arbitrary contents — see [§6b](#6b-line-type-stripping-and-traversal-depth) and [D-7](#decision-d-7--v0-drops-high-risk-line-types). |
| **Tool inputs** | `tool_use.input` — Bash `command`, Agent `prompt`, MCP tool inputs (arbitrary schemas) | Commands and prompts carry paths, secrets, and free-text PII. Reached only via structural traversal ([§6b](#6b-line-type-stripping-and-traversal-depth)). |
| **Subagent / free-text prompts** | `toolUseResult.prompt`, `SubagentStart.initial_prompt` | Concentrated free-text PII — the full prompt handed to a subagent. |
| **Free-text prompts & tool output** | `message.content` (string and array shapes), `tool_result.content` | Arbitrary content. May contain names, company info, proprietary code. **Not reliably auto-scrubbable** — see [§4 Non-goals](#4-non-goals). |
| **Attachments** | `attachment` lines; image content blocks | Opaque to regex (binary/base64). v0 **drops `attachment` lines** — see [D-7](#decision-d-7--v0-drops-high-risk-line-types). |
| **Thinking signatures** | `thinking.signature` | High-entropy opaque blob; can false-positive on secret patterns. Replaced with a fixed placeholder (no analytical value in a fixture). |
| **Timestamps** | `timestamp` on most lines | Reveals working hours, session duration, cadence — a fingerprint. Addressed by jitter ([§9](#9-layer-4-jitter-deferred-to-v1-but-designed)), deferred to v1. |
| **UUIDs** | `uuid`, `parentUuid`, `sessionId`, `agentId`, `requestId`, `message.id`, `tool_use.id` | Not inherently sensitive (high-entropy random), but if remapped the conversation graph must stay linked. Remapping is **off by default** ([§8](#8-layer-2-identifiers)). |

Two surfaces are **out of scope by design**: model IDs/versions (`message.model`, `version`)
and token-accounting numbers (`usage.*`) carry no PII and are analytically valuable, so the
sanitizer leaves them untouched (token counts are only perturbed by the deferred jitter layer,
and even then off by default).

---

## 3. Goals

- **Fail-closed.** Any rule error, any malformed line, or any secret surviving to the
  output aborts the run with a non-zero exit and **no output file**. There is never a
  partial scrub.
- **No silent transforms.** The `.scrubbed` sidecar enumerates every category of change so
  a human reviewer can audit what happened — without the sidecar itself becoming a leak.
- **Deterministic.** Same input + same config → byte-identical output. This is what makes
  per-file runs safe (see [§7 consistency](#consistency-determinism-is-the-safety-property))
  and keeps committed fixtures git-stable.
- **Layered.** Independent rule layers (paths → identifiers → secrets → jitter) applied in a
  fixed order, each independently testable.
- **Versioned output.** Every sidecar records `sanitizer_version`; downstream consumers
  (the fixture-validator, sibling projects) can trust or distrust by version.
- **Standalone.** Usable with no dependency on this repo's layout or on AgentFluent/CodeFluent.

---

## 4. Non-goals

These are **explicitly out of scope** and the PRD states them loudly because over-trusting
the sanitizer is the most likely way to leak data.

- **The sanitizer is not a guarantee against all PII in free-text prompts.** It catches
  *structured* leaks — paths, configured identifiers, and secret *patterns*. It cannot catch
  "my name is Jane and I work at AcmeCorp" typed into a prompt. Mitigations: the sidecar
  drives human review, and the repo's standing policy keeps **synthetic the default**
  (per [CLAUDE.md fixtures](../../CLAUDE.md) — use sanitized "only when realistic data shape
  can't be reproduced synthetically").
- **No GUI / interactive review mode** (deferred; see [§14](#14-future-work-v1)).
- **No streaming sanitization of live sessions.** Operates on files at rest.
- **No automatic upload** to any destination. The tool writes local files; publishing is a
  separate, human-initiated step.
- **No reverse-mapping.** The scrub is one-way. The sidecar deliberately cannot reconstruct
  the original (see [§10](#10-the-scrubbed-sidecar)).
- **Jitter is designed but not implemented in v0** (see [§9](#9-layer-4-jitter-deferred-to-v1-but-designed)).

---

## 5. Design principles & the role of the post-scrub residual scan

The single most important safety mechanism is the **residual secret scan**: after all
transform layers have run, the sanitizer re-runs the secret-pattern detector over the
*output*. If anything matches, a secret survived redaction (a bug, or a secret split across
a transform boundary, or an unknown encoding) — the run **aborts and writes nothing**.

This means the design has two distinct secret interactions, and conflating them is a common
mistake:

1. **Detection during scrub** (expected): secret patterns match in the input → redacted →
   counted in the sidecar. A secret match here is normal — it's the tool doing its job.
2. **Residual verification after scrub** (must be clean): the same patterns run over the
   output. A match here is a failure condition, not a normal event.

The residual scan is also why the fixture-validator re-scans independently rather than
trusting the sidecar (see [§13](#13-fixture-validator-integration)) — defense in depth, the
same check enforced at two layers owned by two tools.

**Amendment 2026-08-21 (#195) — the output-side guarantee is extended to LITERAL config rules.**
The scan described above covered only the *secret* layer, and that asymmetry was itself a
defect. Secret patterns are re-run over the serialized output, so a value the structural walk
never reached is still in those bytes and still aborts the run: any traversal gap fails
**closed**. The `paths` and `identifiers` layers ran *inside* the walk with no output-side
pass at all, so the same gap leaked **silently** — exit 0, output written, and a sidecar
affirmatively reporting `residual_scan: clean` on a file that still contained the value. That
is worse than no sidecar, because it converts the human review step this design depends on
into a rubber stamp.

Two instances were found by two different methods — [#190](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/190)
(dict keys are never visited by the walk) and [#194](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/194)
(the skip-list exempted user data at any depth; its bare-name mechanism was fixed in 0.4.0, with a
deliberate residual noted in §6b B) — but enumerating positions
cannot close the class: tool inputs are tool-defined and MCP servers define their own schemas, so the position
space grows without this project's involvement. As of 0.4.0 the configured **literal** `paths`
and `identifiers` rules are re-run over the **decoded** output — every string leaf *and every dict
key* — and a survivor aborts the run.

**What this deliberately does not cover, stated plainly because the sidecar attests to it.**
**Regex** `paths`/`identifiers` rules are covered by the in-walk scrub only and are **not**
re-verified output-side. The restriction is semantic, not a shortcut. The property the scan
asserts is *"presence in the output is a leak, unconditionally"*. That holds for a literal rule,
whose `match` **is** a specific real-world string the operator wants gone. It does not hold for a
regex rule, whose `match` is a *shape* — and shapes legitimately survive scrub. Two demonstrated
cases: a runtime-synthesized value (`remap_uuids: true` mints UUIDs no load-time check has seen),
and a field the pipeline preserves *on purpose* (at the default `remap_uuids: false` the UUID-graph
fields are skip-listed so the parent/subagent graph stays linkable). Scanning regex rules aborted
every such session at exit 2 with nothing mis-scrubbed, and with no override the config could never
scrub any file at all.

So for regex rules, #190 remains open — dict keys are still never visited, and the oracle does not
re-verify a `re:` rule, so a value in a key survives silently — and that is a known, recorded limit
rather than a silent one. (#194's mechanism is closed: its positions are now visited and scrubbed in-walk under
both rule kinds.) Scanning the **decoded** tree rather than the serialized text is the other half of this
amendment and is not cosmetic: rules match decoded leaf values, so a serialized-domain scan was
blind to every value containing a backslash, a quote or a control character — a Windows home
directory (`C:\Users\name`) is the canonical `paths` case and serializes with doubled backslashes,
so it shipped with a clean sidecar.

Two properties of that scan are load-bearing and are recorded here rather than only in the
code:

- **The abort names `section[index]`, never the rule and never the matched span.** A secret
  pattern's `kind` is a generic label, but a path/identifier rule's `match` value *is* the
  literal PII the config exists to scrub — which is why the config file is gitignored
  ([§12b](#12b-config-storage-and-safety)). This gate fires on runs that otherwise look
  successful, i.e. the ones that run in CI and inside Claude Code sessions, so a diagnostic
  carrying the value would write real PII into the very artifact class this tool sanitizes.
- **There is no mechanism that excuses a match, and that is a deliberate negative
  requirement.** The scan asks one question — does a literal rule match anywhere in the decoded
  output? — and any match aborts. It consults no allow-list of the sanitizer's own replacements.

  This is recorded here because the obvious design is the wrong one and it was built and shipped
  once before being caught. The reasoning that justified it was: I-3 forbids a rule from matching
  any *configured* replacement, so transitively no replacement can equal any original, so a match
  whose span is exactly a recorded replacement must be the sanitizer's own output and can be
  excused safely. **That transitive step is false.** I-3 vets the literal `replace` *template*; a
  regex rule's actual replacement is produced at runtime by `match.expand()` and no load-time check
  ever sees it. With `paths: /home/realuser → /home/user` and `identifiers: re:HOME_(\w+) →
  /home/\1`, the input `HOME_realuser` makes the identifier layer mint `/home/realuser`, record it,
  and the allow-set then excused the paths rule whose `match` value that *is* — exit 0, the
  operator's real home directory in the output, `residual_scan: clean`. Layer order is what makes it
  reachable: paths run before identifiers, so the paths rule never sees the value during scrub. It
  exists only in the output, which is precisely what this gate is for. `rules/paths.py` documents
  the same backreference blind spot from the transform side.

  **Do not re-derive an allow-set from the premise that the config guard covers it.** What the
  config guard does cover is enough on its own: I-3 forbids a rule from matching any configured
  replacement, the `gitBranch` placeholder, or any `<REDACTED:kind>` placeholder, so none of those
  can trip this scan without an exemption. What an allow-set uniquely bought was excusing a literal
  `match` value that happens to equal a UUID a run synthesized — contrived, and failing closed on it
  costs availability rather than safety.

  Masking — deleting recorded replacements from the text before matching — was considered and
  rejected earlier for a separate reason worth keeping: a rule `match: abc123` / `replace: abc`
  passes I-3, so stripping every `abc` from a value where `abc123` genuinely leaked leaves `123`,
  the rule stops matching, and the leak ships clean. Both mechanisms fail in the same direction,
  which is the one a security tool cannot afford.

---

## 6. Architecture overview

A line-oriented pipeline. Each JSONL line is parsed, passed through the ordered transform
layers, and re-serialized. The substitution table accumulates across lines so replacements
are **consistent within a file** (the same real home dir maps to the same placeholder on
line 1 and line 5,000).

```
input.jsonl
   │
   ▼  parse line (fail-closed on malformed JSON)
┌─────────────────────────────────────────────┐
│  Layer 1: paths        (deterministic remap) │
│  Layer 2: identifiers  (deterministic remap) │
│  Layer 3: secrets      (redact + count)      │
│  Layer 4: jitter       (DEFERRED to v1)      │
└─────────────────────────────────────────────┘
   │  accumulate substitution table + counts
   ▼  (all lines processed)
residual scans: secrets over the output text, literal rules over the decoded tree (#195)  ──► match? ABORT, no output
   │  clean
   ▼
atomic write: output.jsonl  +  output.jsonl.scrubbed
```

Module layout (matches the [README's planned shape](../../tooling/sanitizer/README.md)):

```
tooling/sanitizer/
├── pyproject.toml                 # uv-managed; entry point `ccs-sanitize`
├── src/ccs_sanitize/
│   ├── __init__.py
│   ├── cli.py                     # arg parsing, exit codes, atomic write
│   ├── pipeline.py                # line loop, layer ordering, residual scan
│   ├── config.py                  # YAML load + validation (paths/identifiers)
│   ├── subtable.py                # consistent substitution table
│   ├── rules/
│   │   ├── paths.py
│   │   ├── identifiers.py
│   │   ├── secrets.py             # vendored pattern library — the security floor
│   │   └── jitter.py              # v1 stub; design documented, not wired in
│   └── sidecar.py                 # redacted sidecar emission
├── tests/
│   ├── unit/
│   └── fixtures/                  # known-bad inputs (synthetic, pattern-matching)
└── README.md
```

---

## 6b. Line-type stripping and traversal depth

Two questions the line loop must answer explicitly. Both were under-specified in the first
draft and surfaced by architectural review (C-1, C-2); leaving them implicit would let two
implementers make incompatible — and unsafe — choices.

### Step A — strip high-risk line types (before any transform)

Some line types carry content that cannot be credibly pattern-scrubbed. **v0 drops them wholesale**
rather than ship a false sense of safety (see [D-7](#decision-d-7--v0-drops-high-risk-line-types)):

- `file-history-snapshot` — `snapshot.trackedFileBackups` holds *entire pre-edit file contents*
  indexed by absolute path. Running path/identifier/secret regexes over arbitrary file bodies is
  not a credible scrub. v0 drops the line.
- `attachment` — image/binary payloads are opaque to regex.

Stripping is governed by `--strip-types` (default: `file-history-snapshot,attachment`). Dropped
lines are counted in the sidecar (`stripped_lines:` block, [§10](#10-the-scrubbed-sidecar)).

**Caveat for downstream analysis:** dropping `file-history-snapshot` means a sanitized fixture
cannot illustrate `/rewind` semantics. When a fixture needs that surface, build it
**synthetically** (the repo's default posture) rather than relaxing the strip list.

### Step B — structural traversal, not stringify-and-regex

Each surviving line is walked **structurally**: the parsed JSON object is traversed recursively
and rules are applied to every **string-valued leaf**, governed by an explicit **skip-list** of
fields left untouched:

- **Skip-list (never scrubbed):** an **allow-list of ROOT-ANCHORED paths**. An entry is an
  exact path from the line object (list indices elided, as `walk_strings` elides them). A path
  not on the list is **visited and scrubbed**.

  **This was a bare-name list and that was the bug (#194).** The names below were documented as
  "content-free identity/identifier fields with no user-data collision risk at any depth", and
  the any-depth part is false: `tool_use.input` is arbitrary tool-defined JSON and MCP servers
  define their own schemas, so a tool parameter named `type`, `version`, `sessionId` or
  `max_tokens` sat at a position the walker refused to visit — the value survived, the run
  exited 0, and the sidecar reported `residual_scan: clean`. Four separate mechanisms had the
  same defect: the bare-name list, the UUID-name list, a `*_tokens` **suffix** rule, and a
  `parent == "usage"` rule. A fifth, `_ANCHORED_PARENT_LAST_SKIPS`, was *described* as anchored
  but matched the immediate parent name at any depth, so `tool_use.input.content.id` collided
  too — the exact case its own code comment warned about.

  **Tiers.** The distinction is which entries are load-bearing. The implementation splits the
  first bullet's two kinds into separate sets (`_UUID_PATHS` / `_PRESERVE_PATHS` and
  `_IDENTIFIER_PATHS`), so four constants back the two ideas below:

  - **Load-bearing preserves** — the value could match a configured rule, so visiting it would
    really change bytes: the UUID-graph paths `uuid` / `parentUuid` / `sessionId` / `agentId` /
    `toolUseResult.agentId` (skipped unless `remap_uuids` is on — §8), and
    `message.content.signature` (thinking.signature; replaced with a fixed placeholder, not
    scrubbed — see [§2](#2-background-what-makes-raw-session-jsonl-dangerous)). Opaque format
    identifiers preserved so the record graph stays linkable: `requestId`, `message.id`,
    `message.content.id` (tool_use.id), `message.content.tool_use_id`.
  - **Enum discriminators** — `type`, `version`, `message.type`, `message.role`,
    `message.model`, `message.content.type`, `message.content.caller.type`, and the `error.*` /
    `usage.*` / `diagnostics` discriminators. A path or identifier rule does not match
    `"assistant"` or `"standard"`, so visiting these is a **no-op today**; they are listed to
    pin intent against a rule that did collide, not because they protect anything on their own.

    **The test for this tier is ownership — who writes the value, the format or a tool — not
    whether the key is named `type` and not how many values it takes.** The cardinality reading
    is wrong and two members of the tier disprove it: `version` (4 distinct values in the
    corpus, a new one every release) and `message.model` (4, a new one every model) are wide
    open and correctly exempt, because the runtime writes them.

    `toolUseResult.type` was removed from the list during review of this change. The data
    dictionary calls it a "tool-specific subtype indicator" on an envelope it documents as
    tool-dependent, so whichever tool produced the result picks the value — the same unbounded
    space #194 is about, one level in. It is now scrubbable like the rest of that envelope's
    tool output. (The corpus corroborates with three tool-varying values, `text` 41 / `create`
    29 / `update` 9 — fewer than either counterexample above, which is precisely why the count
    is not the test.) `toolUseResult.content.type` and `message.content.content.type` are
    excluded too, but on a **related, not identical** argument: their values *are* format-owned
    enums, and what disqualifies them is position — they sit inside a tool_result payload, so
    exempting a key there widens the exempt surface into tool-shaped data. Ownership of the
    value decides `toolUseResult.type`; ownership of the surrounding envelope decides those two.
    All three are pinned as known name collisions in `tests/test_skip_allow_list_corpus.py` so
    the decision is recorded rather than re-litigated.

    `message.content.caller.type` is exempt on the opposite side of the same test, and the
    argument is **structural, not statistical**: `caller` is a sibling of `input` on the
    `tool_use` content block (342/342 corpus occurrences, key set `{type,id,name,input,caller}`,
    every one on a `tool_use` block). A tool controls the *contents of `input`* and nothing else
    on that envelope, so it cannot reach `caller`. The exemption would stand if a second caller
    kind shipped tomorrow.

    **Known weakness of an unmechanized rule.** Ownership is human judgment read off format docs
    that are themselves incomplete — `caller` is not documented in `reference/data-dictionary.md`
    at all, so that exemption's premise currently rests on the structural argument rather than on
    the reference. No mechanical proxy is proposed: pinning each entry's observed value-set would
    fire constantly on `version`/`model` and stay silent on the cases that matter. The mitigation
    is the conservative default the failure direction already makes cheap: **when ownership is
    unclear, leave the position unlisted and let it be scrubbed.**

  **No subtree prefixes.** A "skip everything under X" entry is the `"usage" in path`
  membership test this spec's implementation already deleted once, merely rooted, and it fails
  the same way: `error.*` alone carries `error.headers.set-cookie`,
  `error.headers.anthropic-organization-id` and `error.error.error.message`, all of which are
  scrubbed today and all of which a prefix would exempt. The `usage` subtrees are enumerated
  instead — each holds exactly four string leaves, all closed enums, because token counts are
  integers and never reach the transform at all.

  **The failure direction is now inverted, deliberately.** A format position missing from the
  list gets **over-scrubbed** rather than user data being silently skipped.

  **Be precise about what detects that, because the obvious candidate does not.**
  `test_golden_determinism.py` cannot see a dropped allow-list entry — ablating all 29 one at a
  time leaves the golden output byte-identical, because the golden config holds only literal PII
  rules and no format-marker value contains one. That is the same fact the enum tier rests on.
  The guard is `tests/test_skip_allow_list_corpus.py`, which pins the list contents literally,
  requires every entry to appear in the corpus, ablation-tests each entry against a config whose
  rule matches the value at that position, and pins the set of allow-listed *names* appearing at
  non-allow-listed *paths*. What none of that catches is a genuinely new format position with a
  name nothing on the list uses. **That gap is open, not covered**, and is tracked in
  [#201](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/201) — the
  `format-scan` drift check AC-10 asked for as a fast-follow. Human review is what currently
  happens there; it is not coverage. (This sentence said "the format-watch queue and human review
  cover that" through four review rounds, after the same wording had already been retracted in
  `pipeline.py` and `tests/test_skip_allow_list_corpus.py` — the spec is the authority those
  comments defer to, so it was the worst of the three places to leave it standing.) The list is
  also only as current as the corpus behind it.

  **The allow-list carries a deliberate residual.** Five of its 29 entries sit inside
  `toolUseResult` (`agentId` and the four `usage` leaves), which §6b B argues is a tool-shaped
  envelope — the same argument that took `toolUseResult.type` off the list. A nonconforming tool
  writing user data into one of those five exact keys plants it at a position the walk still
  refuses to visit. It is accepted because scrubbing the runtime's billing rollup and its graph
  link corrupts format-owned fields, and because the residual secret scan still sweeps those
  positions for literal secrets. Recorded here so "#194 is closed" is read as the mechanism being
  closed, not the class.
- **Everything else that is a string leaf is scrubbed**, including the nested surfaces a
  line-level view hides: `message.content[].text`, `tool_use.input.*` (Bash `command`, Agent
  `prompt`, MCP inputs), `tool_result.content` (both string and array shapes),
  `toolUseResult.stdout`/`stderr`/`prompt`/`structuredPatch`, and every path-bearing field.

Rationale (C-1): a structural walk with a skip-list makes the auditable question
*"which fields do we deliberately NOT scrub?"* — a short, reviewable list — instead of
*"did we remember to reach every field that might carry data?"*, which a stringify-and-regex
approach can never prove. Both `message.content` shapes fall out for free, because the walker
keys on string leaves, not on the line's shape. The residual secret scan ([§5](#5-design-principles--the-role-of-the-post-scrub-residual-scan))
still runs over the fully serialized output as the backstop, so a missed leaf is caught before
any file is written.

---

## 7. Layer 1: paths

**What it does.** Replaces the home directory, the project slug, and configured absolute
paths with stable placeholders, consistently across the whole file.

**Why paths run first.** Path normalization is the broadest structural transform. Running it
first means later layers see already-normalized text, and the residual scan at the end is the
backstop for any interaction effects.

**Configuration** (YAML — see [§12 config model](#config-model-hybrid)):

```yaml
paths:
  # ordered; first match wins. literal by default, or `re:` for regex.
  - match: "/home/fdpearce"
    replace: "/home/user"
  - match: "re:-home-fdpearce-([a-z0-9-]+)"   # project slug: scrub home, keep project name
    replace: "-home-user-\\1"
```

**Consistency = determinism is the safety property.** Because replacements are deterministic
(no randomness), sanitizing the *parent* session and a *subagent trace* file in two separate
runs still yields a coherent set: `cwd` in the parent and `cwd` in the subagent both map to
`/home/user/...` identically. This is the reason v0 can safely operate one file at a time.
The moment a *randomized* transform is introduced (jitter, or UUID shuffling with a random
seed), per-file runs would diverge and a **session-bundle mode with a shared seed** becomes
necessary — which is one reason jitter is deferred (see [§9](#9-layer-4-jitter-deferred-to-v1-but-designed)).

---

## 8. Layer 2: identifiers

**What it does.** Replaces configured emails, usernames, and (optionally) `gitBranch` values
with placeholders. Like paths, deterministic and consistent.

```yaml
identifiers:
  - match: "fpearce@gmail.com"
    replace: "user@example.com"
  - match: "re:[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}"   # catch-all email
    replace: "user@example.com"
options:
  scrub_git_branch: true      # gitBranch -> "feature/example" (branch names leak ticket IDs)
  remap_uuids: false          # see below
```

**UUID remapping is off by default.** `uuid`/`parentUuid`/`sessionId`/`agentId` are
high-entropy random values that leak nothing on their own, so the default is to leave them.
When `remap_uuids: true`, the substitution table must remap them **consistently** so the
`parentUuid → uuid` graph, the `sessionId` shared key, and the `agentId` parent↔subagent link
all stay intact — a broken graph makes the fixture useless. Because consistent remapping with
a fixed seed is deterministic, it stays compatible with per-file runs; a *random* seed is what
forces bundle mode (see §7).

---

## 9. Layer 3: secrets

**What it does.** Detects values matching known credential patterns and replaces each with a
**non-reversible** placeholder `<REDACTED:kind>` (e.g. `<REDACTED:anthropic-key>`). Secrets are
**redacted, never remapped** — there is no legitimate value to preserve.

**The pattern library is code-defined, not YAML** (see [Decision D-1](#decision-d-1--rule-configuration-is-hybrid)),
and comes in two tiers in `rules/secrets.py`.

**Tier 1 — vendored from the hook (sync-locked).** Copied verbatim from
[`.claude/hooks/detect_secrets_in_output.py`](../../.claude/hooks/detect_secrets_in_output.py):

```python
VENDORED_PATTERNS = [               # MUST stay identical to the hook's SECRET_PATTERNS
    (r"sk-ant-[A-Za-z0-9_-]{20,}",     "anthropic-key"),
    (r"sk-proj-[A-Za-z0-9_-]{20,}",    "openai-project-key"),
    (r"sk-[A-Za-z0-9]{40,}",           "openai-key-legacy"),
    (r"ghp_[A-Za-z0-9]{30,}",          "github-pat-classic"),
    (r"github_pat_[A-Za-z0-9_]{40,}",  "github-pat-fine"),
    (r"AKIA[A-Z0-9]{16}",              "aws-access-key-id"),
    (r"AIza[A-Za-z0-9_-]{35}",         "gcp-api-key"),
    (r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP |ENCRYPTED )?PRIVATE KEY-----", "pem-private-key"),
]
```

PEM private-key armor was promoted from Tier 2 to Tier 1 (and added to the hook's
`SECRET_PATTERNS`) because `cat ~/.ssh/id_rsa`, `openssl pkcs8` output, and
passphrase-protected `ssh-keygen` output are exactly the live tool-output shapes the
hook exists to block. The `ENCRYPTED ` alternative covers PKCS#8 encrypted keys, which
the original regex missed.

**Tier 2 — batch-only additions (sanitizer floor, C-3).** The hook fires on each *live tool
output*; the sanitizer scrubs a *whole session at rest*, which exposes credential shapes the
hook does not currently catch — bearer tokens, JWTs, DB connection strings with embedded
passwords, and Slack tokens (all plausibly present in Bash `stdout` or a config file's
contents). These are **not** part of the sync-set; whether the hook should also gain them is
tracked separately and requires architect review before promotion:

```python
BATCH_PATTERNS = [                  # sanitizer-only; NOT compared against the hook
    (r"(?i)authorization:\s*bearer\s+[A-Za-z0-9._-]+",               "bearer-token"),
    (r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}", "jwt"),
    (r"(?i)(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|amqps?)://[^:\s/]+:[^@\s]+@", "conn-string-pw"),
    (r"xox[baprs]-[A-Za-z0-9-]{10,}",                                "slack-token"),
]
SECRET_PATTERNS = VENDORED_PATTERNS + BATCH_PATTERNS
```

**The sidecar never records the matched value** — not even truncated, since a prefix still
leaks entropy. Only `{matches: N}` per kind (see [§10](#10-the-scrubbed-sidecar)).

**Config may *add* patterns, never remove built-ins.** The YAML accepts an additive
`extra_secret_patterns` list so a user can extend coverage (e.g. a company-internal token
shape). It cannot disable or weaken a built-in pattern — the floor is fixed in code.

**Drift guard (I-4).** Vendoring duplicates Tier 1 between the hook and the sanitizer. The hook
stores **pre-compiled** `re.Pattern` objects while the sanitizer stores **raw strings**, so a
naive equality check fails. The sync-test (`tests/test_secret_patterns_in_sync.py`) normalizes
by extracting `.pattern` from each compiled hook regex, then compares the resulting
`(pattern_string, label)` tuples element-wise — order included — against `VENDORED_PATTERNS`.
`BATCH_PATTERNS` is explicitly excluded from the comparison. See
[Decision D-6](#decision-d-6--vendor-the-secret-pattern-library).

### 9b. Layer 4: jitter (deferred to v1, but designed)

**Decision D-3: jitter is not implemented in v0.** Rationale: it keeps the security-critical
core small and reviewable, and jitter is the one layer that introduces *randomness*, which
breaks the per-file determinism that makes v0's single-file model safe (see §7). It is the
natural first feature of v1, alongside session-bundle mode.

**The v1 design, recorded now so the seam exists:**

- **Granularity: per-session offset.** A single random offset (e.g. ±N days plus a
  within-day shift) is applied to *all* `timestamp` fields in a session, preserving the
  *relative* timing between lines (so durations, gaps, and cadence-of-thought remain
  analytically intact while the absolute wall-clock — which reveals working hours and dates
  — is destroyed). Per-field or per-message jitter was rejected: it would corrupt relative
  timing, which is exactly the analytically valuable signal, while adding configuration
  surface that is easy to get wrong.
- **Token-count jitter: off by default**, and when on, bounded (±small %) so accounting stays
  roughly faithful. Most sharing scenarios don't need it.
- **Shared seed → bundle mode.** Because jitter is randomized, a parent session and its
  subagent traces must be jittered with the **same seed and same offset** or their timestamps
  desynchronize. v1 therefore introduces a `--session-dir` mode that processes a parent plus
  its `subagents/*.jsonl` with one shared substitution table and one jitter seed.

The `rules/jitter.py` module ships in v0 as a stub with this design in its docstring and a
`jitter: disabled` line in every v0 sidecar, so the format is forward-compatible.

---

## 10. The `.scrubbed` sidecar

**Decision D-2: redacted per-substitution detail; secrets count-only; no original values.**

The sidecar must be auditable (a reviewer can see *what kind* of thing changed and *how often*)
without itself becoming a leak surface. The README's original example embedded full
`original → replacement` mappings — that would store the very home dir and secrets you just
scrubbed, in a file sitting right next to the "safe" output. Rejected.

Final format:

```yaml
sidecar_schema_version: 1                         # shape of THIS document (Q9); independent of the tool version
sanitizer_version: 0.1.0
scrubbed_at: 2026-05-29T18:30:00Z
input_filename: real-subagent-trace.jsonl       # basename only, never the full path
input_sha256: 9f2c...                            # one-way hash of the raw input (traceability)
config_version: 1
config_source: .ccs-sanitize.yaml
lines_processed: 512                              # input items iterated: survivors + stripped + blank/whitespace lines (#43)
stripped_lines:                                   # whole lines dropped (§6b, D-7)
  file-history-snapshot: 8
  attachment: 1
rules_applied:
  paths:       {substitutions: 14, distinct: 3}
  identifiers: {substitutions: 6,  distinct: 2}
  secrets:     {matches: 2}                       # redacted-and-removed; COUNT ONLY
  jitter:      disabled
substitutions:                                    # placeholders + replacement, never originals
  - {rule: paths,       placeholder: "<home-dir>",     replacement: "/home/user",          occurrences: 9}
  - {rule: paths,       placeholder: "<project-slug>", replacement: "-home-user-project",  occurrences: 5}
  - {rule: identifiers, placeholder: "<email>",        replacement: "user@example.com",    occurrences: 6}
residual_scan: clean                              # post-scrub re-scans: secrets + literal rules (#195)
```

Notes:

- `sidecar_schema_version` (added at `0.3.0`, ruling Q9) versions the **shape** of the sidecar
  and nothing else: a field added, removed, renamed, or retyped. `sanitizer_version` continues
  to key the byte-level determinism contract ("same input + same config → byte-identical
  output", which holds only *within* a version). The two are independent: a new sanitizer
  version does not imply a new schema version. Without it, every consumer would have to
  maintain a table mapping sanitizer releases to sidecar shapes. [§9b](#9b-layer-4-jitter-deferred-to-v1-but-designed)
  jitter, which turns the `jitter` scalar into a structured value, is the first expected
  consumer of a bump to `2`. The public statement of both contracts lives in the sanitizer
  README's "Stability and the determinism contract" section, which is the authority for what
  each version bump promises.
- `input_sha256` is a one-way hash of the *raw* input — it aids traceability and dedup and is
  safe (not reversible). It resolves the README's ambiguous "input_hash ... not stored" note:
  the raw input is not stored; its hash is.
- The `substitutions` block shows the *replacement* and a generic `placeholder` category, but
  **never the original**. **Replacements must themselves be non-sensitive (I-3):** the sidecar
  reproduces them verbatim, so a config that maps a path to another real path would leak through
  the sidecar. Config validation rejects a replacement that itself matches any path/identifier/
  secret rule, and the docs steer users to generic targets (`/home/user`, `user@example.com`).
- `stripped_lines` records whole lines dropped by `--strip-types` ([§6b](#6b-line-type-stripping-and-traversal-depth));
  their contents are never inspected or surfaced.
- Secrets contribute only a count. No matched bytes, no kind-level original, nothing reversible.
- `residual_scan: clean` is always present and always `clean` on a written file — if it were
  not clean, the file would not have been written. **Be precise about what it attests to**, since
  this line is the human review gate before publishing and an overclaim here is exactly the
  rubber-stamp failure [§5](#5-design-principles--the-role-of-the-post-scrub-residual-scan)
  describes. As of 0.4.0 (#195) it attests to: the secret patterns (position-agnostic over the
  serialized output) **and the LITERAL `paths`/`identifiers` rules** (decoded output, leaves and
  dict keys).

  It does **not** attest to the four things below. The list is written out because an unstated
  exclusion is how this line starts overclaiming again — and it is **not** a closed set: add to it
  whenever a new limit is found, rather than letting the omission do the claiming.

  - **Regex `paths`/`identifiers` rules**, which are scrub-only — for those, `clean` means the walk
    scrubbed what it reached, not that nothing survived (#198).
  - **Values nested inside a JSON-encoded string leaf.** Both the scrub and the rule scan decode one
    level, so a value carrying its own escaping inside an inner JSON document is missed by both. A
    plain nested value *is* caught; it is the inner escaping that defeats it. A pre-existing limit
    of the transform rather than of the scan, tracked in #198.
  - **A configured value that appears as a JSON number rather than a string.** The structural walk
    transforms string leaves, and the rule scan walks decoded strings, so neither sees a numeric
    leaf: `{"account_id": 1004728391}` survives a rule whose match is `1004728391`. This one is
    worth watching rather than filing away, because [#126](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/126)
    (numeric GitHub user ids) is exactly that shape. Tracked in #198.
  - **A secret whose bytes differ between the serialized and decoded forms.** `scan_residual` reads
    serialized text, so an escapable byte (backslash, quote, control character) inside a match makes
    the serialized and decoded forms diverge. **The built-in floor is not encoding-complete**, and
    the set has not been audited pattern by pattern for this — one confirmed gap is enough to
    retire the claim that it is. `bearer-token` is
    `(?i)authorization:\s*bearer\s+[A-Za-z0-9._-]+`, and `\s` matches a newline or tab, which JSON
    escapes, so a bearer token whose separator is a newline, in a position the walk cannot reach, is
    missed by both layers. Reproduced. Do **not** replace this with a generalization about the
    built-ins being alphanumeric: `conn-string-pw` matches its user and password through negated
    classes (`[^:\s/]+`, `[^@\s]+`) that accept quotes and backslashes, and `pem-private-key` is a
    literal containing spaces and dashes. Those two happen to still match in serialized form, but
    the reason is per-pattern rather than structural. Auditing the set is #198's.

  Before 0.4.0 this field attested to secrets alone, so it could appear on a file that still held a
  configured path or identifier. The planned fixture-validator
  ([§13](#13-fixture-validator-integration)) re-derives rather than trusting this field, and must
  apply the same literal/regex split so the two tools do not diverge on what `clean` means.

---

## 11. CLI shape & fail-closed behavior

```
ccs-sanitize <input.jsonl> -o <output.jsonl> [options]

Options:
  -o, --output PATH       Output JSONL path (required). Sidecar is <output>.scrubbed.
  -c, --config PATH       Rules YAML. Default: ./.ccs-sanitize.yaml or alongside input.
      --dry-run           Scan and print the sidecar to stdout; write nothing.
      --force             Allow overwriting an existing output file (default: refuse).
      --strip-types LIST  Line types dropped wholesale (§6b). Default:
                          file-history-snapshot,attachment.
  -v, --verbose           Per-rule progress to stderr.
      --version           Print sanitizer version.
```

**Exit codes (fail-closed):**

| Code | Meaning | Output written? |
|---|---|---|
| 0 | Success | yes (+ sidecar) |
| 1 | Usage error (bad args, missing input, output exists without `--force`) | no |
| 2 | **Safety failure** — rule raised, line failed to parse, or either output-side scan found a survivor (a secret, or — as of 0.4.0, #195 — a **literal** `paths`/`identifiers` value) | **no** |
| 3 | Config error (YAML invalid, regex won't compile, attempt to disable a built-in pattern) | no |

**Atomicity & rename order (I-5).** Output and sidecar are written to temp files in the
destination directory and renamed into place only after the full file is processed *and* the
residual scan passes. The **sidecar is renamed first, then the output** — so a crash in the
gap can leave an orphan sidecar (harmless, and overwritten on re-run) but can never leave a
scrubbed output with no sidecar, which would otherwise pass a sidecar-existence check while
being unaccounted for. A failed or interrupted run never leaves a partial scrub.

**Serialization is pinned for determinism (I-1).** Output lines are re-emitted with
`json.dumps(obj, ensure_ascii=False, separators=(",", ":"))` and **original key order preserved**
(Python's `json.loads` keeps insertion order, so a straight round-trip is
order-stable; keys are *not* sorted). Pinning these parameters is what turns "deterministic
output" from a claim into a property — without it, two environments could emit byte-different
but semantically equal output and break the determinism and idempotency tests.

**Malformed JSONL aborts (no skip flag in v0).** A session file should be well-formed; a parse
error means something is wrong, so the safe action is to stop. No `--skip-malformed` escape
hatch ships in v0 — adding a way to silently drop lines is a footgun on a security tool.

**The CLI is the sanctioned reader of raw sessions.** The [`block_secret_reads.py`](../../.claude/hooks/block_secret_reads.py)
hook blocks `Read`/`Edit`/`Grep`/`Glob` on `~/.claude/projects/*.jsonl` but deliberately
**not Bash** — so `ccs-sanitize ~/.claude/projects/.../sess.jsonl -o fixtures/sanitized/...`,
invoked via Bash, is the intended path for turning a raw session into a committable fixture.

---

## 12. Packaging & configuration

### Packaging — in-repo only for v0

**Decision D-5: in-repo only for v0; not published to PyPI.** Per the roadmap. A `pyproject.toml`
with a `ccs-sanitize` entry point lives at `tooling/sanitizer/`, uv-managed. Dependencies are
kept minimal: stdlib for the pipeline and secret patterns (mirroring the hooks' stdlib-only
constraint), plus PyYAML for config parsing. Target Python 3.11+. Extraction to a standalone
PyPI package (`claude-code-sessions-sanitizer`) is deferred until a standalone audience
materializes — the module layout is kept import-clean so extraction is mechanical later.

### Amendment 2026-08-16 — D-5 reversed: the sanitizer publishes to PyPI {#d-5-amendment}

**Decision D-5a (2026-08-16), superseding D-5: `claude-code-sessions-sanitizer` publishes to
PyPI, first public version `0.3.0`.** D-5 above is left intact as the record of what was
decided on 2026-05-29 and why. This amendment supersedes it; it does not rewrite it.

Scoping doc: [`plan-sanitizer-pypi.md`](plan-sanitizer-pypi.md). Tracking issue:
[#158](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/158), under the
`epic:sanitizer-pypi` label.

**Trigger.** D-5 deferred publication "until a standalone audience materializes." It has. The
audience of record is **CCDC contributors** ([#75](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/75)),
the public sanitized-session corpus effort. External contributors to a public corpus need a
`pip install`-able scrubber. Telling them to clone this monorepo and run an in-tree tool is a
higher barrier and a worse security story, because people improvise their own scrubbing when
the sanctioned tool is inconvenient. That is the whole justification; no other motivation is
part of the written record.

**Rulings recorded with this amendment.** Downstream issues consume these as written decisions
rather than as conversation:

| # | Question | Ruling |
|---|---|---|
| Q1 | Which standalone audience triggers the reversal? | CCDC contributors ([#75](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/75)). |
| Q2 | First public version: `0.3.0` or `1.0.0`? | **`0.3.0`.** The package is `Development Status :: 3 - Alpha`, the CLI surface may still move, and `1.0.0` would over-promise against a determinism contract that only holds *within* a version. |
| Q3 | Distribution name? | Keep **`claude-code-sessions-sanitizer`** (descriptive, namespaced, searchable); the console script stays `ccs-sanitize`. ~~Reserve `ccs-sanitize` on PyPI defensively, as an inert placeholder that installs no console script.~~ _The reservation half was **reversed 2026-08-19** by [D-9](#decision-d-9--ccs-sanitize-is-deliberately-not-reserved-on-pypi) ([#166](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/166)): an empty placeholder is PEP 541-reclaimable. The distribution name itself stands._ |
| Q5 | Force the vendored secret-pattern dedup before publishing? | **Defer.** Only the sanitizer's copy ships; `test_secret_patterns_in_sync.py` keeps it element-wise identical to the hook copy, so the artifact cannot silently drift below the hook's floor. [§17](#17-future-work-v1) stands as future work, not a publish blocker. |
| Q7 | Upload credential? | **PyPI Trusted Publishing (OIDC).** No long-lived API token at rest. A leaked token would let an attacker publish a poisoned sanitizer, and every user of that release is by definition handling raw session data. |
| Q9 | Should the sidecar carry a `sidecar_schema_version` independent of `sanitizer_version`? | **Yes. `sidecar_schema_version: 1` ships at `0.3.0`** (ruled 2026-08-17, [#160](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/160)). The asymmetry decides it: added now, every public-era sidecar carries it; added at `0.4.0`, consumers handle its absence forever. It versions the sidecar *shape* only; `sanitizer_version` still keys byte-level determinism. See [§10](#10-the-scrubbed-sidecar). |

**Supported public surface at `0.3.0`.** The **CLI** and the **`.scrubbed` sidecar format**
([§10](#10-the-scrubbed-sidecar)) are the supported contract. The module surface
(`orchestrator`, `pipeline`, `rules`, and everything else under `ccs_sanitize`) is **private
and may move without a MAJOR bump.** Stating this is cheap now and expensive to retrofit:
silence invites strangers to import internals that then become costly to change. The
fork-and-customize path is served by YAML config and additive `extra_secret_patterns`, which
is data rather than code, so no consumer needs to import the pipeline in-process. If someone
asks for a documented library API, that is a new decision.

**What this amendment does not change.** D-1 (hybrid config), D-6 (vendored patterns), D-7
(strip high-risk line types), and the [§4](#4-non-goals) non-goals all stand. Publishing is a
distribution change, not a design change. What it does change is who bears the cost of a
defect: a stranger who trusted the word "sanitizer," not the author who already knows the
limitations. The consequences of that (shipped LICENSE, PyPI-safe README, a loud statement of
the [§4](#4-non-goals) free-text gap, SECURITY.md and a disclosure path, tests green on the
published ref, a public determinism contract) are scoped in
[`plan-sanitizer-pypi.md` §5](plan-sanitizer-pypi.md), not here.

### Config model — hybrid {#config-model-hybrid}

**Decision D-1: hybrid.** Secret patterns are **code-defined** (the non-weakenable security
floor); path and identifier rules are **YAML-configured per project** (`.ccs-sanitize.yaml`).
YAML may *add* secret patterns (`extra_secret_patterns`) but never remove built-ins.

Rationale: a security tool whose secret detection can be silently weakened by editing a config
file is a tool that will eventually be weakened by a careless edit. Keeping the floor in code
means the worst a bad config can do is over-scrub (safe) or fail to add a project-specific
path rule (visible in the sidecar counts), never under-detect a secret.

Full config schema:

```yaml
version: 1
paths:        [ {match: "...", replace: "..."}, ... ]   # ordered, first-match-wins
identifiers:  [ {match: "...", replace: "..."}, ... ]
options:
  scrub_git_branch: true
  remap_uuids: false
extra_secret_patterns:                                   # ADDITIVE only
  - {pattern: "re:CORP-[A-Z0-9]{32}", kind: "corp-token"}
```

### 12b. Config storage and safety {#12b-config-storage-and-safety}

The config file holds the literal strings the sanitizer is meant to scrub (real home dir,
real email, real name, etc.). The sidecar records only the **basename** of the config
under `config_source:` ([§10](#10-the-scrubbed-sidecar)) so committed sidecars do not
depend on the config file being safe to commit — but the config file itself is the
leak surface and is treated as sensitive across the rest of the threat model below.

**Threat model.** Two distinct leak paths:

1. **Primary — `git add .` commits the live config.** A naïve user follows the README,
   creates `.ccs-sanitize.yaml` at the repo root next to the input, and runs `git add .`.
   The config now lives in git history with every `match:` value verbatim. This is the
   dominant failure mode and the one a CLI tool can address mechanically.
2. **Secondary — Read of the config surfaces PII into the Claude Code session transcript.**
   Any tool that returns file contents (`Read`, `Edit` on the config) brings literal
   match values into the conversation, which can land in transcripts and JSONL session
   files. This is addressed by a hook in `.claude/hooks/` (see [#47](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/47)).

**Defense layers — required.**

- **Convention: gitignore the live config; commit a schema-only template.**
  `.ccs-sanitize.yaml` is gitignored; `.ccs-sanitize.example.yaml` is committed and
  contains placeholders only. Mirrors the `.env` / `.env.example` pattern. New users
  bootstrap with `ccs-sanitize --init`, which copies the template into place.
- **Built-in pre-run gitignore guard (default-on; opt out with `--no-check`).**
  Before `load_config` runs, the sanitizer asks `git check-ignore -v <config>`
  whether the resolved config path is gitignored. If not: refuse to operate, exit
  code 3, actionable error naming the file and pointing at `.ccs-sanitize.example.yaml`.
  The check runs on every invocation so a user who ignored the `--init` reminder
  still hits a clear error before the scrub starts. If `git` is unavailable or the
  cwd is not a git repository, the check warns to stderr and proceeds —
  defense-in-depth, not the only defense. `--no-check` is a deliberate override of
  the guard, not the remedy for exit 3 (gitignoring the config is), and the test
  suite is its main legitimate user; a repo-less environment does not need it,
  because that case already takes the warn-and-proceed path
  ([#164](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/164)).

**Defense layers — additional.**

- **Hook-level read-block ([#47](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/47)).** `.claude/hooks/block_secret_reads.py` denies
  `Read`/`Edit`/`NotebookEdit`/`Grep`/`Glob`/`Bash` targeting `.ccs-sanitize.yaml` so the
  config cannot be surfaced into the session transcript even by Claude Code itself.
  Asymmetric — `Write` is allowed so the user can still let Claude Code construct the
  file via `--init` or rewrite-from-scratch — mirrors the existing raw-session JSONL
  pattern. The pattern is anchored to the live basename, so the committed
  `.ccs-sanitize.example.yaml` schema reference stays readable. This layer is additional:
  the convention + `--check` already close the primary threat; the hook backs up
  the secondary threat without being the only defense.

**`--init` behavior.** `ccs-sanitize --init` writes `.ccs-sanitize.example.yaml` (if
missing) and `.ccs-sanitize.yaml` (if missing, populated from the template) in the
current working directory. It does **not** mutate `.gitignore` — modifying a tracked
file on first run is surprising behavior and risks merge conflicts. It prints a
one-line reminder that `.ccs-sanitize.yaml` should be gitignored before committing.
The pre-run gitignore guard above enforces it mechanically on every subsequent
scrub, so a user who skips the reminder is caught. `--init` refuses to combine with
any scrub-only argument (`<input>`, `-o`, `-c`, `--dry-run`, `--force`, `--no-check`)
so a user who runs `ccs-sanitize --init input.jsonl -o out.jsonl` expecting both
init AND a scrub gets a clear usage error rather than a silent partial run.

**Sidecar safety claim.** `config_source` is basename-only by design ([§10](#10-the-scrubbed-sidecar)). A committed `.scrubbed` sidecar carries no path
information that could leak the config's location or contents, regardless of whether
the local config is gitignored. The basename-only choice means the safety of the
**committed sidecar** does not depend on the safety of the **uncommitted config**.

---

## 13. Fixture-validator integration

**Decision D-4: the validator re-scans independently and never trusts the sidecar.**

When [`tooling/fixture-validator/`](../../tooling/fixture-validator/README.md) checks a file
in `fixtures/sanitized/`, it:

1. Confirms a `.scrubbed` sidecar exists and its `sanitizer_version` is recognized.
   **"Recognized" must mean a maintained allowlist of historical versions, not "the current
   one."** A sanitized artifact stays pinned to the version that produced it, determinism only
   holds within a version, and re-scrubbing after a MAJOR bump is a deliberate manual act.
   Publishing to PyPI ([D-5a](#d-5-amendment)) accelerates release churn, so a validator that
   accepts only the newest version would start rejecting valid archived fixtures almost
   immediately. The validator should also read `sidecar_schema_version` to pick the shape it
   validates against, rather than inferring the shape from `sanitizer_version`.
2. **Independently re-runs the secret-pattern scan** over the fixture contents.
3. Optionally verifies `input_sha256` shape and required sidecar keys.

**`residual_scan: clean` does not yet mean "no configured value survived."** The output-side
oracle (#195) re-verifies **literal** `paths`/`identifiers` rules only; a `re:` rule is
deliberately not re-verified, so for a regex config the field attests to the secret scan and to
the literal rules, and to nothing about the regex ones (#198). #194 narrowed what that gap can
reach — the traversal positions it used to leak through are now visited and scrubbed — but it
did not close it, and the validator should not read the field as a full guarantee until #198
lands.

The validator does *not* trust the sidecar's `residual_scan: clean` as proof — it re-derives
it. This is defense in depth: a stale sidecar (output edited after scrub), a forged sidecar, or
a sanitizer bug all get caught at the validator layer. The cost is a cheap second regex pass;
the benefit is that fixture safety does not depend on the sanitizer having been bug-free at
scrub time. The "hybrid / trust counts" option was rejected — re-scanning is cheap enough that
there's no reason to trust *any* part of the security claim.

---

## 14. Testing strategy

Known-bad inputs live in `tests/fixtures/`. **They are synthetic and contain pattern-matching-but-fake secrets**
(e.g. `sk-ant-` followed by 25 `A`s) — never a real key.
This is itself a security requirement: the test suite must not be the thing that commits a
real credential.

Coverage:

- **Per-surface scrub tests** — a fixture line carrying each: home dir, project slug, absolute
  path, email, git branch with a ticket ID, and each Tier-1 and Tier-2 secret pattern. Assert
  the output contains none of the original tokens and the sidecar counts are correct.
- **Structural-traversal test (C-1)** — secrets/paths planted in *nested* leaves the line-level
  view hides (`tool_use.input.command`, `toolUseResult.stdout`, `tool_result.content` array
  shape, `message.content[].text`); assert all are scrubbed and skip-list fields
  (`message.model`, `usage.*`, `thinking.signature`) are untouched.
- **Strip-types test (C-2/D-7)** — input with `file-history-snapshot` and `attachment` lines;
  assert they are dropped, counted in `stripped_lines`, and no `trackedFileBackups` content
  survives anywhere in the output.
- **Residual-scan / fail-closed test** — craft an input where naive redaction could be bypassed
  (a secret split across a transform boundary); assert the residual scan catches it, the run
  exits 2, and no output file exists.
- **No-partial-scrub test** — induce a rule error mid-file; assert no output and no sidecar.
- **Determinism test** — same input + config → byte-identical output across two runs (pins the
  serialization parameters from [§11](#11-cli-shape--fail-closed-behavior)).
- **Idempotency test** — sanitizing an already-sanitized file is a no-op (0 substitutions,
  `residual_scan: clean`).
- **Sidecar-never-leaks test** — assert no original sensitive token (home dir, email, secret)
  *and no configured replacement that is itself sensitive* appears anywhere in the sidecar (I-3).
- **Pattern-sync test** (repo-level) — normalize the hook's compiled `SECRET_PATTERNS` via
  `.pattern` and assert element-wise equality with `VENDORED_PATTERNS` (drift guard from §9);
  `BATCH_PATTERNS` excluded.

---

## 15. Open questions — resolutions

Every open question from [`tooling/sanitizer/README.md`](../../tooling/sanitizer/README.md)
and the [epic](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/1),
with its resolution. All resolved 2026-05-29.

| # | Source | Question | Resolution | Decision |
|---|---|---|---|---|
| 1 | README | YAML-configured vs code-defined rules | **Hybrid** — secrets in code (additive-only YAML extension), paths/identifiers in YAML | [D-1](#decision-d-1--rule-configuration-is-hybrid) |
| 2 | README | Sidecar: substitution dictionaries vs counts | **Redacted per-substitution detail**; secrets count-only; no original values | [D-2](#decision-d-2--redacted-sidecar) |
| 3 | README | Jitter granularity (field/message/session) | **Deferred to v1**; designed as per-session offset | [D-3](#9b-layer-4-jitter-deferred-to-v1-but-designed) |
| 4 | README | Validator: re-scan vs trust sidecar | **Independent re-scan**, never trust the sidecar | [D-4](#13-fixture-validator-integration) |
| 5 | Roadmap | PyPI package vs in-repo | **In-repo only for v0** — _superseded 2026-08-16 by [D-5a](#d-5-amendment): publishes to PyPI at `0.3.0`_ | [D-5](#packaging--in-repo-only-for-v0), [D-5a](#d-5-amendment) |
| 6 | Roadmap | Secret-pattern library: copy vs dependency | **Vendor (copy)** into the sanitizer; sync-test guards drift. _Publishing does not force collapsing it ([D-8](#decision-d-8--the-vendored-tier-1-duplication-does-not-block-the-publish), 2026-08-19)._ | [D-6](#decision-d-6--vendor-the-secret-pattern-library), [D-8](#decision-d-8--the-vendored-tier-1-duplication-does-not-block-the-publish) |
| 7 | Review | High-risk line types (`file-history-snapshot`, `attachment`) | **Dropped wholesale in v0** via `--strip-types`; synthetic fixtures cover those surfaces | [D-7](#decision-d-7--v0-drops-high-risk-line-types) |

### Decision D-1 — rule configuration is hybrid
Secrets code-defined (non-weakenable floor, additive YAML extension allowed); paths/identifiers
in YAML. A config-weakenable security floor will eventually be weakened by accident; keeping it
in code means a bad config can only over-scrub or miss a path rule, never under-detect a secret.

### Decision D-2 — redacted sidecar
Per-substitution detail using category placeholders and the (non-sensitive) replacement value;
secrets contribute a count only; no original values anywhere. Keeps the sidecar auditable
without making it a second copy of the data we just scrubbed.

### Decision D-6 — vendor the secret-pattern library
This repo is **upstream** of AgentFluent (per [CLAUDE.md](../../CLAUDE.md) and the data
dictionary). Taking a runtime dependency on AgentFluent would invert that relationship. The
pattern set is therefore copied into `rules/secrets.py`, which becomes a candidate canonical
home; a future task can have the hook and/or AgentFluent consume from here. A repo-level
sync-test prevents the vendored Tier-1 copy and the hook's copy from drifting in the meantime.

### Decision D-7 — v0 drops high-risk line types
`file-history-snapshot` (full file contents in `trackedFileBackups`) and `attachment` (opaque
binary/image payloads) cannot be credibly scrubbed with pattern rules. v0 drops them wholesale
(`--strip-types`, counted in the sidecar) rather than ship a false sense of safety. Surfaces
that need those line types in a fixture are built synthetically. Content-level scrubbing is
future work ([§17](#17-future-work-v1)). Surfaced by architect review (C-2), 2026-05-29.

### Decision D-8 — the vendored Tier-1 duplication does not block the publish

Recorded 2026-08-19 ([#165](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/165)). Publishing to PyPI does **not** force collapsing the Tier-1
duplication between `rules/secrets.py` and the hook. Three reasons, in descending order of
weight:

1. **Only one copy ships.** The wheel packages `src/ccs_sanitize` only, and the sdist's
   `include` allowlist does not carry `.claude/`. A published artifact therefore contains
   exactly one pattern set. There is no installable state in which a user holds two divergent
   copies.
2. **The two in-repo copies are held identical by test.** `test_secret_patterns_in_sync.py`
   compares them element-wise, order included ([§9](#9-layer-3-secrets), I-4), so the
   published artifact cannot drift below the hook's detection floor without turning that test
   red in this repo first.
3. **The cost is maintenance, not correctness.** The duplication is a burden this repo
   carries. It is not a risk its users carry. Only the second kind blocks a release.

**Precondition, stated so it can be checked.** This deferral holds only while the sync test
actually runs in CI. When #165 was filed that was aspirational, since no Python CI existed yet.
It is now satisfied twice over: [#162](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/162) put the suite on a 3.11/3.12/3.13 matrix, and [#185](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/185) added a
step asserting the drift guard *ran* rather than merely that the suite was green, because a
skipped test still reports green.

That second step carries more weight than it looks. [#182](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/182) established that the sync test skips
itself when it detects an unpacked sdist, where `.claude/hooks/` does not exist. The skip is
keyed to a `PKG-INFO` marker rather than to the hook's absence, precisely so a missing hook
*inside a checkout* fails loudly instead of silently disabling this decision's precondition.

If the sync test is dropped from the matrix, or its skip condition ever widens far enough to
fire inside a checkout, **D-8 is void** and the duplication must be revisited before the next
release.

The [§17](#17-future-work-v1) "shared secret-pattern source" cleanup remains future work, neither blocked by nor
blocking the publish. Tier 2 pattern evaluation ([#32](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/32)) touches the same library and should read
this before reopening the question.

### Decision D-9 — `ccs-sanitize` is deliberately not reserved on PyPI

Recorded 2026-08-19 ([#166](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/166)). The published distribution is
`claude-code-sessions-sanitizer` ([D-5a](#d-5-amendment), ruling Q3) while the console script
users actually type is `ccs-sanitize`. The Q3 ruling and
[`plan-sanitizer-pypi.md`](plan-sanitizer-pypi.md) §4.7 both recommended reserving the short
name as an inert placeholder, on the reasoning that claiming an unused name is cheap now and
impossible later. **That half of the ruling is reversed.** The reasoning runs backwards for an
empty project.

[PEP 541](https://peps.python.org/pep-0541/) lists among its *invalid project* criteria,
verbatim, "project is name squatting (package has no functionality or is empty)". It offers no
exemption for a placeholder whose owner publishes a related real project, and none for an
honest description. An inert stub is therefore reclaimable by the same mechanism it was meant
to defend against: cheap to claim and revocable to hold, which is the opposite of the premise
it rested on.

Two further reasons, either sufficient alone:

1. **A single name is false completeness.** PEP 503 normalization means one reservation covers
   `ccs_sanitize` and `ccs.sanitize`, a real but narrow win. The semantic neighbours
   (`ccs-sanitizer`, `claude-code-sanitizer`, `claude-sanitize`) are unbounded. PyPI's own
   confusable-name guard keys on string similarity to existing projects, and the short name is
   not string-similar to the long one, so it would not fire in either direction.
2. **The blocker is not the credential.** Worth recording because it was the first objection
   raised and it is wrong. PyPI's *pending* trusted-publisher flow is per project name, so a
   second project could be created tokenlessly exactly as the first one was, leaving repo
   secrets empty. The real cost is machinery: a third GitHub environment (the `sanitizer-v*`
   deployment-tag rule is per-environment), a second publisher registration, and a duplicated
   or parameterized release workflow, all maintained for a package that does nothing.

**Alternatives considered.**

- *Inert placeholder stub* — **rejected.** Non-durable under PEP 541, and pays the setup cost
  without buying the protection.
- *Functional dependency-only alias* — a real `ccs-sanitize` distribution declaring no console
  script of its own, depending on `claude-code-sessions-sanitizer`. This avoids both traps: it
  has functionality, so it is not squatting, and only the real package declares the entry
  point, so two distributions never compete for one script name and shadow each other by
  install order. **Deferred, not rejected.** It carries the same setup cost, so it is held as
  the escalation play if a squatter appears or if CCDC adoption raises the stakes.
- *Documentation plus monitoring* — **chosen.** The sanitizer README states that no
  `ccs-sanitize` distribution exists and that anything found under that name is not this tool.
  That lets a user detect a substitution, rather than relying on the name staying unavailable.

**Threat model, stated plainly, because the blast radius is what makes this worth a decision
rather than a shrug.** A lookalike sanitizer that under-scrubs leaks the victim's secrets while
they believe they are protected. The risk is real. It is also low-frequency: every discovery
path (this repo, the sanitizer README, the post series, the CCDC docs) names the real install
target, so reaching the short name requires conflating a console script with a distribution
name. If that assumption stops holding, escalate to the alias above rather than to a stub.

---

## 16. Phasing & acceptance criteria

**Phase 1 (this document):** PRD accepted. Done when every open question in §15 is resolved
and the design is signed off.

**Phase 2 (implementation):** acceptance criteria from the [epic](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/1):

- [ ] CLI usable as `ccs-sanitize <input.jsonl> -o <output.jsonl>`
- [ ] Strip-types step drops `file-history-snapshot`/`attachment` (§6b); structural traversal
      with skip-list reaches nested leaves (§6b)
- [ ] Layered rules: paths → identifiers → secrets (jitter stub present, disabled)
- [ ] `.scrubbed` sidecar in the redacted format of §10
- [ ] Fails closed: any rule error or residual secret aborts; no partial scrubs
- [ ] Test suite covers the known-bad inputs of §14
- [ ] At least one real session sanitized and committed to `fixtures/sanitized/` with sidecar

---

## 17. Future work (v1+)

- **Jitter** (per-session offset) + **session-bundle mode** (`--session-dir`, shared seed) —
  the two are coupled (§9b).
- ~~**PyPI extraction** as `claude-code-sessions-sanitizer` if a standalone audience appears.~~
  **Active as of 2026-08-16** — the audience appeared (CCDC, [#75](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/75)).
  See [D-5a](#d-5-amendment) and [`plan-sanitizer-pypi.md`](plan-sanitizer-pypi.md).
- **Interactive review mode** — surface free-text prompts/outputs for human confirmation,
  addressing the §4 free-text limitation.
- **Content-level handling of `file-history-snapshot`** — scrub `trackedFileBackups` file
  bodies (path-aware, per-file-type) instead of dropping the line wholesale (D-7), so sanitized
  fixtures can illustrate `/rewind` semantics.
- **Shared secret-pattern source** — collapse the vendored Tier-1 duplication (§9) once the
  canonical home is decided. Still future work, and explicitly **not** forced by the PyPI
  publish ([D-8](#decision-d-8--the-vendored-tier-1-duplication-does-not-block-the-publish)): only `rules/secrets.py` ships, and the sync test holds the two
  in-repo copies identical.

---

## 18. Decision history

| Date | Change |
|---|---|
| 2026-08-19 | **D-9** recorded ([#166](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/166)): `ccs-sanitize` is deliberately **not** reserved on PyPI, reversing the reservation half of ruling Q3. An inert placeholder meets PEP 541's name-squatting criterion and is reclaimable, one name is false completeness against an unbounded neighbour space, and the credential objection was unfounded (the pending-publisher flow is per project name). A functional dependency-only alias is held as the escalation. |
| 2026-08-19 | **D-8** recorded ([#165](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/165)): the vendored Tier-1 duplication ([§9](#9-layer-3-secrets), [D-6](#decision-d-6--vendor-the-secret-pattern-library)) does not block the PyPI publish, because only `rules/secrets.py` ships and the sync test holds the in-repo copies identical. The deferral's precondition is now met: the suite runs on a 3.11/3.12/3.13 matrix ([#162](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/162)) and CI asserts the drift guard ran rather than skipped ([#185](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/185)). `0.3.0` published to PyPI the same day ([#163](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/163)), via Trusted Publishing with no API token in the chain. |
| 2026-05-29 | PRD created. D-1 through D-6 decided (§15). Jitter deferred to v1. |
| 2026-08-17 | Ruling **Q9** recorded ([#160](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/160)): the sidecar carries `sidecar_schema_version: 1` from `0.3.0`, versioning the sidecar shape independently of the tool version ([§10](#10-the-scrubbed-sidecar)). `0.3.0` cut as the first public release, with the determinism contract and the version-lifecycle / disclosure policy published in the sanitizer README and `SECURITY.md` respectively ([#161](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/161)). Release tags are component-scoped: `sanitizer-v<version>`. |
| 2026-08-16 | **D-5 reversed** by [D-5a](#d-5-amendment) ([#158](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/158)): the sanitizer publishes to PyPI at `0.3.0`, triggered by the CCDC contributor audience ([#75](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/75)). Rulings Q1/Q2/Q3/Q5/Q7 recorded; supported public surface declared as CLI + sidecar format, modules private. Scoping doc: [`plan-sanitizer-pypi.md`](plan-sanitizer-pypi.md). |
| 2026-05-29 | Architect review incorporated ([issue #1 comment](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/1)): structural-traversal + strip-types spec (§6b, C-1/C-2), D-7 added, secret floor expanded to two tiers (§9, C-3), serialization pinned + rename order (§11, I-1/I-5), replacement-leak guard (§10, I-3), sync-test comparison shape (§9, I-4). |
