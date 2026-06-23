# Tool Invocation

The canonical walkthrough of the `tool_use` → `tool_result` cycle in Claude Code's JSONL session format: how the pairing works, what the sibling `toolUseResult` envelope carries per tool, how the `Agent` tool differs, and how to parse error and parallel-call patterns.

This doc is the depth layer to the brief [Tool invocation pattern](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/data-dictionary.md#tool-invocation-pattern) section in [`data-dictionary.md`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/data-dictionary.md). Field-level definitions live there; this doc walks the pattern end-to-end and breaks the `toolUseResult` envelope out by tool.

Per repo convention, sections are versioned independently with a "Verified against Claude Code v<X>" header. Where a per-tool shape has not been independently re-verified beyond the union documented in [`data-dictionary.md`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/data-dictionary.md#tooluseresult-envelope), the section says so.

**Runtime scope.** Verification in this doc is against the **Claude Code** runtime (v2.1.150). The Agent SDK (Python and TypeScript) writes session files in the same JSONL format and shares the same tool invocation pattern conceptually, but exposes a different built-in tool surface and may exercise the `toolUseResult` envelope differently. Where this distinction matters for a specific tool or claim, the section notes it inline. Sections will be updated with Agent SDK verification once representative session files are available to sample.

---

## What the tool invocation pattern is

**Verified against Claude Code v2.1.150.**

Every tool call Claude Code makes — reading a file, running a shell command, delegating to a subagent, fetching a URL — is recorded in the session JSONL as a two-line cycle:

1. An **`assistant`** line carrying one or more `tool_use` content blocks inside `message.content`. Each block has a unique `id`, a `name` (the tool), and tool-specific `input`.
2. A subsequent **`user`** line carrying one or more `tool_result` content blocks inside `message.content`. Each block has a `tool_use_id` referencing the prior `tool_use.id`, plus `content` (the tool's output) and an optional `is_error` flag.

For context-bearing tools, the same user line also carries a top-level **`toolUseResult`** key — a sibling of `message`, not a child of it — with camelCase metadata about the invocation.

The pattern matters because every analytics or audit task on Claude Code sessions reduces to walking this cycle. What did the agent do? Read the `tool_use` blocks. What came back? Walk to the matching `tool_result`. How long did it take, how many tokens did it burn, what status did it return? Read the `toolUseResult` envelope. The cycle is the smallest semantically complete unit of agent activity in the format.

See the full content-block field definitions in [`data-dictionary.md`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/data-dictionary.md#content-blocks): [`tool_use`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/data-dictionary.md#tool_use), [`tool_result`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/data-dictionary.md#tool_result), and the [`toolUseResult` envelope](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/data-dictionary.md#tooluseresult-envelope).

---

## The pairing key: `tool_use_id`

**Verified against Claude Code v2.1.150.**

The load-bearing identifier is the tool-call ID:

- On the assistant side: `message.content[].id` (where `type == "tool_use"`).
- On the user side: `message.content[].tool_use_id` (where `type == "tool_result"`).

In observed v2.1.150 sessions these IDs use the `toolu_` prefix followed by a base64-style suffix. Synthetic fixtures in this repo use `toolu_synthetic_NNN` so they are visibly distinguishable from real IDs.

### Walking a session to reconstruct what happened

To rebuild the full tool history of a session:

1. Iterate the JSONL lines in file order.
2. For each `assistant` line, scan `message.content` for `tool_use` blocks. Index them by `id`.
3. For each `user` line, scan `message.content` for `tool_result` blocks. Look up the parent `tool_use` by `tool_use_id`.
4. If the user line has a top-level `toolUseResult` key, attach it to the same pairing.

A few invariants worth knowing before you build on this:

- **Order is not always strictly adjacent.** A single assistant turn may emit multiple `tool_use` blocks in one message (see [Parallel tool calls](#parallel-tool-calls)). The corresponding `tool_result` blocks may arrive in one user message or split across several.
- **Every `tool_use` should have exactly one matching `tool_result`** within the same session file. A missing pair almost always indicates an interrupted session — the cycle was never closed before the session ended.
- **`tool_use_id` is unique within a session.** It is not globally unique. Two sessions can independently mint `toolu_abc123`; correlate by `sessionId` first if you are aggregating across files.
- **Subagent traces have their own `tool_use_id` space.** A subagent's internal tool calls are recorded in `~/.claude/projects/<slug>/<session-uuid>/subagents/agent-<agentId>.jsonl`, not the parent file. The parent file only shows the `Agent` tool's `tool_use` → `tool_result` pair plus the `toolUseResult` rollup. See [The Agent tool](#the-agent-tool) and [`subagent-traces.md`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/subagent-traces.md).

---

## End-to-end example

**Verified against Claude Code v2.1.150.**

The canonical synthetic example of the cycle lives at [`anatomy-tool-use-cycle.jsonl`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/fixtures/synthetic/anatomy-tool-use-cycle.jsonl). It is three lines long and shows a `Read` tool invocation. See its [generator sidecar](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/fixtures/synthetic/anatomy-tool-use-cycle.jsonl.generator.md) for the structural points the fixture is designed to surface.

Briefly, what each line carries:

| Line | Type | What it shows |
|---|---|---|
| 1 | `user` | The plain user prompt asking about a file. `message.content` is a string. |
| 2 | `assistant` | A mixed-content response: a `text` block ("I'll read the file.") followed by a `tool_use` block invoking `Read`. `stop_reason: "tool_use"` indicates the model paused to invoke a tool, not because it finished. |
| 3 | `user` | The tool response. `message.content` is now an **array** containing one `tool_result` block. The `tool_use_id` matches the prior assistant line's `tool_use.id`. No top-level `toolUseResult` envelope, because `Read` produces minimal metadata. |

The structural surprise for readers is that **tool results live inside `user` messages, not as their own top-level type**. The data-dictionary calls this out as the format's "most counterintuitive structural detail." Any parser that filters by `type == "tool_result"` at the top level will find zero results; tool results are always nested inside `user.message.content` arrays.

---

## Common tool names

**Verified against Claude Code v2.1.150 (built-in tools); MCP pattern verified against the documented `mcp__<server>__<tool>` convention.**

Tool names are exact strings as they appear in `message.content[].name` on `assistant` `tool_use` blocks (and as keys in `toolStats` inside the `Agent` envelope). The set is **extensible** — plugins and MCP servers add tools at runtime, and new built-ins are added across Claude Code releases — so this table is descriptive, not exhaustive.

The **Agent SDK** exposes a different built-in tool surface; tools listed here are Claude Code's. SDK-specific tools (and the SDK's own subagent invocation pattern) are out of scope for this section until session files are available to verify.

### Built-in tools (Claude Code v2.1.150)

| Name | One-line semantics |
|---|---|
| `Read` | Read a file from disk. Input: `file_path` (+ optional `offset`, `limit`, `pages` for PDFs). |
| `Write` | Create or overwrite a file. Input: `file_path`, `content`. |
| `Edit` | In-place string replacement in a file. Input: `file_path`, `old_string`, `new_string`, optional `replace_all`. |
| `Bash` | Run a shell command. Input: `command`, `description`, optional `timeout`, `run_in_background`, `dangerouslyDisableSandbox`. |
| `Glob` | Filesystem pattern match. Input: `pattern`, optional `path`. |
| `Grep` | Content search across files. Input: `pattern`, optional `path`, `glob`, `output_mode`, `-i`/`-n`/`-A`/`-B`/`-C` flag equivalents. |
| `Agent` | Delegate to a subagent. Input: `subagent_type`, `description`, `prompt`. See [The Agent tool](#the-agent-tool). |
| `AskUserQuestion` | Surface a structured question/multi-choice prompt to the user. Input: a `questions` array. |
| `WebFetch` | Fetch a URL and return parsed content. Input: `url`, optional `prompt` for summarization. |
| `WebSearch` | Run a web search. Input: `query`. |
| `NotebookEdit` | Edit cells in a Jupyter notebook. Input: notebook path + cell-specific fields. |
| `ExitPlanMode` | Leave plan mode after presenting a plan. Input: `plan`. |
| `ToolSearch` | Resolve deferred tool schemas at runtime. Input: a `query` string and optional `max_results`. Returns tool schemas the harness can then invoke. |
| `EnterWorktree` / `ExitWorktree` | Move into or out of a git worktree mid-session. |
| `Monitor` | Stream events from a background process. |
| `TaskCreate` / `TaskUpdate` / `TaskList` / `TaskGet` / `TaskOutput` / `TaskStop` | Manage the session's task list. |
| `ScheduleWakeup` | Schedule a delayed wake-up in `/loop` dynamic mode. |

The above list reflects tools observable in v2.1.150 Claude Code sessions and matches the names used in the `toolStats` synthetic example at [`anatomy-agent-invocation.jsonl`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/fixtures/synthetic/anatomy-agent-invocation.jsonl). Tools that ship with specific harness modes (SDK, web) or that are added by future Claude Code releases will not appear here until re-verification.

### MCP tools

MCP server tools follow the pattern:

```
mcp__<server>__<tool>
```

where `<server>` is the MCP server name as registered in `~/.claude/settings.json` and `<tool>` is the tool name the server advertises. Examples observed in synthetic fixtures and the data-dictionary:

- `mcp__github__get_issue`
- `mcp__github__add_issue_comment`
- `mcp__github__create_pull_request`

The MCP convention is stable across Claude Code versions; the specific set of MCP tools available in a session depends entirely on the user's configured servers.

### Plugin and skill-bundled tools

Plugins (and the MCP servers they bring) can register additional tools. There is no fixed namespace beyond the MCP `mcp__*` prefix; native plugin-registered tools may use any string. Treat unknown tool names you encounter as opaque labels rather than assuming a built-in.

---

## The `toolUseResult` envelope by tool

**Verified against Claude Code v2.1.150 union table in [`data-dictionary.md`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/data-dictionary.md#tooluseresult-envelope); per-tool key subsets below are derived from that union and the AgentFluent-sourced behavior recorded in fixture generator notes. Re-verification per tool is in progress.**

The `toolUseResult` top-level key is the most information-dense surface in the format. It is **tool-dependent** — different tools populate different subsets of keys. The data-dictionary documents the union of observed keys; the tables below break the union out by tool so a parser knows what to expect for each.

Two structural rules apply across all tools:

1. **`toolUseResult` sits at the line's top level**, beside `message`, not inside `message.content`. It uses **camelCase** (the rest of the format is mostly snake_case).
2. **Not every tool populates it.** Lightweight tools (notably `Read` in many cases, and simple lookups) may omit `toolUseResult` entirely; the `tool_result.content` carries everything the parser needs. Context-bearing tools (`Agent`, `Bash`, `Edit`, `WebFetch`, etc.) always populate it.

### Read

| Key | Type | Notes |
|---|---|---|
| `type` | string | Tool-specific subtype indicator. |
| `file` / `filePath` | string | Path read. |
| `bytes` | number | Bytes read. |
| `content` | string | The file's content (also surfaced in `tool_result.content`). |
| `isImage` | boolean | `true` when the file decoded as an image (returned as a content block, not text). |

`Read` is the lightest of the file tools; in many observed sessions the entire `toolUseResult` is small or absent — the actionable data is in `tool_result.content`.

### Write

| Key | Type | Notes |
|---|---|---|
| `type` | string | Subtype indicator. |
| `file` / `filePath` | string | Path written. |
| `content` | string | Content written. |
| `structuredPatch` | object/array | The diff produced (when applicable). |
| `userModified` | boolean | Whether the user modified the file between Claude's plan and Claude's write. |

### Edit

| Key | Type | Notes |
|---|---|---|
| `type` | string | Subtype indicator. |
| `filePath` / `originalFile` | string | Path edited; pre-edit canonical path. |
| `oldString`, `newString` | string | The substitution. |
| `replaceAll` | boolean | Whether the edit was a single-occurrence replace or replace-all. |
| `structuredPatch` | object/array | The diff produced. |
| `userModified` | boolean | Whether the user modified the file between read and edit. |

`Edit` populates more of the envelope than `Read` or `Write` because it carries the diff. Tools that audit Claude's file edits (e.g., for security review) rely on `structuredPatch`.

### Bash

| Key | Type | Notes |
|---|---|---|
| `stdout` | string | Captured standard output. |
| `stderr` | string | Captured standard error. |
| `code` | number | Exit code. `0` for success, non-zero for failure. |
| `interrupted` | boolean | `true` when the command was interrupted (timeout, user cancel) before completion. |
| `noOutputExpected` | boolean | Whether the harness expected the command to produce no output. |
| `durationMs` / `durationSeconds` | number | Wall-clock duration. |

`Bash` is the most diagnostic-rich tool: the combination of `code`, `interrupted`, and `stderr` is enough to characterize most command outcomes without parsing `stdout`.

### Grep, Glob

| Key | Type | Notes |
|---|---|---|
| `query` | string | The pattern searched for. |
| `matches` | array | Match results. |
| `searchCount` | number | Number of matches. |
| `results` | array | Result entries (Glob: paths; Grep: matched lines or path+line ranges depending on `output_mode`). |

### WebFetch, WebSearch

| Key | Type | Notes |
|---|---|---|
| `url` | string | URL fetched (WebFetch). |
| `result` | string | The fetched/searched result content. |
| `durationMs` | number | Wall-clock duration. |

Per the data-dictionary's union table; per-tool re-verification still pending.

### AskUserQuestion

| Key | Type | Notes |
|---|---|---|
| `questions` | array | The structured question payload, including any multi-choice options. |
| `answers` | array | The user's structured response. |

The `questions`/`answers` shape is what differentiates `AskUserQuestion` from a free-form `user` prompt — both Claude's question and the user's response are captured as structured arrays inside `toolUseResult`, in addition to (or instead of) plain text on the next `user` line.

### Agent

The richest envelope. See [The Agent tool](#the-agent-tool) below for the dedicated walkthrough; here is the table summary:

| Key | Type | Notes |
|---|---|---|
| `status` | string | `"success"` or `"error"`. |
| `agentId` | string (UUID) | Links to the subagent trace file. |
| `agentType` | string | The `subagent_type` that ran. |
| `prompt` | string | The prompt the parent passed to the subagent. |
| `totalDurationMs` | number | Wall-clock duration of the subagent run. |
| `totalTokens` | number | Token rollup across the entire subagent run. |
| `totalToolUseCount` | number | Number of tool invocations inside the subagent. |
| `usage` | object | Token breakdown (same shape as `message.usage`). |
| `toolStats` | object | Per-tool invocation counts (e.g., `{"Read": 4, "mcp__github__get_issue": 1}`). |

### MCP tools (`mcp__<server>__<tool>`)

MCP tool result envelopes typically include `status`, `durationMs`, and tool-specific keys that depend on what the MCP server returns. Because MCP tools are user-installed, the envelope shape is not fixed by Claude Code — re-verify per server.

The union table calls out `total_deferred_tools` for tool-discovery flows (e.g., `ToolSearch` resolving deferred MCP schemas).

### Tools without a dedicated envelope

Several tools either always omit `toolUseResult` or populate only `status` and `type`. Observed examples: lightweight harness controls (`ExitPlanMode`, `EnterWorktree`/`ExitWorktree` in many cases). Their actionable result is the `tool_result.content` value.

When `toolUseResult` is absent, the cycle is still valid — `tool_use_id` pairing is the only structural requirement. The envelope is additional, not load-bearing.

---

## The Agent tool

**Verified against Claude Code v2.1.150 using [`anatomy-agent-invocation.jsonl`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/fixtures/synthetic/anatomy-agent-invocation.jsonl) and the data-dictionary's `toolUseResult` envelope table.**

The `Agent` tool is structurally identical to every other tool at the parent-session level — it's a `tool_use` followed by a `tool_result` — but it has two unusual properties that make it the most consequential tool for analytics:

1. Its `toolUseResult` envelope carries a **rollup of the entire subagent run** in a single object: total duration, total tokens, per-tool counts.
2. Its `agentId` links to a **separate JSONL trace file** that contains the subagent's full internal activity.

Claude Code restricts subagents from invoking further subagents, so the Agent tool only appears in parent sessions, not inside subagent traces. The Agent SDK may exhibit nested invocations; see [`subagent-traces.md` § Nesting](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/subagent-traces.md#nesting) for the runtime distinction.

### `tool_use.input` shape

The Agent tool's input always has three keys:

| Field | Type | Notes |
|---|---|---|
| `subagent_type` | string | The agent type to invoke (e.g., `"general-purpose"`, `"pm"`, `"code-reviewer"`). Maps to a configured subagent definition. |
| `description` | string | A short label for the invocation (used in UI and logs). |
| `prompt` | string | The actual prompt passed to the subagent. |

This is the only signal in the parent session of **what the parent asked the subagent to do**. Tools that audit subagent quality (e.g., AgentFluent) read this string alongside the subagent's trace to evaluate task → result fidelity.

### `tool_result.content`

A summary string returned by the subagent at the end of its run. This is whatever the subagent's final assistant message said — typically a short report on what it accomplished. For deeper detail (every tool call, every reasoning step), open the subagent trace file.

### `toolUseResult` rollup

See [Agent](#agent) in the envelope table above. The envelope is the parent's window into the subagent's run:

- `agentId` — the link to the trace file at `~/.claude/projects/<slug>/<session-uuid>/subagents/agent-<agentId>.jsonl`.
- `agentType`, `prompt` — echo of the `tool_use.input` for convenient correlation without re-walking the assistant line.
- `totalDurationMs`, `totalTokens`, `totalToolUseCount` — bulk rollup numbers. `totalToolUseCount` is the subagent's **own-direct** count, not cumulative across any further subagents it spawned.
- `usage` — token breakdown in the same shape as `message.usage` (see [Usage and token accounting](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/data-dictionary.md#usage-and-token-accounting)).
- `toolStats` — a `{tool_name: count}` object summarizing what the subagent did. The single most useful field for "what did this subagent actually do" analytics.

**Multi-level caveat (Agent SDK).** This whole `toolUseResult` rollup is present only on **first-level** subagent results. When a subagent itself delegates (possible in the Agent SDK, not in Claude Code), the deeper `Agent` `tool_result` carries no `toolUseResult` — only an inline `subagent_tokens: <N>` trailer — so a depth-≥2 subagent's rollup numbers must come from its own trace. See [`subagent-traces.md` § Multi-level (nested) delegation](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/subagent-traces.md#multi-level-nested-delegation).

### The link to the subagent trace file

When the parent line carries `toolUseResult.agentId == "X"`, the file at:

```
~/.claude/projects/<slug>/<session-uuid>/subagents/agent-X.jsonl
```

contains the complete subagent trace. Every line in that file carries `isSidechain: true` — the canonical signal you are reading a subagent trace rather than a parent session.

For the structure of that file — `attributionAgent`, `sourceToolAssistantUUID`, the per-line-type attribution pattern, what fields propagate vs. reset across invocation boundaries — see [`subagent-traces.md`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/subagent-traces.md).

### Double-counting hazard

The subagent's tokens appear in **both** the subagent trace file (on each interior `assistant` line) and the parent session's `toolUseResult.usage`. A naive sum that walks every JSONL file in `~/.claude/projects/<slug>/` will double-count subagent tokens. Use one or the other, not both. The data-dictionary's [cost-computation pitfalls](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/data-dictionary.md#common-pitfalls-in-cost-computation) section covers this; it shows up here because the `toolUseResult` rollup is the surface most likely to trip an aggregator.

---

## Error patterns

**Verified against Claude Code v2.1.150; per-tool error fixtures are forthcoming.**

Tool failures are represented at two levels:

1. **The `tool_result` block** carries an optional `is_error` boolean. `true` indicates the tool reported an error. Absent or `false` on the happy path.
2. **The `toolUseResult` envelope** may carry a tool-specific status field. For most tools this is `status` (`"success"` or `"error"`). For `Bash`, additional signals include:
   - `code != 0` — non-zero exit status.
   - `interrupted: true` — command was killed (timeout or user cancel) before completing.
   - `stderr` non-empty — command emitted error output (not necessarily a failure, but worth surfacing).

### Failures vs. partial successes

Some tools return useful partial output even when `is_error: true`. `Bash` is the canonical case: a command can exit non-zero, produce useful `stderr` (which the model can read and react to), and still leave `stdout` populated. Parsers that treat `is_error == true` as "throw away the output" lose information.

The rule: `is_error` indicates the tool's self-reported error status; the *content* of the result still has to be inspected to know what actually happened.

### Interruption

`Bash` (and any long-running tool that supports cancellation) records interruption via `toolUseResult.interrupted: true`. The `tool_result.content` may still contain partial output captured before the interruption.

A session can also end mid-cycle — an assistant `tool_use` block with no matching `tool_result` in the file. This is structurally an "incomplete cycle" rather than a tool error per se; treat it as a session-level interruption rather than a tool failure.

---

## Parallel tool calls

**Verified against Claude Code v2.1.150.**

A single assistant turn may emit **multiple `tool_use` blocks** in one `message.content` array. The model is opting to invoke several tools in parallel, and the harness will execute them and return all results before the next assistant turn.

Two patterns observed:

1. **All results in one user message.** The next `user` line's `message.content` array contains multiple `tool_result` blocks, one per `tool_use_id`. The data-dictionary's [`tool_result`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/data-dictionary.md#tool_result) section covers the per-block shape.
2. **Results split across user messages.** Less common, but observed when the harness streams results back as each tool finishes. The pairing remains intact via `tool_use_id`; parsers should not assume "one assistant tool turn → one user response line."

To detect parallel tool calls in a session, count `tool_use` blocks per `assistant` line:

```
length(.message.content | map(select(.type == "tool_use")))
```

Any value greater than 1 is a parallel turn.

Parallel invocations matter for analytics because **per-tool durations are not strictly comparable across parallel and serial tools**. A serial sequence of three `Read` calls takes ~3× as long as one. A parallel batch of three `Read` calls takes ~1× as long. Either case shows up as `toolStats: {"Read": 3}` inside a subagent envelope. If you care about wall-clock characterization, you have to distinguish them by walking the assistant content arrays.

---

## Tool stats for analysis

**Verified against Claude Code v2.1.150.**

Two fields are load-bearing for any analytics that wants to characterize what a session did:

- **`tool_use.name`** — the tool name string on each invocation. Aggregating these (e.g., counting per name across an entire session) tells you what the agent reached for.
- **`toolUseResult.toolStats`** — pre-computed per-tool counts inside `Agent` invocations. Saves you from re-walking the subagent's trace file just to characterize what it did. The single most useful field for subagent-fluency analytics.

Both fields use the same exact-string tool names (`Read`, `Bash`, `mcp__github__get_issue`, etc.). They join cleanly: if you keep a per-session tool-name histogram and want to differentiate "the main agent did this" from "a subagent did this," compare `tool_use.name` aggregation in the parent file against `toolStats` rollups inside Agent envelopes.

A simple jq idiom for the parent-session histogram:

```bash
jq -r 'select(.type == "assistant") | .message.content[]? | select(.type == "tool_use") | .name' "$F" | sort | uniq -c | sort -rn
```

For subagent rollups (per-Agent-call):

```bash
jq 'select(.toolUseResult.toolStats) | .toolUseResult.toolStats' "$F"
```

Sibling project [AgentFluent](https://github.com/frederick-douglas-pearce/agentfluent) uses both shapes for its agent-quality diagnostics.

---

## Cross-references

- **Field-level definitions:** [`data-dictionary.md`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/data-dictionary.md) — every field on `tool_use`, `tool_result`, and the `toolUseResult` envelope union.
- **Subagent trace files:** [`subagent-traces.md`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/subagent-traces.md) — the file at `~/.claude/projects/<slug>/<session-uuid>/subagents/agent-<agentId>.jsonl`, the `isSidechain: true` invariant, and `attributionAgent` / `sourceToolAssistantUUID` linkages.
- **Synthetic fixtures used in this doc:**
  - [`anatomy-tool-use-cycle.jsonl`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/fixtures/synthetic/anatomy-tool-use-cycle.jsonl) — the basic Read cycle.
  - [`anatomy-agent-invocation.jsonl`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/fixtures/synthetic/anatomy-agent-invocation.jsonl) — the Agent tool invocation with full `toolUseResult` envelope.
  - [`anatomy-subagent-trace.jsonl`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/fixtures/synthetic/anatomy-subagent-trace.jsonl) — the subagent-side companion to the Agent invocation fixture.
- **Format version history:** When [`format-version-history.md`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/format-version-history.md) is created, per-tool envelope changes (key additions, renames, removals) will be tracked there. Until then, version-specific shifts are captured inline in the sections above when noticed.
