# anatomy-subagent-trace.jsonl — generator notes

**Authored:** 2026-05-26 by hand (Fred Pearce, via Claude Code).
**Reconciled:** 2026-06-10 — expanded from a 4-line excerpt to the full 16-line / 7-tool-call run so the trace's per-turn token usage sums **exactly** to the parent's `toolUseResult.usage` rollup (issue #98). Regenerated via a small Python builder (see [How to regenerate](#how-to-regenerate)).
**Pairs with:** [`anatomy-agent-invocation.jsonl`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/fixtures/synthetic/anatomy-agent-invocation.jsonl) (the parent-side view).
**Used by:** [`reference/subagent-traces.md`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/subagent-traces.md) (W3 #8) and Part 3 ("Inside the subagent trace file," #65).
**Verified against Claude Code:** v2.1.150 — line-by-line attribution-field placement verified via jq recon against real Claude Code subagent traces on 2026-05-26. Agent SDK subagent traces may exhibit different patterns; treat the field placement encoded in this fixture as Claude Code-specific until SDK traces are available for sampling.

## What this fixture illustrates

The subagent-side view that pairs with `anatomy-agent-invocation.jsonl`'s parent-side view. Sixteen lines covering one complete `pm` subagent run: the initial prompt, **seven tool calls** (1 `mcp__github__get_issue` + 4 `Read` + 2 `mcp__github__add_issue_comment`), and the final summary. The line sequence:

1. `user` — the initial prompt the parent passed to the subagent. Carries `agentId` and `promptId`, **no** `sourceToolAssistantUUID` (nothing earlier in this file to point at).
2. `assistant` — first turn: text + a `tool_use` for `mcp__github__get_issue`. Carries `agentId`, `attributionAgent`, and (because the turn invokes an MCP tool) `attributionMcpServer` / `attributionMcpTool`.
3. `user` — the matching `tool_result`, with a minimal `toolUseResult` (`status`, `durationMs`). Carries `sourceToolAssistantUUID` pointing at line 2's `uuid`.
4–11. Four `Read` calls, each an `assistant` `tool_use` turn followed by its `user` `tool_result`. `Read` is **not** an MCP tool, so those assistant turns carry `attributionAgent` but **no** `attributionMcp*`; the `Read` result lines carry **no** `toolUseResult` (simple tools leave it absent).
12–15. Two `mcp__github__add_issue_comment` calls, same assistant-turn / tool-result shape as the get_issue call — MCP attribution present, `toolUseResult` present on the result lines.
16. `assistant` — the final text turn. The summary string here is the exact string the parent sees in its `tool_result.content`. Carries `agentId` and `attributionAgent`; no MCP attribution (no tool in this turn).

The shown post excerpt (Part 3) inlines lines 1, 2, 3, and 16 — a faithful four-line abbreviation of this full run.

## Key structural points readers should see

- **Every line carries `isSidechain: true` and a top-level `agentId`.** These two together are the canonical "this is a subagent line" signal.
- **`sessionId` is NOT shared with the parent.** The parent fixture uses `00000000-0000-0000-0000-000000000003`; this fixture uses `77777777-7777-7777-7777-777777777003`. In Claude Code, each subagent invocation has its own sessionId. The connection to the parent is via `agentId` and the file's location on disk, not via `sessionId`. Whether the Agent SDK follows the same convention is not yet verified.
- **Per-line-type attribution placement** (the rule verified by jq recon against Claude Code traces on 2026-05-26):
  - `attributionAgent` appears on `assistant` lines only — always present there. Its value is the **subagent type that ran** (here, `"pm"`, matching the parent fixture's `toolUseResult.agentType`).
  - `attributionMcpServer` / `attributionMcpTool` appear on `assistant` lines when an MCP tool is involved in the turn. The `get_issue` and both `add_issue_comment` turns carry them; the four `Read` turns and the final summary do not.
  - `promptId` appears on `user` lines only — always present there.
  - `sourceToolAssistantUUID` appears on `user` lines that carry a `tool_result`. Each points at the `uuid` of the same-file `assistant` line whose `tool_use` it answers. The initial prompt (line 1) does **not** carry it (no earlier assistant line to point at).
- **`sourceToolAssistantUUID` is an internal pairing key, NOT a back-pointer to the parent.** Every value is the `uuid` of an assistant line **earlier in this same file**. There is **no** field on Claude Code subagent lines that points at the parent session.
- **`parentUuid` chains within the subagent file.** Line 1 is the root (`parentUuid: null`); subsequent lines chain back through the file's own `uuid`s, not the parent's.
- **The final assistant text matches the `tool_result.content` string on the parent's user line** (in `anatomy-agent-invocation.jsonl`). The parent sees only that summary; this file shows where it came from.

### Token reconciliation (the load-bearing invariant)

This fixture pair is the worked example behind the "same tokens, counted twice" point in [`subagent-traces.md` § Token accounting](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/subagent-traces.md#token-accounting). The numbers are constructed to reconcile exactly, so the double-count is demonstrable:

- The eight `assistant` lines' `message.usage` fields **sum exactly** to the parent's `toolUseResult.usage`:

  | Field | Sum across trace assistant turns | Parent `toolUseResult.usage` |
  |---|---|---|
  | `input_tokens` | 6000 | 6000 |
  | `output_tokens` | 2000 | 2000 |
  | `cache_creation_input_tokens` | 12000 | 12000 |
  | `cache_read_input_tokens` | 16000 | 16000 |

- `totalTokens` (36000) is defined here as the **sum of all four `usage` fields** (input + output + cache_creation + cache_read = total token volume across the run). **Note:** Claude Code's exact production formula for `totalTokens` is not pinned in the reference; this fixture adopts the four-field sum as a clear, reader-verifiable definition. If upstream is later confirmed to compute it differently (e.g., excluding cache reads), update this fixture and the note together.
- `totalToolUseCount` (7) equals the number of `tool_use` blocks in the trace, and `toolStats` (`{Read:4, mcp__github__get_issue:1, mcp__github__add_issue_comment:2}`) equals their per-name tally.
- `totalDurationMs` (132140, parent-side) is slightly longer than the trace's own first→last timestamp span (~131504 ms), reflecting parent-side spawn/return overhead bracketing the subagent run.

The per-turn **split** of cache_creation vs cache_read across turns is illustrative (turn 1 writes cache; later turns read it, cache_creation tapering) — only the **column sums** above are load-bearing.

## Synthetic conventions used

- `sessionId`: `77777777-7777-7777-7777-777777777003` (deliberately different from the parent fixture to make the "sessionId is not shared in Claude Code" point concrete).
- `agentId`: `99999999-9999-9999-9999-999999999001` (matches the parent's `toolUseResult.agentId`).
- Assistant-line `uuid`s use the `aaaaaaaa-…-aaaaaaaa000N` family (N = 1…8, in turn order); user-line `uuid`s use the `bbbbbbbb-…-bbbbbbbb000N` family (N = 1…8).
- `tool_use.id`s: `toolu_synthetic_sub_001` … `toolu_synthetic_sub_007` (get_issue, four Reads, two add_issue_comment), continuing from the parent fixture's `toolu_synthetic_002`.
- Assistant `message.id`s: `msg_synthetic_sub_001` … `msg_synthetic_sub_008`.
- `attributionAgent`: `"pm"` (matches the parent's `agentType`).
- Model: `claude-sonnet-4-6` for the subagent (distinct from the parent's `claude-opus-4-7` to emphasize that subagent and parent can run different models).
- Read targets and comment bodies are synthetic, in the `/home/dev/example-project` working dir; no real paths or content.

## Deliberate omissions

- **No `thinking` blocks.** This subagent does not have extended thinking enabled. A separate fixture could illustrate that.
- **No nested subagent.** Claude Code does not permit subagents to invoke further subagents, so nested invocations cannot be illustrated using Claude Code-shaped fixtures. Agent SDK nesting is an open verification item in `subagent-traces.md`.
- **No `<persisted-output>` / `tool-results/` spill.** All tool results here are small enough to inline; the large-output spill path is a separate fixture/topic (Part 5).
- **No `attachment` lines.** Real subagent traces occasionally include attachment lines (e.g., for image inputs); the fixture stays at the message-and-tool-call level.
- **No `meta.json` sidecar.** The per-invocation `agent-<id>.meta.json` manifest is documented in `subagent-traces.md`; this fixture is the trace only.

## How to regenerate

Regenerated 2026-06-10 via a Python builder that constructs each line as an ordered dict and writes `json.dumps(..., separators=(",", ":"))` per line (one object per line, no trailing whitespace). The builder fixes the eight assistant turns' `usage` so the four columns sum to the chosen rollup, then validates: JSONL parse, `parentUuid` chain, `sourceToolAssistantUUID` pairing, attribution placement, and the cross-fixture token match against `anatomy-agent-invocation.jsonl`. To change the run, edit the per-turn usage/timestamps/tool list in the builder and re-validate; keep the rollup in the parent fixture in sync (the cross-fixture sum check is the gate).
