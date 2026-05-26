# anatomy-agent-invocation.jsonl — generator notes

**Authored:** 2026-05-26 by hand (Fred Pearce, via Claude Code)
**Used by:** W1 post — "Anatomy of a Claude Code session" (issue #6)
**Verified against Claude Code:** v2.1.150

## What this fixture illustrates

The `Agent` tool invocation pattern, which is the structural anchor for understanding subagent delegation. Three lines in the *parent* session:

1. A `user` prompt asking for a subagent to do something
2. An `assistant` `tool_use` invoking the `Agent` tool with a `subagent_type` and a `prompt`
3. A `user` message containing the matching `tool_result` block — **and** a sibling top-level key `toolUseResult` carrying the subagent's invocation metadata

The `toolUseResult` envelope is the part that surprises most readers: it is **not** inside `message.content`, and it is **not** a normal content block. It sits at the top level of the line, alongside `message`, `timestamp`, and so on. It uses camelCase field names (unlike most other fields in the format).

This fixture is also the gateway to the subagent-traces story (`~/.claude/projects/<slug>/<session-uuid>/subagents/agent-<agentId>.jsonl`) but does **not** include the subagent trace file itself — that's a Part 2 topic.

## Key structural points readers should see

- The `Agent` tool's `input` carries `subagent_type`, `description`, and `prompt` — these are how the parent session captures *what* it asked the subagent to do.
- The `tool_result.content` is the subagent's final returned summary (a string here, but could be richer).
- The `toolUseResult` envelope sits beside `message`, not inside it. Fields:
  - `status` — `success` or `error`
  - `agentId` — links to a separate subagent JSONL file at `~/.claude/projects/<slug>/<session-uuid>/subagents/agent-<agentId>.jsonl`
  - `agentType` — which subagent ran (matches `subagent_type` from the input)
  - `totalDurationMs`, `totalTokens`, `totalToolUseCount` — rollups across the entire subagent run
  - `usage` — sub-totals broken out into input/output/cache fields
  - `toolStats` — per-tool invocation counts inside the subagent
- The subagent took ~132 seconds and burned ~18k tokens (from `totalDurationMs` and `totalTokens`) — the parent session sees these rollups but does **not** see the subagent's individual tool calls in this file. Those live in the subagent trace file.

## Synthetic conventions used

- `sessionId`: `00000000-0000-0000-0000-000000000003`
- `agentId`: `99999999-9999-9999-9999-999999999001` — the prefix `9999` marks subagent IDs in our synthetic family
- `tool_use.id`: `toolu_synthetic_002` (continues from fixture 2's `001`)
- Model: `claude-opus-4-7` for the parent (matches the model named in the post's verification context)
- `toolStats` includes synthetic MCP tool names (`mcp__github__get_issue`, `mcp__github__add_issue_comment`) to illustrate that tool names in `toolStats` are exact strings as they appear in the JSONL

## Deliberate omissions

- The corresponding subagent trace file is NOT included. Subagent traces deserve their own fixture and their own walkthrough (forthcoming in Part 2 or as a standalone fixture once `reference/subagent-traces.md` lands).
- `status` is `"success"`. The error path (`status: "error"`, partial `toolUseResult` data) is a Part 2 topic.
- No nested subagents — `agentType: "pm"` is a leaf invocation. Real sessions may show subagents invoking other subagents.

## Authoritative shape source

Field semantics here track [AgentFluent's CLAUDE.md "JSONL Data Format" section](https://github.com/frederick-douglas-pearce/agentfluent/blob/main/CLAUDE.md#jsonl-data-format) as of 2026-05-26. Once W3 (issue #5) populates `reference/data-dictionary.md`, this fixture's generator notes should be re-pointed at the canonical reference.

## How to regenerate

Authored by hand. To produce a similar fixture, substitute UUIDs (preserving the family scheme), the agent type and prompt, the rollup numbers, and timestamps. Validate as JSONL.
