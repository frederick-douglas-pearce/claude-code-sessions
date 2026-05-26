# Data Dictionary

**Verified against Claude Code:** _(pending — populate when first content lands)_

This document is the canonical field-level reference for Claude Code's JSONL session format. Each section describes a message type or sub-structure and lists every observed field with its type, semantics, and any version-specific notes.

> **Status:** Skeleton. Content will be migrated from AgentFluent's existing format notes (with verification and version stamping) in a follow-up pass.

---

## File location

_TODO: Document the `~/.claude/projects/<slug>/<uuid>.jsonl` convention — slug derivation from working directory, per-project subdirectories, subagent trace subdirectories, file rotation behavior._

## Common fields

All message types share a baseline set of fields:

_TODO: Document `type`, `timestamp` (ISO 8601 UTC), `uuid`, `parentUuid`, `sessionId`, `isSidechain`, `cwd`, `version`, and any others observed across types._

## Message types

### `assistant`

Model responses — text, tool calls, token usage.

_TODO: Document `message.role`, `message.model`, `message.content` (text + tool_use blocks), `message.usage` (input_tokens, output_tokens, cache_creation_input_tokens, cache_read_input_tokens), `message.stop_reason`._

### `user`

Prompts AND tool result envelopes (in Claude Code, tool results live inside user messages, not as their own top-level type).

_TODO: Document the two shapes of `message.content` — plain string vs. array of content blocks. Document how `tool_result` blocks appear inside user content, and how `toolUseResult` is a sibling key on the message carrying agent invocation metadata (`totalTokens`, `totalDurationMs`, `totalToolUseCount`, `agentId`, `agentType`, `usage`, `toolStats`)._

### Skipped types

_TODO: Document `file-history-snapshot`, `progress`, `hook_progress`, `bash_progress`, `system`, `create` — what they are, why most parsers ignore them, what use cases might need them._

## Content blocks

### `text`

_TODO: Plain-text content block. Document the `text` field and any subtle escaping behavior._

### `tool_use`

_TODO: Document `id`, `name`, `input` (per-tool schema), how it pairs with `tool_result` via `tool_use_id`._

### `tool_result`

_TODO: Document `tool_use_id` (the pairing key), `content` (string or array of blocks), `is_error`._

### `thinking`

_TODO: When present (extended thinking enabled), document the `thinking` field shape and how it's cached vs. emitted._

## Tool invocation pattern

The `tool_use` → `tool_result` cycle is the load-bearing structure for understanding what an agent did. The `Agent` tool deserves its own walkthrough.

_TODO: End-to-end example of an Agent tool invocation: the assistant emits `tool_use` with `name: "Agent"` and `subagent_type` in input; the user message containing the matching `tool_result` block carries a sibling `toolUseResult` envelope with `agentId`, `totalTokens`, `totalDurationMs`, `toolStats`, etc. Cover how the `agentId` links to a separate subagent JSONL file._

## Subagent traces

_TODO: Document the `~/.claude/projects/<slug>/<session-uuid>/subagents/agent-<agentId>.jsonl` layout. Inside the subagent file, every message has `isSidechain: true`. The internal trace contains the full tool_use/tool_result cycle, per-step usage, and reasoning steps that the parent session only sees as a summary._

## Usage and token accounting

_TODO: Per-field breakdown of `usage`: `input_tokens`, `output_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens`. When each is non-zero. How they sum at the session level vs. per-message. Common pitfalls (e.g., cache fields are zero on the first turn)._

## Hook event fields

_TODO: Document the JSON contract Claude Code sends to PreToolUse, PostToolUse, Stop, SubagentStop, and other hook event types. Highlight version-specific additions like `duration_ms` (v2.1.119), `background_tasks` and `session_crons` (v2.1.145)._

## Format version notes

When this section is populated, it cross-references `format-version-history.md` once that file exists. Every documented field that has version-specific behavior carries a footnote linking to its first-appearance and any rename/removal entries.

_TODO: After the version-history doc lands, link every version-specific field here._
