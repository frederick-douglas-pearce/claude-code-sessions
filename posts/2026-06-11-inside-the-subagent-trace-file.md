---
layout: post
title: "Inside the subagent trace file"
date: 2026-06-11 00:00:00-0800
description: "Part 3 of the anatomy series. When Claude Code delegates to a subagent, the parent session records only a rollup — the subagent's real work lives in a separate trace file. Where it is, how it links back, and why isSidechain is the field that matters."
categories: ["claude-code-sessions"]
tags: ["claude-code", "agent-sdk", "jsonl", "sessions", "subagents", "foundation"]
og_image: https://frederick-douglas-pearce.github.io/assets/img/inside-the-subagent-trace-file-og.png
og_card_source: social/images/2026-06-11-linkedin-inside-the-subagent-trace-file/og-card.png
featured: false
claude_code_version_verified: v2.1.233
---

[Part 2 of this series](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/posts/2026-06-04-reading-a-claude-code-session-line-by-line.md) ended by teasing the value of `agent_id` in the parent session jsonl data as "the literal handle that takes you to the subagent's full trace file".

This post fills in the details. We're going to take that `agent_id`, follow it to a separate file on disk, and open it. The same activity is recorded twice — at two granularities, in two files — and that split is the thread this post pulls on.

Here's the short version: when the parent session delegates to a subagent, it records a **rollup** — a condensed account of the whole run: a duration, a token total, a per-tool count, and the subagent's final summary. It does not record what the subagent actually did, step by step. That lives somewhere else.

## Following the handle

The `agent_id` from the Part 2 snippet is `99999999-9999-9999-9999-999999999001`. That same UUID is a file name. The subagent's complete trace lives at:

```
~/.claude/projects/<slug>/<session-uuid>/subagents/agent-99999999-9999-9999-9999-999999999001.jsonl
```

Three things to notice about that path:

- `<slug>` is the same project root as the parent session — the slugified `cwd` (Part 1 covered the slug convention).
- `<session-uuid>/` is a directory that sits _next to_ the parent's `<session-uuid>.jsonl` file, sharing its name. It's created lazily — it exists only when the session produces overflow that doesn't belong inline: a subagent trace, a spilled tool result, or both.
- `subagents/` holds the traces — one `agent-<agentId>.jsonl` per subagent invocation, each with its own `agentId`. Invoke the `pm` agent three times in one session and you get three traces. Each trace also gets a small `agent-<agentId>.meta.json` companion, and there's often a `tool-results/` sibling directory too — both covered below.

So the directory layout for a session that delegated work looks like this:

```
~/.claude/projects/<slug>/
├── <session-uuid>.jsonl                          # parent session
└── <session-uuid>/
    ├── subagents/
    │   ├── agent-<agentId>.jsonl                  # the trace — one per invocation
    │   ├── agent-<agentId>.meta.json             #   + a tiny manifest beside each trace
    │   └── …                                     #   (one .jsonl + .meta.json pair per subagent)
    └── tool-results/                             # large tool outputs spilled out of the JSONL (see Part 5)
        └── …
```

The only parent → subagent link in the session data is `toolUseResult.agentId` on the parent's `user` line — the same value the Part 2 snippet surfaced. The file name is that value with an `agent-` prefix and a `.jsonl` suffix. There's no per-line back-pointer _inside_ the subagent's lines that names the parent; that direction is reconstructed from where the file sits on disk — with a partial assist from the `meta.json` sidecar (below), which records the parent `toolUseId` that spawned the run.

Two other things share that `<session-uuid>/` directory, and naming them now keeps the layout above from being a surprise when you open your own:

- **A manifest beside each trace.** Every `agent-<agentId>.jsonl` has a small `agent-<agentId>.meta.json` companion — a few hundred bytes. It's an index card for the run: the subagent's `agentType`, the human-readable `description` from the parent's `Agent` call, the `toolUseId` that spawned it, a `worktreePath` when the subagent ran in an isolated git worktree, and (from v2.1.187) a `spawnDepth` integer that matters once subagents start spawning subagents — see [the nesting section](#the-gap-that-closed-nesting). That `toolUseId` is the one piece of the subagent → parent relationship carried in data rather than reconstructed from disk: it names the exact parent `Agent` `tool_use` this run answers, which the file's location alone can't tell you. The manifest also lets Claude Code — and your own tooling — list and route subagents without opening and parsing every trace. One wrinkle worth flagging: the manifest spells the key `toolUseId`, while the session lines use `toolUseID`. Same value, different casing, in files that sit next to each other.
- **A `tool-results/` sibling.** Alongside `subagents/` you'll often see a `tool-results/` directory. It isn't subagent-specific — it's where Claude Code spills _large_ tool outputs that would otherwise bloat a single JSONL line. When a tool result is big, the `tool_result` content in the session carries a `<persisted-output>` wrapper with a truncated preview, and the full payload lands in `tool-results/`, named after the tool call that produced it. That's a tool-invocation concern more than a subagent one, so it gets its full treatment in Part 5 — it's flagged here only so the directory listing makes sense.

A word on versions: this post is verified against Claude Code v2.1.150, and the trace-file internals below hold there. The two sidecars are a reminder that the on-disk _layout_ keeps evolving independently of the line format — `tool-results/` predates this post's baseline, and the per-subagent `meta.json` shows up in current sessions. The [reference docs](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/subagent-traces.md) track the directory layout as it shifts; the rest of this post stays inside the trace file itself.

## What's actually in the file

Open `agent-99999999-...-999999999001.jsonl` and you'll find it looks _almost_ exactly like a parent session: the same line shape, the same `type` values, `assistant` lines with `message.content` and `message.usage`, `user` lines carrying tool results. If you've read Part 2, you can already parse it.

Here's a four-line slice of that trace — the prompt, the first tool call, and the final summary, with the four `Read`s and two `add_issue_comment`s in between elided. The full sixteen-line run pairs with the parent invocation [in the fixtures](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/fixtures/synthetic/anatomy-subagent-trace.jsonl):

```jsonl
{"type":"user","sessionId":"77777777-7777-7777-7777-777777777003","uuid":"bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbb0001","parentUuid":null,"isSidechain":true,"agentId":"99999999-9999-9999-9999-999999999001","promptId":"prompt_synthetic_001","cwd":"/home/dev/example-project","version":"2.1.150","timestamp":"2026-05-22T16:45:02.300Z","message":{"role":"user","content":"Read issue #5 and draft acceptance criteria for each open item."}}
{"type":"assistant","sessionId":"77777777-7777-7777-7777-777777777003","uuid":"aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaa0001","parentUuid":"bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbb0001","isSidechain":true,"agentId":"99999999-9999-9999-9999-999999999001","attributionAgent":"pm","attributionMcpServer":"github","attributionMcpTool":"get_issue","cwd":"/home/dev/example-project","version":"2.1.150","timestamp":"2026-05-22T16:45:03.110Z","message":{"id":"msg_synthetic_sub_001","type":"message","role":"assistant","model":"claude-sonnet-4-6","content":[{"type":"text","text":"I'll read issue #5 first."},{"type":"tool_use","id":"toolu_synthetic_sub_001","name":"mcp__github__get_issue","input":{"owner":"example","repo":"example","issue_number":5}}],"usage":{"input_tokens":3,"output_tokens":60,"cache_creation_input_tokens":13000,"cache_read_input_tokens":0},"stop_reason":"tool_use"}}
{"type":"user","sessionId":"77777777-7777-7777-7777-777777777003","uuid":"bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbb0002","parentUuid":"aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaa0001","isSidechain":true,"agentId":"99999999-9999-9999-9999-999999999001","promptId":"prompt_synthetic_001","sourceToolAssistantUUID":"aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaa0001","cwd":"/home/dev/example-project","version":"2.1.150","timestamp":"2026-05-22T16:45:04.512Z","message":{"role":"user","content":[{"type":"tool_result","tool_use_id":"toolu_synthetic_sub_001","content":"Issue #5: Migrate JSONL format docs to reference/. Open items: data-dictionary, subagent-traces, tool-invocation, two coordinating PRs."}]},"toolUseResult":{"status":"success","durationMs":1402}}
{"type":"assistant","sessionId":"77777777-7777-7777-7777-777777777003","uuid":"aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaa0008","parentUuid":"bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbb0008","isSidechain":true,"agentId":"99999999-9999-9999-9999-999999999001","attributionAgent":"pm","cwd":"/home/dev/example-project","version":"2.1.150","timestamp":"2026-05-22T16:47:13.804Z","message":{"id":"msg_synthetic_sub_008","type":"message","role":"assistant","model":"claude-sonnet-4-6","content":[{"type":"text","text":"Drafted acceptance criteria for issue #5 covering scope, success conditions, and test plan. See comment on the issue."}],"usage":{"input_tokens":3,"output_tokens":300,"cache_creation_input_tokens":1500,"cache_read_input_tokens":27000},"stop_reason":"end_turn"}}
```

Read top to bottom, that's the shape of a subagent run: the prompt that started it, an `assistant` turn that calls a tool, the `tool_result` for that call, and — skipping the run's middle — the final `assistant` turn with the summary. (That last line's `parentUuid` points at `…bbbb0008`, the result of the second comment, which is one of the elided turns; in the full trace the chain is unbroken.) The summary on that last line — _"Drafted acceptance criteria for issue #5..."_ — is the exact string the parent recorded as the subagent's `tool_result`. Same words, two files.

But look at the fields that _aren't_ in a parent session. Every single line carries `isSidechain: true`. Every line carries a top-level `agentId`. The `assistant` lines carry `attributionAgent`. The `user` lines carry `promptId`, and the tool-result line carries `sourceToolAssistantUUID`. None of those appear in a parent session file. They're the markers that tell you you've crossed into a sidechain.

## `isSidechain` is the field that matters

If you take one field away from this post, take this one.

Every line inside a subagent trace file carries `isSidechain: true`. Parent-session lines carry `isSidechain: false`, or omit the field entirely on some message types. That makes it the **canonical, content-free signal** for telling a subagent line apart from a parent-session line.

Why does "content-free" matter? Because the alternatives are all worse:

- **Don't branch on file path.** A hook script, or a tool that's been handed a stream of lines from a pipe, may not know which file a line came from.
- **Don't branch on the presence of `agentId`.** It's reliable inside trace files, but keying on "does this field exist" is brittle — it couples your parser to one field's presence rather than to a boolean that exists precisely to answer this question.
- **Don't branch on `attribution*` heuristics.** Those fields have a per-line-type presence pattern (more on that below), so "does this line have `attributionAgent`" gives you the wrong answer on every `user` line in the trace.

`isSidechain` is the one field designed to answer "is this a subagent line?" — so branch on it. The operational rule of thumb:

- **Skip sidechain lines** when you're counting user-visible turns or rendering the main conversation thread. They aren't main-conversation turns.
- **Skip them** when aggregating per-session tokens _if you're also reading the parent's rollup_ — otherwise you count the same tokens twice (the [token-accounting](#one-gotcha-before-part-4) section below is the warning; Part 4 is the fix).
- **Include them** when you're auditing what the agent actually did — which tools it called, what it reasoned about, how long each step took. That's the entire reason the trace file exists.

## The `sessionId` is not the one you'd expect

Here's the tricky part of the parent ↔ subagent relationship: **the subagent does not share the parent's `sessionId`.**

Look at the trace fixture again. Every line carries `"sessionId":"77777777-7777-7777-7777-777777777003"`. Now look at the parent invocation [in the paired fixture](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/fixtures/synthetic/anatomy-agent-invocation.jsonl) — its lines carry `"sessionId":"00000000-0000-0000-0000-000000000003"`. Different values. Each subagent invocation gets its **own** `sessionId`, distinct from the parent's and distinct from every other subagent's.

So where is the parent's session UUID in the subagent file? It isn't — not in any field. It appears only as the **directory name** that contains the subagent file:

```
~/.claude/projects/<slug>/<PARENT-session-uuid>/subagents/agent-<agentId>.jsonl
                          ▲
                          this, and only this, is the parent's sessionId
```

The link from subagent back to parent is encoded entirely in the file's location on disk. There is no per-line back-pointer that names the parent session or the parent's invoking `assistant` line. If you move a subagent file out of its directory, you've severed the only thread connecting it to its parent.

This has a concrete consequence for tooling: if you glob `~/.claude/projects/**/subagents/*.jsonl` and read the lines without tracking which directory each came from, you've thrown away the parent linkage. The `agentId` tells you _which invocation_ a line belongs to; it does not tell you _which parent session_ launched it. Only the path does.

## The subagent-specific fields, and the one that lies about its name

Three subagent-specific fields show up alongside `agentId` — one of them an `attribution*` field, two not — and each has a **strict per-line-type presence pattern**. They don't appear on every line — they appear on specific line types, consistently. Knowing the pattern lets you branch on `type` first and only check the fields that apply:

| Field                     | `assistant` lines | `user` lines                 | What it is                                                                                                                        |
| ------------------------- | ----------------- | ---------------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| `agentId`                 | ✅ always         | ✅ always                    | UUID of this subagent invocation — matches the file name and the parent's `toolUseResult.agentId`.                                |
| `attributionAgent`        | ✅ always         | ❌ never                     | The subagent _type_ that ran (`"pm"`, `"general-purpose"`, a custom agent name). Matches `toolUseResult.agentType` on the parent. |
| `promptId`                | ❌ never          | ✅ always                    | Identifier for the prompt-flow this user line belongs to. Stable across the user lines of one invocation.                         |
| `sourceToolAssistantUUID` | ❌ never          | ✅ on tool-result lines only | The `uuid` of the `assistant` line whose `tool_use` this user line is the result for.                                             |

(There's also an `attributionMcpServer` / `attributionMcpTool` pair that shows up on `assistant` lines involved in an MCP-tool turn — you can see it on the first `assistant` line of the fixture, which calls `mcp__github__get_issue`. The exact trigger condition is still an [open verification item](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/subagent-traces.md#open-verification-items).)

(And one more, `attributionSkill`, marks an `assistant` turn that ran under an invoked Skill. It's the odd one out: unlike the fields above, it shows up in _parent_ sessions too — Skills run in the main loop, not just inside subagents — so it is _not_ a sidechain signal. For the "is this a subagent line?" question, `isSidechain` remains the field to branch on; the [reference doc](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/subagent-traces.md#attribution-fields) covers `attributionSkill` in full.)

The interesting one is `sourceToolAssistantUUID`, because its name invites a wrong inference. It _sounds_ like it should point back at the parent's invoking `assistant` line — the "source tool" that launched the subagent. It does not.

Trace it in the fixture. The tool-result `user` line carries `"sourceToolAssistantUUID":"aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaa0001"`. That UUID is the `uuid` of the `assistant` line _earlier in the same subagent file_ — the one that emitted `tool_use` id `toolu_synthetic_sub_001`. In other words, it's an **internal pairing key**: it ties a tool result back to the tool call it answers, within the subagent's own trace.

```
subagent file (internal pairing — stays within the file)
─────────────
assistant line:  uuid "aaaa…0001"  emits tool_use "toolu_synthetic_sub_001"
                 ▲
                 │  sourceToolAssistantUUID
                 │
user line:       tool_result.tool_use_id "toolu_synthetic_sub_001"
```

It's redundant with `tool_use_id`, but it lives at the top level of the line, which lets a parser reconstruct the assistant ↔ user tool cycle without descending into the `message.content` array. Useful — but it points _inward_, never at the parent. The only parent link carried on the trace lines themselves is the forward `agentId`; the back-reference lives in the directory path and the `meta.json` sidecar (above), not in the line data.

## The rollup is a summary. The trace file is the evidence.

This is the single most important thing to understand about the split, so it's worth stating plainly: **the parent's `toolUseResult` envelope is a rollup; the subagent trace file is the actual record.**

Here's what the parent saw for our `pm` invocation — the `toolUseResult` from the parent fixture, expanded:

```json
{
  "status": "success",
  "prompt": "Read issue #5 and draft acceptance criteria for each open item.",
  "agentId": "99999999-9999-9999-9999-999999999001",
  "agentType": "pm",
  "totalDurationMs": 132140,
  "totalTokens": 28803,
  "totalToolUseCount": 7,
  "usage": {
    "input_tokens": 3,
    "output_tokens": 300,
    "cache_creation_input_tokens": 1500,
    "cache_read_input_tokens": 27000
  },
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
```

That's genuinely useful. At a glance you know the `pm` agent ran for ~132 seconds, made 7 tool calls, spent four of them reading, and edited nothing. For a lot of questions, that's enough, and you never have to open the trace file.

But notice what it can't tell you, and one field that will actively mislead you. `toolStats` is keyed by tool **category**, not by tool name, and those seven keys are the entire vocabulary. So `readCount: 4` means four read-category calls, and it can't distinguish `Read` from `Glob`, let alone tell you _which files_. The three non-read calls collapse into `otherToolCount: 3` without naming a single tool or MCP server, so the rollup can't tell you the agent touched GitHub at all, never mind _what the comments said_ or whether the first attempt failed and the second was a retry. It records the final summary string, not the reasoning that produced it. There's a shape trap in the object too: `linesAdded` and `linesRemoved` are edit magnitude, not invocation counts, so summing every value in `toolStats` yields a number dominated by line counts. Use `totalToolUseCount` for the invocation total. And the token fields are a trap of their own: `totalTokens` and `usage` here snapshot a **single** turn, the subagent's last, not the whole run, so they undercount what the run actually processed and can't tell you which turn was expensive. `toolStats`, `totalToolUseCount`, and `totalDurationMs` are genuine run-level rollups; the token fields are not. Part 4 is where that trap gets its full treatment.

| Dimension   | Parent `toolUseResult` (rollup)                  | Subagent trace file (evidence)                                  |
| ----------- | ------------------------------------------------ | --------------------------------------------------------------- |
| Granularity | One line covering the whole run                  | Every model turn, every tool call, every result                 |
| Tokens      | A single turn's `totalTokens` + `usage` snapshot | Per-`assistant`-line `message.usage`, summable to the run total |
| Tools       | Per-**category** counts (`{"readCount": 4}`)     | Every `tool_use`/`tool_result` pair, full `input` and `content` |
| Duration    | One `totalDurationMs` scalar                     | Per-line `timestamp`s — diff them yourself                      |
| Reasoning   | Absent                                           | `thinking` blocks (when extended thinking is on)                |

This is exactly why most parsers stop at the parent envelope and treat a subagent as a single opaque tool call. The rollup is thinner than it looks: no tool names anywhere, so the trace file is the _only_ place a subagent's tool identity is recorded. The data is _there_ — it just lives in a different file, and you have to know to go get it. Anything that measures what a subagent actually did, rather than what the parent claims it did, has to read the trace.

## What you won't find in a trace file

Subagent traces are more homogeneous than parent sessions. Across the Claude Code subagent files sampled for the [reference doc](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/subagent-traces.md) (v2.1.150), only three `type` values appear: `assistant`, `user`, and the occasional `attachment`.

Conspicuously absent: `file-history-snapshot`, `system`, `permission-mode`, `ai-title`, `last-prompt`. Those are session-level concerns, and they stay in the parent file. The most consequential of these is `file-history-snapshot` — the backbone of `/rewind` that Part 2 covered. If a subagent edits code, the _edit_ happens in the subagent's run, but the **snapshot line is written to the parent session**, not the trace file. So a tool reconstructing edit history from snapshots reads the parent and will see subagent edits there; a tool reconstructing _which agent made an edit_ has to correlate the snapshot's timing against the trace. The rewind machinery is centralized in the parent; it doesn't fork per subagent.

The practical upshot: a Claude Code trace file is mostly long runs of alternating `assistant`/`user` lines. Anything that parses parent sessions can parse a trace with the same code path, given five adjustments — `isSidechain: true` on every line, `agentId` on every line, `attributionAgent` on every `assistant` line, `promptId` on every `user` line, and `sourceToolAssistantUUID` on tool-result lines only.

## The gap that closed: nesting

When this post first ran, this section flagged nesting as the one open question, and guessed wrong about where it would land. The guess was that subagents spawning subagents was an Agent SDK concern that Claude Code didn't have, so the defensive advice below was insurance you'd never cash in on a Claude Code session. It arrived in Claude Code first, at **v2.1.172**, and the advice is now the thing keeping your parser correct rather than a hedge.

Here's the corrected picture. **Claude Code subagents can spawn their own subagents.** Every trace file still sits directly under `<session-uuid>/subagents/`, but not for the reason this post originally gave. The old reasoning was that the flat layout was a _consequence_ of the runtime forbidding nested invocation: no nested calls, so no nesting. That inference is dead. The layout is flat anyway.

That's now an observation rather than a deduction. A scan across 2,047 session files spanning v2.1.109 to v2.1.233 found **zero** nested `subagents/<agentId>/subagents/…` directories, including in the sessions that do contain depth-2 subagents. A depth-2 subagent is written as a sibling of its own parent, in the same folder, with nothing in the path to say which spawned which. So the diagram above still holds at every depth observed, and the reason it holds is that Claude Code chose a flat layout, not that it had no other option.

Two things follow that are worth building on:

- **The directory tells you nothing about the tree.** It never did in the SDK, and now it doesn't in Claude Code either. The `meta.json` sidecar's `toolUseId` is what names the spawning call, and at depth 2 that call lives in _another subagent's trace file_, not the parent session. Rebuilding the tree means indexing tool-use ids across every file in the session, not just the parent.
- **A new manifest key records the depth.** From v2.1.187, `meta.json` carries `spawnDepth`, an integer that's 1 for a subagent the main session spawned directly. Read it defensively: it's absent from every manifest written before v2.1.187, and absent means "this version didn't record it," not "depth 1."

The depth cap is a moving target and the upstream changelog contradicts itself about it, so don't hard-code a number. `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH` is the environment variable that controls it; setting it to `1` restores the old single-level behavior if you want the simple world back.

The advice from the original version stands unchanged, which is the part I'm glad about: **don't hard-code a fixed directory depth. Walk the directory structure, and reconstruct the call tree from `agentId` relationships in the data rather than from the shape of the path.** What changed is the reason to bother. That posture used to cost you nothing on flat Claude Code sessions and pay off only if you also targeted the SDK. Now it's what stands between you and silently dropping every depth-2 subagent in any session from v2.1.172 onward.

One place the two runtimes still genuinely differ, and it matters for Part 4's subject: in the Agent SDK, a depth-2 spawn's `tool_result` carries **no** `toolUseResult` rollup at all, just an inline `subagent_tokens` trailer. Claude Code keeps the full rollup at depth 2. So the cost-attribution story in the next post doesn't degrade as Claude Code sessions get deeper, even though it does for the SDK.

## One gotcha before Part 4

There's a trap baked into the two-file split, and it deserves a flag here even though its full treatment is the next post's job.

A subagent's token usage shows up in **two places that measure different things**: on every `assistant` line _inside_ the trace file (`message.usage`, per turn), and in the parent's `toolUseResult.usage` / `totalTokens`. It is tempting to read the parent's number as the run total, but it is a snapshot of a **single** turn, the subagent's last one. Sum the trace and you get what the run processed; read the rollup and you get one turn, which understates it, often several-fold. The two are not interchangeable, and the gap doesn't look obviously wrong, which is what makes it dangerous.

The "right" way depends on which question you're asking: the subagent's real processed tokens (sum the trace), a session total (parent turns plus each subagent's trace sum), or its cost (the trace, priced per turn at each turn's own model). And what about the four token kinds, `service_tier`, and per-model pricing? That's a whole post. [Part 4 — "Token accounting is harder than it looks"](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/posts/2026-06-24-token-accounting-is-harder-than-it-looks.md) is where the rollup-versus-trace hazard gets the full treatment. For now, know that the parent's number is a single-turn snapshot, not the run total, so don't read it as the subagent's cost.

## Try it on your own sessions

Find a session that delegated to a subagent (the Part 2 rollup snippet will surface the `agentId`), then point these at the trace file. Both use defensive `?` operators so non-matching lines are skipped rather than raising errors — the same discipline from Part 2. They assume `jq` on bash or zsh (macOS, Linux, or Windows via WSL or Git Bash); native PowerShell users can install `jq` with `winget install jqlang.jq` and adapt the piping.

```bash
# Count the subagent's model turns (every assistant line in the trace):
cat ~/.claude/projects/<slug>/<session-uuid>/subagents/agent-<agentId>.jsonl \
  | jq -r 'select(.isSidechain? == true and .type? == "assistant") | .uuid' \
  | wc -l

# List the tools the subagent ACTUALLY called, in order —
# the evidence behind the parent's toolStats aggregate:
cat ~/.claude/projects/<slug>/<session-uuid>/subagents/agent-<agentId>.jsonl \
  | jq -r 'select(.type? == "assistant")
      | .message.content[]? | select(.type? == "tool_use") | .name'
```

The first snippet answers "how many turns did this subagent take?" — a number the parent rollup never gives you. The second one expands the parent's `toolStats` counts back into an ordered list of what the subagent did, which is the difference between "four read-category calls and three other calls" and "read these four files, in this order, then commented on the issue twice." That expansion — from rollup back to transcript — is one of many reasons trace files are worth opening.

## What's next

We've now seen both halves of a delegation: the parent's rollup (Part 2) and the subagent's full trace (this post). The recurring theme is that the same activity is recorded twice, at two granularities, in two files — and the token gotcha above is the sharpest edge of that fact.

[Part 4](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/posts/2026-06-24-token-accounting-is-harder-than-it-looks.md) takes the gotcha seriously. "What did this session actually cost?" sounds like a sum, but between the four token kinds, cache reads priced differently from cache creation, `service_tier`, per-model pricing, and the rollup-versus-trace trap we just flagged, it's the question this whole series has been circling. Token accounting is harder than it looks, and the data to get it right is all sitting in these files.

The sources behind this post:

- **Reference grounding:** [`reference/subagent-traces.md`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/subagent-traces.md)
- **Series planning:** [`series-outline.md`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/.claude/specs/series-outline.md)
- **Synthetic fixtures** — valid JSONL, so the `jq` snippets run against them without a real session: the [parent invocation](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/fixtures/synthetic/anatomy-agent-invocation.jsonl) and the [subagent trace](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/fixtures/synthetic/anatomy-subagent-trace.jsonl)

If your own traces show a `type` value, an attribution field, or a nesting layout I haven't described — a `spawnDepth` above 2 would be especially interesting, from either runtime — that's exactly the kind of thing that updates the reference docs and sharpens later posts. Please let me know by creating an issue in the `claude-code-sessions` repo linked above.

---

**Correction (2026-07-19).** An earlier version of this post described the parent's `toolUseResult.usage` / `totalTokens` as "rolled up across the whole run" and called the trace and rollup "the same tokens, counted twice," warning that summing both inflates a session total. That was backwards. The token fields in the rollup are a single assistant turn's snapshot (the subagent's last), not a run total, so reading them as the run's cost undercounts it, by a median of about 6x on a live corpus of 691 invocations. The `toolStats`, `totalToolUseCount`, and `totalDurationMs` fields are genuine run-level rollups; the token fields are the exception. The displayed envelope, the comparison table, and the "gotcha" section have been corrected, and the paired fixtures were re-cut to match ([#144](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/144)). The canonical treatment is in [`reference/subagent-traces.md` — Token accounting](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/subagent-traces.md#token-accounting).

**Correction (2026-08-15).** An earlier version of this post showed `toolStats` keyed by tool name (`{"Read": 4, "mcp__github__get_issue": 1, …}`) and reasoned from that shape: that the rollup told you the agent made "7 tool calls across `Read`, `get_issue`, and `add_issue_comment`," and that its limit was not knowing _which files_ `Read` touched. The shape was wrong. `toolStats` is keyed by tool **category**, with the same seven keys on every instance observed in a real session, and the tool-name form has never appeared in one. It came from this repo's own synthetic fixture, since re-cut ([#154](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/154), [#156](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/156)). This widens the post's argument rather than weakening it: the rollup names no tools at all, and MCP calls disappear into `otherToolCount` without naming a server, so the trace file is even more necessary than the original text claimed. The envelope, the comparison table, and the three prose passages that reasoned from tool names have been corrected, and one further trap is now called out: `linesAdded` / `linesRemoved` share the object with the invocation counters, so summing `toolStats` values gives a line-count-dominated number rather than a tool-call count. Use `totalToolUseCount`. Canonical treatment: [`reference/data-dictionary.md` — `toolStats` shape](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/data-dictionary.md#toolstats-shape).

**Correction (2026-08-15).** The nesting section was titled "The one gap worth flagging: nesting" and rested on a Claude Code property that stopped being true after this post ran: that subagents cannot spawn their own subagents. It was accurate at v2.1.150, the version this post was verified against, and Claude Code gained nested subagents at **v2.1.172**, 22 versions later. Unlike the two corrections above, nothing here was wrong when written. This is version drift, which is what re-verification is for, so this post's `claude_code_version_verified` moves from v2.1.150 to v2.1.233 (the nesting section is the part re-verified against the newer corpus; the inline v2.1.150 markers elsewhere still mark their own scope). Three claims were wrong going forward and are corrected: that the flat layout is a _consequence_ of the restriction, that nesting is an Agent SDK possibility rather than a Claude Code reality, and that "for Claude Code, the flat single-level layout is solid." The layout _is_ still flat, now confirmed by observation rather than deduced from the restriction: a scan across 2,047 session files spanning v2.1.109–v2.1.233 found zero nested `subagents/` directories, including in sessions containing depth-2 subagents ([#169](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/169), [#170](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/170)). The section's actual advice, walk the directory and rebuild the tree from `agentId` relationships rather than path shape, was right for the wrong reason and is unchanged. What changed is that it is now load-bearing on Claude Code, not just insurance against a hypothetical SDK trace. Also added: `spawnDepth` in the manifest, `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH` as the depth control, and the one place the runtimes still diverge (the SDK drops the `toolUseResult` rollup at depth ≥ 2; Claude Code keeps it). Canonical treatment: [`reference/subagent-traces.md` — Nesting](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/subagent-traces.md#nesting).

---

_Drafted with Claude Code (verified against v2.1.233). The ideas, claims, and any errors are mine._
