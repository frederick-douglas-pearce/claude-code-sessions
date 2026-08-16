# Subagent traces

When the parent session invokes the `Agent` tool, the subagent's complete internal trace is written to a **separate JSONL file**, not inlined in the parent session. This document covers that file: where it lives, how it links back to the parent, what its lines look like, and the gotchas that follow from the split.

For the field-level union across all message types, see [`data-dictionary.md`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/data-dictionary.md). For the parent-side `Agent` tool walkthrough (the `tool_use`, the `tool_result`, and the `toolUseResult` envelope as the parent sees them), see [`tool-invocation.md`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/tool-invocation.md). This doc starts where that one leaves off — inside the subagent trace file itself.

**Runtime scope.** Verification in this doc is against the **Claude Code** runtime, baseline v2.1.150, with the nesting sections re-verified against a v2.1.109–v2.1.233 corpus scan (see [Nesting](#nesting)). The Agent SDK (Python and TypeScript) writes session files in the same JSONL format but exercises it differently in places, and several sections below note where that matters.

**Both runtimes now support nested subagent invocation.** Claude Code gained it at **v2.1.172**. Earlier revisions of this doc described a Claude Code depth-1 restriction, which was accurate at the v2.1.150 baseline and stopped being true 22 versions later. Agent SDK probes (Python SDK 0.2.106 / CLI 2.1.185) confirmed that both single-level and multi-level SDK delegation reuse the Claude Code layout and linkage, that nested delegation records a **flat** `subagents/` directory (no nested sub-directories), and that the SDK shares one `sessionId` across all nesting levels — see [Agent SDK parity](#agent-sdk-parity). The TypeScript SDK remains unverified.

Three runtime divergences survive, each documented in place below: the SDK shares one `sessionId` across every level where Claude Code gives each subagent its own; the SDK drops the `toolUseResult` rollup at depth ≥ 2 where Claude Code keeps it; and SDK traces carry `entrypoint: "sdk-py"`.

---

## What a subagent trace is

**Verified against Claude Code v2.1.150.**

A subagent trace is the JSONL stream of a subagent's run. It contains every model turn the subagent took, every `tool_use` block it emitted, every `tool_result` it received, every `thinking` block when extended thinking is enabled, and per-step token usage. The same line shape as a parent session, with three systematic differences:

1. Every line carries `isSidechain: true`.
2. Every line carries a top-level `agentId` field that identifies the subagent invocation.
3. Subagent-specific fields (`attributionAgent`, `promptId`, `sourceToolAssistantUUID`, the `attributionMcp*` pair) appear with a strict per-line-type pattern — not on every line.

The parent session, by contrast, only records the *outcome* of the subagent run — a rollup of tokens, duration, and per-tool counts, plus the subagent's final summary as the `tool_result.content` string. The parent does **not** record the subagent's individual steps. Tools and posts that want step-level detail (which tools the subagent called, how long each took, what the model was reasoning about between calls) must read the subagent trace file directly.

This split is the reason `claude-code-sessions` documents subagent traces in their own reference doc rather than treating them as a footnote to the parent session.

---

## File layout

**Verified against Claude Code v2.1.150.** The sidecar directories (`subagents/`, `tool-results/`) and the per-invocation `meta.json` were additionally confirmed by an observational format scan over `~/.claude/projects/` spanning v2.1.4–v2.1.170 — directory names, key names, value *types*, and file sizes only; no message content was read.

A session that delegates work grows a `<session-uuid>/` directory beside its `<session-uuid>.jsonl` file. That directory collects the two kinds of overflow that don't belong inline: subagent traces (under `subagents/`) and spilled large tool outputs (under `tool-results/`).

```
~/.claude/projects/<slug>/
├── <session-uuid>.jsonl                              # parent session
└── <session-uuid>/                                   # created lazily on first overflow
    ├── subagents/                                    # one (trace + manifest) pair per invocation
    │   ├── agent-<agentId-1>.jsonl                   #   the subagent trace
    │   ├── agent-<agentId-1>.meta.json               #   a small manifest sidecar (see below)
    │   ├── agent-<agentId-2>.jsonl
    │   ├── agent-<agentId-2>.meta.json
    │   └── …
    └── tool-results/                                 # large tool outputs spilled out of the JSONL
        └── <tool-use-id>.txt | <tool-use-id>.json    #   one file per oversized tool result
```

| Path component | Semantics |
|---|---|
| `~/.claude/projects/<slug>/` | Same project root as the parent session. `<slug>` is the slugified `cwd` (see [`data-dictionary.md` § File location](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/data-dictionary.md#file-location)). |
| `<session-uuid>/` | A sibling directory to `<session-uuid>.jsonl`. Created lazily — exists only once the session produces overflow that doesn't fit inline: a subagent trace, a spilled tool result, or both. |
| `subagents/` | The session's subagent-files directory. Present when the session invoked at least one subagent. |
| `agent-<agentId>.jsonl` | The subagent trace. One file per subagent invocation. The `<agentId>` segment in the file name is the same UUID that appears in the parent's `toolUseResult.agentId` on the `user` line that carried the subagent's `tool_result`. |
| `agent-<agentId>.meta.json` | A small manifest written beside each trace. See [The `meta.json` manifest](#the-metajson-manifest). |
| `tool-results/` | Sibling to `subagents/`. Holds large tool outputs spilled out of the session JSONL — **not** subagent-specific. See [Spilled tool results](#spilled-tool-results) below, and [`tool-invocation.md`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/tool-invocation.md) for the full mechanism. |

A subagent **invocation** (one `Agent` `tool_use` from the parent) maps to exactly one trace file plus its manifest. If the parent invokes the same `subagent_type` multiple times in the same session, you get multiple pairs — one per invocation, each with its own `agentId`.

### The `meta.json` manifest

**Verified against Claude Code v2.1.233.** Key set confirmed by observational scan over 1,235 `agent-<id>.meta.json` files spanning v2.1.109–v2.1.233 (superseding an earlier 563-file scan over v2.1.4–v2.1.170) — key names and value *types* only, plus the `spawnDepth` integer; no other values read.

Beside every `agent-<agentId>.jsonl` trace sits a small `agent-<agentId>.meta.json` (tens to a few hundred bytes) — a manifest that lets Claude Code, and your own tooling, enumerate and route subagents without opening and parsing the full trace. Counts below are out of 1,235 manifests. Only `agentType` is guaranteed, and several keys are recent additions, so **read this manifest defensively**: a missing key usually means "the Claude Code version that wrote this manifest did not record it", not "the value is empty".

| Key | Present on | Type | What it is |
|---|---|---|---|
| `agentType` | every manifest (1235/1235) | `str` | The subagent type that ran (`"general-purpose"`, `"pm"`, a custom agent name). Same value as `attributionAgent` in the trace and `toolUseResult.agentType` on the parent. |
| `description` | every manifest (1235/1235) | `str` | The human-readable task description from the parent's `Agent` call. An earlier 563-file scan found it on 546/563, so do not treat it as guaranteed. |
| `toolUseId` | often (931/1235) | `str` | The id of the parent `Agent` `tool_use` that spawned this run. See the casing note below. |
| `spawnDepth` | v2.1.187 onward (467/1235) | `int` | The subagent's nesting level, 1 for a subagent spawned directly by the main session. Absent from every manifest written before v2.1.187, so treat absence as "not recorded" rather than depth 1. See [Nesting](#nesting). |
| `model` | rarely (26/1235) | `str` | The model the subagent ran on, when it differs from the session default. |
| `name` | rarely (14/1235) | `str` | A display name for the invocation. |
| `worktreePath` | rarely (8/1235) | `str` | Filesystem path of the git worktree the subagent ran in, present only for worktree-isolated runs. |
| `worktreeBranch` | rarely (2/1235) | `str` | The branch checked out in that worktree. |
| `spawnedWithWorktree` | rarely (1/1235) | `bool` | Marks a worktree-isolated run. |
| `worktreeCleanlyRemoved` | rarely (1/1235) | `bool` | Whether the worktree was cleaned up afterward. |
| `parentAgentId` | almost never (1/1235) | `str` | The spawning agent's id, on a depth-2 manifest at v2.1.226. Too rare to build on yet; see [open item 3](#open-verification-items). |

Note that `spawnDepth` is the only integer and the two `worktree*` flags are the only booleans; everything else is string-valued. Earlier revisions of this doc said all manifest keys were string-valued, which held for the key set known at the time.

**`toolUseId` is the one part of the subagent → parent relationship carried in data rather than inferred from disk location.** The trace lines themselves carry no field naming the parent (see [Parent ↔ subagent linkage](#parent--subagent-linkage)); the manifest's `toolUseId` names the exact parent `tool_use` the run answers. Note it sits *beside* the trace, not inside it.

**Casing wrinkle.** The manifest spells this key `toolUseId` (lowercase `d`), while session and trace lines spell the analogous id `toolUseID` (uppercase `D`). Same kind of value, different casing, in files that sit next to each other — a parser reading both must handle both spellings.

### Spilled tool results

**Verified against Claude Code v2.1.150.** Directory presence, file-size band, and the in-content wrapper were confirmed by the observational scan (89 spilled files across 40 sessions).

Alongside `subagents/`, a session often grows a `tool-results/` directory. It is **not** subagent-specific: it holds *large* tool outputs that would otherwise bloat a single JSONL line. When a tool result is big, the in-session `tool_result` content carries a `<persisted-output>` wrapper with a truncated preview, and the full payload lands in `tool-results/`, named after the tool call that produced it (`<tool-use-id>.txt` or `.json`). Observed spilled files ranged from ~20 KB to ~860 KB (median ~64 KB), implying a spill threshold near 20 KB. The in-JSONL reference is that plain-text `<persisted-output>` wrapper inside `tool_result.content` — **not** a dedicated JSON pointer key (the scan's tool_result-line key set carries no spill-pointer field).

This is a tool-invocation concern, not a subagent one; it is documented in full in [`tool-invocation.md`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/tool-invocation.md). It appears here only so the `<session-uuid>/` directory listing makes sense.

### Nesting

**Verified against Claude Code v2.1.233.** Re-verified 2026-08-15 by an observational scan over 2,047 session files (232,471 lines, 1,235 `meta.json` manifests) spanning v2.1.109–v2.1.233. Directory names, key names, and the `spawnDepth` integer only; no message content was read. Method and full numbers: [issue #169](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/169).

**Claude Code subagents can spawn their own subagents, as of v2.1.172.** Earlier revisions of this section stated the opposite. That was correct at the v2.1.150 baseline and stopped being correct 22 versions later, so any parser written against the old text will silently miss depth-2+ subagent data in newer sessions.

The depth cap is version-dependent and, from v2.1.217, configurable:

| Claude Code version | Nesting behavior |
| --- | --- |
| through v2.1.171 | Subagents cannot spawn subagents. Every subagent is depth 1. |
| v2.1.172 | Nested spawning introduced, announced as "up to 5 levels deep". |
| v2.1.181 | Foreground subagents brought under the same depth limit as background ones. |
| v2.1.187 | Depth tracking fixed, and `spawnDepth` begins appearing in the `meta.json` manifest. |
| v2.1.217 / v2.1.219 | Default cap stated as depth 3. Set `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH=1` to restore the old single-level behavior. |

Two cautions on that table. The upstream CHANGELOG is self-inconsistent about the cap: v2.1.172 says five levels and v2.1.219 says "depth 3 (was 1)", which cannot both describe a monotonic history. The corpus scan settles part of it, since depth-2 Claude Code subagents were recorded at **v2.1.195**, inside the window v2.1.219 describes as capped at 1. It does not settle the rest: the deepest subagent observed anywhere in the corpus is **depth 2**, so neither the five-level nor the three-level cap has been seen exercised. Treat the cap numbers as CHANGELOG claims and `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH` as the thing that actually controls it. Second, `spawnDepth` is absent from every manifest written before v2.1.187, so a manifest with no `spawnDepth` key means "this Claude Code version did not record depth", not "depth 1".

#### The layout is flat, at every depth, in both runtimes

**Observed, not inferred.** The scan found **zero** nested `subagents/<agentId>/subagents/…` directories across 294 session directories, including the sessions that contain depth-2 subagents. An Agent SDK probe that forced a two-level chain (`main → delegator → leaf`, Python SDK 0.2.106 / CLI 2.1.185, 2026-06-22) found the same thing. Every subagent, at every depth, in either runtime, is written as a sibling file directly under the single `<session-uuid>/subagents/` directory:

```
<session-uuid>/subagents/
├── agent-<delegatorId>.jsonl        # depth 1
├── agent-<delegatorId>.meta.json
├── agent-<leafId>.jsonl             # depth 2 — SAME directory, not nested
└── agent-<leafId>.meta.json
```

A deeper call chain just yields more siblings in the same folder. The directory shape therefore carries **no depth or parent information**, and the call tree must be reconstructed from the data (see [Reconstructing a multi-level call tree](#reconstructing-a-multi-level-call-tree)).

The recommended posture is unchanged: **walk the flat `subagents/` directory and reconstruct the call tree from `toolUseId`/`agentId` linkages, never from path shape.** What changed is why it matters. This used to be defensive advice that cost a Claude Code parser nothing, because a Claude Code session could not nest. Now it is load-bearing on Claude Code too. The TypeScript SDK is not yet sampled, but the format is shared; treat the flat layout as the expected arrangement until shown otherwise.

#### Where a nested spawn is recorded

The `tool_result` for a nested spawn lives in **the spawning agent's own trace file**, not the parent session transcript. Across the corpus this held without exception: all 449 depth-1 spawn sites sat in `<session-uuid>.jsonl`, and all 6 depth-2 spawn sites sat in the depth-1 subagent's `agent-<id>.jsonl`. This is the mechanical reason path shape cannot give you the tree, and why the reconstruction below has to index `tool_use.id` across every file rather than just the main session.

#### `spawnDepth` and `parentAgentId` in the manifest

Two `meta.json` manifest keys bear on nesting:

| Key | Observed behavior |
| --- | --- |
| `spawnDepth` | Integer nesting level, 1 for a subagent spawned directly by the main session. Present on every manifest from v2.1.187 onward and absent from every manifest before it. Observed values in the corpus: 1 (461 manifests) and 2 (6 manifests). |
| `parentAgentId` | Names the spawning agent directly. **Rare.** Present on 1 of 1,235 manifests scanned (a depth-2 manifest at v2.1.226), so it is not yet something a parser can depend on. |

The Agent SDK announced a `parent_agent_id` field on subagent session *messages* at TS SDK v0.3.202, which would make tree reconstruction much cheaper than the cross-file join. **The Claude Code counterpart is not there yet:** neither `parentAgentId` nor `parent_agent_id` appears as a line-level key anywhere in the 2,047-file corpus. Until it does, the `toolUseId` join is the only reliable Claude Code linkage.

---

## Agent SDK parity

**Verified against Agent SDK `claude-agent-sdk` 0.2.106 / `claude` CLI 2.1.185 (Python), captured 2026-06-22.** Covers single-level (parent → subagent) and a forced two-level chain (`main → delegator → leaf`). The TypeScript SDK is still unsampled (see [Open verification items](#open-verification-items)).

A first empirical Agent SDK probe confirms that **SDK subagent traces match the Claude Code shape.** A forced delegation from a Python SDK agent produced, under the parent session directory, exactly the layout documented above:

```
<session-id>/subagents/agent-<agentId>.jsonl        # child trace
<session-id>/subagents/agent-<agentId>.meta.json    # manifest sidecar
```

What held identically to Claude Code:

- **`isSidechain: true` on every child-trace line**, the same canonical subagent marker (see [The `isSidechain` marker](#the-issidechain-marker)).
- **Same `user`/`assistant` schema** as the main session — nothing in the child trace's message shape is SDK-specific.
- **Parent → child linkage holds three ways**, all matching the Claude Code conventions: the parent `tool_use.id` equals the `tool_result.tool_use_id` equals the sidecar's `toolUseId`; and `toolUseResult.agentId` equals the `agent-<agentId>.jsonl` file name.

What is new or SDK-marked:

- **`entrypoint: "sdk-py"`** on the child-trace lines (the Python SDK marker), where a Claude Code child trace carries the interactive value. The marker propagates into the subagent trace, not just the main session.
- **`resolvedModel` on the parent's `toolUseResult`** — the concrete model the child ran, a new rollup field (see [`data-dictionary.md` § toolUseResult envelope](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/data-dictionary.md#tooluseresult-envelope); tracked as format-watch F-016).
- **`agentId` was observed as a short hex string** (~17 hex chars) rather than a dashed UUID. The linkage semantics are unchanged — it still names the trace file and matches `toolUseResult.agentId` — only the token *shape* differed in the probe.

This **partially closes** the long-standing open gap on Agent SDK nested invocations: single-level delegation is now confirmed to reuse the Claude Code layout and linkage. The probe used a *pure* SDK agent (no MCP, no inherited settings) over one delegation level, so the attribution-field placement under MCP routing and the set of `type` values in richer runs remain unverified. The recommended posture from [Nesting](#nesting) stands, and now applies to Claude Code as well: walk the directory structure and reconstruct the call tree from `agentId` linkages rather than assuming a fixed depth.

The SDK parent-side envelope is shown in [`agent-sdk-invocation.jsonl`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/fixtures/synthetic/agent-sdk-invocation.jsonl); the Claude Code child-trace shape it pairs with is [`anatomy-subagent-trace.jsonl`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/fixtures/synthetic/anatomy-subagent-trace.jsonl) (the probe confirmed the SDK child trace matches that shape, plus the `entrypoint: "sdk-py"` marker).

### Multi-level (nested) delegation

The Agent SDK lets a subagent invoke its own subagent. So does Claude Code, from v2.1.172 (see [Nesting](#nesting)), so this section is no longer an SDK-only concern. It is kept here because the SDK probe is where each property was first pinned down, and because **one of the four diverges between the runtimes** — item 3 below. A probe that forced `main → delegator → leaf` pinned down four things beyond the single-level parity above:

1. **The layout is flat (no nested directories).** Every subagent at every depth is a sibling under the one `<session-uuid>/subagents/` directory — see [Nesting](#nesting). **Same in Claude Code**, confirmed by the v2.1.109–v2.1.233 scan. `sessionId` is the same across all levels (the SDK shares the main session's id; see the [`sessionId` note](#parent--subagent-linkage) for the contrast with Claude Code), and `entrypoint: "sdk-py"` is carried throughout.

2. **Parent linkage is by-data, not by-path.** Because the directory is flat, the only thing that says which agent spawned which is the `toolUseId` in each subagent's `.meta.json` sidecar — and that id names a `tool_use` block that lives in the *spawning agent's* trace, which at depth ≥ 2 is **another subagent file, not the main session.** **Same in Claude Code**, where all 6 observed depth-2 spawn sites sat in the depth-1 subagent's trace file. See [Reconstructing a multi-level call tree](#reconstructing-a-multi-level-call-tree).

3. **The `toolUseResult` rollup is top-level only — in the SDK. This one does _not_ carry over to Claude Code.** In the SDK, the rich rollup envelope (`totalTokens`, `totalToolUseCount`, `resolvedModel`, `toolStats`, …) is attached only on the **main session's** `user` line carrying a *level-1* result. At depth ≥ 2 the spawning `Agent` `tool_result` block carries **no** `toolUseResult` sibling, only an inline `subagent_tokens: <N>` text trailer in the result content. Metrics for a depth-≥2 SDK subagent must be derived from that subagent's own trace (or the trailer), not read off a parent envelope the way level-1 metrics can.

   Claude Code behaves differently, and better: **every** observed depth-2 Claude Code spawn site carried a full `toolUseResult` sibling, matching all 449 depth-1 control sites. Claude Code cost attribution at depth ≥ 2 is therefore intact, and the SDK caveat must not be generalized to it. Note also that the `subagent_tokens` trailer is not a depth marker in Claude Code: it appeared on 292 of 449 depth-1 sites and 1 of 6 depth-2 sites, coexisting with the rollup rather than replacing it.

   | Runtime | Spawn | Where its `tool_result` lives | `toolUseResult`? |
   |---|---|---|---|
   | Agent SDK | main → delegator (level 1) | main `<session-uuid>.jsonl` | **yes** (full rollup) |
   | Agent SDK | delegator → leaf (level 2) | `agent-<delegatorId>.jsonl` | **no** (only a `subagent_tokens` trailer) |
   | Claude Code | main → subagent (depth 1) | main `<session-uuid>.jsonl` | **yes** (full rollup) |
   | Claude Code | subagent → subagent (depth 2) | `agent-<parentId>.jsonl` | **yes** (full rollup) |

   The Claude Code rows rest on 6 depth-2 observations, all from one corpus. The direction is unambiguous (6 of 6 carry the rollup where the SDK carries none), but treat the sample as thin.

4. **Counter/token semantics.** `totalToolUseCount` is **own-direct, not cumulative** — a delegator reported only the tool calls it made itself (including its own `Agent` call) and **excluded** the leaf's tool calls. `totalTokens` reads as directionally inclusive of descendants but does **not** equal a raw sum of per-turn `message.usage` (cache accounting differs); settle the exact inclusivity rule against real bytes before summing across levels, or a multi-level aggregator will miscount. (For a **single**-level rollup the semantics are now settled: `totalTokens` is one assistant turn's snapshot, not a run sum, per [Token accounting](#token-accounting). The multi-level cross-level inclusivity here is a separate, still-open question.) `resolvedModel` reports the **child's** resolved model, not the parent's — in a sonnet-parent / haiku-child run it read `claude-haiku-4-5-20251001`.

### Reconstructing a multi-level call tree

**Applies to both runtimes.** This procedure lives under the SDK-parity heading because the SDK probe is where it was worked out, but it is what a Claude Code session from v2.1.172 onward requires too. The corpus scan confirmed the step-2 lookup resolves in Claude Code exactly as described: every one of the 453 joinable manifests located its spawning `tool_result`, with depth-2 manifests resolving into another subagent's trace rather than the main session.

The flat directory gives you the *set* of agents but not the *edges*. Build the tree from data:

1. Index every `tool_use.id` → `(containing trace file, that file's agentId)` across **all** files — the main session JSONL **and** every `agent-<id>.jsonl`. (A subagent's own `agentId` is on each of its trace lines and in its file name.)
2. For each subagent, read `toolUseId` from its `agent-<id>.meta.json` and look it up in that index. The trace that *emitted* that `tool_use` is the parent; its `agentId` (or "main session," if the id resolved there) is the parent agent.
3. The root subagents are those whose `toolUseId` resolved into the main session JSONL; everything else hangs off another subagent.

What is **not** a cross-file parent link, despite looking like one: `attributionAgent` is the agent's **own** type name (a self-label), and `sourceToolAssistantUUID` / `parentUuid` are **intra-file** message-threading pointers only (see [`sourceToolAssistantUUID` is an internal pairing key](#sourcetoolassistantuuid-is-an-internal-pairing-key--not-a-parent-back-pointer)). Keying a multi-level linker on any of those silently flattens a 3-level tree to 2.

---

## The `isSidechain` marker

**Verified against Claude Code v2.1.150.**

Every line inside a subagent trace file carries `isSidechain: true`. Parent-session lines carry `isSidechain: false` (or omit the field on some message types).

This is the **canonical, content-free signal** for distinguishing a subagent trace line from a parent-session line. Parsers that only see a stream of lines (e.g., from a hook script, or from a glob over `~/.claude/projects/`) should branch on this field — not on file path, not on the presence of `agentId`, not on `attribution*` heuristics.

| `isSidechain` value | What it means | Lines that carry it |
|---|---|---|
| `true` | Line is inside a subagent trace file | Every line in `agent-<agentId>.jsonl` |
| `false` or absent | Line is in a parent session file | Every line in `<session-uuid>.jsonl` |

### When to treat sidechain lines differently

Sidechain lines are *not* main-conversation turns from the user's point of view. Tools should:

- **Skip them** when computing the user-visible turn count or rendering the main conversation thread.
- **Include them** when aggregating per-session tokens. The parent's `toolUseResult.usage` rollup is a single-turn snapshot, not a substitute for the subagent's per-turn usage, so dropping the sidechain lines in favor of the rollup **undercounts** (see [Token accounting](#token-accounting) below).
- **Include them** when auditing tool calls the agent made, debugging subagent behavior, computing per-agent quality metrics, or reconstructing the full action trace.

The data-dictionary lists `isSidechain` as a common field across line types ([§ Common fields](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/data-dictionary.md#common-fields)). This doc adds the operational guidance.

---

## Parent ↔ subagent linkage

**Verified against Claude Code v2.1.150.**

The link between a parent session and a subagent trace file is **one-directional in the data, bidirectional in practice**. The data carries an explicit parent → subagent link via `agentId`. The reverse direction (subagent → parent) is implicit — the subagent file's location on disk encodes it. There is no per-line back-pointer field that points at the parent session.

### Parent → subagent: `agentId`

On the parent session's `user` line carrying the subagent's `tool_result`, the top-level `toolUseResult.agentId` field is the link:

```
parent line                          subagent file
─────────────                        ─────────────
user.toolUseResult.agentId  ─────►   agent-<agentId>.jsonl
                                     (and: every line's top-level agentId)
```

For the parent side, see [`anatomy-agent-invocation.jsonl`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/fixtures/synthetic/anatomy-agent-invocation.jsonl), in which the parent's `user` line carries `"toolUseResult": {..., "agentId": "99999999-9999-9999-9999-999999999001", ...}`. The corresponding subagent trace file is named `agent-99999999-9999-9999-9999-999999999001.jsonl`, and every line in that file — `assistant`, `user`, and `attachment` alike — carries the same value in a top-level `agentId` field.

### Subagent → parent: implicit via directory location

There is **no per-line field on subagent trace lines that points at the parent's session UUID or the parent's invoking `assistant` `uuid`.** Within the trace itself, the reverse linkage is reconstructed from the file system: the subagent file lives at `~/.claude/projects/<slug>/<session-uuid>/subagents/agent-<agentId>.jsonl`, and `<session-uuid>` is the parent's sessionId.

The one in-data exception sits *beside* the trace, not inside it: the `agent-<agentId>.meta.json` manifest records the parent `Agent` `tool_use` id as `toolUseId` (see [The `meta.json` manifest](#the-metajson-manifest)). That names the exact parent `tool_use` the run answers — a link the trace lines alone don't carry. So a precise statement is: the trace *lines* carry only the forward `agentId`; the reverse pointer lives in the manifest sidecar and the directory path, not in the trace's line data. In a **multi-level** chain, in either runtime, that `toolUseId` may point at a `tool_use` emitted in *another subagent's* trace rather than the main session — so resolving it requires indexing tool-use ids across every file, not just the parent session (see [Reconstructing a multi-level call tree](#reconstructing-a-multi-level-call-tree)).

Importantly, **`sessionId` is NOT shared between parent and subagent in Claude Code.** Each subagent invocation has its **own** sessionId — distinct from the parent's. The subagent files in a parent's `subagents/` subdirectory have their own sessionIds, and the parent's sessionId appears only as the *directory name* containing them.

**The Agent SDK diverges here.** In the nested SDK probe (Python SDK 0.2.106 / CLI 2.1.185), every trace at every level — main, delegator, and leaf — carried the **same** `sessionId` (the main session's), which also matched the `<session-uuid>` directory name. So under the SDK the directory name and the in-line `sessionId` coincide, and `sessionId` cannot tell a level-1 subagent from a level-2 one — use the file's `agentId` and the `toolUseId` join for that. Whether the TypeScript SDK matches, and whether this Python-SDK behavior is stable across versions, is not yet confirmed.

### `sourceToolAssistantUUID` is an internal pairing key — NOT a parent back-pointer

The `sourceToolAssistantUUID` field appears only on **`user` lines** inside a subagent trace, and only on user lines that carry a `tool_result` (i.e., not on the initial user prompt that started the subagent). Every observed value matches the `uuid` of an `assistant` line **earlier in the same subagent file** — specifically, the assistant line that emitted the `tool_use` whose result this user line carries.

```
subagent file (internal pairing)
─────────────
assistant line: uuid: "aaaa…0001", message.content[*].tool_use.id: "toolu_X"
                ▲
                │ sourceToolAssistantUUID
                │
user line:      tool_result.tool_use_id: "toolu_X"
```

So `sourceToolAssistantUUID` is a **redundant** line-level pairing key alongside `tool_use_id`. It exists at the top level of the line, which lets a parser reconstruct the assistant ↔ user tool cycle without descending into `message.content` arrays. It does not point at anything in the parent session.

This corrects a natural-sounding but wrong inference: it is **not** the case that this field points at the parent's invoking assistant line. The only data-carried link to the parent is `agentId`; the directory location carries the rest.

---

## Attribution fields

**Verified against Claude Code v2.1.150.**

The `attribution*` family captures *what the subagent is and how it routes*. Each field has a strict per-line-type presence pattern in Claude Code traces, summarized below. The Agent SDK may exercise these fields differently; until verified, treat the patterns below as Claude Code-specific.

| Field | Present on `assistant` lines | Present on `user` lines | Present on `attachment` lines | What it means |
|---|---|---|---|---|
| `agentId` | ✅ always | ✅ always | ✅ always | UUID of this subagent invocation. Matches the file name and the parent's `toolUseResult.agentId`. |
| `attributionAgent` | ✅ always | ❌ never | ❌ never | The subagent type that ran (e.g., `"general-purpose"`, `"pm"`, a custom agent name). Identifies *what* this subagent is. The value matches `toolUseResult.agentType` on the parent line that invoked this run. |
| `attributionMcpServer` | ✅ when an MCP tool is involved in the turn | ❌ never | ❌ never | The MCP server name (e.g., `"github"`). Appears on assistant turns that interact with an MCP-defined tool. Absent (key omitted) on assistant turns that don't. |
| `attributionMcpTool` | ✅ when an MCP tool is involved in the turn | ❌ never | ❌ never | The specific MCP tool name (e.g., `"get_issue"`). Paired with `attributionMcpServer` — appears together or not at all. |
| `attributionSkill` | ✅ when the turn ran under an invoked Skill | ❌ never | ❌ never | The name of the Skill the assistant turn ran under. Parallels `attributionAgent`/`attributionMcp*`. **Not subagent-exclusive** — see the caveat below. |
| `promptId` | ❌ never | ✅ always | ❌ never | An identifier for the prompt-flow this user line participates in. Stable across user lines of a single subagent invocation. |
| `sourceToolAssistantUUID` | ❌ never | ✅ on tool_result user lines (not the initial prompt) | ❌ never | The `uuid` of the same-file `assistant` line whose `tool_use` this user line is the result for. See [Parent ↔ subagent linkage](#parent--subagent-linkage). |

The per-line-type discipline is consistent across all observed Claude Code subagent files. A parser that needs to filter by attribution can branch on `type` first and only check the fields that apply to that type.

**`attributionSkill` is not a sidechain marker.** Unlike `attributionAgent` — which the observational scan found *only* on sidechain assistant lines (10,291 sidechain, 0 main), making it a reliable subagent signal — `attributionSkill` appears on both subagent-trace and parent-session assistant lines (4,785 sidechain, 1,895 main in the scan), because Skills run in the main loop as well as inside subagents. So `attributionSkill` tells you *a Skill was active for this turn*, not *this line is from a subagent*. For the subagent question, branch on `isSidechain` (see [The `isSidechain` marker](#the-issidechain-marker)). The same caveat applies to `attributionMcpServer`/`attributionMcpTool`, which also appear on main-session assistant lines when an MCP tool is used outside a subagent.

### `attributionAgent` example values

Observed values include `"general-purpose"` (the default agent for ad-hoc delegation) and the names of project-scoped subagents. The value is the same string that appears as `subagent_type` in the parent's `Agent` `tool_use.input` and as `agentType` in the parent's `toolUseResult`. So:

```
parent line                              subagent file
─────────────                            ─────────────
tool_use.input.subagent_type     ───┐
toolUseResult.agentType          ───┼──►  every assistant line's attributionAgent
                                    │
                                    └──   (and the file's agentId in the file name)
```

### When `attributionMcpServer`/`attributionMcpTool` appear

These appear on assistant lines associated with an MCP-tool turn. Whether they appear on the assistant line that *emits* the MCP `tool_use`, only on turns that *follow* an MCP `tool_result` (i.e., the model's next reasoning after an MCP tool returned), or on both, is not yet disambiguated by the recon — the observation is that roughly half of the assistant lines in a given subagent's MCP-using flow carry these. Treat as "MCP-routing context present when this assistant turn interacts with an MCP server."

When no MCP tool is involved in the turn, both fields are **absent** (the keys are not present on the line), not empty strings.

---

## Internal trace structure

**Verified against Claude Code v2.1.150.**

Inside a Claude Code subagent trace file, message types are restricted compared to parent sessions. Across all subagent files sampled on this machine, only three `type` values appear:

| Line `type` | Observed | Notes |
|---|---|---|
| `assistant` | ✅ | The subagent's model turns. `message.content` carries `text`, `tool_use`, and (when extended thinking is on) `thinking` blocks. `message.usage` carries per-turn token usage. See [`data-dictionary.md` § assistant](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/data-dictionary.md#assistant). |
| `user` | ✅ | The initial prompt that started the subagent, plus tool result envelopes responding to the subagent's `tool_use` blocks. The same two-shape pattern as parent-session `user` lines (string OR array `content`). When the subagent invokes a context-bearing tool, the `user` line carries a top-level `toolUseResult` envelope just like the parent. |
| `attachment` | ✅ | Files or images attached to a subagent message. Same shape as parent-session attachment lines. Observed sparingly. |

Notably **not observed in Claude Code subagent traces**: `file-history-snapshot`, `system`, `permission-mode`, `ai-title`, `last-prompt`, `queue-operation`. These are session-level concerns recorded only in the parent file. In particular, `file-history-snapshot` — the data structure that powers `/rewind` (see [`data-dictionary.md` § File-history snapshots](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/data-dictionary.md#file-history-snapshots-in-detail)) — stays in the parent session. Code edits made by a subagent are still snapshotted, but the snapshot lines are written to the parent file, not the subagent's trace file.

This means Claude Code subagent traces are mostly homogeneous: long runs of alternating `assistant`/`user` lines with the occasional `attachment`. Agent SDK subagent traces may exhibit a different set of message types; until verified, treat the restricted-set claim as Claude Code-specific.

### Inside `message` on subagent lines

The `message` object follows the same field shape as parent-session lines:

- **`assistant`** lines: `message` has `role`, `id`, `type`, `model`, `content`, `usage`, `stop_reason`, optionally `stop_sequence`, `stop_details`, `diagnostics`. See [`data-dictionary.md` § assistant](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/data-dictionary.md#assistant).
- **`user`** lines: `message` has `role` and `content` (string for the initial prompt, array for tool_result envelopes). Same two-shape pattern as parent. See [`data-dictionary.md` § user](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/data-dictionary.md#user).

Anything that parses parent sessions can parse subagent traces with the same code path, given:

1. `isSidechain: true` on every line.
2. `agentId` on every line.
3. `attributionAgent` on every `assistant` line; `promptId` on every `user` line.
4. `sourceToolAssistantUUID` on tool-result user lines only.
5. Restricted set of `type` values in Claude Code traces (no `file-history-snapshot`, no `system`, etc.); possibly broader in Agent SDK traces.

See [`anatomy-subagent-trace.jsonl`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/fixtures/synthetic/anatomy-subagent-trace.jsonl) for a synthetic four-line example that pairs with the parent-side [`anatomy-agent-invocation.jsonl`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/fixtures/synthetic/anatomy-agent-invocation.jsonl).

---

## What the parent sees vs. what's in the file

**Verified against Claude Code v2.1.150.**

The same subagent run produces two artifacts, and they record fundamentally different views:

| Aspect | Parent session line (`toolUseResult` envelope) | Subagent trace file |
|---|---|---|
| Granularity | **Rollup**: one user line summarizing the whole subagent run | **Step-by-step**: every model turn, every tool call, every result |
| Token data | `toolUseResult.usage` (a **single turn's** snapshot, not a run total) and `toolUseResult.totalTokens` (that snapshot's four-field sum) | Per-`assistant`-line `message.usage` (one object per model turn; **dedupe by `message.id`** before summing) |
| Tool data | `toolUseResult.toolStats` — *category* counters only (`readCount`, `searchCount`, `bashCount`, `editFileCount`, `otherToolCount`), with no per-tool-name breakdown. See [`data-dictionary.md` § `toolStats` shape](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/data-dictionary.md#toolstats-shape). | Every `tool_use`/`tool_result` pair, with full `input` and `content` |
| Duration | `toolUseResult.totalDurationMs` (single scalar) | Per-line `timestamp`s; derive durations by diff |
| Final output | `tool_result.content` — the subagent's final summary as a string | The same final summary appears as the last `assistant` `text` block; the entire reasoning that produced it is also present |
| Reasoning | Not present | `thinking` blocks on `assistant` lines (when extended thinking is enabled) |
| Intermediate text | Not present | All `assistant` `text` blocks across all turns |

The pattern: **`toolUseResult` is what the parent agent and its model see; the subagent file is what an analytics tool sees if it cares about how the subagent actually behaved.** AgentFluent's diagnostics and CodeFluent's coaching both need the per-step view; the parent envelope alone is too coarse.

This is also why most simple parsers stop at the parent envelope and treat the subagent's existence as a single tool call. The data is there if you want it — it just lives in a different file.

---

## Token accounting

**Verified against Claude Code v2.1.150.** The rollup semantics below were additionally confirmed against a live corpus of **691 linked subagent invocations** (measured 2026-07-18, `claude-agent-sdk` 0.2.106 / CLI 2.1.185). Anthropic states this format is internal and may change on any release, so the identity in [What `totalTokens` actually is](#what-totaltokens-actually-is) is worth **asserting in your own tests** rather than assuming.

Subagent token usage appears in **two places**, and they measure **different quantities**. Treating them as interchangeable, or summing them, is the most common cost-accounting error against this format.

1. On each `assistant` line **inside** the subagent trace file, `message.usage` records **that one model turn's** usage. One entry per turn.
2. In the parent session, `toolUseResult.usage` and `toolUseResult.totalTokens` on the `user` line carrying the subagent's `tool_result` record a **single turn's** usage. A snapshot, not a run total.

> **Correction (2026-07-18).** Earlier revisions of this section described the parent rollup as *cumulative across the subagent run* and warned that trace plus rollup "double-count." That is inverted. The rollup is one turn; aggregating from it alone **undercounts** processed tokens by a median **5.8x** and dollar cost by roughly 15x. The corpus figures below replace the old guidance.

### What `totalTokens` actually is

The parent's `totalTokens` is exactly the sum of the four fields in the sibling `toolUseResult.usage`:

```
totalTokens == usage.input_tokens
             + usage.output_tokens
             + usage.cache_creation_input_tokens
             + usage.cache_read_input_tokens
```

This held **691/691 (100%)** across the corpus, a deterministic identity safe to assert in tests. And that `usage` is **one assistant turn's** usage: it equals the subagent's **final** turn in 582/691 (84.2%) of cases, the residual 16% being runs where the snapshotted turn is not the trace's last assistant line. Either way it is a **single-turn context-size proxy**, neither tokens billed nor tokens processed across the run.

### Why the rollup is not a run total

The Messages API is [stateless](https://platform.claude.com/docs/en/build-with-claude/working-with-messages): the full conversation history is re-sent on every request. So each turn's `usage` re-reports the whole context that turn was given, and `cache_read_input_tokens` recurs turn over turn, growing as the conversation grows. Snapshotting one turn (what `totalTokens` does) yields a *context size*. Summing all turns yields *tokens processed*, the correct basis for cost, because you are genuinely billed each turn for re-read context at the cheaper cache-read rate.

This is also why the error stayed hidden. Summed across a run, the **expensive** components alone (`input + output + cache_creation`, excluding cache reads) come to a median **1.02x** of `totalTokens` (p90 1.21x): each context token is cache-*written* about once per run, so `Σ cache_creation` ≈ final context size ≈ `totalTokens`. The rollup lands within a couple percent of a real, meaningful number, which is exactly why summing it looked right. Include cache reads (what you actually process) and the ratio of real processed tokens to `totalTokens` runs to a median **5.8x**, p90 14.2x, max 79.7x. The direction is **always** understatement.

### Streaming snapshots and `message.id`

A second, independent trap sits inside the trace file. Claude Code writes **multiple `assistant` lines for one logical turn** as a response streams; they share a `message.id`, and each carries a running snapshot of `usage`, not an increment. Across the measured corpus, **986/1,047 files (94%)** contained duplicate `message.id`s, and naively summing every assistant line inflated the total by **1.99x**.

Deduplicate before summing: group `assistant` lines by `message.id`, keep the record with the **greatest `output_tokens`** (the most complete snapshot), and take **all four** usage fields from that same record. Do not take a per-field max across records, which mixes snapshots. Note also that `input_tokens` is often a placeholder on non-final chunks (observed as `1` on 11,133 lines, `2` on 4,019, `3` on 2,300, `0` on 491), so never read it off an arbitrary chunk.

### Aggregation patterns

| You want… | Use |
|---|---|
| A subagent's **real processed tokens** (the basis for cost) | The subagent trace file: deduplicate `assistant` lines by `message.id` (above), then sum `message.usage` across turns. **Not** the parent rollup. |
| A subagent's **peak context size** | The trace's **final** deduped turn, summing its input-side buckets (`input_tokens + cache_creation_input_tokens + cache_read_input_tokens`). See [Context size is a trace-only measure](#context-size-is-a-trace-only-measure). `totalTokens` is a rough proxy only, low ~16% of the time. |
| **Total session** processed tokens | Deduped `message.usage` on parent `assistant` lines **plus** each subagent trace's deduped per-turn sum. Include the sidechain lines; do not substitute the parent rollup for them. |
| Just the subagent's **cost** | The trace file, priced **per turn at that turn's own `message.model` rate** (see below). The rollup carries no model and is a snapshot, so it cannot be priced. |

Two rules of thumb fall out: **never sum `totalTokens`** (use it only as an explicitly labeled, approximate context-size reading), and **never price `toolUseResult.usage`** (it is one turn). When some invocations have trace files and some do not (see the depth-≥2 no-rollup case under [Multi-level (nested) delegation](#multi-level-nested-delegation)), report coverage alongside the number rather than silently blending real per-turn sums with snapshots.

### Context size is a trace-only measure

Since `totalTokens` is a single turn's usage, it is tempting to read it as "how big did this subagent's context get." That works only when the snapshotted turn is the run's **final** turn, which holds in 582/691 (84.2%) of cases. Because the Messages API re-sends the whole history each turn, context grows monotonically, so the final turn holds the **peak** context. In the other ~16%, `totalTokens` snapshots an **earlier, smaller** turn and therefore **understates** the peak, with no way to correct for it (the mechanism selecting the snapshotted turn is not characterized).

For a reliable context-size figure, read the trace directly. Take the final deduped turn and sum its **input-side** buckets:

```
peak context ≈ last_turn.input_tokens
             + last_turn.cache_creation_input_tokens
             + last_turn.cache_read_input_tokens
```

`output_tokens` is generated, not read, so exclude it if you want "context the model saw"; include it for "final turn total processed" (which is what `totalTokens` approximates). If a run might compact or have its context edited mid-run — rare in short subagent runs — take the **max** input-side sum across all deduped turns rather than assuming the last turn is largest.

### The rollup carries no model — and is a snapshot anyway

Even setting the snapshot problem aside, the parent rollup could not price a subagent on its own: `toolUseResult.usage` records token counts and `service_tier` but **not the model the subagent ran on**. The rollup's keys are `cache_creation, cache_creation_input_tokens, cache_read_input_tokens, inference_geo, input_tokens, iterations, output_tokens, server_tool_use, service_tier, speed` — every cost-relevant field except the model. The model lives **solely** on the subagent's per-turn `assistant` lines, in `message.model`, inside the trace file.

So the rollup fails cost on two independent counts: it is a single turn (undercounts the quantity, per the sections above), **and** it names no model (can't price whatever quantity it does hold). Correct cost is computed **per turn, at each turn's own `message.model` rate**, from the trace, because a subagent can run on a different model than its parent (the `anatomy-*` fixtures show an Opus parent delegating to a Sonnet subagent) or, in principle, on more than one model across its turns.

A blended session rate does not rescue this. It misattributes a cheaper subagent's tokens to the parent's rate, and a rate derived from a cache-inflated token denominator is itself diluted (cache reads cost ~0.1x but count at full token weight). Per-turn, per-model pricing is the only thing that fixes both the quantity and the rate. This is also the structural reason the rollup stops short: a snapshot of one turn never carried the per-turn model-and-usage split that pricing needs. `service_tier` survives as a single scalar only because the format treats it as summarizable to one value, an approximation exact only if the tier held across every turn. Both assumptions (that a Claude Code subagent ever switches model mid-run, and that `service_tier` is invariant across its turns) are inferred, not fixture-confirmed; see [Open verification items](#open-verification-items).

The same caveats from [`data-dictionary.md` § Common pitfalls in cost computation](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/data-dictionary.md#common-pitfalls-in-cost-computation) apply: model identity (`message.model`) is needed for cost; `service_tier` affects pricing; cache reads and cache creation are billed differently from regular input tokens. For an **authoritative** cross-check, the [Usage & Cost Admin API](https://platform.claude.com/docs/en/manage-claude/usage-cost-api) returns real billed spend per workspace; Anthropic states the client-side `costUSD`/`total_cost_usd` figures are estimates. Reconciling a log-derived total against that report is the strongest available validation of any cost figure derived from these files.

---

## Cross-references

| Doc | What's there |
|---|---|
| [`data-dictionary.md`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/data-dictionary.md) | Field-level reference for every message type and content block — the source of truth for field semantics. The [Subagent traces](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/data-dictionary.md#subagent-traces) section is the brief; this doc is the depth. |
| [`tool-invocation.md`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/tool-invocation.md) | The full `Agent` tool walkthrough: how the parent invokes a subagent, the `tool_use` → `tool_result` cycle, the `toolUseResult` envelope from the parent's perspective. |
| [`anatomy-agent-invocation.jsonl`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/fixtures/synthetic/anatomy-agent-invocation.jsonl) | Parent-side fixture: three lines showing prompt → `Agent` tool_use → `tool_result` + `toolUseResult` envelope. Synthetic. |
| [`anatomy-subagent-trace.jsonl`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/fixtures/synthetic/anatomy-subagent-trace.jsonl) | Subagent-side fixture pairing with the above. Four lines showing the initial prompt, the subagent's first `assistant` turn, its tool result, and its final `assistant` turn. |

---

## Open verification items

Tracked here in plain view rather than in a separate TODO file, so any reader who hits these gaps can see the same caveats:

1. **Agent SDK subagent file layout, nesting, and field semantics** — Agent SDK probes (Python SDK 0.2.106 / CLI 2.1.185, 2026-06-22) confirmed both **single-level** and **multi-level** SDK delegation reuse the Claude Code layout and `agentId` linkage, that nested delegation records a **flat** `subagents/` directory, and that the SDK **shares one `sessionId` across all levels** (a divergence from Claude Code) — see [Agent SDK parity](#agent-sdk-parity). Those are no longer open. Still unverified: attribution-field placement under MCP routing, the set of `type` values in richer SDK runs, the exact `totalTokens` cross-level inclusivity rule, and the **TypeScript SDK** throughout. Re-verify as TS-SDK and MCP-bearing session files become available.

2. **Claude Code nesting above depth 2** — nested Claude Code subagents are confirmed (v2.1.172 onward; see [Nesting](#nesting)), but the deepest run observed in the v2.1.109–v2.1.233 corpus is **depth 2**, on 6 manifests. Neither the "5 levels" cap announced at v2.1.172 nor the "depth 3" default announced at v2.1.217/v2.1.219 has been seen exercised, and the two announcements contradict each other. Three sub-questions stay open until a depth-3+ Claude Code session is captured: whether the flat layout still holds at depth 3+ (expected, but only depth 2 is observed), whether the `toolUseResult` rollup still appears at depth 3+ (it does at depth 2, unlike the SDK), and what the effective default cap actually is. `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH` is the documented control either way.

3. **Claude Code `parentAgentId` rollout** — the key appears on 1 of 1,235 manifests scanned, at v2.1.226, and never as a line-level field. The TS SDK announced a line-level `parent_agent_id` at v0.3.202. Whether Claude Code is mid-rollout of the same field or simply does not carry it is unresolved; a single occurrence at one of the newest versions in the corpus is suggestive but not conclusive. Re-check on a later scan. If it does land on trace lines, it replaces the cross-file `toolUseId` join with a direct pointer.
4. **`attributionMcpServer`/`attributionMcpTool` precise trigger condition** — observed on a subset of assistant lines in MCP-using subagent flows. Whether they appear specifically on the assistant line that emits an MCP `tool_use`, on the line that follows an MCP `tool_result`, or on both, is not yet disambiguated. See [When attributionMcpServer/attributionMcpTool appear](#when-attributionmcpserverattributionmcptool-appear).
5. **`attributionSkill` precise trigger condition and value space** — confirmed present on both subagent-trace and main-session assistant lines (so it is not a sidechain marker; see [Attribution fields](#attribution-fields)). Which turns within a Skill's execution carry it, and whether its value space is a closed vocabulary, are not yet characterized. The value (a Skill name) was not read by the observational scan.
6. ~~**`meta.json` `toolUseId` → parent cross-file match**~~ — **resolved 2026-08-15.** The 2026-08-15 scan performed the join in-memory across the whole corpus and every one of the 453 manifests carrying both a `spawnDepth` and a `toolUseId` matched exactly one `tool_result` block, with zero unmatched. Depth-1 manifests matched into the main session transcript (449 of 449) and depth-2 manifests into the spawning subagent's own trace (6 of 6). The linkage is machine-verified and can be treated as guaranteed. (The scan used the id only as a join key and did not emit it, per the scanner's content-free contract.)

7. **Whether a subagent's `model` or `service_tier` ever varies mid-run** — the [Token accounting](#token-accounting) note that a single rollup `model` field would be insufficient rests on a subagent taking turns on more than one model; the claim that the rollup's single `service_tier` is exact rests on the tier holding across all turns. Both are structurally possible to violate (model switching mid-session is documented, and the API can change service tier per request), but every trace fixture observed to date runs on a single model and a single tier. Confirm against a real multi-model or tier-fallback subagent run, or construct a synthetic fixture, before treating either as more than inferred. The two halves are tracked separately: the model-switch question (can one subagent invocation span more than one model?) in [issue #138](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/138), and the `service_tier`-stability question in [issue #137](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/137) (the leading hypothesis being that the API holds a single tier across an invocation, so a priority→standard fallback prices all of that subagent's turns at standard). Until resolved, the rollup is safe for token accounting regardless; only the cost interpretation depends on these.

Each of these is the kind of detail the format-watch skill can pick up incrementally; this section is the durable place to track them until they're resolved.
