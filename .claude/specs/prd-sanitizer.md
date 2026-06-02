# PRD — Session JSONL Sanitizer (`ccs-sanitize`)

**Status:** Design (Phase 1 of W2). Implementation has not started.
**Owner:** Fred Pearce
**Roadmap item:** [W2 — Sanitizer design + v0 implementation](roadmap-v0.md#w2--sanitizer-design--v0-implementation)
**Tracking issue:** [#1 — Epic: Sanitizer design + v0 implementation](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/1)
**Created:** 2026-05-29
**Last updated:** 2026-05-29

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
trusting the sidecar (see [§11](#11-fixture-validator-integration)) — defense in depth, the
same check enforced at two layers owned by two tools.

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
residual secret scan over full output  ──► match? ABORT, no output
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

- **Skip-list (never scrubbed):** `message.model`, `version`, `type`, `*.role`, the numeric
  `usage.*` / `*_tokens` fields, `message.id` / `requestId` / `tool_use.id` / `tool_use_id` and
  the UUID fields (unless `remap_uuids` is on), and `thinking.signature` (replaced with a fixed
  placeholder, not scrubbed — see [§2](#2-background-what-makes-raw-session-jsonl-dangerous)).
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
sanitizer_version: 0.1.0
scrubbed_at: 2026-05-29T18:30:00Z
input_filename: real-subagent-trace.jsonl       # basename only, never the full path
input_sha256: 9f2c...                            # one-way hash of the raw input (traceability)
config_version: 1
config_source: .ccs-sanitize.yaml
lines_processed: 512
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
residual_scan: clean                              # post-scrub secret re-scan result
```

Notes:

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
  not clean, the file would not have been written.

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
| 2 | **Safety failure** — rule raised, line failed to parse, or residual scan found a secret | **no** |
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
  still hits a clear error before the scrub starts. `--no-check` opts out for CI
  environments without a `.git` directory and for the test suite. If `git` is
  unavailable or the cwd is not a git repository, the check warns to stderr and
  proceeds — defense-in-depth, not the only defense.

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
2. **Independently re-runs the secret-pattern scan** over the fixture contents.
3. Optionally verifies `input_sha256` shape and required sidecar keys.

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
| 5 | Roadmap | PyPI package vs in-repo | **In-repo only for v0** | [D-5](#packaging--in-repo-only-for-v0) |
| 6 | Roadmap | Secret-pattern library: copy vs dependency | **Vendor (copy)** into the sanitizer; sync-test guards drift | [D-6](#decision-d-6--vendor-the-secret-pattern-library) |
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
- **PyPI extraction** as `claude-code-sessions-sanitizer` if a standalone audience appears.
- **Interactive review mode** — surface free-text prompts/outputs for human confirmation,
  addressing the §4 free-text limitation.
- **Content-level handling of `file-history-snapshot`** — scrub `trackedFileBackups` file
  bodies (path-aware, per-file-type) instead of dropping the line wholesale (D-7), so sanitized
  fixtures can illustrate `/rewind` semantics.
- **Shared secret-pattern source** — collapse the vendored Tier-1 duplication (§9) once the
  canonical home is decided.

---

## 18. Decision history

| Date | Change |
|---|---|
| 2026-05-29 | PRD created. D-1 through D-6 decided (§15). Jitter deferred to v1. |
| 2026-05-29 | Architect review incorporated ([issue #1 comment](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/1)): structural-traversal + strip-types spec (§6b, C-1/C-2), D-7 added, secret floor expanded to two tiers (§9, C-3), serialization pinned + rename order (§11, I-1/I-5), replacement-leak guard (§10, I-3), sync-test comparison shape (§9, I-4). |
