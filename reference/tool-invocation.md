# Tool Invocation

The canonical walkthrough of the `tool_use` → `tool_result` cycle in Claude Code's JSONL session format: how the pairing works, what the sibling `toolUseResult` envelope carries per tool, how the `Agent` tool differs, and how to parse error and parallel-call patterns.

This doc is the depth layer to the brief [Tool invocation pattern](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/data-dictionary.md#tool-invocation-pattern) section in [`data-dictionary.md`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/data-dictionary.md). Field-level definitions live there; this doc walks the pattern end-to-end and breaks the `toolUseResult` envelope out by tool.

Per repo convention, sections are versioned independently with a "Verified against Claude Code v<X>" header. Where a per-tool shape has not been independently re-verified beyond the union documented in [`data-dictionary.md`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/data-dictionary.md#tooluseresult-envelope), the section says so.

**Runtime scope.** Verification in this doc is against the **Claude Code** runtime. The baseline is v2.1.150; every section re-verified by the scan below carries a v2.1.243 marker. The Agent SDK (Python and TypeScript) writes session files in the same JSONL format and shares the same tool invocation pattern conceptually, but exposes a different built-in tool surface and may exercise the `toolUseResult` envelope differently. Where this distinction matters for a specific tool or claim, the section notes it inline. Sections will be updated with Agent SDK verification once representative session files are available to sample.

**Scan provenance (2026-08-25).** The per-tool envelope tables, the block-splitting section, the spilled-results section, and the parallel-call section were re-verified by an observational scan over 2,480 local session files — 289,773 lines, 109 distinct Claude Code versions spanning v2.1.5 through v2.1.243. Structural only: key names, JSON value types, public taxonomy enums, and counts, under the same no-values contract as [`tooling/format-scan/scan.py`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/tooling/format-scan/scan.py). No message content was read. Counts quoted below are out of that corpus. Method and full numbers: [issue #210](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/210).

---

## What the tool invocation pattern is

**Verified against Claude Code v2.1.243.**

Every tool call Claude Code makes — reading a file, running a shell command, delegating to a subagent, fetching a URL — is recorded in the session JSONL as a two-line cycle:

1. An **`assistant`** line carrying a `tool_use` content block inside `message.content`. Each block has a unique `id`, a `name` (the tool), and tool-specific `input`.
2. A subsequent **`user`** line carrying one or more `tool_result` content blocks inside `message.content`. Each block has a `tool_use_id` referencing the prior `tool_use.id`, plus `content` (the tool's output) and an optional `is_error` flag.

That is the *logical* cycle. Physically, Claude Code writes **one JSONL line per content block**, so a turn that fires three tools is three assistant lines rather than one — see [One line per content block](#one-line-per-content-block) before writing anything that walks `message.content` arrays.

For context-bearing tools, the same user line also carries a top-level **`toolUseResult`** key — a sibling of `message`, not a child of it — with camelCase metadata about the invocation.

The pattern matters because every analytics or audit task on Claude Code sessions reduces to walking this cycle. What did the agent do? Read the `tool_use` blocks. What came back? Walk to the matching `tool_result`. How long did it take, how many tokens did it burn, what status did it return? Read the `toolUseResult` envelope. The cycle is the smallest semantically complete unit of agent activity in the format.

See the full content-block field definitions in [`data-dictionary.md`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/data-dictionary.md#content-blocks): [`tool_use`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/data-dictionary.md#tool_use), [`tool_result`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/data-dictionary.md#tool_result), and the [`toolUseResult` envelope](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/data-dictionary.md#tooluseresult-envelope).

---

## One line per content block

**Verified against Claude Code v2.1.243.**

The cycle above is usually drawn as two lines: one assistant line, one user line. That is the logical shape. The physical shape is different, and the difference changes what "an assistant turn" means for every consumer of this format.

**Claude Code writes one JSONL line per content block.** A model turn that emits a `text` block and two `tool_use` blocks is written as three `assistant` lines, each carrying a single-element `message.content` array. The lines are tied together by fields they share, not by being one line:

- **`requestId`** — the API request the turn came from. This is the grouping key to use.
- **`message.id`** — the model message id. Also shared across the turn's lines, and the sensible fallback where `requestId` is absent.

Multi-block assistant lines are nearly extinct: **14** of them across the scan corpus's 289,773 lines. Grouping assistant lines by `requestId` shows how far the split runs — 19,863 requests wrote a single line, 21,013 wrote two, 15,381 wrote three, with a tail out to 30 lines for one request.

What follows from it:

- **Counting assistant lines overcounts turns.** Group by `requestId` first, then count groups.
- **Per-line content inspection misses siblings.** A `text` block and the `tool_use` block it introduces are different lines. Code looking for both in one `message.content` array finds neither together.
- **Counting blocks *within* a line measures line-splitting, not model behavior.** [Parallel tool calls](#parallel-tool-calls) is where this bites hardest, and where this doc previously gave advice that no longer works.
- **`usage` repeats across a turn's lines.** Deduplicating by `message.id` before summing token usage is the standing advice in this repo (see the [undercount hazard](#undercount-hazard) and [`data-dictionary.md` § `usage` is per-request](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/data-dictionary.md#usage-is-per-request-context-recurs-every-turn)); block-splitting is a large part of why it is necessary.

The synthetic fixtures in this repo predate the split and show the logical shape — a `text` block and a `tool_use` block in one line's `message.content` array. They are still correct about the *cycle*; they are not representative of how current Claude Code lays that cycle out on disk.

---

## The pairing key: `tool_use_id`

**Verified against Claude Code v2.1.243** for the invariants below; the `toolu_` prefix observation is from the v2.1.150 baseline and was not re-checked (the 2026-08-25 scan reads key names, not values).

The load-bearing identifier is the tool-call ID:

- On the assistant side: `message.content[].id` (where `type == "tool_use"`).
- On the user side: `message.content[].tool_use_id` (where `type == "tool_result"`).

In observed sessions these IDs use the `toolu_` prefix followed by a base64-style suffix. Synthetic fixtures in this repo use `toolu_synthetic_NNN` so they are visibly distinguishable from real IDs.

### Walking a session to reconstruct what happened

To rebuild the full tool history of a session:

1. Iterate the JSONL lines in file order.
2. For each `assistant` line, scan `message.content` for `tool_use` blocks. Index them by `id`.
3. For each `user` line, scan `message.content` for `tool_result` blocks. Look up the parent `tool_use` by `tool_use_id`.
4. If the user line has a top-level `toolUseResult` key, attach it to the same pairing.

A few invariants worth knowing before you build on this:

- **Order is not always strictly adjacent.** A single model turn may fire several tools, written as several consecutive `assistant` lines sharing a `requestId` (see [One line per content block](#one-line-per-content-block) and [Parallel tool calls](#parallel-tool-calls)). The corresponding `tool_result` blocks may arrive in one user line or split across several.
- **Every `tool_use` should have exactly one matching `tool_result`** within the same session file. A missing pair almost always indicates an interrupted session — the cycle was never closed before the session ended.
- **`tool_use_id` is unique within a session.** It is not globally unique. Two sessions can independently mint `toolu_abc123`; correlate by `sessionId` first if you are aggregating across files.
- **Subagent traces have their own `tool_use_id` space.** A subagent's internal tool calls are recorded in `~/.claude/projects/<slug>/<session-uuid>/subagents/agent-<agentId>.jsonl`, not the parent file. The parent file only shows the `Agent` tool's `tool_use` → `tool_result` pair plus the `toolUseResult` rollup. See [The Agent tool](#the-agent-tool) and [`subagent-traces.md`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/subagent-traces.md).

---

## End-to-end example

**Verified against Claude Code v2.1.243.** The fixture itself was authored against the v2.1.150 baseline; see the line-layout caveat below.

The canonical synthetic example of the cycle lives at [`anatomy-tool-use-cycle.jsonl`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/fixtures/synthetic/anatomy-tool-use-cycle.jsonl). It is three lines long and shows a `Read` tool invocation. See its [generator sidecar](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/fixtures/synthetic/anatomy-tool-use-cycle.jsonl.generator.md) for the structural points the fixture is designed to surface.

Briefly, what each line carries:

| Line | Type | What it shows |
|---|---|---|
| 1 | `user` | The plain user prompt asking about a file. `message.content` is a string. |
| 2 | `assistant` | A mixed-content response: a `text` block ("I'll read the file.") followed by a `tool_use` block invoking `Read`. `stop_reason: "tool_use"` indicates the model paused to invoke a tool, not because it finished. |
| 3 | `user` | The tool response. `message.content` is now an **array** containing one `tool_result` block. The `tool_use_id` matches the prior assistant line's `tool_use.id`. No top-level `toolUseResult` envelope, because `Read` produces minimal metadata. |

One caveat on that fixture: line 2 puts a `text` block and a `tool_use` block in the same `message.content` array. That is the logical shape of a turn, and it is what makes the fixture readable, but current Claude Code would write those as two lines — see [One line per content block](#one-line-per-content-block).

The structural surprise for readers is that **tool results live inside `user` messages, not as their own top-level type**. The data-dictionary calls this out as the format's "most counterintuitive structural detail." Any parser that filters by `type == "tool_result"` at the top level will find zero results; tool results are always nested inside `user.message.content` arrays.

---

## Common tool names

**Verified against Claude Code v2.1.243 (built-in tools); MCP pattern verified against the documented `mcp__<server>__<tool>` convention.**

Tool names are exact strings as they appear in `message.content[].name` on `assistant` `tool_use` blocks. (They do **not** appear as keys in `toolStats` inside the `Agent` envelope, which is keyed by category — see [`data-dictionary.md` § `toolStats` shape](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/data-dictionary.md#toolstats-shape).) The set is **extensible** — plugins and MCP servers add tools at runtime, and new built-ins are added across Claude Code releases — so this table is descriptive, not exhaustive.

The **Agent SDK** exposes a different built-in tool surface; tools listed here are Claude Code's. SDK-specific tools (and the SDK's own subagent invocation pattern) are out of scope for this section until session files are available to verify.

### Built-in tools (Claude Code v2.1.243)

The set has grown substantially past the v2.1.150 baseline this doc was first written against. Names below were observed in `tool_use.name` across the scan corpus.

**File and shell:**

| Name | One-line semantics |
|---|---|
| `Read` | Read a file from disk. Input: `file_path` (+ optional `offset`, `limit`, `pages` for PDFs). |
| `Write` | Create or overwrite a file. Input: `file_path`, `content`. |
| `Edit` | In-place string replacement in a file. Input: `file_path`, `old_string`, `new_string`, optional `replace_all`. |
| `Bash` | Run a shell command. Input: `command`, `description`, optional `timeout`, `run_in_background`, `dangerouslyDisableSandbox`. |
| `Glob` | Filesystem pattern match. Input: `pattern`, optional `path`. |
| `Grep` | Content search across files. Input: `pattern`, optional `path`, `glob`, `output_mode`, `-i`/`-n`/`-A`/`-B`/`-C` flag equivalents. |
| `NotebookEdit` | Edit cells in a Jupyter notebook. Input: notebook path + cell-specific fields. |

**Model-facing lookups and delegation:**

| Name | One-line semantics |
|---|---|
| `Agent` | Delegate to a subagent. Input: `subagent_type`, `description`, `prompt`. See [The Agent tool](#the-agent-tool). |
| `WebFetch` | Fetch a URL and return parsed content. Input: `url`, optional `prompt` for summarization. |
| `WebSearch` | Run a web search. Input: `query`. |
| `AskUserQuestion` | Surface a structured question/multi-choice prompt to the user. Input: a `questions` array. |
| `Skill` | Invoke a packaged skill by name. Input: `skill`, optional `args`. |
| `ToolSearch` | Resolve deferred tool schemas at runtime. Input: a `query` string and optional `max_results`. Returns tool schemas the harness can then invoke. |
| `StructuredOutput` | Return a schema-validated result object. Appears when a caller forces structured output from an agent. |
| `ReportFindings` | Emit typed review findings for the host UI to render, rather than as prose. |

**Session and harness control:**

| Name | One-line semantics |
|---|---|
| `EnterPlanMode` / `ExitPlanMode` | Enter plan mode; leave it after presenting a plan. `ExitPlanMode` input: `plan`. |
| `EnterWorktree` / `ExitWorktree` | Move into or out of a git worktree mid-session. |
| `TaskCreate` / `TaskUpdate` / `TaskList` / `TaskGet` / `TaskOutput` / `TaskStop` | Manage the session's task list and background tasks. |
| `Monitor` | Stream events from a background process. |
| `ScheduleWakeup` | Schedule a delayed wake-up in `/loop` dynamic mode. |
| `SendMessage` | Send a message to another agent or session. |
| `ListAgents` | Enumerate the agents reachable by `SendMessage`. |
| `Artifact` | Publish, read, or update a hosted HTML artifact. |
| `CronList` | List cron jobs scheduled in the session. Its `CronCreate` / `CronDelete` siblings exist in the harness but did not appear in the scan corpus. |
| `RemoteTrigger` | Call the remote-trigger API that manages scheduled cloud routines. |

The list is descriptive of the scan corpus (v2.1.5–v2.1.243), not a contract. Tools that ship with specific harness modes (SDK, web) or that arrive in later Claude Code releases will not appear here until re-verification, and a session's actual surface depends on which features are enabled for that user. Treat an unrecognized `tool_use.name` as a valid tool you have not seen yet, never as malformed data.

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

**Verified against Claude Code v2.1.243.** The `Read`, `Bash`, `Grep`, and `Glob` tables below were rebuilt from the 2026-08-25 observational scan and carry observed counts. The remaining tables are still the v2.1.150 union from [`data-dictionary.md`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/data-dictionary.md#tooluseresult-envelope) plus AgentFluent-sourced generator notes. **A table without counts has not been re-verified** — treat it as a starting hypothesis, not a contract.

> **Correction (2026-08-25, [#210](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/210)).** Four of these tables were wrong, not merely incomplete. `Bash` listed a `code` exit-status field that does not exist. `Read` was documented flat when it is nested. `Grep` and `Glob` shared a table whose four keys were **all** fictional, and whose key sets barely overlap in reality. The corrected tables are below; the errors are called out in place so anyone who built against the old text knows what to go fix.

The `toolUseResult` top-level key is the most information-dense surface in the format. It is **tool-dependent** — different tools populate different subsets of keys. The data-dictionary documents the union of observed keys; the tables below break the union out by tool so a parser knows what to expect for each.

Three structural rules apply across all tools:

1. **`toolUseResult` sits at the line's top level**, beside `message`, not inside `message.content`. It uses **camelCase** (the rest of the format is mostly snake_case).
2. **Not every tool populates it.** Lightweight tools may omit `toolUseResult` entirely; the `tool_result.content` then carries everything the parser needs. `Read` is the clearest case: 8,866 of 13,589 Read results carry an envelope, 4,723 carry none. Context-bearing tools (`Agent`, `Bash`, `Edit`, `WebFetch`) populate it consistently.
3. **It is not always an object.** On a minority of results, `toolUseResult` is a **bare string** — the tool's output text with no envelope around it. Observed: `Bash` 1,075, `Read` 607, `Edit` 240, `Write` 139, `WebFetch` 20, `Grep` 14. Code that reaches straight for `toolUseResult.stdout` throws or silently yields null on every one of them. Type-check before indexing: `isinstance(tur, dict)` in Python; in `jq`, either `select((.toolUseResult | type) == "object")` or the `?` operator (`.toolUseResult?.stdout?`), which suppresses the "cannot index string" error rather than aborting the run.

### Read

**The Read envelope is nested, not flat.** It has exactly two top-level keys, and one of them is an object holding everything else. Earlier revisions of this doc listed `filePath`, `bytes`, `content`, and `isImage` at the top level; of those, only the nested forms of `filePath` and `content` exist at all. There is **no `bytes` key** and **no `isImage` key** anywhere in a Read envelope.

| Key | Type | Count | Notes |
|---|---|---|---|
| `type` | string | 8,265 | Result subtype. |
| `file` | object | 8,265 | Everything below hangs off this. |

Inside `file`:

| Key | Count | Notes |
|---|---|---|
| `file.filePath` | 8,155 | Path read. |
| `file.content` | 8,152 | The text handed to the model. |
| `file.numLines` | 8,152 | How many lines this read returned. |
| `file.startLine` | 8,152 | Where the returned slice starts. |
| `file.totalLines` | 8,152 | How many lines the file has. |
| `file.originalSize` | 111 | Size before truncation. |
| `file.base64` | 110 | Image reads: the encoded image. |
| `file.type` | 110 | Image reads: the image type. |
| `file.dimensions` | 100 | Image reads: pixel dimensions. |
| `file.truncatedByTokenCap` | 43 | The read was cut short by the token cap. |
| `file.cells` | 2 | Notebook reads. |

Two things the flat version hid:

- **`startLine` / `numLines` / `totalLines` record that Claude read a _slice_** — and, by subtraction, how much of the file it never saw. Any audit asking "did Claude actually look at the code it is describing?" needs all three.
- **Image reads are signalled by `file.base64` + `file.dimensions` + `file.type`**, not by an `isImage` boolean. Branch on the presence of `file.base64`.

`Read` remains the lightest of the file tools by envelope presence: 8,866 of 13,589 results carry a `toolUseResult`, 4,723 carry none, and 607 of the ones that do carry the [bare-string form](#the-tooluseresult-envelope-by-tool) rather than an object. When the envelope is absent, `tool_result.content` is the whole story.

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

**There is no `code` key. Exit status is not a first-class field on the Bash envelope.** Earlier revisions of this doc listed `code`, `durationMs`, and `durationSeconds`; the scan found **zero** of the three across 30,427 Bash envelopes spanning 103 Claude Code versions. Code branching on `toolUseResult.code` has always been branching on `null`.

Stable core, present on essentially every Bash envelope since v2.1.9:

| Key | Type | Count | Notes |
|---|---|---|---|
| `stdout` | string | 30,427 | Captured standard output. |
| `stderr` | string | 30,427 | Captured standard error. Non-empty is not by itself a failure. |
| `interrupted` | bool | 30,427 | `true` when the command was killed (timeout or user cancel) before completing. |
| `isImage` | bool | 30,426 | Whether the result came back as an image content block. |
| `noOutputExpected` | bool | 30,399 | Whether the harness expected the command to produce no output. Since v2.1.71. |

Conditional keys, each present only for the situation that produces it:

| Key | Type | Count | First seen | What it marks |
|---|---|---|---|---|
| `gitOperation` | string | 963 | v2.1.158 | The command was recognized as a git operation. |
| `returnCodeInterpretation` | string | 207 | v2.1.71 | A rendered reading of how the command exited. The nearest thing to an exit-status signal. |
| `persistedOutputPath` | string | 162 | v2.1.109 | Output was spilled to `tool-results/`. See [Spilled tool results](#spilled-tool-results). |
| `persistedOutputSize` | int | 162 | v2.1.109 | Size of the spilled payload. |
| `backgroundTaskId` | string | 152 | v2.1.71 | The command was backgrounded; this is its handle. |
| `staleReadFileStateHint` | — | 84 | v2.1.126 | Cached read state for a touched file is stale. |
| `backgroundCwdHint` | — | 28 | v2.1.210 | Working-directory hint for a backgrounded command. |
| `timedOutAfterMs` | — | 6 | v2.1.220 | The command hit its timeout, and after how long. |
| `assistantAutoBackgrounded` | — | 6 | v2.1.152 | The harness backgrounded the command on its own. |
| `dangerouslyDisableSandbox` | — | 5 | v2.1.238 | The call ran with the sandbox override. |

Two caveats on that second table. The scan recorded key names, types, and counts only — no values — so the **What it marks** column is read off the key name and the Claude Code feature it lines up with, not off observed data; treat it as a strong hint rather than verified semantics. And types are left blank where the sample was too small to state one confidently.

`Bash` is still the most diagnostic-rich tool in the format, but the diagnosis runs through `interrupted`, `stderr`, and the result content — not an exit code. See [Error patterns](#error-patterns).

### Grep

Earlier revisions gave `Grep` and `Glob` a shared table listing `query`, `matches`, `searchCount`, and `results`. **None of those four keys were observed for either tool**, and the two tools' real key sets overlap on only `filenames` and `numFiles` — so they get separate tables.

Observed across 1,565 `Grep` calls; the envelope is present on 881 of them.

| Key | Count | Notes |
|---|---|---|
| `mode` | 870 | The `output_mode` the call ran in. Drives which of the keys below appear. |
| `filenames` | 870 | The files matched. |
| `numFiles` | 870 | How many files matched. |
| `content` | 743 | Matched content, for the content-returning modes. |
| `numLines` | 735 | Lines returned. |
| `totalLines` | 454 | Lines available before any limit was applied. |
| `totalFiles` | 96 | Files available before any limit was applied. |
| `appliedLimit` | 47 | A result limit was applied. |
| `numMatches` | 8 | Match count, for counting mode. |
| `appliedOffset` | 2 | A result offset was applied. |

Because `mode` gates the rest, a parser cannot assume `content` or `numLines` on an arbitrary Grep result. Read `mode` first.

### Glob

Observed across 478 `Glob` calls; the envelope is present on 191 of them.

| Key | Count | Notes |
|---|---|---|
| `filenames` | 186 | The paths matched. |
| `durationMs` | 186 | Wall-clock duration. `Glob` reports this; `Grep` does not. |
| `numFiles` | 186 | How many paths matched. |
| `truncated` | 186 | Whether the returned list was cut short. |
| `totalMatches` | 139 | Matches before truncation. |
| `countIsComplete` | 139 | Whether `totalMatches` is exact. |

`truncated` plus `countIsComplete` is the pair that tells you whether the file list Claude saw was the whole answer — worth checking before concluding from a session that a pattern matched nothing else.

### WebFetch, WebSearch

Not re-verified by the 2026-08-25 scan; the table below is the v2.1.150 union.

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
| `totalTokens` | number | A **single turn's** snapshot (the subagent's final turn), the four-field sum of `usage`. **Not** a run total — see the [undercount hazard](#undercount-hazard). |
| `totalToolUseCount` | number | Number of tool invocations inside the subagent (a true run-level count). |
| `usage` | object | The subagent's **final-turn** token usage (same shape as `message.usage`), not a run total. |
| `toolStats` | object | Tool-activity counters keyed by **category**, not tool name (`readCount`, `searchCount`, `bashCount`, `editFileCount`, `otherToolCount`, `linesAdded`, `linesRemoved`). See [`data-dictionary.md` § `toolStats` shape](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/data-dictionary.md#toolstats-shape). |

### MCP tools (`mcp__<server>__<tool>`)

MCP tool result envelopes typically include `status`, `durationMs`, and tool-specific keys that depend on what the MCP server returns. Because MCP tools are user-installed, the envelope shape is not fixed by Claude Code — re-verify per server.

The union table calls out `total_deferred_tools` for tool-discovery flows (e.g., `ToolSearch` resolving deferred MCP schemas).

### Tools without a dedicated envelope

Several tools either always omit `toolUseResult` or populate only `status` and `type`. Observed examples: lightweight harness controls (`ExitPlanMode`, `EnterWorktree`/`ExitWorktree` in many cases). Their actionable result is the `tool_result.content` value.

When `toolUseResult` is absent, the cycle is still valid — `tool_use_id` pairing is the only structural requirement. The envelope is additional, not load-bearing.

---

## Spilled tool results

**Verified against Claude Code v2.1.243.** Directory layout, file-size band, and the in-content wrapper were confirmed by an earlier observational scan (89 spilled files across 40 sessions); the envelope pointer keys and their first-seen version come from the 2026-08-25 scan.

When a tool result is too large to sit comfortably in one JSONL line, Claude Code writes the payload to a file and leaves a pointer behind. This is the mechanism [`subagent-traces.md`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/subagent-traces.md#spilled-tool-results) points here for. It shows up in that doc because the spill directory sits beside `subagents/`, but it is a tool-invocation concern and not subagent-specific — any tool can spill.

**Where it lands.** In the session's lazily created overflow directory:

```
~/.claude/projects/<slug>/<session-uuid>/
└── tool-results/
    └── <tool-use-id>.txt | <tool-use-id>.json
```

One file per spilled result, named after the `tool_use.id` that produced it. Observed spilled files ran from ~20 KB to ~860 KB (median ~64 KB), implying a spill threshold near 20 KB.

**What stays in the JSONL.** Two references, at two levels:

1. **In `tool_result.content`** — a plain-text `<persisted-output>` wrapper carrying the output's size, the path the full payload was written to, and a truncated preview of its head. This is prose inside the content string, not structured JSON, so reading it means pattern-matching text.
2. **In the `toolUseResult` envelope** — `persistedOutputPath` (string) and `persistedOutputSize` (int), both since **v2.1.109**. This is a real structured pointer, and it is the one to prefer. The 2026-08-25 scan broke these out on the [`Bash`](#bash) envelope, where they appear together on 162 results; spilling is not Bash-specific, but Bash is the tool the scan counted.

The envelope pointer is the newer of the two, so a parser covering the full version range needs both paths: fall back to the text wrapper when `persistedOutputPath` is absent. Note that the pointer lives in the **envelope**, one level up from the `tool_result` block — the block's own key set carries no spill field, which is why an earlier scan of block keys concluded no pointer key existed at all.

**Why it matters for analysis.** A spilled result means the session file no longer contains what the model actually read. Anything that measures output volume, searches tool output for a string, or reconstructs what was in context has to follow the pointer or knowingly settle for the preview. And for this repo's purposes specifically: a spilled file is raw, unredacted tool output sitting on disk outside the session JSONL, so anything that sanitizes or publishes session data has to cover `tool-results/` too, not just the `.jsonl`.

---

## The Agent tool

**Verified against Claude Code v2.1.150 using [`anatomy-agent-invocation.jsonl`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/fixtures/synthetic/anatomy-agent-invocation.jsonl) and the data-dictionary's `toolUseResult` envelope table.**

The `Agent` tool is structurally identical to every other tool at the parent-session level — it's a `tool_use` followed by a `tool_result` — but it has two unusual properties that make it the most consequential tool for analytics:

1. Its `toolUseResult` envelope carries **run-level rollups** in a single object: total duration and per-tool counts. (Its token fields, `totalTokens` / `usage`, are the exception — a **single-turn snapshot**, not a run total. See the [undercount hazard](#undercount-hazard).)
2. Its `agentId` links to a **separate JSONL trace file** that contains the subagent's full internal activity.

**Corrected 2026-08-15.** This paragraph previously said Claude Code restricts subagents from invoking further subagents, so the Agent tool only appears in parent sessions. That was true at the v2.1.150 baseline and stopped being true at **v2.1.172**. The `Agent` tool now appears **inside subagent traces too**, in both runtimes: a corpus scan over v2.1.109–v2.1.233 found every depth-2 spawn recorded in the spawning subagent's own `agent-<id>.jsonl`, never in the parent transcript. Do not assume an `Agent` `tool_use` implies a parent-session line. See [`subagent-traces.md` § Nesting](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/subagent-traces.md#nesting).

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
- `totalDurationMs`, `totalToolUseCount` — true run-level rollups. `totalToolUseCount` is the subagent's **own-direct** count, not cumulative across any further subagents it spawned.
- `totalTokens`, `usage` — **not** run rollups. Both are a single-turn snapshot (the subagent's final turn); see the [undercount hazard](#undercount-hazard) below and [Usage and token accounting](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/data-dictionary.md#usage-and-token-accounting).
- `toolStats` — category counters (`readCount`, `searchCount`, `bashCount`, `editFileCount`, `otherToolCount`) plus edit magnitude (`linesAdded`, `linesRemoved`). Useful for a coarse "what shape of work was this" read; it does **not** name individual tools.

**Multi-level caveat — Agent SDK only.** Subagents can delegate further in both runtimes (Claude Code from v2.1.172), but only the SDK drops the rollup when they do. In the **Agent SDK**, this whole `toolUseResult` rollup is present only on **first-level** subagent results; the deeper `Agent` `tool_result` carries no `toolUseResult`, only an inline `subagent_tokens: <N>` trailer, so a depth-≥2 subagent's rollup numbers must come from its own trace. In **Claude Code** the rollup is present at depth ≥ 2 as well, so this caveat does not apply there. Either way the deeper `tool_result` lives in the spawning subagent's own trace file. See [`subagent-traces.md` § Multi-level (nested) delegation](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/subagent-traces.md#multi-level-nested-delegation).

### The link to the subagent trace file

When the parent line carries `toolUseResult.agentId == "X"`, the file at:

```
~/.claude/projects/<slug>/<session-uuid>/subagents/agent-X.jsonl
```

contains the complete subagent trace. Every line in that file carries `isSidechain: true` — the canonical signal you are reading a subagent trace rather than a parent session.

For the structure of that file — `attributionAgent`, `sourceToolAssistantUUID`, the per-line-type attribution pattern, what fields propagate vs. reset across invocation boundaries — see [`subagent-traces.md`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/subagent-traces.md).

### Undercount hazard

The parent's `toolUseResult.usage` / `totalTokens` is a **single-turn snapshot** (the subagent's final turn), not a run total. The subagent's real spend is the sum of **all** its per-turn `message.usage` inside the trace file, deduplicated by `message.id`. Reading spend off the rollup alone **under**counts by a median ~5.8x. The correct move is the opposite of the intuitive "use one or the other": for spend, always sum the trace's per-turn usage; use the parent rollup only as an explicitly labeled context-size proxy. The data-dictionary's [cost-computation pitfalls](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/data-dictionary.md#common-pitfalls-in-cost-computation) and [per-request usage note](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/data-dictionary.md#usage-is-per-request-context-recurs-every-turn) cover the mechanism; it shows up here because the `toolUseResult` rollup is the surface most likely to trip an aggregator into the undercount.

> **Note (2026-07-19, #144).** Earlier revisions of this section called this a *double-count* hazard and advised summing the trace **or** the rollup. That was backwards: the rollup is one turn, so it can't double the trace — it undercounts it. Corrected above.

---

## Error patterns

**Verified against Claude Code v2.1.243; per-tool error fixtures are forthcoming.**

Tool failures are represented at two levels:

1. **The `tool_result` block** carries an optional `is_error` boolean. `true` indicates the tool reported an error. Absent or `false` on the happy path.
2. **The `toolUseResult` envelope** may carry a tool-specific status field. For most tools this is `status` (`"success"` or `"error"`). **`Bash` is the exception: it has no exit-code field** (see [Bash](#bash)). Its signals are:
   - `interrupted: true` — the command was killed (timeout or user cancel) before completing.
   - `stderr` non-empty — the command emitted error output. Not necessarily a failure, but worth surfacing.
   - `returnCodeInterpretation` — a rendered reading of how the command exited, on 207 of 30,427 Bash envelopes since v2.1.71. The closest thing to an exit status, and far too rare to build a success test on.
   - `timedOutAfterMs` — only on timeouts, and only from v2.1.220.

   For `Bash`, that leaves `is_error` on the `tool_result` block plus the result content as the primary signal. Anything that used to test `code != 0` was testing `null != 0` — which evaluates true, so every Bash call in the corpus reads as a failure.

### Failures vs. partial successes

Some tools return useful partial output even when `is_error: true`. `Bash` is the canonical case: a command can fail, produce useful `stderr` (which the model reads and reacts to), and still leave `stdout` populated. Parsers that treat `is_error == true` as "throw away the output" lose information. The scan makes that a measured claim rather than a hedge: of 2,300 `tool_result` blocks flagged `is_error: true`, **all 2,300** carried content. Not one was empty.

The rule: `is_error` indicates the tool's self-reported error status; the *content* of the result still has to be inspected to know what actually happened.

### Interruption

`Bash` (and any long-running tool that supports cancellation) records interruption via `toolUseResult.interrupted: true`. The `tool_result.content` may still contain partial output captured before the interruption.

A session can also end mid-cycle — an assistant `tool_use` block with no matching `tool_result` in the file. This is structurally an "incomplete cycle" rather than a tool error per se; treat it as a session-level interruption rather than a tool failure.

---

## Parallel tool calls

**Verified against Claude Code v2.1.243.**

A single model turn may fire **several tools at once**. The harness executes them and returns all the results before the next turn.

**Detecting them means grouping by `requestId`, not counting blocks within a line.** Because Claude Code writes [one line per content block](#one-line-per-content-block), the `tool_use` blocks of a parallel turn are separate `assistant` lines sharing a `requestId` (and a `message.id`). They are not siblings in one `message.content` array.

> **Correction (2026-08-25, [#210](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/210)).** This section previously said a parallel turn is one assistant line carrying multiple `tool_use` blocks, and gave `length(.message.content | map(select(.type == "tool_use")))` as the detector, with "any value greater than 1 is a parallel turn." Run against the scan corpus, that method finds **4** parallel turns out of 68,395 lines carrying a `tool_use` block, because multi-block lines have all but disappeared. The real rate is 16.8%. Anyone who built on the old method concluded that Claude Code almost never parallelizes.

Grouped by `requestId`, the corpus looks like this:

| | Count | Share |
|---|---|---|
| Requests carrying ≥1 `tool_use` | 55,008 | |
| Serial — exactly one tool | 45,751 | 83.2% |
| Parallel — two or more tools | 9,257 | 16.8% |
| Largest single request | 22 tools | |

Working detection:

```bash
jq -s '
  [.[] | select(.type == "assistant" and (.isSidechain? // false) == false)]
  | group_by(.requestId? // .message.id?)
  | map({
      request_id: (.[0].requestId? // .[0].message.id? // "unknown"),
      tool_use_count: ([.[] | .message.content[]? | select(.type == "tool_use")] | length)
    })
  | map(select(.tool_use_count > 1))
' "$F"
```

Three deliberate choices in that snippet:

- **`-s` (slurp).** Grouping needs the whole file at once. This is not a streaming query, and it costs memory on large sessions.
- **`.message.id` as fallback.** Lines missing `requestId` still group by the model message they came from.
- **The `isSidechain` filter.** On a parent session it is a no-op, but point the same query at a subagent trace file (where every line is `isSidechain: true`) or at several files at once and the filter is what keeps a subagent's parallelism out of the parent's numbers. See [`subagent-traces.md`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/subagent-traces.md#the-issidechain-marker).

**The result side splits too.** The `tool_result` blocks answering a parallel turn may arrive in one `user` line or across several, depending on how the harness streams them back. Pairing holds by `tool_use_id` either way; do not assume "one assistant tool turn → one user response line" in either direction. The data-dictionary's [`tool_result`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/data-dictionary.md#tool_result) section covers the per-block shape.

Parallel invocations matter for analytics because **per-tool durations are not comparable across parallel and serial tools**. A serial sequence of three `Read` calls takes ~3× as long as one. A parallel batch of three takes ~1× as long. Both show up as the same `readCount: 3` inside a subagent envelope, which cannot distinguish them at all. If you care about wall-clock characterization, the `requestId` grouping above is the only thing in the file that tells you which one you are looking at.

---

## Tool stats for analysis

**Verified against Claude Code v2.1.243.**

Two fields are load-bearing for any analytics that wants to characterize what a session did:

- **`tool_use.name`** — the tool name string on each invocation. Aggregating these (e.g., counting per name across an entire session) tells you what the agent reached for.
- **`toolUseResult.toolStats`** — pre-computed **category** counters inside `Agent` invocations. Saves you from re-walking the subagent's trace file when a coarse characterization will do.

**These two do not join on tool name.** `tool_use.name` is an exact tool string; `toolStats` is keyed by category and never names a tool. So a per-session tool-name histogram cannot be reconciled against subagent `toolStats` at tool granularity — to separate "the main agent did this" from "a subagent did this" by tool, you must open the subagent's trace file and aggregate its own `tool_use.name` blocks.

A simple jq idiom for the parent-session histogram:

```bash
jq -r 'select(.type == "assistant") | .message.content[]? | select(.type == "tool_use") | .name' "$F" | sort | uniq -c | sort -rn
```

For subagent rollups (per-Agent-call) — note this returns category counters, not a tool histogram:

```bash
jq 'select(.toolUseResult?.toolStats?) | .toolUseResult.toolStats' "$F"
```

The `?` operators are load-bearing, not decoration: without them, `jq` raises "cannot index string" and prints an error on every line where `toolUseResult` is a [bare string](#the-tooluseresult-envelope-by-tool).

To get a real tool histogram for a subagent, run the first idiom against that subagent's trace file (`subagents/agent-<agentId>.jsonl`) rather than the parent session.

Sibling project [AgentFluent](https://github.com/frederick-douglas-pearce/agentfluent) uses both shapes for its agent-quality diagnostics.

---

## Cross-references

- **Field-level definitions:** [`data-dictionary.md`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/data-dictionary.md) — every field on `tool_use`, `tool_result`, and the `toolUseResult` envelope union.
- **Subagent trace files:** [`subagent-traces.md`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/subagent-traces.md) — the file at `~/.claude/projects/<slug>/<session-uuid>/subagents/agent-<agentId>.jsonl`, the `isSidechain: true` invariant, and `attributionAgent` / `sourceToolAssistantUUID` linkages. Its `<session-uuid>/` directory listing includes the `tool-results/` spill directory documented here in [Spilled tool results](#spilled-tool-results).
- **Synthetic fixtures used in this doc:**
  - [`anatomy-tool-use-cycle.jsonl`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/fixtures/synthetic/anatomy-tool-use-cycle.jsonl) — the basic Read cycle.
  - [`anatomy-agent-invocation.jsonl`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/fixtures/synthetic/anatomy-agent-invocation.jsonl) — the Agent tool invocation with full `toolUseResult` envelope.
  - [`anatomy-subagent-trace.jsonl`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/fixtures/synthetic/anatomy-subagent-trace.jsonl) — the subagent-side companion to the Agent invocation fixture.
- **Format version history:** When [`format-version-history.md`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/format-version-history.md) is created, per-tool envelope changes (key additions, renames, removals) will be tracked there. Until then, version-specific shifts are captured inline in the sections above when noticed.
