---
layout: post
title: "Reading a Claude Code session, line by line"
date: 2026-06-04 00:00:00-0800
description: "Part 2 of the anatomy series. Every type of line in a session JSONL, the snake_case/camelCase split that reveals two layers (API content wrapped in Claude Code's bookkeeping), and why tool results live inside user messages."
categories: ["claude-code-sessions"]
tags: ["claude-code", "agent-sdk", "jsonl", "sessions", "foundation"]
og_image: https://frederick-douglas-pearce.github.io/assets/img/reading-a-claude-code-session-line-by-line-og.png
og_card_source: social/images/2026-06-04-linkedin-reading-a-claude-code-session-line-by-line/og-card.png
featured: false
claude_code_version_verified: v2.1.150
---

Open any Claude Code session JSONL file and one structural quirk jumps out within a few lines: some field names use `snake_case` and others use `camelCase`. `tool_use_id` and `stop_reason` next to `parentUuid` and `toolUseResult`. It looks inconsistent.

It isn't — it's a tell. `snake_case` fields are generally content the Anthropic API defines: things the model produces and consumes. `camelCase` fields are envelope metadata that Claude Code's harness adds on top — session identifiers, parent UUIDs, tool-invocation rollups. Once that split clicks, the format stops looking messy and starts providing architectural insight: Anthropic API conversations are always wrapped in Claude Code's bookkeeping.

This is Part 2 of the [Anatomy of a Claude Code session](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/posts/2026-05-26-anatomy-of-a-claude-code-session.md) series. Part 1 covered where session files live and what Claude Code itself uses them for. This post is the structural tour: every type of line you'll find inside a session, the two layers (API content and harness metadata) that compose them, why tool results live inside `user` messages, and what the `toolUseResult` envelope carries that the model never sees.

By the end you'll have a mental model for every distinct `type` value in a session JSONL — including the many "metadata" types that most parsers silently drop — and three `jq` snippets to start asking your own questions of any session file on your disk.

If you want field-level definitions while reading, [`reference/data-dictionary.md`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/data-dictionary.md) in the repo is the source of truth. This post is the narrative; that doc is the lookup.

---

## The taxonomy at a glance

Every line in a session JSONL has a top-level `type` field. In v2.1.150 you'll see **at least** the distinct values below. The list is observational — Anthropic doesn't publicly catalogue the full set, and sessions in the wild can carry types this list hasn't sampled yet. Treat the table as a strong starting point, not a closed taxonomy.

| What it is                                         | `type` values                                                                                 |
| -------------------------------------------------- | --------------------------------------------------------------------------------------------- |
| **Activity** — what you and the model said and did | `user`, `assistant`                                                                           |
| **State** — what the session knows about itself    | `file-history-snapshot`, `system`, `permission-mode`, `ai-title`, `last-prompt`, `attachment` |
| **Telemetry** — events emitted as things happen    | `progress`, `hook_progress`, `bash_progress`, `queue-operation`                               |

Two types I've seen in real sessions but haven't independently verified at the time of writing are `custom-title` (which appears to be the user-set session title, distinct from the auto-generated `ai-title`) and `pr-link` (the per-session PR association mentioned in Part 1). They're not in the table above because the reference doc hasn't catalogued them yet — but if you run the `jq` snippet at the end of this post against your own sessions, expect to see them and other types appear.

The first bucket is what most parsers think a "session" is. The second is what `/rewind`, the resume picker, and the permission UI all read. The third is the chatter the harness emits while you're working — usually irrelevant for after-the-fact analysis, sometimes invaluable for debugging.

I'll walk each bucket in turn, then come back to the structural twist that hides inside `user` messages.

---

## `assistant` — the model's voice

This is the line type with the richest internal structure, because everything the model produces gets packed into it. The top-level envelope (`type`, `sessionId`, `uuid`, `parentUuid`, `timestamp`, `cwd`, `version`) is the same as on every other line. The interesting payload lives inside `message`.

```json
{
  "type": "assistant",
  "message": {
    "role": "assistant",
    "model": "claude-sonnet-4-6",
    "content": [
      { "type": "text", "text": "I'll read the file." },
      {
        "type": "tool_use",
        "id": "toolu_synthetic_001",
        "name": "Read",
        "input": { "file_path": "/home/dev/example-project/src/main.py" }
      }
    ],
    "usage": {
      "input_tokens": 18,
      "output_tokens": 35,
      "cache_creation_input_tokens": 0,
      "cache_read_input_tokens": 1240
    },
    "stop_reason": "tool_use"
  }
}
```

Three things to notice.

**`message.content` is an array of content blocks**, not a string. A single assistant turn can carry multiple blocks of different types. The example above has two — a `text` block saying "I'll read the file" followed by a `tool_use` block invoking Read. This is exactly what you'd expect when the model both speaks and reaches for a tool in the same turn. Parsers that assume "one text response per assistant line" will silently drop the tool call.

The block types you'll see inside `content`:

- **`text`** — plain text. Most common.
- **`tool_use`** — the model invoking a tool. Carries an `id`, the tool `name`, and tool-specific `input`. Pairs with a later `tool_result`.
- **`thinking`** — extended-thinking content blocks. Only present when extended thinking was enabled for the session. Includes a `signature` field; treat it as an opaque blob.

**`message.usage` is the only token accounting that matters.** This is where input, output, cache-read, and cache-creation tokens are reported. There are no token counts on `user` lines — Claude Code doesn't bill the user for typing. If you want session-level totals, you sum across `assistant` lines, and you need to account for the four token kinds separately because they're priced differently. Part 1 went into this; the short version is "naive summing produces wrong dollar figures."

**`stop_reason` tells you whether the model finished or paused.** Two values dominate:

- `"end_turn"` — the model is done. No tool call to come.
- `"tool_use"` — the model stopped to invoke a tool. The very next user line should carry the matching `tool_result`.

If you're walking a session to reconstruct what happened, `stop_reason` is how you predict whether the next line will be a real user prompt or a tool response.

---

## `user` — and the structural twist

`user` lines are simpler in their envelope but stranger in what they contain. The twist is this: **tool results are not their own top-level type**. They're content blocks inside `user` messages.

That is, when Claude Code finishes a `Read` and feeds the file contents back to the model, the file contents land in a `user` line. Not a `tool_result` line. Not a `system` line. A `user` line.

This is the format's most counterintuitive detail, and every parser author runs into it at least once. If you write a quick filter — "give me all the tool results in this session" — and filter by `type == "tool_result"` at the top level, you'll get zero hits. Tool results are always nested inside `user.message.content` arrays.

### Two shapes of `message.content`

A `user` line carries one of two payload shapes:

**Shape 1 — a string.** This is a plain user prompt. The string is the literal text you typed.

```json
{ "type": "user", "message": { "role": "user", "content": "What's in src/main.py?" } }
```

**Shape 2 — an array of content blocks.** This is how tool results come back, and occasionally how structured prompts (e.g., with attached context) are recorded.

```json
{
  "type": "user",
  "message": {
    "role": "user",
    "content": [
      {
        "type": "tool_result",
        "tool_use_id": "toolu_synthetic_001",
        "content": "def main():\n    print('Hello, world!')\n"
      }
    ]
  }
}
```

The `tool_use_id` on the result is the **pairing key** that ties this back to a prior `tool_use` block in some earlier `assistant` line. The IDs are unique within a session — they look like `toolu_<base64-ish-suffix>` in real sessions.

### Why is it a user message?

Because in the Anthropic API, conversations alternate strictly between `user` and `assistant` roles. Tool results have to come back as one of those two, and the model can't issue its own tool result — only the runtime can. So the runtime impersonates the user, packs the tool output into a `tool_result` content block, and emits it as a `user` line. The model reads that line as the next "user turn" and decides what to do next.

This isn't Claude Code being quirky. It's [the Anthropic Messages API's tool-use protocol](https://platform.claude.com/docs/en/build-with-claude/tool-use) faithfully recorded. Once you see it that way, the alternation pattern becomes load-bearing for parsing: in any tool-using sequence, `assistant` (with `tool_use`) is always followed by `user` (with `tool_result`).

---

## The `toolUseResult` envelope

Here's the part that surprises readers who think they've figured the format out: when the underlying tool was a context-bearing one (`Agent`, `Bash`, `Edit`, `WebFetch`, and others), the `user` line that carries the tool result also carries a **second top-level key** called `toolUseResult`. It sits beside `message`, not inside it.

```json
{
  "type": "user",
  "message": {
    "role": "user",
    "content": [
      {
        "type": "tool_result",
        "tool_use_id": "toolu_synthetic_002",
        "content": "Drafted acceptance criteria for issue #5..."
      }
    ]
  },
  "toolUseResult": {
    "status": "success",
    "agentId": "99999999-9999-9999-9999-999999999001",
    "agentType": "pm",
    "totalDurationMs": 132140,
    "totalTokens": 18234,
    "totalToolUseCount": 7,
    "toolStats": {
      "readCount": 4,
      "searchCount": 0,
      "bashCount": 0,
      "editFileCount": 0,
      "linesAdded": 0,
      "linesRemoved": 0,
      "otherToolCount": 3
    }
  }
}
```

Two things stand out here. First, **the field name uses camelCase** (`toolUseResult`, `agentId`, `totalDurationMs`). Most of the message content inside `message` — the part that mirrors the Anthropic API's content blocks — uses `snake_case`: `tool_use`, `tool_result`, `tool_use_id`, `input_tokens`, `stop_reason`. The outer Claude Code-specific envelope fields (including `sessionId`, `parentUuid`, `isSidechain`, and now `toolUseResult`) use camelCase. It's a useful tell while you're reading: camelCase generally means "harness-level metadata," snake_case generally means "API-level content."

Second, **the envelope lives outside `message.content`**, not inside it. That placement is meaningful: the contents of `message.content` are what gets sent back to the model. The envelope is metadata for the harness and any parser that comes later. The model never sees `toolUseResult`; you do.

What's in it depends on the tool. The full union of observed keys is in [`data-dictionary.md`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/data-dictionary.md#tooluseresult-envelope); a few representative subsets:

- **`Agent`** — `agentId`, `agentType`, `prompt`, `totalDurationMs`, `totalTokens`, `totalToolUseCount`, `toolStats`. This is the surface that powers any per-subagent diagnostic. Note that `toolStats` is keyed by tool _category_, not tool name: the seven keys above are the whole vocabulary, so the two MCP calls and the one non-read tool call in this example collapse into `otherToolCount: 3` with no server or tool named. Note also that `linesAdded` and `linesRemoved` are edit magnitude, not invocation counts, so summing every value in `toolStats` gives you a number dominated by line counts. Use `totalToolUseCount` for the invocation total.
- **`Bash`** — `stdout`, `stderr`, `code`, `interrupted`, `durationMs`. Enough to characterize most command outcomes without parsing `stdout`.
- **`Edit`** — `filePath`, `oldString`, `newString`, `replaceAll`, `structuredPatch`, `userModified`. The diff is in `structuredPatch`; security-review tooling lives off that field.
- **`Read`** — often minimal or absent. The actionable content is in `tool_result.content`; `Read` doesn't need a separate envelope.

If you're building anything that analyzes sessions — tool-usage patterns, subagent cost rollups, edit audits — `toolUseResult` is where most of the high-information signal lives. [`reference/tool-invocation.md`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/tool-invocation.md) breaks the envelope out per tool with the per-key semantics.

---

## The "skipped" types — and why some of them aren't

Beyond `user` and `assistant`, a session JSONL carries several other top-level types. Most parsers drop all of them. Some you can safely ignore. One in particular you can't — not if you want to understand what `/rewind` is doing.

### `file-history-snapshot`

This is the type that powers `/rewind`'s "restore code" capability. It's not metadata. It's the actual data structure that lets Claude Code put your files back the way they were.

The top-level shape:

```json
{
  "type": "file-history-snapshot",
  "messageId": "<some-message-uuid>",
  "isSnapshotUpdate": false,
  "snapshot": {
    "messageId": "...",
    "timestamp": "...",
    "trackedFileBackups": {
      "/abs/path/to/file.py": "<file contents before the edit>",
      "...": "..."
    }
  }
}
```

The `trackedFileBackups` map is keyed by absolute file path; the values are the file's contents _before_ each Claude-tool edit. When you run `/rewind` and choose to restore code, Claude Code reads these entries in reverse chronological order and writes the prior contents back to disk.

Part 1 inferred this connection from the docs (rewind persists across sessions and is cleaned up with sessions, therefore it has to live in the session files). Reading the JSONL confirms it directly: every Claude-tool edit produces a snapshot entry. If you want to audit which files Claude edited and when — or reproduce `/rewind`'s behavior in your own tools — these are the lines you read.

This type also has a property worth noting: the snapshots cover only files Claude edited via its file-editing tools. Bash-driven changes (`rm`, `mv`, `cp`) and your own external edits aren't here. The snapshots are scoped to the tool surface that emits them.

### `system`

Records internal Claude Code events: model switches mid-session, tool registry updates, harness-level state changes. Fields include `subtype`, `durationMs`, `isMeta`, and `content`.

You'd usually skip these. The exception is diagnostic work — debugging why a session behaved oddly, or correlating a sudden model change with a behavior shift.

### `permission-mode`

A single-purpose line recording a permission-mode transition (e.g., from `"default"` to `"acceptEdits"` or `"bypassPermissions"`). Carries `permissionMode`, `sessionId`, and `type`.

Useful for two things: auditing permission posture across a session, and correlating tool failures with the permission state at the time. Otherwise ignorable.

### `ai-title`, `last-prompt`

Picker metadata. `ai-title` is the auto-generated session title you see when you run `/resume`. `last-prompt` is a pointer to the most recent user prompt — the picker uses it to render the preview line.

Useful if you're building a session index or a resume-picker UI outside Claude Code. Otherwise display chrome.

### `attachment`

A line representing an attachment (a pasted file, an image, a structured context blob) associated with a nearby message. Carries the standard envelope fields plus an `attachment` payload.

Useful for recovering the full multimodal context of a turn. If you only read `user.message.content`, you'll miss anything that was pasted in as an attachment rather than typed as inline text.

### `progress`, `hook_progress`, `bash_progress`, `queue-operation`

Streaming events emitted as a tool runs, a hook executes, or the harness schedules work internally. Generally high-volume chatter. The data-dictionary notes that the first three weren't observed in v2.1.150 sample sessions — they may still be emitted under specific conditions (long-running commands, hooks that emit progress), but presence is conditional.

For real-time monitoring of a session-in-progress (`tail -f` on the JSONL), these are gold. For after-the-fact analysis, they're usually noise.

---

## Putting it together

If you sit down with a real session JSONL in `~/.claude/projects/<slug>/` and start parsing it now, here's the mental model that holds up:

1. **Walk top to bottom.** The file is in chronological order. `parentUuid` chains messages together; `parentUuid: null` means a turn-starter.
2. **Index `tool_use` blocks by `id` as you go.** Every `tool_use.id` should later appear as a `tool_result.tool_use_id` in some downstream `user` line. Missing pairs almost always mean an interrupted session.
3. **For each tool-result-carrying `user` line, also check for a sibling `toolUseResult`.** That's where the rich metadata lives — duration, tokens, tool stats, status. It's at the top level, not inside `message.content`, and it uses camelCase.
4. **Decide explicitly what to do with the "skipped" types.** If you only care about user-visible activity, drop them all. If you care about file edits over time, keep `file-history-snapshot`. If you care about session orchestration or diagnostics, keep `system` and `permission-mode`.

Three lines of `jq` that take this from theory to practice. Run them on any of your session files. Snippets below assume `jq` on bash or zsh (macOS, Linux, or Windows via WSL or Git Bash); native PowerShell users can install `jq` via `winget install jqlang.jq` and adapt the piping syntax.

```bash
# Every distinct top-level type in the file, with counts:
cat <session>.jsonl | jq -r '.type' | sort | uniq -c

# Every tool the assistant invoked, in order:
cat <session>.jsonl | jq -r 'select(.type=="assistant")
  | .message.content[]? | select(.type=="tool_use") | .name'

# Every subagent invocation with its rollup:
# NB: totalTokens is a single-turn context-size snapshot, NOT the run's
# token total. Don't sum it or price it; see the caveat below and Part 4.
cat <session>.jsonl | jq 'select(.toolUseResult?.agentType?)
  | {agent: .toolUseResult.agentType,
     agent_id: .toolUseResult.agentId,
     duration_ms: .toolUseResult.totalDurationMs,
     context_tokens: .toolUseResult.totalTokens}'
```

The `?` operators in the third snippet matter: in real sessions, `toolUseResult` is sometimes an array or a string rather than an object, and without the `?` guards `jq` will raise an indexing error on those lines. With them, non-matching lines are silently skipped.

The first snippet is the fastest way to feel the shape of a session you've never opened before — and the easiest way to discover top-level `type` values this post hasn't catalogued. The second is a one-line agent-trace. The third pulls the rollup of every subagent the parent session delegated to. The `agent_id` value in that rollup is the literal handle that takes you to the subagent's full trace file at `~/.claude/projects/<slug>/<session-uuid>/subagents/agent-<agent_id>.jsonl` — which is where Part 3 picks up. I deliberately omitted `toolStats` from the third snippet, because its category counters answer a coarser question than the rest of the rollup does, and reading them alongside per-tool data invites the mistake of treating them as a per-tool breakdown.

One caveat on that `context_tokens` field. `toolUseResult.totalTokens` looks like the subagent's token total, but it is a snapshot of a single assistant turn's context size, not a sum across the run, so it understates what the run actually processed and must not be summed across invocations or priced as cost. That's why the key here is named `context_tokens`, not `tokens`. [Part 4](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/posts/2026-06-24-token-accounting-is-harder-than-it-looks.md) is the full treatment; for now, read it as a rough context-size figure, and get real token totals by summing the trace file's per-turn `message.usage`.

---

## What's next

This post stopped at the parent-session level. The third post in the series goes one level deeper: when an `Agent` tool call produces a separate subagent trace file, what's in that file, how it relates back to the `toolUseResult.agentId` you just saw, and why subagent trace files are arguably the most structurally interesting part of the entire format.

If you want to look ahead, [`reference/subagent-traces.md`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/subagent-traces.md) in the repo is where that work is grounded. Part 3 is the narrative on top.

The synthetic fixtures referenced throughout this post are in [`fixtures/synthetic/`](https://github.com/frederick-douglas-pearce/claude-code-sessions/tree/main/fixtures/synthetic). If you want to run the `jq` snippets without using a real session, those files are valid JSONL by design and contain the structural patterns described here.

If there's a line type or a behavior I didn't cover that you've seen in your own sessions, I'd love to know — that's exactly the kind of thing that updates the reference docs and refines later posts.

---

**Correction (2026-07-19).** The subagent `jq` recipe above originally emitted `tokens: .toolUseResult.totalTokens`, which reads as the subagent's token total. It isn't: `totalTokens` is a single assistant turn's context-size snapshot, not a sum across the run, and using it as a token total undercounts the run (by a median of about 6x on a live corpus of 691 invocations) and can't be priced. The key has been renamed to `context_tokens` with a caveat, and a pointer added to get real token totals from the trace. See [Part 4](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/posts/2026-06-24-token-accounting-is-harder-than-it-looks.md) and [`reference/subagent-traces.md` — Token accounting](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/subagent-traces.md#token-accounting).

**Correction (2026-08-15).** The `toolUseResult` example above originally showed `toolStats` keyed by tool name (`{"Read": 4, "mcp__github__get_issue": 1, …}`). That shape has never been observed in a real session. `toolStats` is keyed by tool **category**, and every real instance carries the same seven keys shown in the corrected block. The tool-name form came from this repo's own synthetic fixture, which has since been re-cut ([#154](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/154), [#156](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/156)). `totalToolUseCount: 7` was and remains correct. Two consequences, now spelled out in the `Agent` bullet: there is no per-tool detail in the rollup at all, and `linesAdded` / `linesRemoved` are edit magnitude sitting in the same object as the counters, so summing the object does not give you a tool-call count. The claim that the shape varies by agent type was part of the same error and has been dropped. Canonical treatment: [`reference/data-dictionary.md` — `toolStats` shape](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/data-dictionary.md#toolstats-shape).

---

_Drafted with Claude Code (verified against v2.1.150). The ideas, claims, and any errors are mine._
