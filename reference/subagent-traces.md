# Subagent traces

When the parent session invokes the `Agent` tool, the subagent's complete internal trace is written to a **separate JSONL file**, not inlined in the parent session. This document covers that file: where it lives, how it links back to the parent, what its lines look like, and the gotchas that follow from the split.

For the field-level union across all message types, see [`data-dictionary.md`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/data-dictionary.md). For the parent-side `Agent` tool walkthrough (the `tool_use`, the `tool_result`, and the `toolUseResult` envelope as the parent sees them), see [`tool-invocation.md`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/tool-invocation.md). This doc starts where that one leaves off — inside the subagent trace file itself.

**Runtime scope.** Verification in this doc is against the **Claude Code** runtime (v2.1.150). The Agent SDK (Python and TypeScript) writes session files in the same JSONL format but may exercise it differently — most notably, Claude Code restricts subagents from invoking further subagents, while the Agent SDK permits nested subagent invocations. Several sections below note where this distinction matters. Agent SDK probes (Python SDK 0.2.106 / CLI 2.1.185) have now confirmed that both **single-level** and **multi-level** SDK delegation reuse the Claude Code layout and linkage, that nested delegation records a **flat** `subagents/` directory (no nested sub-directories), and that the SDK shares one `sessionId` across all nesting levels — see [Agent SDK parity](#agent-sdk-parity). The TypeScript SDK remains unverified.

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

**Verified against Claude Code v2.1.150.** Key set confirmed by observational scan over 563 `agent-<id>.meta.json` files spanning v2.1.4–v2.1.170 — key names and value *types* only; no values read.

Beside every `agent-<agentId>.jsonl` trace sits a small `agent-<agentId>.meta.json` (tens to a few hundred bytes) — a manifest that lets Claude Code, and your own tooling, enumerate and route subagents without opening and parsing the full trace. All observed keys are string-valued:

| Key | Present on | What it is |
|---|---|---|
| `agentType` | every manifest (563/563) | The subagent type that ran (`"general-purpose"`, `"pm"`, a custom agent name). Same value as `attributionAgent` in the trace and `toolUseResult.agentType` on the parent. |
| `description` | most (546/563) | The human-readable task description from the parent's `Agent` call. |
| `toolUseId` | when present (256/563) | The id of the parent `Agent` `tool_use` that spawned this run. See the casing note below. |
| `worktreePath` | rarely (10/563) | Filesystem path of the git worktree the subagent ran in, present only for worktree-isolated runs. |

**`toolUseId` is the one part of the subagent → parent relationship carried in data rather than inferred from disk location.** The trace lines themselves carry no field naming the parent (see [Parent ↔ subagent linkage](#parent--subagent-linkage)); the manifest's `toolUseId` names the exact parent `tool_use` the run answers. Note it sits *beside* the trace, not inside it.

**Casing wrinkle.** The manifest spells this key `toolUseId` (lowercase `d`), while session and trace lines spell the analogous id `toolUseID` (uppercase `D`). Same kind of value, different casing, in files that sit next to each other — a parser reading both must handle both spellings.

### Spilled tool results

**Verified against Claude Code v2.1.150.** Directory presence, file-size band, and the in-content wrapper were confirmed by the observational scan (89 spilled files across 40 sessions).

Alongside `subagents/`, a session often grows a `tool-results/` directory. It is **not** subagent-specific: it holds *large* tool outputs that would otherwise bloat a single JSONL line. When a tool result is big, the in-session `tool_result` content carries a `<persisted-output>` wrapper with a truncated preview, and the full payload lands in `tool-results/`, named after the tool call that produced it (`<tool-use-id>.txt` or `.json`). Observed spilled files ranged from ~20 KB to ~860 KB (median ~64 KB), implying a spill threshold near 20 KB. The in-JSONL reference is that plain-text `<persisted-output>` wrapper inside `tool_result.content` — **not** a dedicated JSON pointer key (the scan's tool_result-line key set carries no spill-pointer field).

This is a tool-invocation concern, not a subagent one; it is documented in full in [`tool-invocation.md`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/tool-invocation.md). It appears here only so the `<session-uuid>/` directory listing makes sense.

### Nesting

**Claude Code (v2.1.150) restricts subagents from invoking further subagents.** As a result, every subagent invocation in a Claude Code session originates from the parent session, and every subagent trace file lives directly under `<session-uuid>/subagents/`. The "flat" layout you see in a Claude Code project is therefore a consequence of the runtime restriction, not a layout choice — there is no nesting in Claude Code because there is no nested invocation.

The **Agent SDK**, which writes session files in the same JSONL format, *does* permit subagents to invoke further subagents — the Claude Code restriction is a property of that runtime, not of the JSONL format itself. An Agent SDK probe that forced a two-level chain (`main → delegator → leaf`, Python SDK 0.2.106 / CLI 2.1.185, 2026-06-22) settled what that produces on disk: **a flat layout.** Every subagent, at every depth, is written as a sibling file directly under the single `<session-uuid>/subagents/` directory:

```
<session-uuid>/subagents/
├── agent-<delegatorId>.jsonl        # level 1
├── agent-<delegatorId>.meta.json
├── agent-<leafId>.jsonl             # level 2 — SAME directory, not nested
└── agent-<leafId>.meta.json
```

There are **no** nested `subagents/<agentId>/subagents/…` directories — a deeper call chain just yields more siblings in the same folder. The directory shape therefore carries **no depth or parent information**: the call tree must be reconstructed from the data (see [Reconstructing a multi-level call tree](#reconstructing-a-multi-level-call-tree)). This confirms the recommended posture for tooling that must handle both runtimes — **walk the flat `subagents/` directory and reconstruct the call tree from `toolUseId`/`agentId` linkages, never from path shape.** The TypeScript SDK is not yet sampled, but the format is shared; treat the flat layout as the expected arrangement until shown otherwise.

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

This **partially closes** the long-standing open gap on Agent SDK nested invocations: single-level delegation is now confirmed to reuse the Claude Code layout and linkage. The probe used a *pure* SDK agent (no MCP, no inherited settings) over one delegation level, so the attribution-field placement under MCP routing, the set of `type` values in richer runs, `sessionId` sharing, and **multi-level nesting** remain unverified. The recommended posture from [Nesting](#nesting) stands: walk the directory structure and reconstruct the call tree from `agentId` linkages rather than assuming a fixed depth.

The SDK parent-side envelope is shown in [`agent-sdk-invocation.jsonl`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/fixtures/synthetic/agent-sdk-invocation.jsonl); the Claude Code child-trace shape it pairs with is [`anatomy-subagent-trace.jsonl`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/fixtures/synthetic/anatomy-subagent-trace.jsonl) (the probe confirmed the SDK child trace matches that shape, plus the `entrypoint: "sdk-py"` marker).

### Multi-level (nested) delegation

The Agent SDK lets a subagent invoke its own subagent — a layout **unobservable in Claude Code**, which forbids it. A probe that forced `main → delegator → leaf` pinned down four things beyond the single-level parity above:

1. **The layout is flat (no nested directories).** Every subagent at every depth is a sibling under the one `<session-uuid>/subagents/` directory — see [Nesting](#nesting). `sessionId` is the same across all levels (the SDK shares the main session's id; see the [`sessionId` note](#parent--subagent-linkage) for the contrast with Claude Code), and `entrypoint: "sdk-py"` is carried throughout.

2. **Parent linkage is by-data, not by-path.** Because the directory is flat, the only thing that says which agent spawned which is the `toolUseId` in each subagent's `.meta.json` sidecar — and that id names a `tool_use` block that lives in the *spawning agent's* trace, which at depth ≥ 2 is **another subagent file, not the main session.** See [Reconstructing a multi-level call tree](#reconstructing-a-multi-level-call-tree).

3. **The `toolUseResult` rollup is top-level only.** The rich rollup envelope (`totalTokens`, `totalToolUseCount`, `resolvedModel`, `toolStats`, …) is attached only on the **main session's** `user` line carrying a *level-1* result. At depth ≥ 2 the spawning `Agent` `tool_result` block carries **no** `toolUseResult` sibling — only an inline `subagent_tokens: <N>` text trailer in the result content. Metrics for a depth-≥2 subagent must be derived from that subagent's own trace (or the trailer), not read off a parent envelope the way level-1 metrics can.

   | Spawn | Where its `tool_result` lives | `toolUseResult`? |
   |---|---|---|
   | main → delegator (level 1) | main `<session-uuid>.jsonl` | **yes** (full rollup) |
   | delegator → leaf (level 2) | `agent-<delegatorId>.jsonl` | **no** (only a `subagent_tokens` trailer) |

4. **Counter/token semantics.** `totalToolUseCount` is **own-direct, not cumulative** — a delegator reported only the tool calls it made itself (including its own `Agent` call) and **excluded** the leaf's tool calls. `totalTokens` reads as directionally inclusive of descendants but does **not** equal a raw sum of per-turn `message.usage` (cache accounting differs); settle the exact inclusivity rule against real bytes before summing across levels, or a multi-level aggregator will double-count. `resolvedModel` reports the **child's** resolved model, not the parent's — in a sonnet-parent / haiku-child run it read `claude-haiku-4-5-20251001`.

### Reconstructing a multi-level call tree

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
- **Skip them** when aggregating per-session tokens *if* you are also reading `toolUseResult.usage` from the parent (otherwise you double-count — see [Token accounting](#token-accounting) below).
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

The one in-data exception sits *beside* the trace, not inside it: the `agent-<agentId>.meta.json` manifest records the parent `Agent` `tool_use` id as `toolUseId` (see [The `meta.json` manifest](#the-metajson-manifest)). That names the exact parent `tool_use` the run answers — a link the trace lines alone don't carry. So a precise statement is: the trace *lines* carry only the forward `agentId`; the reverse pointer lives in the manifest sidecar and the directory path, not in the trace's line data. In a **multi-level** SDK chain, that `toolUseId` may point at a `tool_use` emitted in *another subagent's* trace rather than the main session — so resolving it requires indexing tool-use ids across every file, not just the parent session (see [Reconstructing a multi-level call tree](#reconstructing-a-multi-level-call-tree)).

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
| Token data | `toolUseResult.usage` (cumulative across the subagent run) and `toolUseResult.totalTokens` (single scalar) | Per-`assistant`-line `message.usage` (one object per model turn) |
| Tool data | `toolUseResult.toolStats` (per-tool *counts*, e.g., `{"Read": 4, "Bash": 2}`) | Every `tool_use`/`tool_result` pair, with full `input` and `content` |
| Duration | `toolUseResult.totalDurationMs` (single scalar) | Per-line `timestamp`s; derive durations by diff |
| Final output | `tool_result.content` — the subagent's final summary as a string | The same final summary appears as the last `assistant` `text` block; the entire reasoning that produced it is also present |
| Reasoning | Not present | `thinking` blocks on `assistant` lines (when extended thinking is enabled) |
| Intermediate text | Not present | All `assistant` `text` blocks across all turns |

The pattern: **`toolUseResult` is what the parent agent and its model see; the subagent file is what an analytics tool sees if it cares about how the subagent actually behaved.** AgentFluent's diagnostics and CodeFluent's coaching both need the per-step view; the parent envelope alone is too coarse.

This is also why most simple parsers stop at the parent envelope and treat the subagent's existence as a single tool call. The data is there if you want it — it just lives in a different file.

---

## Token accounting

**Verified against Claude Code v2.1.150.**

Subagent token usage is reported in **two places** for the same activity:

1. On each `assistant` line **inside** the subagent trace file, in `message.usage` (one entry per model turn the subagent took).
2. In the parent session, in `toolUseResult.usage` and `toolUseResult.totalTokens` on the `user` line that carried the subagent's `tool_result` (rolled up across the entire subagent run).

These are the **same tokens, reported twice**. Naive aggregation that sums both sources will double-count.

### Aggregation patterns

| You want… | Use |
|---|---|
| Total session token consumption (cheap, no subagent-file IO) | Parent session only: sum `message.usage` on parent `assistant` lines + sum `toolUseResult.usage` on parent `user` lines for tool results that carry it. |
| Total session token consumption (with subagent breakdown) | Parent session lines + each subagent file's per-line `message.usage` — **but exclude** the `toolUseResult.usage` rollup on the parent line for that subagent (to avoid double-counting). |
| Just the subagent's cost | Each subagent file's per-line `message.usage` summed; OR equivalently, the parent's `toolUseResult.usage` for that subagent. They should match. |

The same caveats from [`data-dictionary.md` § Common pitfalls in cost computation](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/data-dictionary.md#common-pitfalls-in-cost-computation) apply: model identity (`message.model`) is needed for cost; `service_tier` affects pricing; cache reads and cache creation are billed differently from regular input tokens.

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

1. **Agent SDK subagent file layout, nesting, and field semantics** — Claude Code restricts subagents from invoking further subagents, so this doc's Claude Code findings are limited to single-level (parent → subagent) cases. Agent SDK probes (Python SDK 0.2.106 / CLI 2.1.185, 2026-06-22) confirmed both **single-level** and **multi-level** SDK delegation reuse the Claude Code layout and `agentId` linkage, that nested delegation records a **flat** `subagents/` directory, and that the SDK **shares one `sessionId` across all levels** (a divergence from Claude Code) — see [Agent SDK parity](#agent-sdk-parity). Those are no longer open. Still unverified: attribution-field placement under MCP routing, the set of `type` values in richer SDK runs, the exact `totalTokens` cross-level inclusivity rule, and the **TypeScript SDK** throughout. Re-verify as TS-SDK and MCP-bearing session files become available.
2. **`attributionMcpServer`/`attributionMcpTool` precise trigger condition** — observed on a subset of assistant lines in MCP-using subagent flows. Whether they appear specifically on the assistant line that emits an MCP `tool_use`, on the line that follows an MCP `tool_result`, or on both, is not yet disambiguated. See [When attributionMcpServer/attributionMcpTool appear](#when-attributionmcpserverattributionmcptool-appear).
3. **`attributionSkill` precise trigger condition and value space** — confirmed present on both subagent-trace and main-session assistant lines (so it is not a sidechain marker; see [Attribution fields](#attribution-fields)). Which turns within a Skill's execution carry it, and whether its value space is a closed vocabulary, are not yet characterized. The value (a Skill name) was not read by the observational scan.
4. **`meta.json` `toolUseId` → parent cross-file match** — the manifest key `toolUseId` is documented from its name and the F-002 recon as the spawning parent `Agent` `tool_use` id; the scan confirmed the key's presence and string type but did not read the value (a tool-use id), so the exact cross-file match to the parent line was not machine-verified here. Confirm against a synthetic fixture before treating the linkage as guaranteed.

Each of these is the kind of detail the format-watch skill can pick up incrementally; this section is the durable place to track them until they're resolved.
