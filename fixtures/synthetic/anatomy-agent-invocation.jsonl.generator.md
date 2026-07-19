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
  - `totalDurationMs`, `totalToolUseCount` — true run-level rollups (whole-run duration and tool-call count)
  - `totalTokens`, `usage` — a **single-turn snapshot**, NOT a run total. `usage` is the subagent's *final* assistant turn's `message.usage`, and `totalTokens` is the sum of its four fields. This is the single most misread part of the envelope; see the reconciliation section below.
  - `toolStats` — per-tool invocation counts inside the subagent (a true run-level count)
- The subagent took ~132 seconds (`totalDurationMs`, a real run total) and made 7 tool calls (`totalToolUseCount`). But `totalTokens` (28,803) is **not** what the run processed — it is one turn's context snapshot. The run actually processed ~180k tokens across its 8 turns (see the trace fixture); the rollup understates that by ~6.25x. The parent session sees only these envelope values, never the subagent's individual turns — those live in the subagent trace file. Part 4 unpacks why the snapshot is not the spend.

### Rollup numbers reconcile with the paired trace

As of the #144 token-accounting correction (superseding the earlier #98/#99/#103 "column-sum" construction, which modeled the rollup as a run total — it is not), this envelope models the rollup as a **single-turn snapshot**, matching the *final* assistant turn of the paired [`anatomy-subagent-trace.jsonl`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/fixtures/synthetic/anatomy-subagent-trace.jsonl):

- `usage` (`input 3 / output 300 / cache_creation 1500 / cache_read 27000`) equals the trace's **8th (final)** `assistant` line's `message.usage` exactly. This is the worked example of the single-turn-snapshot rule: the rollup is one turn, not a run total.
- `totalTokens` (28803) is the sum of those four fields (3 + 300 + 1500 + 27000). The `totalTokens == sum of the four usage fields` identity is confirmed **691/691** against a live corpus — see [`subagent-traces.md` § Token accounting](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/subagent-traces.md#token-accounting).
- **The undercount is now the demonstrable lesson.** The trace's *real* processed total across all 8 turns is 180,020 tokens; the rollup snapshots 28,803, understating by ~6.25x. To get real spend, sum the trace's per-turn usage (deduped by `message.id`), never the rollup.
- `totalToolUseCount` (7), `toolStats`, and `totalDurationMs` (132140) are true run-level values and match the trace. Only `usage`/`totalTokens` are the single-turn snapshot.

The cross-fixture invariant is now: **parent `toolUseResult.usage` == the trace's final assistant turn's `message.usage`** (and `totalTokens` == the sum of those four fields). If you change either fixture's token numbers, keep that identity intact.

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
