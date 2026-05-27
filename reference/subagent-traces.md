# Subagent traces

When the parent session invokes the `Agent` tool, the subagent's complete internal trace is written to a **separate JSONL file**, not inlined in the parent session. This document covers that file: where it lives, how it links back to the parent, what its lines look like, and the gotchas that follow from the split.

For the field-level union across all message types, see [`data-dictionary.md`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/data-dictionary.md). For the parent-side `Agent` tool walkthrough (the `tool_use`, the `tool_result`, and the `toolUseResult` envelope as the parent sees them), see [`tool-invocation.md`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/tool-invocation.md). This doc starts where that one leaves off — inside the subagent trace file itself.

**Runtime scope.** Verification in this doc is against the **Claude Code** runtime (v2.1.150). The Agent SDK (Python and TypeScript) writes session files in the same JSONL format but may exercise it differently — most notably, Claude Code restricts subagents from invoking further subagents, while the Agent SDK may permit nested subagent invocations. Several sections below note where this distinction matters. Sections will be updated with Agent SDK verification once representative session files are available to sample.

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

**Verified against Claude Code v2.1.150.**

Subagent trace files sit under a session-uuid-named subdirectory alongside the parent session JSONL:

```
~/.claude/projects/<slug>/
├── <session-uuid>.jsonl                              # parent session
└── <session-uuid>/
    └── subagents/
        ├── agent-<agentId-1>.jsonl                   # one file per subagent invocation
        ├── agent-<agentId-2>.jsonl
        └── agent-<agentId-N>.jsonl
```

| Path component | Semantics |
|---|---|
| `~/.claude/projects/<slug>/` | Same project root as the parent session. `<slug>` is the slugified `cwd` (see [`data-dictionary.md` § File location](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/data-dictionary.md#file-location)). |
| `<session-uuid>/` | A sibling directory to `<session-uuid>.jsonl`. Created lazily — exists only if the session invoked at least one subagent. |
| `subagents/` | The single subagent-files directory for the session. |
| `agent-<agentId>.jsonl` | One file per subagent invocation. The `<agentId>` segment in the file name is the same UUID that appears in the parent's `toolUseResult.agentId` on the `user` line that carried the subagent's `tool_result`. |

A subagent **invocation** (one `Agent` `tool_use` from the parent) maps to exactly one file. If the parent invokes the same `subagent_type` multiple times in the same session, you get multiple files — one per invocation, each with its own `agentId`.

### Nesting

**Claude Code (v2.1.150) restricts subagents from invoking further subagents.** As a result, every subagent invocation in a Claude Code session originates from the parent session, and every subagent trace file lives directly under `<session-uuid>/subagents/`. The "flat" layout you see in a Claude Code project is therefore a consequence of the runtime restriction, not a layout choice — there is no nesting in Claude Code because there is no nested invocation.

The **Agent SDK**, which writes session files in the same JSONL format, may permit subagents to invoke further subagents — the Claude Code restriction is a property of that runtime, not of the JSONL format itself. Whether nested Agent SDK invocations produce:

- A flat `subagents/` directory containing every subagent in the call tree (with the tree reconstructed from `agentId` relationships), or
- A nested layout such as `<session-uuid>/subagents/<agentId>/subagents/<sub-agentId>.jsonl`, or
- Some other arrangement,

is **not yet verified in this reference**. Until Agent SDK session files are available for sampling, treat the flat-layout description above as Claude Code-specific. The recommended posture for tooling that needs to handle both runtimes: walk the directory structure rather than assuming a fixed depth, and use `agentId` linkages to reconstruct the call tree from data, not from path shape.

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

There is **no per-line field on subagent lines that points at the parent's session UUID or the parent's invoking `assistant` `uuid`.** The reverse linkage is reconstructed entirely from the file system: the subagent file lives at `~/.claude/projects/<slug>/<session-uuid>/subagents/agent-<agentId>.jsonl`, and `<session-uuid>` is the parent's sessionId.

Importantly, **`sessionId` is NOT shared between parent and subagent in Claude Code.** Each subagent invocation has its **own** sessionId — distinct from the parent's. The subagent files in a parent's `subagents/` subdirectory have their own sessionIds, and the parent's sessionId appears only as the *directory name* containing them. Whether the Agent SDK follows the same convention is not yet verified.

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
| `promptId` | ❌ never | ✅ always | ❌ never | An identifier for the prompt-flow this user line participates in. Stable across user lines of a single subagent invocation. |
| `sourceToolAssistantUUID` | ❌ never | ✅ on tool_result user lines (not the initial prompt) | ❌ never | The `uuid` of the same-file `assistant` line whose `tool_use` this user line is the result for. See [Parent ↔ subagent linkage](#parent--subagent-linkage). |

The per-line-type discipline is consistent across all observed Claude Code subagent files. A parser that needs to filter by attribution can branch on `type` first and only check the fields that apply to that type.

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

1. **Agent SDK subagent file layout, nesting, and field semantics** — Claude Code restricts subagents from invoking further subagents, so this doc's findings are necessarily limited to single-level (parent → subagent) cases produced by the Claude Code runtime. The Agent SDK may exhibit nested invocations and may differ in `sessionId` sharing, attribution-field placement, the set of `type` values, and other details. Re-verify when representative Agent SDK session files are available.
2. **`attributionMcpServer`/`attributionMcpTool` precise trigger condition** — observed on a subset of assistant lines in MCP-using subagent flows. Whether they appear specifically on the assistant line that emits an MCP `tool_use`, on the line that follows an MCP `tool_result`, or on both, is not yet disambiguated. See [When attributionMcpServer/attributionMcpTool appear](#when-attributionmcpserverattributionmcptool-appear).

Each of these is the kind of detail the format-watch skill can pick up incrementally; this section is the durable place to track them until they're resolved.
