# Data Dictionary

The canonical field-level reference for Claude Code's JSONL session format. Each section describes a message type or sub-structure and lists every observed field with its type, semantics, and any version-specific notes.

Reference docs are versioned **per section**, not per document — a single section may be verified against a different Claude Code version than its neighbors. When the format-watch skill flags a change, only the affected sections get re-verified and re-stamped.

This doc grew out of [AgentFluent's CLAUDE.md "JSONL Data Format" section](https://github.com/frederick-douglas-pearce/agentfluent/blob/main/CLAUDE.md#jsonl-data-format), with additional fields and message types observed during verification against current sessions. Where AgentFluent's notes and observed behavior diverge, observed behavior wins.

**Runtime scope.** Field-level verification in this doc is against the **Claude Code** runtime (v2.1.150). The same JSONL format is produced by the **Agent SDK** (Python and TypeScript), but the two runtimes do not necessarily exercise the format identically — for example, the SDK shares one `sessionId` across every nesting level where Claude Code gives each subagent its own, and the SDK drops the `toolUseResult` rollup at nesting depth ≥ 2 where Claude Code keeps it. Where this distinction matters for a specific claim, the section notes it inline. (An earlier revision listed nested subagent invocation itself as a runtime difference. **Claude Code gained nested subagents at v2.1.172**; see [`subagent-traces.md` § Nesting](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/subagent-traces.md#nesting).) Empirical **Agent SDK probes** (Python SDK `claude-agent-sdk` 0.2.106 / `claude` CLI 2.1.185, captured 2026-06-22) have now confirmed the SDK writes the same format to the same location, with the same subagent/spill overflow layout, through both single-level and a forced two-level (nested) delegation — nested SDK delegation records a **flat** `subagents/` directory, the same shape as single-level. The SDK-specific findings they pinned down — `entrypoint: "sdk-py"`, `promptSource`, `toolUseResult.resolvedModel`, and a single `sessionId` shared across all nesting levels — are noted inline below (and in [`subagent-traces.md`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/subagent-traces.md)) with that SDK/CLI version pin (distinct from the v2.1.150 Claude Code baseline). The TypeScript SDK remains unverified.

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

### Overflow subdirectory: subagent traces and spilled tool results

When a session produces data that doesn't belong inline, Claude Code writes it under a `<session-uuid>/` subdirectory created lazily beside the parent `<session-uuid>.jsonl`:

```
~/.claude/projects/<slug>/<session-uuid>/
├── subagents/
│   ├── agent-<agentId>.jsonl        # subagent trace (one per invocation)
│   └── agent-<agentId>.meta.json    # small manifest sidecar beside each trace
└── tool-results/
    └── <tool-use-id>.txt | .json    # tool outputs spilled out of the JSONL when large
```

- **`subagents/`** — each subagent invocation produces a trace file plus a small `agent-<agentId>.meta.json` manifest (keys: `agentType`, `description`, `toolUseId`, `spawnDepth`, `model`, `name`, `worktreePath`, `worktreeBranch`, `spawnedWithWorktree`, `worktreeCleanlyRemoved`, `parentAgentId` — only `agentType` is guaranteed, and `spawnDepth` appears from v2.1.187). The `agentId` in the trace file name matches the `toolUseResult.agentId` on the parent session's user message that carried the subagent's `tool_result`. The directory is **flat at every nesting depth** in both runtimes, so it carries no parent or depth information. Note the casing split: the manifest uses `toolUseId` while session lines use `toolUseID`. Full treatment in [`subagent-traces.md` § File layout](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/subagent-traces.md#file-layout).
- **`tool-results/`** — when a tool result is large (observed spill ≈ 20 KB and up), the in-session `tool_result.content` carries a `<persisted-output>` wrapper with a truncated preview, and the full payload is written here, named after the producing tool call. The `tool_result` block itself carries no pointer key — only that text wrapper — but the sibling `toolUseResult` envelope does: `persistedOutputPath` and `persistedOutputSize`, since v2.1.109. Full treatment in [`tool-invocation.md` § Spilled tool results](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/tool-invocation.md#spilled-tool-results).

See [Subagent traces](#subagent-traces) below for the line-level shape of the trace files.

### Retention

Claude Code's documentation describes a 30-day default cleanup configurable via the `cleanupPeriodDays` setting in `~/.claude/settings.json`. Observed behavior in practice may differ — see [decisions.md O001](../.claude/specs/decisions.md) for context.

---

## Common fields

**Verified against Claude Code v2.1.150.**

Some fields appear on most or all line types; others are type-specific. The table below documents fields that are observed across multiple line types — type-specific fields are documented in their respective sections below.

| Field | Type | Semantics |
|---|---|---|
| `type` | string | Discriminator for the line's shape. Values include `assistant`, `user`, `system`, `pr-link`, `file-history-snapshot`, `attachment`, `permission-mode`, `ai-title`, `last-prompt`, `queue-operation`, and others. See [Message types](#message-types), [`pr-link`](#pr-link), and [Skipped types](#skipped-types). |
| `timestamp` | string (ISO 8601 UTC) | When the line was written. Present on most line types except some metadata types (e.g., `ai-title`, `last-prompt`). |
| `uuid` | string (UUID) | Per-line identifier. Unique within a session. |
| `parentUuid` | string (UUID) or `null` | Links this line to its predecessor in the conversation graph. `null` on the first line of a session. Used to reconstruct linear vs forked conversation flow. |
| `sessionId` | string (UUID) | Shared across every line in a session. The session-level key. Matches the `<session-uuid>` in the file name. |
| `isSidechain` | boolean | `true` for every line inside a subagent trace file; `false` (or absent) in parent session files. The canonical signal that you're reading a subagent trace, not a parent session. |
| `cwd` | string | Working directory at the time the line was written. Can change mid-session if the user `cd`s. |
| `version` | string | Claude Code version (e.g., `"2.1.150"`) at the time the line was written. Can change mid-session if Claude Code is updated. |
| `entrypoint` | string | How the session was started. Observed `"claude"` for the interactive CLI (v2.1.150 baseline). The **Python Agent SDK** writes `"sdk-py"` — verified against an Agent SDK probe session (SDK 0.2.106 / CLI 2.1.185), present on every `user`/`assistant` line; this is the intrinsic discriminator separating an SDK session from an interactive one (`userType` is `"external"` for both, so it does not discriminate). The `-py` suffix implies the TypeScript SDK likely emits `"sdk-ts"` — not yet verified. The same probe observed interactive sessions carrying `"cli"` (not `"claude"`) at CLI 2.1.185, suggesting the interactive value may have shifted since the v2.1.150 baseline; re-verify on the next baseline bump. Not documented in AgentFluent's notes; added to this reference based on v2.1.150 observation. |
| `gitBranch` | string | The git branch active in `cwd` at the time the line was written. Empty string when not in a git repository. Powers the session picker's `Ctrl+B` branch filter. |
| `requestId` | string | An identifier the client uses to correlate requests with model responses. Present on `assistant` lines and some others. |
| `userType` | string | Identifies the user/runtime context — observed value `"external"` for normal CLI usage. |
| `promptSource` | string | How the prompt that this line carries originated. Appears on `user` **prompt** lines (not on tool-result `user` lines). Observed values: `"typed"` (interactively typed prompt), `"sdk"` (a programmatic Agent SDK prompt via `query()` / `ClaudeAgentOptions` — verified against an Agent SDK probe session, SDK 0.2.106 / CLI 2.1.185), and `"synthesized"`-style sources for injected prompts such as compaction summaries (see the compaction work). A corroborating SDK discriminator alongside `entrypoint`, but narrower — it is present only on prompt lines, so key on `entrypoint` for the robust SDK-vs-interactive test. |

Some fields documented in AgentFluent's notes (`isSidechain`, `cwd`, `version`) hold; the rest above (`entrypoint`, `gitBranch`, `requestId`, `userType`, `promptSource`) are additions this reference observed beyond those notes — `entrypoint`'s `"sdk-py"` value and `promptSource` were pinned by the Agent SDK probe (SDK 0.2.106 / CLI 2.1.185); the others against v2.1.150.

---

## Message types

### `assistant`

**Verified against Claude Code v2.1.170.** The core `message` fields are unchanged since v2.1.150; the top-level API-error markers below were added in the v2.1.170 re-verification, with presence confirmed by structural scan (values not read).

**Upstream source for the `stop_*` rows.** `message.stop_reason`, `message.stop_sequence`, and `message.stop_details` are mostly **API-layer semantics rather than harness fields**, so a Claude Code version stamp does not describe what was checked for them, and they carry no separate version marker.

Re-verifying them takes **two instruments**. The value sets and their meanings come from Anthropic's documentation: verified 2026-09-11 against [Stop reasons and fallback](https://platform.claude.com/docs/en/build-with-claude/handling-stop-reasons), [Refusals and fallback](https://platform.claude.com/docs/en/build-with-claude/refusals-and-fallback#refusal-response), and [Fallback credit](https://platform.claude.com/docs/en/build-with-claude/fallback-credit). What Claude Code writes into a session file is a separate question that only a scan answers, and the rows below carry at least one claim of that kind: `stop_sequence: ""` on `<synthetic>` harness lines. Check a claim about what a value _means_ against the docs, and a claim about what lands _on disk_ against sessions.

Model responses — text, tool calls, reasoning, and token usage. Top-level fields are those listed in [Common fields](#common-fields). The `message` object carries the model-side payload:

| Field | Type | Semantics |
|---|---|---|
| `message.role` | string | Always `"assistant"`. |
| `message.id` | string | The API message ID (e.g., `"msg_..."`). Identifies the model's response at the API layer. |
| `message.type` | string | Always `"message"`. Identifies this as a message in the Anthropic API content envelope. |
| `message.model` | string | Model identifier (e.g., `"claude-sonnet-4-6"`, `"claude-opus-4-7"`). Can change mid-session if the model is switched. |
| `message.content` | array | An array of content blocks. Block types: [`text`](#text), [`tool_use`](#tool_use), [`thinking`](#thinking). A single assistant message can carry multiple blocks of different types (e.g., a `text` block followed by a `tool_use` block when the model both speaks and reaches for a tool in the same turn). |
| `message.usage` | object | Token and accounting metadata. See [Usage and token accounting](#usage-and-token-accounting). |
| `message.stop_reason` | string \| `null` | Why the model stopped. Seven values are documented: `"end_turn"` (model finished), `"max_tokens"` (hit the `max_tokens` limit), `"stop_sequence"` (emitted one of the caller's `stop_sequences`), `"tool_use"` (model paused to invoke a tool), `"pause_turn"` (a server-tool loop hit its iteration limit), `"refusal"` (the model declined, see `stop_details`), and `"model_context_window_exceeded"` (the response filled the model's context window). **Treat this as an open enum, not a closed switch:** an unrecognized value is one you have not seen yet rather than malformed data. **`null` also appears in session files**, on lines recording an incomplete turn rather than a finished one. (At the API layer, `stop_reason` is `null` in the opening `message_start` event and is filled in on `message_delta`.) These lines carry partial `usage` figures, and in this repo's fixtures a turn is occasionally recorded by such lines _alone_, with real `cache_creation_input_tokens` on them, so they are not safe to discard. Deduplicate before summing usage: see [`usage` is per-request](#usage-is-per-request-context-recurs-every-turn) for the rule, which keys on `output_tokens` rather than on this field. |
| `message.stop_sequence` | string \| `null` | Non-`null` only when `stop_reason == "stop_sequence"`, which holds on every assistant line in this repo's fixtures. (The cited pages state that coupling explicitly for `stop_details`, not for this field, so treat it as well corroborated rather than as a quoted contract.) At the API layer it carries the matched entry from the request's `stop_sequences` array, which is what tells a caller passing several sequences which one fired. **Do not assume a non-`null` value here is a caller-supplied sequence.** In Claude Code sessions the key is normally present with a literal `null`, and the only non-`null` instance in this repo's fixtures is an empty string on a `message.model == "<synthetic>"` line, which is the harness sentinel described in [Common pitfalls in cost computation](#common-pitfalls-in-cost-computation) (pitfall 12), not a real API response. |
| `message.stop_details` | object \| `null` | **Populated if and only if `stop_reason == "refusal"`**, and `null` for every other stop reason, not "when available". A parser that reads this field without first checking `stop_reason` hits `null` on the overwhelming majority of assistant lines. Documented sub-fields, **not an exhaustive list**: `type` (`"refusal"`); `category`, naming the policy area, one of `"cyber"`, `"bio"`, `"frontier_llm"`, `"reasoning_extraction"`, `"general_harms"`, or `null`; `explanation`, a human-readable description whose text is not stable, so display it rather than parse it; `recommended_model`, present only on requests that set the beta `fallbacks` parameter and `null` otherwise; and `fallback_credit_token` plus `fallback_has_prefill_claim`, both beta-gated and both `null` when no credit is available. A `null` `category`/`explanation` means the refusal mapped to no named category, which is a normal, permanent value rather than a placeholder. A refusal is an HTTP 200 response, not an error, and it arrives in one of two shapes: **before any output**, carrying `content: []` and `output_tokens: 0`, and not billed; or **mid-stream after partial output**, which retains the partial content and _is_ billed for the input plus the output already streamed. Two consequences: anything summing output tokens must not short-circuit refusal lines to zero, since the mid-stream case is the one that costs money; and the docs are explicit that in either shape you should "treat any partial output as incomplete and discard it", so a refusal's content is not a usable model answer. |
| `message.diagnostics` | object | Optional diagnostic metadata. Observed sub-key: `cache_miss_reason` when a cache lookup did not hit. |

Beyond [Common fields](#common-fields), an `assistant` line can carry top-level **API-error markers** (sibling to `message`, not inside it) when the line records a failed API call rather than a real model turn. These are scan-observed (present; values not read):

| Field | Type | Semantics |
|---|---|---|
| `isApiErrorMessage` | boolean | `true` when this `assistant` line is an API-error record, not a real model turn. **Such lines should be excluded from token and turn metrics** — counting them inflates turn counts and (if any usage shape is present) misattributes tokens. |
| `apiError` | object | Error detail for the failed API call, when present. |
| `apiErrorStatus` | number \| string | HTTP-style status of the API error. |
| `error` | (shape not inspected) | Error detail observed alongside the markers above on some error lines. |

The harness/transport-level retry signal that pairs with these errors (`retryInMs`, `retryAttempt`, `maxRetries`, `cause`) lands on `system` lines — see [`system` § API-retry and inline-error fields](#api-retry-and-inline-error-fields).

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

Top-level fields are those listed in [Common fields](#common-fields). Two optional top-level sibling keys are documented here. They share a structural position, not a weight — `toolUseResult` is one of the highest-information surfaces in the format; `toolDenialKind` is a single short label on the few hundred `user` lines that close a denied tool call:

| Field | Type | Semantics |
|---|---|---|
| `toolUseResult` | object (optional) | Tool invocation metadata. Present when the `user` line carries a `tool_result` block AND the underlying tool was a multi-step or context-bearing tool (Agent, Bash, etc.). Sits at the **top level**, beside `message`, not inside `message.content`. Uses camelCase field names (unusual in this otherwise mostly-snake_case format). See [`toolUseResult` envelope](#tooluseresult-envelope) below. |
| `toolDenialKind` | string (optional) | A top-level key, beside `message` rather than inside it, on the `user` line that closes a **denied** tool call. The `tool_result` block on the same line carries `is_error: true`. The value names **who denied the call**: a rule (which includes a hook), the user, or auto mode. Four values are observed; see [`toolDenialKind` values](#tooldenialkind-values) below. It does **not** separate a hook from a settings rule: a `PreToolUse` hook block is labeled `permission-rule`, and only the `tool_result` text names the hook. **233 lines** carry it in [`scan-2026-09-23.json`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/tooling/format-scan/scan-2026-09-23.json), one `tool_result` block per line (the per-line and block-weighted counts agree at 233). Provenance: [`system` § Hook-execution fields](#hook-execution-fields) for the scan; the values table below for the probe. |

#### `toolDenialKind` values

| Value | Who denied | Probe lines | Evidence in the `tool_result` text |
|---|---|---|---|
| `permission-rule` | A hook or a permission rule | 178 | 172 name a hook: 135 say "blocked by … hook", 37 open with the `<Event>:<Tool> hook error:` prefix. Attested by [`hook-trace-denial-and-stop-ladder.jsonl`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/fixtures/sanitized/hook-trace-denial-and-stop-ladder.jsonl) (a `PreToolUse` hook block). |
| `user-rejected` | The user, declining a permission prompt | 75 | 54 carry "user doesn't want to proceed". |
| `automode-blocked` | The auto-mode classifier | 19 | All 19 mention permission. |
| `automode-unavailable` | Auto mode, unable to run (inferred from the name) | 7 | No fixed phrase matched; the name is the only evidence for the meaning. |

**Provenance.** The committed scan folds values against `TOOL_DENIAL_KIND_ALLOWLIST`, which holds only fixture-attested values, so [`scan-2026-09-23.json`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/tooling/format-scan/scan-2026-09-23.json) reports 147 `permission-rule` and 86 `<other>`. The four names and every count in this table come instead from the **denial-kind probe**, [`tooling/format-scan/probes/denial_kind.py`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/tooling/format-scan/probes/denial_kind.py), run on 2026-10-01 over 4,230 files and 550,447 lines (279 lines carrying the key). It prints a value only if it is enum-shaped, tests the first 300 characters of each `tool_result` text against fixed phrases, and prints only the phrase name; its output contract is in its docstring. All 279 lines had `is_error: true`. A rerun the same day with the hardened v0.2.0 (4,238 files) reproduced every figure except one additional `permission-rule` hook denial from newer sessions, and found every denial line carries exactly one `tool_result` block, so the classification above is never of an ambiguous block. [#276](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/276) tracks attesting the other three values with fixtures and adding them to the allowlist, so a committed scan artifact can replace the probe as the source. Until then, the three unattested values are reproducible by running the probe, not from a committed scan.

**Dating.** The earliest version carrying any value is v2.1.199 (`user-rejected`); `permission-rule` first appears at v2.1.201, `automode-blocked` at v2.1.232, `automode-unavailable` at v2.1.246. That fits the Claude Code CHANGELOG at **v2.1.193**, "Added auto-mode denial reasons to the transcript" ([format-watch F-025](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/.claude/specs/research/jsonl-format-watch.md)). First-seen versions in one person's corpus are an upper bound on when a value was introduced, not the introduction itself.

**The `toolDenialKind` row and values table are not covered by this section's v2.1.150 stamp.** Their evidence is the scan and probe above, aggregated across versions, so they neither re-stamp this section nor inherit its banner, and the sweep in [#231](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/231) should leave them alone.

`toolDenialKind` is **user-side**. The top-level tool-linkage keys on `system` lines — `toolUseID` and its relatives — are cataloged separately under [#93](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/93); the two sets do not overlap and neither owns the other's keys.

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
| `usage` | object | Multi-step tools | Token usage for the tool invocation. Same shape as [`message.usage`](#usage-and-token-accounting). **For the Agent tool this is a single-turn snapshot** (the subagent's final turn), not a run total — see `totalTokens` below. |
| `agentId` | string | Agent tool | UUID linking to the subagent trace file at `~/.claude/projects/<slug>/<session-uuid>/subagents/agent-<agentId>.jsonl`. |
| `agentType` | string | Agent tool | The `subagent_type` that ran (matches the `Agent` tool's input). |
| `resolvedModel` | string | Agent tool | The concrete model the **subagent** actually ran, after alias resolution (e.g., `"claude-haiku-4-5-20251001"`) — the child's model, not the parent's (in a sonnet-parent / haiku-child run it reads the haiku id). Lets a parser read the child's model from the parent envelope without opening the trace file. First observed via the Agent SDK probe (SDK 0.2.106 / CLI 2.1.185); tracked as format-watch F-016. |
| `prompt` | string | Agent tool | The prompt passed to the subagent. |
| `totalDurationMs` | number | Agent tool | Wall-clock time the subagent ran. |
| `totalTokens` | number | Agent tool | A **single assistant turn's** token total (the subagent's *final* turn), equal to the sum of the four `usage` fields on this envelope. **Not** cumulative across the run — aggregating it alone undercounts real spend by a median ~5.8x. The four-field-sum identity is confirmed 691/691 against a live corpus. See [`subagent-traces.md` § Token accounting](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/subagent-traces.md#token-accounting). |
| `totalToolUseCount` | number | Agent tool | Number of tool invocations the subagent made **itself** — own-direct, not cumulative. In a multi-level SDK chain it excludes tool calls made by any further subagents that subagent spawned (its own `Agent` call counts, the grandchild's tool calls do not). |
| `toolStats` | object | Agent tool | Tool-activity counters for work the subagent did itself. Every instance observed in real sessions uses **category counters**, not per-tool-name keys — see [`toolStats` shape](#toolstats-shape) below. |
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

> **Four rows above are superseded (2026-08-25, [#210](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/210)).** A v2.1.243 observational scan found no `code` key on `Bash`, no `bytes` or `isImage` on `Read` (whose envelope is nested under a `file` object), and none of `query` / `matches` / `searchCount` / `results` on `Grep` or `Glob`. The corrected per-tool tables, with observed counts, are in [`tool-invocation.md` § The `toolUseResult` envelope by tool](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/tool-invocation.md#the-tooluseresult-envelope-by-tool). Reconciling this union table against that scan is tracked separately; until it lands, prefer the per-tool tables.

This envelope is one of the highest-information surfaces in the format. The Agent-tool subset (`agentId`, `totalDurationMs`, `totalTokens`, `toolStats`, `agentType`, `prompt`) is the most stable and most analyzed — it's what AgentFluent uses for agent-quality diagnostics. Full per-tool walkthroughs live in [`tool-invocation.md`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/tool-invocation.md).

#### `toolStats` shape

**Verified against Claude Code v2.1.150.**

`toolStats` is keyed by **tool category**, not by tool name. Every instance observed in real sessions carries exactly these seven keys:

```json
{
  "readCount": 12,
  "searchCount": 4,
  "bashCount": 7,
  "editFileCount": 3,
  "linesAdded": 118,
  "linesRemoved": 24,
  "otherToolCount": 2
}
```

Two consequences for parsers:

- **There is no per-tool breakdown.** You can tell how many reads a subagent did; you cannot tell how many of those were `Read` versus `Glob`, and MCP tool calls fall into `otherToolCount` without naming the server. For per-tool detail, read the subagent's own trace file (see [Subagent traces](#subagent-traces)).
- **`linesAdded` / `linesRemoved` are not invocation counts.** They are edit magnitude, mixed into the same object as the counters. Summing all values in `toolStats` to get "tool calls" therefore produces a number dominated by line counts. Use `totalToolUseCount` for the invocation total.

An earlier version of this reference documented `toolStats` as keyed by tool name (`{"Read": 4, "Bash": 2}`) and two synthetic fixtures were authored to match. That shape has **not** been observed in any real session. The tool-name form was a documentation error rather than a variant, and the fixtures have been corrected. Issue [#56](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/56) originally hypothesized that the shape varied by `agentType`; the fixture evidence does not support that, since `pm` appears with the category-counter shape in real sessions and the tool-name shape only in the synthetic fixture.

Evidence is thin in absolute terms: three real-session instances across two agent types (`architect`, `pm`). That is enough to retire the tool-name claim, not enough to promise the seven keys are exhaustive across every agent type or every version. Parsers should read keys defensively rather than assuming the set above is closed.

**Multi-level note — the two runtimes differ here.** Both Claude Code (from v2.1.172) and the Agent SDK let a subagent spawn a further subagent, but they record the deeper result differently.

- **Agent SDK:** this whole `toolUseResult` envelope is attached only on the line carrying a **first-level** subagent result. The deeper `Agent` `tool_result` carries **no** `toolUseResult`, only an inline `subagent_tokens: <N>` text trailer in `tool_result.content`. Metrics for a depth-≥2 SDK subagent must be read from that subagent's own trace, not from a parent envelope.
- **Claude Code:** the envelope is present at depth ≥ 2 as well. Every depth-2 spawn site observed in a v2.1.109–v2.1.233 corpus scan carried a full `toolUseResult`, matching the depth-1 controls, so Claude Code cost attribution does not degrade with nesting depth. The observation rests on 6 depth-2 spawn sites, so treat the sample as thin.

Either way, the deeper `tool_result` lives in the **spawning subagent's own trace file**, not the main session transcript. See [`subagent-traces.md` § Multi-level (nested) delegation](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/subagent-traces.md#multi-level-nested-delegation).

See [`anatomy-agent-invocation.jsonl`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/fixtures/synthetic/anatomy-agent-invocation.jsonl) for an end-to-end synthetic Agent invocation including the `toolUseResult` envelope. For the **Agent SDK** form of the same envelope — carrying `resolvedModel`, with `entrypoint: "sdk-py"` and `promptSource: "sdk"` on the surrounding lines — see [`agent-sdk-invocation.jsonl`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/fixtures/synthetic/agent-sdk-invocation.jsonl).

### `system`

**Verified against Claude Code v2.1.170.** Field presence confirmed by a structural scan of local sessions (key names and carrier type only — no field values read). Specific introduction versions are cited inline from the CHANGELOG where known; fields marked scan-observed have a confirmed carrier type but an uninspected value shape.

Session-internal events emitted by Claude Code itself — model switches, tool-registry refreshes, context-compaction boundaries, hook-execution bookkeeping, and transport-level API retries. Most analytics parsers skip `system` lines (they aren't user-visible model or user activity), but several field families on them are the *only* on-disk record of their respective events, which is why `system` is documented here rather than left under [Skipped types](#skipped-types).

Top-level fields are those listed in [Common fields](#common-fields). The long-standing system-specific fields:

| Field | Type | Semantics |
|---|---|---|
| `subtype` | string | Discriminates the kind of system event. Present on every `system` line. Observed values include `"compact_boundary"` (the context-compaction marker — its `compactMetadata`/`logicalParentUuid` payload is documented separately with the conversation-continuity work). |
| `isMeta` | boolean | `true` for internal/meta events that aren't part of the conversation proper. |
| `content` | string | Human-readable description of the event, when present. |
| `durationMs` | number | Duration of the event, for events that measure one (e.g., a registry refresh). |

#### Hook-execution fields

When configured hooks fire, Claude Code records the outcome on a `system` line. This means hook activity **does** leave a JSONL trace — recorded as `system` events — which is the empirical question [Part 6 ("What hooks leave behind," #68)](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/68) was scoped to answer. All fields below are scan-observed (present as a family on the same lines; values not read):

**Provenance for every count in this subsection.** Figures come from [`tooling/format-scan/scan-2026-09-19.json`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/tooling/format-scan/scan-2026-09-19.json) — 3,500 session files, 436,010 lines, 0 parse errors, spanning **130 Claude Code versions, v2.1.4 through v2.1.278**. What this scanner may emit is enumerated in its own `SECURITY CONTRACT` docstring ([`tooling/format-scan/scan.py`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/tooling/format-scan/scan.py)), which is the authority; rather than paraphrase it, note only the part these figures rest on. **None of the keys counted below has its value read.** Each figure is therefore a count of *lines carrying the key*, evidence about presence and never about content. These are **aggregates across 130 versions, not a single-version verification**: v2.1.278 contributes 1,303 of the 350,954 version-bearing lines, the other 85,056 scanned lines carrying no `version` key at all. Do not read them as re-stamping this section, which stays at its v2.1.170 banner pending the sweep in [#231](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/231).

| Field | Type | Semantics |
|---|---|---|
| `hookCount` | number | How many hooks matched and ran for the triggering event. |
| `hookInfos` | array (shape not inspected) | Per-hook execution detail — which hooks ran. |
| `hookErrors` | array (shape not inspected) | Errors raised by hooks during execution. |
| `hasOutput` | boolean | Whether any hook produced output. |
| `preventedContinuation` | boolean | Whether a hook blocked Claude from continuing (a deny/block decision). |
| `stopReason` | string | Why continuation stopped, when a hook prevented it. |
| `hookAdditionalContext` | string | The `additionalContext` string a `Stop`/`SubagentStop` hook injected back into context, recorded on disk. **Not rare — 2,981 `system` lines carry it**, against 3,964 for each of the six other fields in this table and 10,429 `system` lines in the corpus. Read those as three separate line counts, not as a nesting: the scanner tallies each key per line and never joins them, so the 2,981 cannot be shown to sit *inside* the 3,964. The on-disk trace of the hook **response** contract — see [Hook response schema](#hook-response-schema). |

These lines are frequently accompanied by a top-level `toolUseID` linking the hook run to the tool call that triggered it (for `PreToolUse`/`PostToolUse` hooks); the top-level tool-linkage keys are cataloged separately ([#93](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/93)).

#### API-retry and inline-error fields

A second failure/retry signal, distinct from the *tool-call* retry pairing covered in [Tool invocation pattern](#tool-invocation-pattern) and the shipped retry aside. These record **transport/model-level** API retries (backoff) and inline failures captured by the harness. Scan-observed:

| Field | Type | Semantics |
|---|---|---|
| `retryInMs` | number | Backoff delay before the harness retries the API call. |
| `retryAttempt` | number | Which retry attempt this is. |
| `maxRetries` | number | Configured maximum number of retry attempts. |
| `cause` | string | Cause detail for a failure recorded on the line. |
| `error` | (shape not inspected) | Error detail, when the system event records a failure. |

The companion inline API-error signal on `assistant` lines (`isApiErrorMessage`, `apiError`, `apiErrorStatus`) is documented in the [`assistant`](#assistant) section. Both matter to anyone computing success/failure rates or separating real model turns from error turns.

---

### `pr-link`

**Verified against Claude Code v2.1.150–v2.1.152.** The `pr-link` line itself carries no `version` field; the range is that of the sessions the observed lines appeared in.

Associates a session with a GitHub pull request. Documented here rather than under [Skipped types](#skipped-types) because it is the only field family in the format that records an **exact** session-to-outcome identity. Every other route from a session to what it produced (matching `cwd` + `gitBranch` + `timestamp` against commit history) is a branch-and-time-window heuristic that yields a candidate, not an identity.

```json
{
  "type": "pr-link",
  "sessionId": "0f2c8b1e-...",
  "prNumber": 128,
  "prUrl": "https://github.com/<owner>/<repo>/pull/128",
  "prRepository": "<owner>/<repo>",
  "timestamp": "2026-06-08T17:42:11.903Z"
}
```

| Field | Type | Semantics |
|---|---|---|
| `sessionId` | string | The session this PR is associated with. |
| `prNumber` | number | PR number within `prRepository`. |
| `prUrl` | string | Full URL to the pull request. |
| `prRepository` | string | `owner/repo` slug. |
| `timestamp` | string (ISO 8601 UTC) | When the line was written. |

Notes for parsers:

- **The line is minimal.** It carries no `uuid`, `parentUuid`, `cwd`, `gitBranch`, `version`, or `userType` — none of the [Common fields](#common-fields) except `sessionId`, `timestamp`, and `type`. Code that assumes the common envelope on every line will fault here.
- **Multiple lines per session per PR are expected.** Observed sessions carry several `pr-link` lines with the same `prNumber` at different `timestamp`s. Deduplicate on `prNumber` before counting; do not treat the line count as a PR count.
- **Trigger is partially confirmed.** The observed instances come from sessions that *opened* a PR during the session. Whether `claude --from-pr <n>` also emits the line on entry has not been confirmed against a fixture, so treat "written whenever a session opens a PR" as verified and "written on `--from-pr` entry" as unverified.

Why it matters: from a `prNumber` the whole GitHub surface — reviews, CI status, merge outcome, post-merge issue references — becomes a direct lookup rather than an inference. Its **absence** is also informative, since a session that opened its PR outside the tool leaves only the heuristic path.

---

## Skipped types

**Verified against Claude Code v2.1.150.**

Several message types appear in session JSONL but are typically ignored by analytics parsers — they're either metadata, streaming events, or auxiliary state that doesn't represent model or user activity directly. Whether to parse them depends on the use case.

| `type` value | What it is | Why most parsers ignore it | When you'd want to parse it |
|---|---|---|---|
| `file-history-snapshot` | A snapshot of file state at a checkpoint. Top-level `snapshot.trackedFileBackups` field carries the file contents before each edit. **This is the data structure that powers `/rewind`'s "restore code" capability.** | Not relevant to token or tool analysis. | Anything that wants to reproduce or analyze `/rewind` semantics, or audit which files Claude edited and when. |
| `system` | System events (Claude Code internal): model switches, tool-registry refreshes, compaction boundaries, **hook-execution records**, and **API-retry/error records**. Now documented in its own [`system` section](#system) rather than treated as skippable. | Mostly not user-visible activity. | Reading hook outcomes, API-retry/error records, and compaction boundaries; diagnosing internal session behavior. |
| `permission-mode` | A snapshot of the session's permission mode, not a change event. Fields: `permissionMode`, `sessionId`, `type`, and nothing else: no `timestamp`, `uuid`, `parentUuid`, `cwd`, `version` or `gitBranch`. In the [hook-trace fixtures](https://github.com/frederick-douglas-pearce/claude-code-sessions/tree/main/fixtures/sanitized) (v2.1.278–v2.1.280) one is written ahead of every prompt, right after a `mode` line, repeating the value even when nothing changed. 6,783 lines in [`scan-2026-09-23.json`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/tooling/format-scan/scan-2026-09-23.json). | Session-state metadata, not activity. With no envelope it can be placed only by its position in the file. | Auditing permission posture. For a timestamped value, read `permissionMode` on the prompt's `user` line instead: 5,493 `user` lines carry it in the same scan, and in the fixtures every prompt line does and no tool-result line does. |
| `mode` | The same envelope-free shape, carrying `mode` instead: fields `mode`, `sessionId`, `type`. In the fixtures it sits immediately before each `permission-mode` line and always holds `"normal"`. Its other values and what it tracks are unverified. 14,929 lines in the same scan, more than twice the `permission-mode` count, so the two are not always paired. | Session-state metadata. | Not yet clear, until its values are characterized. |
| `ai-title` | The auto-generated session title shown in the resume picker. Fields: `aiTitle`, `sessionId`, `type`. | Display metadata. | Building a session index outside Claude Code; recovering display names for archived sessions. |
| `last-prompt` | A pointer to the most recent user prompt in the session, used by the resume picker. Fields: `lastPrompt`, `leafUuid`, `sessionId`, `type`. | Index metadata, not activity. | Rebuilding picker-like UI on top of session files. |
| `attachment` | An attachment associated with a message (e.g., a pasted file or image). Carries the standard line envelope fields plus `attachment`. | Often referenced by adjacent user/assistant messages. | Recovering full multimodal session context; auditing what context was attached to which turn. |
| `queue-operation` | Internal operation queue state. Fields: `content`, `operation`, `sessionId`, `timestamp`, `type`. | Internal scheduling state. | Debugging session orchestration. |
| `progress` | Streaming progress events. | High-volume streaming chatter. | Real-time monitoring; debugging long-running tool calls. |
| `hook_progress` | Streaming progress events from hooks. | High-volume streaming chatter. | Debugging hooks. |
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

Note that **the actionable tool metadata is NOT in `tool_result`** — it's in the sibling [`toolUseResult` envelope](#tooluseresult-envelope) at the top level of the same line. Tools that produce metadata (Agent, Bash, etc.) populate `toolUseResult`; tools that don't (e.g., simple Reads) often leave `toolUseResult` minimal or absent. **Some `user` lines carrying this block also carry a top-level [`toolDenialKind`](#user) key.** Treat it as an addition rather than a redirection, and keep checking `is_error` here; the scan counts keys and cannot say what this block carries.

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

A full walkthrough — covering edge cases like interrupted tool calls, parallel tool invocations, and the subagent trace file's relationship to the parent envelope — lives in [`tool-invocation.md`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/tool-invocation.md).

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

**Verified against Claude Code v2.1.150.** Cost semantics (the cache-write TTL split, per-request multipliers, and server-tool surcharges) cross-checked against Anthropic's [pricing page](https://platform.claude.com/docs/en/about-claude/pricing) and a sibling-project (AgentFluent) cost audit on 2026-06-26; rates and multipliers are external and volatile, so re-confirm against the live pricing page before relying on them.

Token accounting lives on `message.usage` (for `assistant` lines) and on `toolUseResult.usage` (for context-bearing tool rollups, including subagent invocations). Both objects share the same shape. This section is the field index; [`cost-model.md`](cost-model.md) is the full cost reference (the complete lever catalog, per-model rate tables, stacking rules, and a worked example).

| Field | Type | Semantics |
|---|---|---|
| `input_tokens` | number | Tokens consumed reading the prompt and prior conversation. |
| `output_tokens` | number | Tokens generated in the response. |
| `cache_creation_input_tokens` | number | Tokens written to the prompt cache during this turn. Billed at a **premium** vs. regular input, and the premium depends on the cache TTL (see `cache_creation`). This flat field is the **sum** of the per-TTL counts in `cache_creation`. |
| `cache_read_input_tokens` | number | Tokens read from the prompt cache. Billed at roughly **0.1×** regular input. |
| `cache_creation` | object | Per-TTL breakdown of cache writes. Sub-keys: `ephemeral_5m_input_tokens` (5-minute TTL, ~**1.25×** input) and `ephemeral_1h_input_tokens` (1-hour TTL, ~**2×** input). Pricing the flat `cache_creation_input_tokens` at a single 1.25× rate **under-reports** whenever 1-hour writes are present; in Claude Code sessions the 1-hour TTL is commonly the dominant share. When this sub-object is absent (older sessions), treat the full count as 5-minute. |
| `output_tokens_details` | object | Breakdown of `output_tokens`. Sub-key `thinking_tokens` counts extended-thinking tokens, which are **already included** in `output_tokens` and billed at the output rate — do not add them on top (see pitfall 9). |
| `service_tier` | string | Billing tier that served the request: `"standard"`, `"priority"` (commitment pricing), or `"batch"` (~**0.5×** input & output). Non-standard tiers are priced differently; check before applying a flat rate. |
| `speed` | string | Inference speed: `"standard"` or `"fast"`. `"fast"` (fast mode) uses premium flat rates that stack on top of caching and data-residency multipliers. |
| `inference_geo` | string | Data-residency region: `"global"` (default), `"us"` (**1.1×** on all token categories, Opus 4.6 / Sonnet 4.6 and later), `"not_available"`, or `""`. |
| `server_tool_use` | object | Counts of server-side tool calls, billed as **separate line items** (not token rates): `web_search_requests` ($10 / 1,000), `web_fetch_requests` (free), and `code_execution_requests` (billed by container-hour against a monthly org-level free tier — the count is here, but the duration and dollar cost are not). |
| `iterations` | number \| array | Internal iteration metadata. Recorded here historically as a scalar count; a 2026-06-26 sibling-project audit instead observed an `iterations[]` **array** repeating the per-message `usage` fields, with the top-level `usage` as the billable rollup. Treat the shape as unsettled and confirm against a current session before relying on it (tracked in [#140](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/140)). |

### `usage` is per-request: context recurs every turn

`message.usage` (and the `toolUseResult.usage` snapshot) is **per API request, not cumulative.** The Messages API is [stateless](https://platform.claude.com/docs/en/build-with-claude/working-with-messages), so Claude Code re-sends the full conversation history on every turn. Two consequences underlie most token-accounting errors against this format, including the subagent-rollup trap in [`subagent-traces.md` § Token accounting](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/subagent-traces.md#token-accounting):

- **`cache_read_input_tokens` recurs and grows turn over turn.** Each turn re-reads the accumulated prefix from cache, so a long conversation re-reports most of its context every turn (at the ~0.1× cache-read rate). Summing per-turn `usage` across a run therefore yields **tokens processed** — the correct basis for cost, since you are genuinely billed each turn for those re-reads — which is far larger than the conversation's final **context size**. A single turn's `usage` yields the context size; the two are different quantities answering different questions. Reading a single-turn snapshot as a run total is what makes the subagent `totalTokens` rollup undercount by a median ~5.8x.
- **Streaming writes multiple `assistant` lines per logical turn.** As a response streams, Claude Code emits several `assistant` lines sharing one `message.id`, each carrying a *running snapshot* of `usage`, not an increment. Summing every `assistant` line double-counts (measured at ~2x on real corpora). Deduplicate first: group `assistant` lines by `message.id`, keep the record with the **greatest `output_tokens`** (the most complete snapshot), and take **all four** usage fields from that same record — never a per-field max across records. Note `input_tokens` is often a placeholder (0–3) on non-final chunks, so never read it off an arbitrary chunk.

### Common pitfalls in cost computation

Token totals are the **raw inputs** to cost computation, not the cost itself. Several gotchas:

1. **Pricing varies by model.** Sonnet, Opus, and Haiku each have different per-million-token rates for input and output. The `message.model` field on each `assistant` line is required for accurate per-line cost computation.
2. **Cache reads are billed at a fraction; cache creation at a premium.** A line with high `cache_read_input_tokens` and low `input_tokens` may be much cheaper than a line with the inverse — even though the total "input volume" is similar.
3. **The subagent rollup is one turn, not a run total.** The parent's `toolUseResult.usage` / `totalTokens` snapshots a **single** assistant turn (the subagent's final turn), whereas the subagent's real spend is the sum of **all** its per-turn `message.usage` in the trace file (deduped by `message.id`). Aggregating from the rollup alone **under**counts processed tokens by a median ~5.8x. Use the trace's per-turn sum for spend; treat the rollup only as an explicitly labeled context-size proxy. (This corrects earlier guidance that framed these as "the same tokens counted twice" — the error is an undercount, not a double-count.) See [`subagent-traces.md` § Token accounting](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/subagent-traces.md#token-accounting).
4. **The subagent rollup has tokens but no model.** The parent-side rollup (`toolUseResult.usage`) carries the subagent's token snapshot and its `service_tier`, but **not** the model the subagent ran on. Because per-token rates are per-model, the rollup cannot be priced on its own. To price a subagent's tokens, read `message.model` from the subagent trace file and price **per turn** — a subagent may run on a different model than its parent, or on more than one. See [`subagent-traces.md` § Token accounting](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/subagent-traces.md#token-accounting).
5. **Cache fields are zero on the first turn.** A fresh session starts with no cache; `cache_creation_input_tokens` and `cache_read_input_tokens` are zero on the first `assistant` line.
6. **`service_tier` affects pricing.** Priority tier and other non-standard tiers have different rates; check the field before applying a flat per-model price.
7. **API-error lines are not real turns.** An `assistant` line flagged `isApiErrorMessage: true` (see [`assistant`](#assistant)) records a failed API call, not a model response. Exclude these from both token aggregation and turn/success-rate counts — naive aggregation that includes them inflates turn counts and can misattribute tokens.
8. **Cache writes are not a single rate.** `cache_creation_input_tokens` is the sum of two TTLs that price differently: 5-minute (~1.25×) and 1-hour (~2×), broken out in `cache_creation`. The 1-hour TTL is commonly the dominant share in Claude Code sessions, so pricing the flat field at 1.25× under-reports. Use the `cache_creation` sub-object; fall back to treating the full count as 5-minute only when it is absent.
9. **Thinking tokens are already counted in `output_tokens`.** `output_tokens_details.thinking_tokens` is a subset of `output_tokens`, not an additional charge. Adding it on top double-counts; it is billed at the output rate as part of `output_tokens`.
10. **The tokenizer changed in Opus 4.7+.** The newer tokenizer can produce up to ~35% more tokens for the same text. This is a **count** effect, already reflected in `usage.*_tokens` — do not apply it as a separate multiplier.
11. **Per-request multipliers beyond model and tier.** `speed: "fast"` (fast mode, premium flat rates), `inference_geo: "us"` (1.1× on all token categories), and `service_tier: "batch"` (0.5×) each change the effective rate and stack per the [pricing page](https://platform.claude.com/docs/en/about-claude/pricing)'s rules. A cost computation that reads only `model` + `service_tier` misses fast mode and data residency.
12. **Skip `<synthetic>` model lines before pricing.** `message.model == "<synthetic>"` is a Claude Code sentinel for internal messages, not a real API call. Pricing it against a rate table is meaningless; exclude it.
13. **Server-side tool calls are separate line items.** `server_tool_use` counts (web search at $10/1,000, code execution by container-hour) are billed outside the per-token rates. The session records the counts; the dollar cost of code execution (a duration against a monthly org-level free tier) is **not** reconstructable from a single session.

Tools like [AgentFluent](https://github.com/frederick-douglas-pearce/agentfluent) and [CodeFluent](https://github.com/frederick-douglas-pearce/codefluent) handle this properly. For one-off cost estimates, the per-line `usage` object is the data; turning it into dollars requires the model name, the service tier, the cache-write TTL split, any per-request multipliers (fast mode, data residency, batch), and an external pricing table kept current. The multipliers above are relative and change less often than absolute rates, but confirm both against the live [pricing page](https://platform.claude.com/docs/en/about-claude/pricing) before relying on them.

---

## Hook event fields

**Verified against [Claude Code hook documentation](https://code.claude.com/docs/en/hooks) and the CHANGELOG as of 2026-10-10 (Claude Code v2.1.296), for the whole section: implementation types, common fields, every event row, and the response schema. Each row was checked against that event's input section in the docs, not only its summary table.**

Hook events are an **outbound JSON contract**. When a configured event fires, Claude Code sends each hook attached to it a JSON payload. The payload is the same whatever the hook is, but how it arrives depends on the hook's implementation type: on stdin for a `command` hook, as the request body for an `http` hook, interpolated into the prompt for a `prompt` or `agent` hook, and substituted into the tool input for an `mcp_tool` hook. See [Hook implementation types](#hook-implementation-types). Hook events are NOT session JSONL message lines. The one exception is the `file-history-snapshot` *message type* (see [Skipped types](#skipped-types)), which is a session line, not a hook event, despite sounding hook-related.

(Hook *firings* are nonetheless recorded in the session JSONL — as bookkeeping fields on `system` lines, separate from this outbound contract. See [`system` § Hook-execution fields](#hook-execution-fields).)

This section documents the outbound JSON shape Claude Code sends to hooks, and — newly — the shape hooks can send **back**. For configuration syntax and matcher semantics, see Claude Code's hooks documentation directly.

### Hook implementation types

A hook's `type` in its settings entry decides what runs, how the payload reaches it, and how it answers. Claude Code supports five. The same five are the documented values of the `hook_type` attribute on the [`claude_code.hook_registered`](https://code.claude.com/docs/en/monitoring-usage) OpenTelemetry event.

| `type` | What runs | Payload delivery | How it answers | Landed |
|---|---|---|---|---|
| `command` | A shell command | JSON on stdin | Exit code, stdout and stderr. See [Hook response schema](#hook-response-schema) | v1.0.38 (hooks released) |
| `http` | A POST to a URL | The request body, `Content-Type: application/json` | A 2xx response whose body uses the same JSON output schema as a `command` hook's stdout. A non-2xx status, a failed connection, or a 2xx body that is neither empty nor a JSON object is a non-blocking error, so a status code alone cannot block | v2.1.63 |
| `mcp_tool` | A tool on a connected MCP server | `${path}` substitution from the payload into string values of the tool's `input`, e.g. `"${tool_input.file_path}"` | The tool's text content, parsed the way a `command` hook's stdout is on exit 0. `isError: true` is a non-blocking error | v2.1.118 |
| `prompt` | A single call to a Claude model, by default the one Claude Code uses for background work; `model` overrides it | The `$ARGUMENTS` placeholder in the hook's `prompt`. Without the placeholder, the payload is appended to the prompt | JSON from the model: `{"ok": true}` to allow, `{"ok": false, "reason": "..."}` to block. What `ok: false` does varies by event | v2.0.30 (prompt-based Stop hooks); `model` field v2.0.41 |
| `agent` | A subagent that can use tools such as Read, Grep and Glob for up to 50 turns. The docs mark it experimental | `$ARGUMENTS`, as for `prompt` | The same `{ok, reason}` schema as `prompt` | Plugin support v2.1.0; the CHANGELOG does not record when settings first accepted it |

Not every event accepts every type. Per the hooks docs as of 2026-10-10:

- **All five types:** `PreToolUse`, `PostToolUse`, `PostToolUseFailure`, `PostToolBatch`, `PermissionDenied`, `UserPromptSubmit`, `UserPromptExpansion`, `Stop`, `SubagentStop`, `TaskCreated`, `TaskCompleted`, `TeammateIdle`.
- **All but `agent`:** `PermissionRequest`. An `agent` hook configured there is skipped.
- **`command` and `mcp_tool` only:** `SessionStart`, `Setup`. Both fire before MCP servers are available at launch, so Claude Code skips an `mcp_tool` hook on every `Setup` and on the launch `SessionStart`. A later `SessionStart`, after `/clear` or a compaction, runs it.
- **`command`, `http` and `mcp_tool`:** the remaining eighteen events.

### Common fields (all events)

Hook event payloads carry these fields alongside the event-specific ones. Fields marked optional are absent on some events or in some sessions:

| Field | Type | Semantics |
|---|---|---|
| `session_id` | string | The session UUID. Matches `sessionId` in JSONL lines. |
| `prompt_id` | string (optional) | UUID of the user prompt being processed. Matches the `prompt.id` attribute on OpenTelemetry events. Whether it equals `promptId` on JSONL lines is not documented or yet observed. Absent until the first user input. |
| `transcript_path` | string | Absolute path to the session JSONL on disk. The file is written asynchronously, so it can lag the current turn when the hook fires. `Stop` and `SubagentStop` carry `last_assistant_message` for that reason. |
| `cwd` | string | Working directory when the hook fired. |
| `scratchpad_dir` | string (optional) | The session's scratchpad directory. Absent when the session has none. Requires v2.1.257 or later. |
| `hook_event_name` | string | The event type that fired (e.g., `"PreToolUse"`). |
| `permission_mode` | string (optional) | Current permission mode: `"default"`, `"plan"`, `"acceptEdits"`, `"auto"`, `"dontAsk"`, or `"bypassPermissions"`. The mode labeled **Manual** arrives as `"default"`. Not all events receive this. |
| `effort` | object (optional) | `{level: "low"\|"medium"\|"high"\|"xhigh"\|"max"}`, the level actually in effect, which can differ from the one requested when the model does not support it. Present for tool-use context events when the current model supports the effort parameter. Also exposed as `$CLAUDE_EFFORT`. |
| `agent_id` | string (optional) | Subagent UUID when the hook fires inside a subagent call. On `TaskCreated`, `TaskCompleted` and `TeammateIdle` it can also identify an in-process teammate (v2.1.290 or later). |
| `agent_type` | string (optional) | Agent name when running with `--agent` or inside a subagent. Inside a subagent, the subagent's type wins over the session's `--agent` value. |

Only `SessionStart` can carry a `model` field. `PreModelSwitch` and `PostModelSwitch` carry `from_model` and `to_model` instead.

### Event types and event-specific fields

Each row lists the event name, when it fires, and fields **beyond** the common set. Matcher syntax is documented in Claude Code's hooks docs.

| Event | When | Event-specific fields |
|---|---|---|
| `SessionStart` | Session begins or resumes | `source` (`"startup"`, `"resume"`, `"clear"`, `"compact"`, `"fork"`), `model` (optional; can be omitted, e.g. after `/clear`), `agent_type` (if `--agent`), `session_title` (if a custom title is set). On `"resume"` or `"fork"` with at least one prior response, also `seconds_since_last_response`, `context_tokens`, `prompt_cache_likely_expired`, `estimated_cache_write_usd` |
| `Setup` | `claude --init-only` or `claude -p --init/--maintenance` | `trigger` (`"init"`, `"maintenance"`) |
| `UserPromptSubmit` | User submits a prompt, before processing. Also fires on turns Claude Code starts on its own | `prompt` (pasted-text placeholders arrive expanded), `session_title` (if a custom title is set) |
| `UserPromptExpansion` | User-typed command expands into a prompt (slash command, MCP prompt) | `expansion_type` (`"slash_command"`, `"mcp_prompt"`), `command_name`, `command_args`, `command_source`, `prompt` |
| `PreToolUse` | Before a tool call executes. Not fired for `EndConversation` | `tool_name`, `tool_input` (tool-specific schema; file-tool paths always absolute), `tool_use_id`, `mcp_server` (MCP tools only: `{name, source}`) |
| `PermissionRequest` | Claude Code is about to ask for permission, or would auto-deny a call that cannot prompt | `tool_name`, `tool_input`, `permission_suggestions` (optional array of permission updates), `mcp_server` (MCP tools only). No `tool_use_id` |
| `PermissionDenied` | Auto mode denies a tool call, including denials without a classifier verdict | `tool_name`, `tool_input`, `tool_use_id`, `reason`, `mcp_server` (MCP tools only) |
| `PostToolUse` | After a tool call succeeds | `tool_name`, `tool_input`, `tool_use_id`, `tool_response` (the tool's structured output object), `duration_ms` (optional), `mcp_server` (MCP tools only) |
| `PostToolUseFailure` | After a tool that started executing fails | `tool_name`, `tool_input`, `tool_use_id`, `error` (string; for Bash and PowerShell the first line is `Exit code N`), `is_interrupt` (optional), `duration_ms` (optional), `mcp_server` (MCP tools only) |
| `PostToolBatch` | Full batch of parallel tool calls resolves, before next model call | `tool_calls` (array of `{tool_name, tool_input, tool_use_id, tool_response}`; here `tool_response` is the serialized `tool_result` content the model sees, not `PostToolUse`'s structured object) |
| `Stop` | Claude finishes responding. Not on user interrupt; API errors fire `StopFailure` | `stop_hook_active`, `last_assistant_message`, `background_tasks` (array of `{id, type, status, description, ...}`), `session_crons` (array of `{id, schedule, recurring, prompt}`) |
| `StopFailure` | Turn ends due to API error | `error` (`"rate_limit"`, `"overloaded"`, `"authentication_failed"`, `"oauth_org_not_allowed"`, `"account_on_hold"`, `"billing_error"`, `"invalid_request"`, `"model_not_found"`, `"server_error"`, `"max_output_tokens"`, `"cloud_credential_error"`, `"unknown"`), `error_details` (optional), `last_assistant_message` (optional; the rendered API error string, not Claude's output) |
| `SubagentStart` | Subagent spawned or resumed, or an in-process teammate handles a new message | `agent_id`, `agent_type` |
| `SubagentStop` | Subagent finishes, including Claude Code's internal agents (where `agent_type` can be `""`) | `stop_hook_active`, `agent_id`, `agent_type`, `agent_transcript_path`, `last_assistant_message`, `background_tasks`, `session_crons` (both scoped to the parent session) |
| `TaskCreated` | A task is being created via `TaskCreate` | `task_id`, `task_subject`, `task_description` (optional), `teammate_name` (optional), `team_name` (optional, deprecated) |
| `TaskCompleted` | A task is being marked completed, via `TaskUpdate` or when a teammate ends its turn with in-progress tasks | `task_id`, `task_subject`, `task_description` (optional), `teammate_name` (optional), `team_name` (optional, deprecated) |
| `TeammateIdle` | Agent team teammate about to go idle | `teammate_name`, `team_name` (deprecated) |
| `InstructionsLoaded` | A CLAUDE.md or `.claude/rules/*.md` file is loaded into context | `file_path`, `memory_type` (`"User"`, `"Project"`, `"Local"`, `"Managed"`), `load_reason` (`"session_start"`, `"nested_traversal"`, `"path_glob_match"`, `"include"`, `"compact"`), `globs` (optional), `trigger_file_path` (optional), `parent_file_path` (optional) |
| `ConfigChange` | A settings, managed-policy, or skill file changes during the session | `source` (`"user_settings"`, `"project_settings"`, `"local_settings"`, `"policy_settings"`, `"skills"`), `file_path` (optional) |
| `CwdChanged` | Working directory changes | `old_cwd`, `new_cwd` |
| `DirectoryAdded` | A working directory is added mid-session with `/add-dir` or the SDK `register_repo_root` control request. Not fired for `--add-dir` at startup, which `SessionStart` covers. Cannot block; the add has already happened (CHANGELOG v2.1.219) | `directory`, `source` (`"slash_command"`, `"register_repo_root"`) |
| `FileChanged` | A watched file changes on disk, whatever changed it | `file_path`, `event` (`"change"`, `"add"`, `"unlink"`) |
| `WorktreeCreate` | A worktree is being created (`--worktree`, `isolation: "worktree"`, or a background session). A hook replaces the default `git worktree` behavior and must return the path | `name` (worktree slug) |
| `WorktreeRemove` | A worktree that a `WorktreeCreate` hook created is being removed | `worktree_path` |
| `PreCompact` | Before context compaction | `trigger` (`"manual"`, `"auto"`), `custom_instructions` (string, or `null`) |
| `PostCompact` | After context compaction completes | `trigger` (`"manual"`, `"auto"`), `compact_summary` |
| `PreModelSwitch` | Before Claude Code applies a model switch that you or a client requested. Can block the switch (CHANGELOG v2.1.251) | `from_model`, `to_model`, `requested_model` (string, or `null` for the default model), `source` (`"command"`, `"picker"`, `"sdk"`), `context_tokens`, `prompt_cache_warm`, `cache_ttl` (`"5m"`, `"1h"`), `estimated_cache_write_usd`, `pricing` (`"configured"`, `"catalog"`, `"default"`) |
| `PostModelSwitch` | After the session's model changes, including changes Claude Code makes itself. Cannot block (CHANGELOG v2.1.251) | The `PreModelSwitch` fields, with two more `source` values: `"auto"` (a fallback or other change Claude Code made) and `"resume"` (the model restored on resume) |
| `Elicitation` | An MCP server requests user input during a tool call | `mcp_server_name`, `message`, `mode` (optional: `"form"`, `"url"`), `url` (optional, URL mode), `elicitation_id` (optional), `requested_schema` (optional, form mode) |
| `ElicitationResult` | User responds to an MCP elicitation, before the response goes back to the server. Not fired when an `Elicitation` hook answered | `mcp_server_name`, `action` (`"accept"`, `"decline"`, `"cancel"`), `mode` (optional), `elicitation_id` (optional), `content` (optional, the submitted values) |
| `MessageDisplay` | While assistant message text streams to the screen, once per batch of completed lines; once per message in `claude -p` and Agent SDK runs. Display-only: a hook can replace the on-screen text with `displayContent`, but the transcript and what Claude sees keep the original (CHANGELOG v2.1.152) | `turn_id`, `message_id` (not the API `msg_…` id, so it does not join to transcript message ids), `index`, `final`, `delta` |
| `Notification` | Claude Code sends a notification | `notification_type` (`"permission_prompt"`, `"idle_prompt"`, `"auth_success"`, `"elicitation_dialog"`, `"elicitation_url_dialog"`, `"elicitation_complete"`, `"elicitation_response"`, `"agent_needs_input"`, `"agent_completed"`, `"quota_auto_resume_fired"`, `"quota_auto_resume_stale"`, `"quota_auto_resume_disabled"`), `message`, `title` (optional) |
| `SessionEnd` | Session terminates | `reason` (`"clear"`, `"resume"`, `"logout"`, `"prompt_input_exit"`, `"other"`) |

`post-session` is not a Claude Code hook event, although an earlier version of this table listed it as one. It is a [self-hosted runner lifecycle hook](https://code.claude.com/docs/en/self-hosted-environments-configuration#post-session): an executable named `post-session` in the runner's `--hooks-dir`, which the runner runs on the host after the Claude Code process exits and before it tears the workspace down. It gets no JSON payload. The runner passes context in environment variables such as `CLAUDE_RUNNER_SESSION_ID` and `CLAUDE_RUNNER_EXIT_REASON` (`completed`, `failed`, `interrupted`, and a reserved `abandoned`), and its exit status never affects the session. It is not configured in `settings.json`; the docs call lifecycle hooks "distinct from Claude Code hooks, which run inside the session." Its sibling lifecycle hooks are `checkout` and `spawn-runner`.

### Hook response schema

How a hook answers depends on its [implementation type](#hook-implementation-types). A `command` hook answers with its exit code. Exit 0 is success, and Claude Code parses stdout for JSON. Exit 2 is a blocking error on events that can block, with stderr as the message. Any other code, including the conventional Unix failure code 1, is a non-blocking error and execution continues. `http` and `mcp_tool` hooks return the same JSON output schema through a response body or a tool result. `prompt` and `agent` hooks return the `{ok, reason}` verdict instead and cannot set the fields below.

The JSON output can carry a `hookSpecificOutput` object. The first named key documented in that payload:

| Field | Returned by | Semantics |
|---|---|---|
| `hookSpecificOutput.additionalContext` | `Stop`, `SubagentStop`; per the hooks docs as of 2026-10-10 also `SessionStart`, `SubagentStart`, `UserPromptSubmit`, `UserPromptExpansion`, `PreToolUse`, `PostToolUse`, `PostToolUseFailure`, `PostToolBatch` and `PostModelSwitch` | Extra context the hook injects into the model's context. On `Stop` and `SubagentStop` it lands when the turn would otherwise stop (added in CHANGELOG v2.1.163). Lets a `Stop` hook **feed information forward** — e.g., "you still have unfinished tasks" — instead of only allowing or blocking the stop. |

When a `Stop` or `SubagentStop` hook returns `additionalContext`, the injected string is recorded on the corresponding `system` line as the `hookAdditionalContext` field (see [`system` § Hook-execution fields](#hook-execution-fields)) — the on-disk trace of this response contract. The `additionalContext` key name is changelog-reported; the `hookAdditionalContext` carrier on `system` lines is scan-observed.

### Version-specific notes

The Claude Code hooks documentation does not keep a per-field version history. The table above is the contract as of 2026-10-10. Where the docs or the CHANGELOG date a field, that date is below.

| Field or value | Event | Landed |
|---|---|---|
| `agent_id`, `agent_transcript_path` | `SubagentStop` | v2.0.42 (CHANGELOG) |
| `last_assistant_message` | `Stop`, `SubagentStop` | v2.1.47 (CHANGELOG) |
| `duration_ms` | `PostToolUse`, `PostToolUseFailure` | v2.1.119 (CHANGELOG) |
| `background_tasks`, `session_crons` | `Stop`, `SubagentStop` | v2.1.145 (CHANGELOG) |
| `source: "fork"` | `SessionStart` | v2.1.214 (docs). Forked sessions reported `"resume"` before that |
| `reason: "bypass_permissions_disabled"` | `SessionEnd` | Removed in v2.1.234 (docs) |
| `quota_auto_resume_*` notification types | `Notification` | v2.1.234 (docs) |
| `seconds_since_last_response`, `context_tokens`, `prompt_cache_likely_expired`, `estimated_cache_write_usd` | `SessionStart` | v2.1.251 (docs) |
| `scratchpad_dir` | common | v2.1.257 (docs) |
| `mcp_server` | `PreToolUse`, `PermissionRequest`, `PermissionDenied`, `PostToolUse`, `PostToolUseFailure` | v2.1.274 (docs) |
| `agent_id` for in-process teammates | `TaskCreated`, `TaskCompleted`, `TeammateIdle` | v2.1.290 (docs) |

The W3 roadmap (issue #7) flagged `duration_ms` (v2.1.119) and `background_tasks`/`session_crons` (v2.1.145) as unplaced version-specific additions. Both are event-specific, not common fields, and are in the rows above.

**Corrected on 2026-10-10 ([issue #293](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/293)).** The 2026-05-26 pass recorded field names that the hooks docs do not use. None of the old names appears in the CHANGELOG either, so they read as errors in that pass rather than upstream renames. Code written against the old table should switch:

| Event | Old name in this table | Documented name |
|---|---|---|
| `SessionEnd` | `end_reason` | `reason` |
| `StopFailure` | `error_type`, `error_message` | `error`, `error_details`; plus `last_assistant_message` |
| `FileChanged` | `change_type` (`created`/`modified`/`deleted`) | `event` (`add`/`change`/`unlink`) |
| `TaskCreated`, `TaskCompleted` | `task_title`; `completion_status` (`TaskCompleted`) | `task_subject`; no status field |
| `ConfigChange` | `config_source`, `changed_keys` | `source`, `file_path`; no changed-keys field |
| `WorktreeCreate` | `worktree_name`, `base_path` | `name`; no base-path field |
| `SubagentStart` | `initial_prompt` | none; only `agent_id` and `agent_type` |
| `SubagentStop` | `result` | `last_assistant_message`, among others |
| `Elicitation` | `server`, `form_schema`, `form_description` | `mcp_server_name`, `requested_schema`, `message` |
| `ElicitationResult` | `server`, `form_schema`, `user_response` | `mcp_server_name`, `content`, `action` |
| `PostToolUse` | `tool_result` | `tool_response` |
| `TeammateIdle` | `reason` | `team_name` |
| `Stop` | listed as common fields only | `stop_hook_active`, `last_assistant_message`, `background_tasks`, `session_crons` |

The same pass also listed `post-session` as an event. It is a self-hosted runner lifecycle hook; see the note under the event table.

---

## Format version notes

When [`format-version-history.md`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/format-version-history.md) is created (not yet started; see [`reference/README.md`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/README.md)), this section will cross-reference it. Every field documented above that has version-specific behavior — addition, rename, removal — will gain a footnote linking to its history entry.

Until that doc exists, version-specific behavior is captured inline in the relevant section's text (see, e.g., the [Version-specific notes](#version-specific-notes) under Hook event fields).
