# anatomy-subagent-trace.jsonl — generator notes

**Authored:** 2026-05-26 by hand (Fred Pearce, via Claude Code)
**Pairs with:** [`anatomy-agent-invocation.jsonl`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/fixtures/synthetic/anatomy-agent-invocation.jsonl) (the parent-side view)
**Used by:** [`reference/subagent-traces.md`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/subagent-traces.md) (W3 #8)
**Verified against Claude Code:** v2.1.150 — line-by-line attribution-field placement verified via jq recon against real Claude Code subagent traces on 2026-05-26. Agent SDK subagent traces may exhibit different patterns; treat the field placement encoded in this fixture as Claude Code-specific until SDK traces are available for sampling.

## What this fixture illustrates

The subagent-side view that pairs with `anatomy-agent-invocation.jsonl`'s parent-side view. Four lines covering one full prompt-and-respond cycle inside the subagent:

1. The initial `user` prompt — the prompt the parent passed to the subagent. Carries `agentId` and `promptId`, **no** `sourceToolAssistantUUID` (nothing earlier in this file to point at).
2. The subagent's first `assistant` turn — text + a `tool_use` for an MCP tool (`mcp__github__get_issue`). Carries `agentId`, `attributionAgent`, and (because the turn invokes an MCP tool) `attributionMcpServer` and `attributionMcpTool`. **No** `sourceToolAssistantUUID` and **no** `promptId` on assistant lines.
3. The matching `user` `tool_result` line. Carries `agentId`, `promptId`, and `sourceToolAssistantUUID` pointing at line 2's `uuid` — the assistant line whose `tool_use` this is a result for.
4. The subagent's final `assistant` text turn — the same summary string the parent will see in its `tool_result.content`. Carries `agentId` and `attributionAgent`; no MCP attribution (no MCP tool involved in this turn).

## Key structural points readers should see

- **Every line carries `isSidechain: true` and a top-level `agentId`.** These two together are the canonical "this is a subagent line" signal.
- **`sessionId` is NOT shared with the parent.** The parent fixture uses `00000000-0000-0000-0000-000000000003`; this fixture uses `77777777-7777-7777-7777-777777777003`. In Claude Code, each subagent invocation has its own sessionId. The connection to the parent is via `agentId` and the file's location on disk, not via `sessionId`. Whether the Agent SDK follows the same convention is not yet verified.
- **Per-line-type attribution placement** (the rule verified by jq recon against Claude Code traces on 2026-05-26):
  - `attributionAgent` appears on `assistant` lines only — always present there. Its value is the **subagent type that ran** (here, `"pm"`, matching the parent fixture's `toolUseResult.agentType`).
  - `attributionMcpServer` and `attributionMcpTool` appear on `assistant` lines when an MCP tool is involved in the turn. Line 2 has them (invokes `mcp__github__get_issue`); line 4 does not (no MCP tool).
  - `promptId` appears on `user` lines only — always present there.
  - `sourceToolAssistantUUID` appears on `user` lines that carry a `tool_result` (here, line 3). Line 1 — the initial prompt — does **not** carry it because there is no earlier assistant line to point at.
- **`sourceToolAssistantUUID` is an internal pairing key, NOT a back-pointer to the parent.** Line 3's value (`aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaa0001`) is the `uuid` of line 2 — the same-file assistant line whose `tool_use` this user line answers. There is **no** field on Claude Code subagent lines that points at the parent session.
- **`parentUuid` chains within the subagent file.** Line 1 is the root (`parentUuid: null`); subsequent lines chain back through the file's own `uuid`s, not the parent's.
- **The final assistant text matches the `tool_result.content` string on the parent's user line** (in `anatomy-agent-invocation.jsonl`). The parent sees only that summary; this file shows where it came from.
- **Token totals on the assistant lines** roughly sum to the parent's `toolUseResult.usage` rollup, illustrating the double-counting risk documented in [`subagent-traces.md` § Token accounting](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/subagent-traces.md#token-accounting).

## Synthetic conventions used

- `sessionId`: `77777777-7777-7777-7777-777777777003` (deliberately different from the parent fixture to make the "sessionId is not shared in Claude Code" point concrete)
- `agentId`: `99999999-9999-9999-9999-999999999001` (matches the parent's `toolUseResult.agentId`)
- Subagent assistant-line `uuid`s use the `aaaaaaaa-...` family
- Subagent user-line `uuid`s use the `bbbbbbbb-...` family
- `tool_use.id`: `toolu_synthetic_sub_001` (continues from the parent fixture's `toolu_synthetic_002`)
- `attributionAgent`: `"pm"` (matches the parent's `agentType`)
- Model: `claude-sonnet-4-6` for the subagent (distinct from the parent's `claude-opus-4-7` to emphasize that subagent and parent can run different models)

## Deliberate omissions

- **No `thinking` blocks.** This subagent does not have extended thinking enabled. A separate fixture could illustrate that.
- **No nested subagent.** Claude Code does not permit subagents to invoke further subagents, so nested invocations cannot be illustrated using Claude Code-shaped fixtures. Agent SDK nesting is an open verification item in `subagent-traces.md`.
- **Only two tool calls.** Real subagents typically take many more steps; the fixture stays minimal to highlight structure, not behavior.
- **`toolUseResult` on the subagent's tool-result line is minimal** (`status`, `durationMs`). A real MCP tool result envelope would carry more — see [`tool-invocation.md`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/tool-invocation.md#mcp-tools-mcpservertool) for per-tool shapes.
- **No `attachment` lines.** Real subagent traces occasionally include attachment lines (e.g., for image inputs); the fixture stays at the message-and-tool-call level.

## How to regenerate

Authored by hand. To produce a similar fixture, substitute UUIDs (preserving the family scheme that makes parent/subagent UUIDs visually distinct), the MCP server/tool names, the prompt and final summary, the tokens, and the timestamps. Validate as JSONL (one JSON object per line, no trailing comma, no blank lines).
