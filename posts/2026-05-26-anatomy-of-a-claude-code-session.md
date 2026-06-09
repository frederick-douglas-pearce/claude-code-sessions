---
layout: post
title: "Anatomy of a Claude Code session"
date: 2026-05-26 00:00:00-0800
description: "Every Claude Code session writes a detailed local JSONL record of your prompts, tool calls, and token usage — here's what's in it and what it powers."
categories: ["foundation"]
tags: ["claude-code", "agent-sdk", "jsonl", "sessions"]
og_image: https://frederick-douglas-pearce.github.io/assets/img/anatomy-of-a-claude-code-session-og.png
og_card_source: social/images/2026-05-28-linkedin-anatomy-of-a-claude-code-session/og-card.png
featured: false
claude_code_version_verified: v2.1.150
---

Every time you run Claude Code or invoke the Agent SDK, it writes a detailed record of your session to a file on your local machine. Every prompt you've typed. Every file the model has read or edited. Every tool it has called — and the result that came back. All of it lands in JSONL form at `~/.claude/projects/`, one file per session, sitting there quietly.

Most people have never opened one of these files. That's a shame, because understanding what's in them changes how you think about every feature Claude Code offers: why `--continue` works, how `/rewind` can undo not just words but the actual files on your disk, where your token costs really come from, and what becomes possible when you treat this data as a first-class artifact rather than a byproduct.

This is the first post in a series on that format. Part 1 covers the what and the why — where the files live, what shape they take, and what Claude Code itself uses them for. Part 2 will go field-by-field through the message-type taxonomy and walk through the more surprising structural details.

---

## Where it lives

Sessions are stored at:

```
~/.claude/projects/<slug>/<session-uuid>.jsonl
```

The `<slug>` is derived from your working directory path, with slashes replaced by dashes. If you're working in `/home/fred/myproject`, the slug is `-home-fred-myproject`. One project directory, one subdirectory.

```
~/.claude/projects/
└── -home-fred-myproject/
    ├── abc12345-wild-flow-0000-000000000001.jsonl
    ├── abc12345-wild-flow-0000-000000000001/
    │   └── subagents/
    │       └── agent-99999999-...jsonl
    └── abc12345-wild-flow-0000-000000000002.jsonl
```

Each `.jsonl` file is one session. The matching subdirectory, if present, holds subagent trace files: one per agent invocation. Those traces are the subject of a later post. For now, it's enough to know they exist.

JSONL stands for JSON Lines — a format where each line is an independent, fully-formed JSON object. A session file has one JSON object per message or event. This makes sessions trivially streamable and parseable line by line without loading the entire file into memory.

---

## What's recorded — in plain English

The short answer is: everything.

Every prompt you type is in there. Every response the model generates. Every tool call — "read this file," "write that function," "run this shell command" — and every result that came back, including file contents, command output, and error messages.

Token counts are on every assistant message — the raw data for cost analysis, though turning those numbers into accurate dollar figures takes more than a simple sum (more on that below). Timestamps are on every line. The working directory and Claude Code version are recorded per message (they can change mid-session if you switch directories or update the tool).

For subagent sessions — when Claude delegates work to a specialized agent — the parent file records how long the subagent ran, how many tokens it used, how many tool calls it made, and a summary of the result. The subagent's own step-by-step trace lives in its own file.

A reader who finishes a session JSONL can reconstruct the entire interaction: what you asked, what the model decided to do, what it found, what it changed, and at what cost. That completeness is what makes the file useful for everything described below.

---

## What this powers in Claude Code itself

This section is the behind-the-curtain reveal. Each of these features that you may use daily is powered, directly or indirectly, by reads against your session JSONL files.

### Resume where you left off

```bash
claude --continue      # resumes the most recent session in the current directory
claude -c              # shorthand
```

When you run `--continue`, Claude Code finds the most recent `.jsonl` file in the current project's subdirectory, reads it, and rebuilds the conversation context. The continuity you experience isn't magic, it's a file read.

### Browse and jump between sessions

```bash
claude --resume        # opens the interactive picker
/resume                # same thing from inside an active session
```

The session picker enumerates every `.jsonl` file in your project directory (and, if you press `Ctrl+A`, across all projects on your machine). Each row in the picker — the session name, message count, git branch, time since last activity — is derived from reading those files. When you select an entry, Claude Code loads that file as your new context.

You can also filter by git branch (`Ctrl+B`) or search by pasting a pull request URL directly into the picker, and it will find the session associated with that PR.

### Branch a conversation

```bash
/branch try-different-approach
claude --continue --fork-session
```

Branching copies the session JSONL file up to the current point into a new file with a new session UUID. You're now working in the copy; the original is untouched and remains in the picker under the same name. Two session IDs, two files, both resumable. The new branch shows up as a child of the original in the picker's tree.

This is "parallel universe territory", but for code reviews, refactors, and anything else where you might want to recover the road not taken.

### Rewind code and conversation

```bash
/rewind                # or press Esc twice when the input is empty
```

This is the feature that most surprised me once I understood what was actually powering it.

Every prompt you've sent in the session is a checkpoint boundary. The rewind menu lists them, and you pick one to act on. Then you choose what to restore: code and conversation together, conversation only (keep your current files), code only (keep the conversation), or compress part of the history into a summary instead of restoring at all.

You can roll back not just what the model said, but the actual files it edited on your disk.

What makes the "restore code" part possible? Those `file-history-snapshot` lines you'll see in a session JSONL — entries that most analytics parsers skip as metadata — are precisely the data rewind needs: snapshots of file state at checkpoint moments. The docs don't spell out the storage mechanism explicitly, but the fact that checkpoints "persist across sessions" and are "cleaned up along with sessions" makes the connection a near-certainty.

The conversation history and the file history live in the same transcript, which is why you can restore them in combination or independently. Checkpoints persist across sessions, so you can resume a session days later and still rewind to an earlier point. They're automatically cleaned up on the same schedule as the session files themselves.

One caveat worth knowing: rewind covers files Claude edited directly through its file-editing tools. Files modified by bash commands (`rm`, `mv`, `cp`) or by you outside of Claude Code aren't tracked. Think of it as session-level undo for Claude's direct edits, not a replacement for git.

### Link a session to a pull request

```bash
claude --from-pr 42
```

Session files can carry per-session PR association metadata. Once a session is linked to a PR number, you can resume it by PR number directly, and the session picker lets you paste a PR URL to filter to it. If you typically open a Claude Code session per feature branch, this gives you a stable handle back to the conversation that produced the PR.

### Export and share

```bash
/export
/export my-session-notes.txt
```

`/export` reads the current session's JSONL and renders it as plain readable text — prompts, responses, and tool outputs formatted for human consumption. Without a filename argument it copies to clipboard; with one it writes to disk. The underlying session file is untouched.

### Compact long sessions

```bash
/compact
/compact focus on the auth module changes
```

When context grows long, `/compact` replaces the earlier conversation history with an AI-generated summary. The summary becomes a new line in the JSONL — one that future resumes can load without replaying every prior exchange. The original messages are preserved in the transcript; the compacted summary is what gets loaded into the context window going forward.

The `/rewind` menu offers targeted versions of the same idea: "Summarize from here" and "Summarize up to here" let you compress a specific slice of the conversation rather than everything before the current point.

---

## What this enables for you

The most immediate thing you can do with this knowledge is direct inspection. Find your project's JSONL directory:

```bash
ls ~/.claude/projects/-home-you-yourproject/
```

Stream a session as it's being written:

```bash
tail -f ~/.claude/projects/-home-you-yourproject/<session-uuid>.jsonl
```

Filter for just the token usage lines to total your costs:

```bash
cat <session>.jsonl | jq 'select(.type=="assistant") | .message.usage'
```

(`jq` is a command-line JSON processor. If you don't have it, `brew install jq` or `apt-get install jq` will get you there.)

Note that summing `input_tokens + output_tokens` gives you raw usage, not actual cost. Pricing varies by model (Sonnet, Opus, and Haiku are each priced differently), cache reads (`cache_read_input_tokens`) are billed at a fraction of regular input tokens, cache creation (`cache_creation_input_tokens`) is billed at a premium, and subagent token totals are also reported in the parent session via the `toolUseResult` envelope — so naive aggregation can double-count. The next paragraph mentions tooling that handles this properly.

You can also see which tools Claude called most often, how long each subagent took, where the model stopped and waited for tool results — all directly from the file.

Two projects I'm building take this further: [AgentFluent](https://github.com/frederick-douglas-pearce/agentfluent) diagnoses agent effectiveness from session traces — tool call patterns, retry rates, delegation efficiency. [CodeFluent](https://github.com/frederick-douglas-pearce/codefluent) reads the same files from the human-AI interaction perspective, treating the patterns as a signal for AI fluency development. Both start from the same JSONL source; what they measure differs.

---

## A peek at the raw shape

Here's the complete content of `fixtures/synthetic/anatomy-minimal-session.jsonl` — the simplest possible session, two lines. Real JSONL is one JSON object per line with no internal line breaks; I've expanded them here for readability:

```jsonl
// from https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/fixtures/synthetic/anatomy-minimal-session.jsonl
{
  "type": "user",
  "sessionId": "00000000-0000-0000-0000-000000000001",
  "uuid": "11111111-1111-1111-1111-111111111001",
  "parentUuid": null,
  "isSidechain": false,
  "cwd": "/home/dev/example-project",
  "version": "2.1.150",
  "timestamp": "2026-05-20T14:30:00.000Z",
  "message": {
    "role": "user",
    "content": "What's the capital of France?"
  }
}
{
  "type": "assistant",
  "sessionId": "00000000-0000-0000-0000-000000000001",
  "uuid": "22222222-2222-2222-2222-222222222001",
  "parentUuid": "11111111-1111-1111-1111-111111111001",
  "timestamp": "2026-05-20T14:30:01.342Z",
  "message": {
    "role": "assistant",
    "model": "claude-sonnet-4-6",
    "content": [{"type": "text", "text": "The capital of France is Paris."}],
    "usage": {
      "input_tokens": 12,
      "output_tokens": 8,
      "cache_creation_input_tokens": 0,
      "cache_read_input_tokens": 0
    },
    "stop_reason": "end_turn"
  }
}
```

A few things to notice: `type` tells you what kind of line this is — `user` here, `assistant` on the next line. `sessionId` is shared across every line in the file; it's the key that ties a session together. `parentUuid` on the first line is `null` because there's no prior message; on the assistant reply it points back to the first line's `uuid`. `timestamp` is UTC ISO 8601. And `cwd` is recorded on every line, as it can change within a session.

The assistant reply adds `message.usage` with input and output token counts. The user message doesn't carry usage because token accounting belongs to model responses.

For the next level of complexity — a tool call and its result — see [`anatomy-tool-use-cycle.jsonl`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/fixtures/synthetic/anatomy-tool-use-cycle.jsonl). For what an Agent tool invocation looks like in the parent session, including the `toolUseResult` envelope that sits outside `message`, see [`anatomy-agent-invocation.jsonl`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/fixtures/synthetic/anatomy-agent-invocation.jsonl).

Those fixtures are where Part 2 starts. See [Data Dictionary: message types](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/data-dictionary.md#message-types) (forthcoming) for the full field-level reference.

---

## What this means for your data

The first thing worth saying: this data stays on your machine. Claude Code doesn't automatically upload session transcripts anywhere. They're local files in `~/.claude/projects/`, readable only by you.

The second thing worth saying: they contain a lot. Every prompt you've typed, including ones where you pasted sensitive context, file contents you asked the model to review, command output including anything printed to stdout, and (if you're not careful) any secrets that ended up in a tool result. The file reads back like a complete record of the working session — because it is.

Practical guidance: think before sharing these files. If you want to share a session as an example — for a blog post, a bug report, or a team review — scrub it first. I'm building [`tooling/sanitizer/`](https://github.com/frederick-douglas-pearce/claude-code-sessions/tree/main/tooling/sanitizer) in [the claude-code-sessions repo](https://github.com/frederick-douglas-pearce/claude-code-sessions) specifically for this: a CLI that strips paths, identifiers, and secret patterns from session JSONL before you publish it. It's not done yet, but the design is in progress.

On retention: Claude Code's documentation describes a 30-day default cleanup via the `cleanupPeriodDays` setting in `~/.claude/settings.json`. In practice, I've found older transcripts tend to persist well past 30 days on my own machine — at the time of this post's publication, 45% of my 556 session files are older than the documented default. Whether this reflects a change in enforcement, a threshold condition for cleanup triggering, or something else, I can't say with certainty.

What I can say: if long-term retention matters to you — for analysis, regression checks, or feeding tools like AgentFluent and CodeFluent that work better with history depth — set `cleanupPeriodDays` explicitly rather than relying on the default behavior. I have mine set to 3650 (ten years — effectively never):

```json
{
  "cleanupPeriodDays": 3650
}
```

Configure for your own retention preferences, not for what you hope the default will do.

---

## What's next

You've been writing JSONL session files every time you've used Claude Code. Now you know where they are, what's in them at a high level, and why every major session management feature you use is reading them directly.

This is Part 1 of an ongoing series. Part 2 goes field by field: the full message-type taxonomy (`assistant`, `user`, the types most parsers skip entirely), why tool results live inside `user` messages rather than as their own type, the `toolUseResult` envelope on Agent invocations and why it uses camelCase when nothing else does, and how subagent traces relate to parent sessions.

If you want to get into the field-level detail before Part 2 lands, the [reference documentation at `reference/data-dictionary.md`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/data-dictionary.md) is being populated alongside this post series. It's the canonical home for format documentation as this repo matures.

Let's connect if this resonates.

---

_Drafted with Claude Code (verified against v2.1.150). The ideas, claims, and any errors are mine._
