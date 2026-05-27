# Data Dictionary

The canonical field-level reference for Claude Code's JSONL session format. Each section describes a message type or sub-structure and lists every observed field with its type, semantics, and any version-specific notes.

Reference docs are versioned **per section**, not per document — a single section may be verified against a different Claude Code version than its neighbors. When the format-watch skill flags a change, only the affected sections get re-verified and re-stamped.

This doc grew out of [AgentFluent's CLAUDE.md "JSONL Data Format" section](https://github.com/frederick-douglas-pearce/agentfluent/blob/main/CLAUDE.md#jsonl-data-format), with additional fields and message types observed during verification against current sessions. Where AgentFluent's notes and observed behavior diverge, observed behavior wins.

---

## File location

**Verified against Claude Code v2.1.150.**

Sessions are stored as JSONL at:

```
~/.claude/projects/<slug>/<session-uuid>.jsonl
```

| Component | What it is |
|---|---|
| `~/.claude/projects/` | Root directory for all Claude Code session data on the machine. Configurable via the `CLAUDE_CONFIG_DIR` environment variable. |
| `<slug>` | Derived from the working directory path at session start. Slashes are replaced with dashes, and the leading slash becomes a leading dash. Example: `/home/user/myproject` → `-home-user-myproject`. |
| `<session-uuid>.jsonl` | One file per session. The file name is the session UUID (also recorded as `sessionId` on every line). |

### Subagent traces

When a session invokes the `Agent` tool, the subagent's full trace is written to a separate file:

```
~/.claude/projects/<slug>/<session-uuid>/subagents/agent-<agentId>.jsonl
```

A session-uuid-named subdirectory holds one `subagents/` directory; each subagent invocation produces a single trace file. The `agentId` in the file name matches the `toolUseResult.agentId` on the parent session's user message that carried the subagent's `tool_result`. See [Subagent traces](#subagent-traces) below for the line-level shape.

### Retention

Claude Code's documentation describes a 30-day default cleanup configurable via the `cleanupPeriodDays` setting in `~/.claude/settings.json`. Observed behavior in practice may differ — see [decisions.md O001](../.claude/specs/decisions.md) for context.

---

## Common fields

**Verified against Claude Code v2.1.150.**

Some fields appear on most or all line types; others are type-specific. The table below documents fields that are observed across multiple line types — type-specific fields are documented in their respective sections below.

| Field | Type | Semantics |
|---|---|---|
| `type` | string | Discriminator for the line's shape. Values include `assistant`, `user`, `system`, `file-history-snapshot`, `attachment`, `permission-mode`, `ai-title`, `last-prompt`, `queue-operation`, and others. See [Message types](#message-types) and [Skipped types](#skipped-types). |
| `timestamp` | string (ISO 8601 UTC) | When the line was written. Present on most line types except some metadata types (e.g., `ai-title`, `last-prompt`). |
| `uuid` | string (UUID) | Per-line identifier. Unique within a session. |
| `parentUuid` | string (UUID) or `null` | Links this line to its predecessor in the conversation graph. `null` on the first line of a session. Used to reconstruct linear vs forked conversation flow. |
| `sessionId` | string (UUID) | Shared across every line in a session. The session-level key. Matches the `<session-uuid>` in the file name. |
| `isSidechain` | boolean | `true` for every line inside a subagent trace file; `false` (or absent) in parent session files. The canonical signal that you're reading a subagent trace, not a parent session. |
| `cwd` | string | Working directory at the time the line was written. Can change mid-session if the user `cd`s. |
| `version` | string | Claude Code version (e.g., `"2.1.150"`) at the time the line was written. Can change mid-session if Claude Code is updated. |
| `entrypoint` | string | How the session was started — observed values include `"claude"` (interactive CLI), but other entrypoints likely exist for the SDK and web modes. Not documented in AgentFluent's notes; added to this reference based on v2.1.150 observation. |
| `gitBranch` | string | The git branch active in `cwd` at the time the line was written. Empty string when not in a git repository. Powers the session picker's `Ctrl+B` branch filter. |
| `requestId` | string | An identifier the client uses to correlate requests with model responses. Present on `assistant` lines and some others. |
| `userType` | string | Identifies the user/runtime context — observed value `"external"` for normal CLI usage. |

Some fields documented in AgentFluent's notes (`isSidechain`, `cwd`, `version`) hold; the four above (`entrypoint`, `gitBranch`, `requestId`, `userType`) are additions observed in v2.1.150 that AgentFluent's notes do not list.

---

## Message types

### `assistant`

**Verified against Claude Code v2.1.150.**

Model responses — text, tool calls, reasoning, and token usage. Top-level fields are those listed in [Common fields](#common-fields). The `message` object carries the model-side payload:

| Field | Type | Semantics |
|---|---|---|
| `message.role` | string | Always `"assistant"`. |
| `message.id` | string | The API message ID (e.g., `"msg_..."`). Identifies the model's response at the API layer. |
| `message.type` | string | Always `"message"`. Identifies this as a message in the Anthropic API content envelope. |
| `message.model` | string | Model identifier (e.g., `"claude-sonnet-4-6"`, `"claude-opus-4-7"`). Can change mid-session if the model is switched. |
| `message.content` | array | An array of content blocks. Block types: [`text`](#text), [`tool_use`](#tool_use), [`thinking`](#thinking). A single assistant message can carry multiple blocks of different types (e.g., a `text` block followed by a `tool_use` block when the model both speaks and reaches for a tool in the same turn). |
| `message.usage` | object | Token and accounting metadata. See [Usage and token accounting](#usage-and-token-accounting). |
| `message.stop_reason` | string | Why the model stopped. Common values: `"end_turn"` (model finished), `"tool_use"` (model paused to invoke a tool). |
| `message.stop_sequence` | string \| `null` | The stop sequence that triggered termination, if any. |
| `message.stop_details` | object | Additional stop information when available (rarely populated in practice). |
| `message.diagnostics` | object | Optional diagnostic metadata. Observed sub-key: `cache_miss_reason` when a cache lookup did not hit. |

Inline minimal example (see [`anatomy-minimal-session.jsonl`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/fixtures/synthetic/anatomy-minimal-session.jsonl) for a full session):

```json
{
  "type": "assistant",
  "sessionId": "00000000-0000-0000-0000-000000000001",
  "uuid": "22222222-2222-2222-2222-222222222001",
  "parentUuid": "11111111-1111-1111-1111-111111111001",
  "timestamp": "2026-05-20T14:30:01.342Z",
  "message": {
    "id": "msg_synthetic_001",
    "type": "message",
    "role": "assistant",
    "model": "claude-sonnet-4-6",
    "content": [{"type": "text", "text": "The capital of France is Paris."}],
    "usage": {"input_tokens": 12, "output_tokens": 8, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0},
    "stop_reason": "end_turn"
  }
}
```

### `user`

**Verified against Claude Code v2.1.150.**

User prompts AND tool result envelopes. In Claude Code, tool results are not their own top-level type — they live inside `user` messages, with optional sibling metadata at the line level. This is the format's most counterintuitive structural detail.

Top-level fields are those listed in [Common fields](#common-fields). One optional top-level sibling key is significant:

| Field | Type | Semantics |
|---|---|---|
| `toolUseResult` | object (optional) | Tool invocation metadata. Present when the `user` line carries a `tool_result` block AND the underlying tool was a multi-step or context-bearing tool (Agent, Bash, etc.). Sits at the **top level**, beside `message`, not inside `message.content`. Uses camelCase field names (unusual in this otherwise mostly-snake_case format). See [`toolUseResult` envelope](#tooluseresult-envelope) below. |

Inside `message`:

| Field | Type | Semantics |
|---|---|---|
| `message.role` | string | Always `"user"`. |
| `message.content` | string OR array | Two distinct shapes — see below. |

**Two shapes of `message.content`:**

1. **String shape** — a plain user prompt. The user typed text; that text is the value.

   ```json
   {"type": "user", "message": {"role": "user", "content": "What's in src/main.py?"}}
   ```

2. **Array shape** — an array of content blocks. Most commonly contains one or more [`tool_result`](#tool_result) blocks responding to prior `tool_use` blocks from the assistant. Less commonly, may contain `text` blocks when a prompt is structured (e.g., with system context attached).

   ```json
   {
     "type": "user",
     "message": {
       "role": "user",
       "content": [
         {"type": "tool_result", "tool_use_id": "toolu_synthetic_001", "content": "def main(): ..."}
       ]
     }
   }
   ```

Parsers must handle both shapes. See [`anatomy-tool-use-cycle.jsonl`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/fixtures/synthetic/anatomy-tool-use-cycle.jsonl) for the array shape in context.

#### `toolUseResult` envelope

**Verified against Claude Code v2.1.150.**

When a `user` line carries a `tool_result` block for a context-bearing tool, an additional top-level key `toolUseResult` sits alongside `message`. This envelope contains tool-specific metadata that doesn't fit inside the standard content-block schema.

The shape is **tool-dependent** — different tools populate different keys. A union of observed keys across all tools in v2.1.150:

| Field | Type | When present | Semantics |
|---|---|---|---|
| `status` | string | Most tools | `"success"`, `"error"`, or tool-specific status |
| `usage` | object | Multi-step tools | Token rollup for the tool invocation. Same shape as [`message.usage`](#usage-and-token-accounting). |
| `agentId` | string | Agent tool | UUID linking to the subagent trace file at `~/.claude/projects/<slug>/<session-uuid>/subagents/agent-<agentId>.jsonl`. |
| `agentType` | string | Agent tool | The `subagent_type` that ran (matches the `Agent` tool's input). |
| `prompt` | string | Agent tool | The prompt passed to the subagent. |
| `totalDurationMs` | number | Agent tool | Wall-clock time the subagent ran. |
| `totalTokens` | number | Agent tool | Total tokens consumed across the subagent's entire run. |
| `totalToolUseCount` | number | Agent tool | Number of tool invocations the subagent made. |
| `toolStats` | object | Agent tool | Per-tool invocation counts inside the subagent (e.g., `{"Read": 4, "Bash": 2}`). |
| `durationMs`, `durationSeconds` | number | Many tools | Tool-specific timing. |
| `stdout`, `stderr` | string | `Bash` | Captured command output streams. |
| `code` | number | `Bash` | Exit code. |
| `interrupted` | boolean | `Bash` | Whether the command was interrupted before completion. |
| `noOutputExpected` | boolean | `Bash` | Whether the command was expected to produce no output. |
| `file`, `filePath`, `originalFile` | string | File tools (`Read`, `Edit`, `Write`) | Paths involved in the operation. |
| `oldString`, `newString`, `replaceAll`, `structuredPatch`, `userModified` | various | `Edit` | Edit-specific metadata, including post-edit diff. |
| `bytes`, `content`, `isImage` | various | `Read` | Read-specific result metadata. |
| `query`, `matches`, `searchCount`, `results` | various | `Grep`, `Glob` | Search-specific results. |
| `url`, `result` | string | `WebFetch` | Web fetch results. |
| `questions`, `answers` | array | `AskUserQuestion` | The question/answer payload. |
| `task`, `taskId` | various | Task tools | Task identifier and content. |
| `total_deferred_tools` | number | Tool discovery | Count of deferred tools surfaced. |
| `updatedFields`, `statusChange`, `success` | various | Various | Tool-specific status fields. |
| `type` | string | Tool-specific | Tool-specific subtype indicator. |
| `codeText` | string | Code-bearing tools | Code content returned by the tool. |

This envelope is one of the highest-information surfaces in the format. The Agent-tool subset (`agentId`, `totalDurationMs`, `totalTokens`, `toolStats`, `agentType`, `prompt`) is the most stable and most analyzed — it's what AgentFluent uses for agent-quality diagnostics. Full per-tool walkthroughs belong in [`tool-invocation.md`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/tool-invocation.md) (forthcoming).

See [`anatomy-agent-invocation.jsonl`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/fixtures/synthetic/anatomy-agent-invocation.jsonl) for an end-to-end synthetic Agent invocation including the `toolUseResult` envelope.

---

## Skipped types

**Verified against Claude Code v2.1.150.**

Several message types appear in session JSONL but are typically ignored by analytics parsers — they're either metadata, streaming events, or auxiliary state that doesn't represent model or user activity directly. Whether to parse them depends on the use case.

| `type` value | What it is | Why most parsers ignore it | When you'd want to parse it |
|---|---|---|---|
| `file-history-snapshot` | A snapshot of file state at a checkpoint. Top-level `snapshot.trackedFileBackups` field carries the file contents before each edit. **This is the data structure that powers `/rewind`'s "restore code" capability.** | Not relevant to token or tool analysis. | Anything that wants to reproduce or analyze `/rewind` semantics, or audit which files Claude edited and when. |
| `system` | System events (Claude Code internal). Fields include `subtype`, `durationMs`, `isMeta`, `content`. Records things like model switches, tool registry updates, and other session-internal state. | Not user-visible activity. | Diagnosing internal session behavior; tracking model changes mid-session. |
| `permission-mode` | Records a change in permission mode (e.g., from `"default"` to `"acceptEdits"`). Fields: `permissionMode`, `sessionId`, `type`. | Session-state metadata, not activity. | Auditing permission posture; correlating tool failures with permission state. |
| `ai-title` | The auto-generated session title shown in the resume picker. Fields: `aiTitle`, `sessionId`, `type`. | Display metadata. | Building a session index outside Claude Code; recovering display names for archived sessions. |
| `last-prompt` | A pointer to the most recent user prompt in the session, used by the resume picker. Fields: `lastPrompt`, `leafUuid`, `sessionId`, `type`. | Index metadata, not activity. | Rebuilding picker-like UI on top of session files. |
| `attachment` | An attachment associated with a message (e.g., a pasted file or image). Carries the standard line envelope fields plus `attachment`. | Often referenced by adjacent user/assistant messages. | Recovering full multimodal session context; auditing what context was attached to which turn. |
| `queue-operation` | Internal operation queue state. Fields: `content`, `operation`, `sessionId`, `timestamp`, `type`. | Internal scheduling state. | Debugging session orchestration. |
| `progress` | Streaming progress events. | High-volume streaming chatter. | Real-time monitoring; debugging long-running tool calls. |
| `hook_progress` | Streaming progress events from hooks. | High-volume streaming chatter. | Debugging hook scripts. |
| `bash_progress` | Streaming progress events from Bash tool calls. | High-volume streaming chatter. | Debugging or monitoring long-running shell commands. |
| `create` | File creation events. | Editing-specific; redundant with `tool_use`/`tool_result` for the Write tool. | Auditing file creation patterns. |

The last four (`progress`, `hook_progress`, `bash_progress`, `create`) appear in AgentFluent's CLAUDE.md notes but were not observed in the v2.1.150 sessions sampled for this reference. They may still be emitted under specific conditions (long-running tool calls, hooks that emit progress); presence is conditional, so they remain documented but unverified for current versions.

### File-history snapshots in detail

`file-history-snapshot` deserves its own brief note because it's the most consequential of the "skipped" types — it's not metadata at all in any meaningful sense, it's the data structure that makes `/rewind` work.

Top-level keys observed: `type`, `messageId`, `isSnapshotUpdate`, `snapshot`.

Inside `snapshot`: `messageId`, `timestamp`, `trackedFileBackups`. The `trackedFileBackups` field carries file contents before each Claude-tool edit, indexed by file path. When the user runs `/rewind` and chooses to restore code, Claude Code reads these entries in reverse and writes the prior contents back to disk.

Confirms the inference made in the W1 post ([`posts/2026-05-26-anatomy-of-a-claude-code-session.md`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/posts/2026-05-26-anatomy-of-a-claude-code-session.md)): file-history-snapshot lines are the rewind backbone.

---

## Content blocks

Content blocks appear inside `message.content` arrays on `assistant` and `user` messages.

### `text`

**Verified against Claude Code v2.1.150.**

Plain text. The most common content block.

| Field | Type | Semantics |
|---|---|---|
| `type` | string | Always `"text"`. |
| `text` | string | The text content. Standard JSON string — newlines and quotes are escaped per JSON rules. No additional Markdown or formatting layer. |

### `tool_use`

**Verified against Claude Code v2.1.150.**

A tool invocation issued by the model. Appears in assistant messages.

| Field | Type | Semantics |
|---|---|---|
| `type` | string | Always `"tool_use"`. |
| `id` | string | Unique tool-call identifier (e.g., `"toolu_..."`). Pairs with `tool_result.tool_use_id` on the response side. |
| `name` | string | Tool name (e.g., `"Read"`, `"Edit"`, `"Bash"`, `"Agent"`, `"mcp__github__get_issue"`). |
| `input` | object | Tool-specific input schema. Each tool defines its own shape — `Read` has `file_path`; `Bash` has `command`/`description`/`timeout`/`run_in_background`; `Agent` has `subagent_type`/`description`/`prompt`; MCP tools have their server-defined input schemas. |

The `id` is the load-bearing pairing key for understanding what an agent did — every `tool_use` should be followed (within the same session) by a matching `tool_result` carrying the same `id` as `tool_use_id`.

### `tool_result`

**Verified against Claude Code v2.1.150.**

The response to a `tool_use`. Appears in user messages.

| Field | Type | Semantics |
|---|---|---|
| `type` | string | Always `"tool_result"`. |
| `tool_use_id` | string | The `id` from the matching `tool_use` block. |
| `content` | string OR array | The tool's output. Most common shape is a plain string. Array shape carries content blocks (e.g., text + image for tools returning multimodal output). |
| `is_error` | boolean (optional) | `true` when the tool reported an error. Absent or `false` on the happy path. |

Note that **the actionable tool metadata is NOT in `tool_result`** — it's in the sibling [`toolUseResult` envelope](#tooluseresult-envelope) at the top level of the same line. Tools that produce metadata (Agent, Bash, etc.) populate `toolUseResult`; tools that don't (e.g., simple Reads) often leave `toolUseResult` minimal or absent.

### `thinking`

**Verified against Claude Code v2.1.150.**

Extended-thinking content blocks, present when extended thinking is enabled for the session. Carries the model's internal reasoning.

| Field | Type | Semantics |
|---|---|---|
| `type` | string | Always `"thinking"`. |
| `thinking` | string | The reasoning text. |
| `signature` | string | An opaque cryptographic signature attesting to the thinking content. Used by the API to verify thinking integrity when the content is replayed in a later turn (e.g., when caching extended thinking across turns). Treat as an opaque blob. |

Whether thinking content blocks appear in a session depends on the model and the `--effort` / `effort` setting at session start.

---

## Tool invocation pattern

**Verified against Claude Code v2.1.150.**

The `tool_use` → `tool_result` cycle is how every tool call is recorded:

1. The assistant emits a [`tool_use`](#tool_use) block with a unique `id` and a tool-specific `input`.
2. The next user message contains a matching [`tool_result`](#tool_result) block whose `tool_use_id` equals the `tool_use.id`.
3. For multi-step or context-bearing tools (Agent, Bash, the `mcp__*` tools, etc.), the user line also carries a sibling [`toolUseResult`](#tooluseresult-envelope) envelope with tool-specific metadata.

The `Agent` tool is structurally identical to other tools at the parent-session level, but additionally produces its own subagent JSONL file (see [Subagent traces](#subagent-traces)). The `toolUseResult.agentId` on the parent's user line is the link.

A full walkthrough — covering edge cases like interrupted tool calls, parallel tool invocations, and the subagent trace file's relationship to the parent envelope — belongs in [`tool-invocation.md`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/tool-invocation.md) (forthcoming).

---

## Subagent traces

**Verified against Claude Code v2.1.150.**

Subagent invocations produce their own JSONL files at:

```
~/.claude/projects/<slug>/<session-uuid>/subagents/agent-<agentId>.jsonl
```

The `agentId` matches the `toolUseResult.agentId` on the parent session's user message that received the subagent's `tool_result`. The file contains the subagent's complete internal trace — every `tool_use`/`tool_result` pair, per-step token usage, and `thinking` blocks if extended thinking is enabled.

Every line in a subagent trace file carries `isSidechain: true`. This is the definitive signal distinguishing subagent traces from parent sessions. Top-level fields are largely the same as parent-session lines, with additional attribution fields:

| Field | Type | Semantics |
|---|---|---|
| `agentId` | string | The subagent's own ID. Matches the file name and the parent's `toolUseResult.agentId`. |
| `attributionAgent` | string | The agent type that invoked this subagent (e.g., `"claude"` for the parent, or another subagent type for nested invocations). |
| `attributionMcpServer` | string | MCP server attribution (when the subagent was invoked via an MCP-defined agent). |
| `attributionMcpTool` | string | MCP tool attribution (when applicable). |
| `promptId` | string | An identifier for the prompt that initiated this subagent run. |
| `sourceToolAssistantUUID` | string | The `uuid` of the parent-session assistant line that emitted the `tool_use` invoking this subagent. The direct backlink to the parent context. |

The full layout — including how nested subagent invocations are represented, what fields propagate vs. reset across invocation boundaries, and how to reconstruct a complete agent-tree view — belongs in [`subagent-traces.md`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/subagent-traces.md) (forthcoming).

---

## Usage and token accounting

**Verified against Claude Code v2.1.150.**

Token accounting lives on `message.usage` (for `assistant` lines) and on `toolUseResult.usage` (for context-bearing tool rollups, including subagent invocations). Both objects share the same shape.

| Field | Type | Semantics |
|---|---|---|
| `input_tokens` | number | Tokens consumed reading the prompt and prior conversation. |
| `output_tokens` | number | Tokens generated in the response. |
| `cache_creation_input_tokens` | number | Tokens written to the prompt cache during this turn. Billed at a **premium** rate vs. regular input tokens. |
| `cache_read_input_tokens` | number | Tokens read from the prompt cache. Billed at a **fraction** of regular input-token cost. |
| `cache_creation` | object | Per-TTL breakdown of cache creation. Observed sub-keys include `ephemeral_5m_input_tokens` (5-minute TTL cache writes). |
| `service_tier` | string | The service tier the request used (e.g., `"standard"`, `"priority"`). Affects pricing. |
| `server_tool_use` | object | Server-side tool usage tracking. Reserved for tools that execute on Anthropic's side rather than the local Claude Code process. |
| `inference_geo` | string | Inference region/geography indicator. |
| `iterations` | number | Internal iteration count metadata. |
| `speed` | string \| number | Inference speed indicator. |

### Common pitfalls in cost computation

Token totals are the **raw inputs** to cost computation, not the cost itself. Several gotchas:

1. **Pricing varies by model.** Sonnet, Opus, and Haiku each have different per-million-token rates for input and output. The `message.model` field on each `assistant` line is required for accurate per-line cost computation.
2. **Cache reads are billed at a fraction; cache creation at a premium.** A line with high `cache_read_input_tokens` and low `input_tokens` may be much cheaper than a line with the inverse — even though the total "input volume" is similar.
3. **Subagent token totals are reported twice.** The subagent's tokens appear on each `assistant` line *inside* the subagent trace file AND are rolled up into the parent session's `toolUseResult.usage` field. Naive aggregation that sums both will double-count. Use one or the other, not both.
4. **Cache fields are zero on the first turn.** A fresh session starts with no cache; `cache_creation_input_tokens` and `cache_read_input_tokens` are zero on the first `assistant` line.
5. **`service_tier` affects pricing.** Priority tier and other non-standard tiers have different rates; check the field before applying a flat per-model price.

Tools like [AgentFluent](https://github.com/frederick-douglas-pearce/agentfluent) and [CodeFluent](https://github.com/frederick-douglas-pearce/codefluent) handle this properly. For one-off cost estimates, the per-line `usage` object is the data; turning it into dollars requires the model name, the service tier, and an external pricing table.

---

## Hook event fields

**Verified against [Claude Code hook documentation](https://code.claude.com/docs/en/hooks) as of 2026-05-26.**

Hook events are an **outbound JSON contract** — Claude Code sends them to hook scripts via stdin when configured events fire. They are NOT session JSONL message lines. The one exception is the `file-history-snapshot` *message type* (see [Skipped types](#skipped-types)), which is a session line, not a hook event, despite sounding hook-related.

This section documents the outbound JSON shape. For configuration syntax, matcher semantics, and the response protocol (allow / block / deny exit codes), see Claude Code's hooks documentation directly.

### Common fields (all events)

Every hook event payload includes these fields:

| Field | Type | Semantics |
|---|---|---|
| `session_id` | string | The session UUID. Matches `sessionId` in JSONL lines. |
| `transcript_path` | string | Absolute path to the session JSONL on disk. |
| `cwd` | string | Working directory when the hook fired. |
| `hook_event_name` | string | The event type that fired (e.g., `"PreToolUse"`). |
| `permission_mode` | string (optional) | Current permission mode: `"default"`, `"plan"`, `"acceptEdits"`, `"auto"`, `"dontAsk"`, or `"bypassPermissions"`. Not all events receive this. |
| `effort` | object (optional) | `{level: "low"|"medium"|"high"|"xhigh"|"max"}`. Present for tool-use context events when the current model supports `--effort`. Also exposed as `$CLAUDE_EFFORT`. |
| `agent_id` | string (optional) | Subagent UUID when the hook fires inside a subagent call. |
| `agent_type` | string (optional) | Agent type when running with `--agent` or inside a subagent. |

### Event types and event-specific fields

Each row lists the event name, when it fires, and fields **beyond** the common set. Matcher syntax is documented in Claude Code's hooks docs.

| Event | When | Event-specific fields |
|---|---|---|
| `SessionStart` | Session begins or resumes | `source` (`"startup"`, `"resume"`, `"clear"`, `"compact"`), `model`, `agent_type` (if `--agent`) |
| `Setup` | `claude --init-only` or `claude -p --init/--maintenance` | `trigger` (`"init"`, `"maintenance"`) |
| `UserPromptSubmit` | User submits a prompt, before processing | `prompt` |
| `UserPromptExpansion` | User-typed command expands into a prompt (slash command, MCP prompt) | `expansion_type` (`"slash_command"`, `"mcp_prompt"`), `command_name`, `command_args`, `command_source`, `prompt` |
| `PreToolUse` | Before a tool call executes | `tool_name`, `tool_input` (tool-specific schema), `tool_use_id` |
| `PermissionRequest` | Permission dialog appears | `tool_name`, `tool_input` |
| `PermissionDenied` | Auto-mode classifier denies a tool call | `tool_name`, `tool_input` |
| `PostToolUse` | After a tool call succeeds | `tool_name`, `tool_input`, `tool_use_id`, `tool_result` |
| `PostToolUseFailure` | After a tool call fails | `tool_name`, `tool_input`, `tool_use_id`, `error` |
| `PostToolBatch` | Full batch of parallel tool calls resolves, before next model call | `tool_calls` (array of `{tool_name, tool_input, tool_use_id, ...}`) |
| `Stop` | Claude finishes responding | (common only) |
| `StopFailure` | Turn ends due to API error | `error_type` (e.g., `"rate_limit"`, `"server_error"`), `error_message` |
| `SubagentStart` | Subagent spawned | `agent_type`, `agent_id`, `initial_prompt` |
| `SubagentStop` | Subagent finishes | `agent_type`, `agent_id`, `result` |
| `TaskCreated` | A task is created via TaskCreate | `task_id`, `task_title`, `task_description` |
| `TaskCompleted` | A task is marked completed | `task_id`, `task_title`, `completion_status` |
| `TeammateIdle` | Agent team teammate going idle | `teammate_name`, `reason` |
| `InstructionsLoaded` | A CLAUDE.md or `.claude/rules/*.md` file is loaded into context | `file_path`, `memory_type` (`"User"`, `"Project"`, `"Local"`, `"Managed"`), `load_reason`, `globs` (optional), `trigger_file_path` (optional), `parent_file_path` (optional) |
| `ConfigChange` | A settings file changes during the session | `config_source` (`"user_settings"`, `"project_settings"`, `"local_settings"`, `"policy_settings"`, `"skills"`), `changed_keys` |
| `CwdChanged` | Working directory changes | `old_cwd`, `new_cwd` |
| `FileChanged` | A watched file changes on disk | `file_path`, `change_type` (`"created"`, `"modified"`, `"deleted"`) |
| `WorktreeCreate` | A worktree is created | `worktree_name`, `base_path` |
| `WorktreeRemove` | A worktree is removed | `worktree_path` |
| `PreCompact` | Before context compaction | `trigger` (`"manual"`, `"auto"`) |
| `PostCompact` | After context compaction completes | `trigger` (`"manual"`, `"auto"`) |
| `Elicitation` | An MCP server requests user input | `server`, `form_schema`, `form_description` |
| `ElicitationResult` | User responds to an MCP elicitation | `server`, `form_schema`, `user_response` |
| `Notification` | Claude Code sends a notification | `notification_type` (`"permission_prompt"`, `"idle_prompt"`, `"auth_success"`, `"elicitation_dialog"`, etc.), `message` |
| `SessionEnd` | Session terminates | `end_reason` (`"clear"`, `"resume"`, `"logout"`, `"prompt_input_exit"`, etc.) |

### Version-specific notes

The Claude Code hooks documentation does not surface a per-field version history. Fields and events documented above represent the contract as of 2026-05-26. The W3 roadmap (issue #7) flagged `duration_ms` (claimed v2.1.119) and `background_tasks`/`session_crons` (claimed v2.1.145) as version-specific additions — these were not surfaced in the current docs page and may have since been folded into the common fields, renamed, or removed. Re-verify against a current Claude Code release when this section needs re-stamping.

---

## Format version notes

When [`format-version-history.md`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/format-version-history.md) is created (not yet started; see [`reference/README.md`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/README.md)), this section will cross-reference it. Every field documented above that has version-specific behavior — addition, rename, removal — will gain a footnote linking to its history entry.

Until that doc exists, version-specific behavior is captured inline in the relevant section's text (see, e.g., the [Version-specific notes](#version-specific-notes) under Hook event fields).
