# agent-sdk-invocation.jsonl — generator notes

**Authored:** 2026-06-22 by hand (Fred Pearce, via Claude Code).
**Used by:** [`reference/data-dictionary.md`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/data-dictionary.md) (`entrypoint`, `promptSource`, `toolUseResult.resolvedModel` rows) and [`reference/subagent-traces.md`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/subagent-traces.md) (Agent SDK parity note). Issue [#132](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/132).
**Provenance:** Synthetic, but field shapes mirror AgentFluent's empirical Agent SDK probe (`research/agent-sdk-probe/FINDINGS.md`, agentfluent #518 / #522). No bytes are copied from the probe corpus — this fixture is fabricated to the shapes the probe documented.
**Verified against:** Agent SDK `claude-agent-sdk` **0.2.106** / `claude` CLI **2.1.185** (the probe's pinned versions), captured 2026-06-22. Distinct from the v2.1.150 Claude Code baseline that the rest of the reference is pinned to.

## What this fixture illustrates

The headline finding of the Agent SDK probe: **the Agent SDK writes the same JSONL format to the same place as Claude Code.** This is a parent-session view of a Python SDK (`sdk-py`) agent delegating one unit of work to a subagent. It is the SDK analogue of [`anatomy-agent-invocation.jsonl`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/fixtures/synthetic/anatomy-agent-invocation.jsonl), constructed to exercise the three fields that are net-new to this reference:

1. **`entrypoint: "sdk-py"`** — on every `user`/`assistant` line. The intrinsic discriminator that distinguishes a Python Agent SDK session from a Claude Code interactive session (which carries a different `entrypoint`; see the data-dictionary row). The `-py` suffix implies the TypeScript SDK likely emits `"sdk-ts"` — not verified here (the probe was Python-only).
2. **`promptSource: "sdk"`** — on the user **prompt** line (line 1) only. Programmatic prompts (`query()` / `ClaudeAgentOptions`) are marked `sdk`; an interactively typed prompt is marked `typed`. It does **not** appear on the tool-result `user` line (line 3), which is not a prompt.
3. **`resolvedModel`** — inside the parent's `toolUseResult` envelope (line 3). The concrete model the child actually ran, after alias resolution. Here it equals the parent's `message.model` because the SDK agent inherited its model, but the field exists precisely so a parser does not have to re-derive the child model from the trace file.

Three lines, mirroring the parent-side `Agent` pattern:

1. `user` — the programmatic prompt. `entrypoint: "sdk-py"`, `promptSource: "sdk"`.
2. `assistant` — an `Agent` `tool_use` (the SDK emits `Agent`, the same block name Claude Code uses, even though the SDK init event advertises the tool as `Task`; see the probe note below). `model` is the SDK's configured model.
3. `user` — the matching `tool_result` plus the top-level `toolUseResult` envelope, carrying the same Agent-tool rollup keys as Claude Code (`agentId`, `agentType`, `totalTokens`, `toolStats`, `usage`, …) **plus** `resolvedModel`.

## Key structural points readers should see

- **Same format, same place.** Every common field (`type`, `sessionId`, `uuid`, `parentUuid`, `isSidechain`, `cwd`, `version`, `userType`, `gitBranch`) has the same shape as a Claude Code session. The SDK session lands at `~/.claude/projects/<cwd-slug>/<session-id>.jsonl` exactly like an interactive session — the probe confirmed the SDK derives the slug from `cwd` the same way.
- **`entrypoint` is the reliable discriminator.** `userType` is `"external"` in both SDK and CC interactive sessions, so it does **not** discriminate. `isSidechain` is `false` for both main sessions. `entrypoint` is the intrinsic, per-line marker.
- **`toolUseResult` envelope matches Claude Code** and adds `resolvedModel`. The Agent-tool subset AgentFluent already keys on (`agentId`, `agentType`, `totalTokens`, `totalToolUseCount`, `totalDurationMs`, `toolStats`, `usage`) is unchanged.
- **`agentId` is a non-UUID short hex string here** (`5dca9e0f1b2c3d4ef`), mirroring the ~17-hex-char shape the probe observed rather than the dashed UUID the Claude Code synthetic fixtures use. It still serves the same role: it names the child trace file (`<session-id>/subagents/agent-<agentId>.jsonl`) and links the parent's `toolUseResult` to that trace. The agentId *shape* difference is recorded here as an observation, not asserted as a reference-level claim — the linkage semantics are what matter and they are identical.

### Internal invariants (validated)

- `toolUseResult.totalTokens` (39408) == sum of the four `usage` fields (8 + 400 + 9000 + 30000).
- `toolUseResult.totalToolUseCount` (3) == sum of `toolStats` (`Read` 2 + `Grep` 1).
- `parentUuid` chains: line 1 root (`null`) → line 2 → line 3.
- `tool_use.id` (`toolu_synthetic_sdk_001`) == the `tool_result.tool_use_id` on line 3.

These mirror the reconciliation discipline of [`anatomy-agent-invocation.jsonl`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/fixtures/synthetic/anatomy-agent-invocation.jsonl), though this fixture is standalone (no paired child-trace fixture), so the cross-fixture token sum is not part of the invariant set.

## Synthetic conventions used

- `sessionId`: `50000000-0000-0000-0000-000000000001` (the `5…` family marks SDK fixtures, distinct from the `0…`/`7…` Claude Code anatomy fixtures).
- `agentId`: `5dca9e0f1b2c3d4ef` — synthetic 17-hex-char value mirroring the probe's observed non-UUID shape.
- `tool_use.id`: `toolu_synthetic_sdk_001`; `message.id`: `msg_synthetic_sdk_001`; `requestId`: `req_synthetic_sdk_001`.
- Model: `claude-haiku-4-5-20251001` (the probe's `ClaudeAgentOptions.model`).
- `cwd`: `/home/dev/agent-sdk-probe` (synthetic; no real path).
- `version`: `2.1.185` (the CLI version the SDK ran against in the probe), not the `2.1.150` baseline.

## Deliberate omissions

- **No paired child-trace fixture.** The probe confirmed the SDK child trace matches the Claude Code shape (`isSidechain: true`, `entrypoint: "sdk-py"`, same `user`/`assistant` schema) and lives at `<session-id>/subagents/agent-<agentId>.jsonl` with an `agent-<agentId>.meta.json` sidecar. The Claude Code child-trace shape is already shown by [`anatomy-subagent-trace.jsonl`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/fixtures/synthetic/anatomy-subagent-trace.jsonl); a dedicated SDK child trace can follow if deeper nesting is later verified.
- **No `<persisted-output>` / `tool-results/` spill.** The probe exercised it (`persistedOutputPath` / `persistedOutputSize` on `toolUseResult`) but that surface is documented separately; this fixture keeps tool output small and inline.
- **Trimmed `message.usage` extras.** Real SDK assistant lines also carry `iterations`, `inference_geo`, `speed`, and `server_tool_use` in `usage` (absorbed harmlessly by parsers that ignore extra keys). Only `service_tier` and `iterations` are shown here to keep the line readable; the others are documented in [`data-dictionary.md` § Usage and token accounting](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/data-dictionary.md#usage-and-token-accounting).
- **No MCP, network, or secret surface.** The probe's representative agent was a pure SDK agent (`setting_sources=[]`, `mcp_servers={}`); this fixture follows suit.

## Probe note: `Agent` vs `Task`

The SDK's runtime `SystemMessage(init)` event advertises the delegation tool as `Task`, but the model emits `tool_use` blocks named **`Agent`** (with `input.subagent_type`) — the same name Claude Code uses and the name this fixture uses. The two are aliased for backwards compatibility (allow-listing `Task` permits the emitted `Agent` with zero permission denials). Parsers should key on the emitted `tool_use.name == "Agent"`, not on the init event's tool list.

## How to regenerate

Authored by hand, then validated as JSONL with the invariant checks above (`totalTokens` == `usage` sum, `totalToolUseCount` == `toolStats` sum, `parentUuid` chain, `tool_use` ↔ `tool_result` pairing). To change the run, substitute the UUIDs (preserving the `5…` family), the agent type/prompt, the rollup numbers, and timestamps, then re-validate. Keep `entrypoint: "sdk-py"`, `promptSource: "sdk"` (prompt line only), and `toolUseResult.resolvedModel` — those three are the reason this fixture exists.
