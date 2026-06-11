---
layout: post
title: "Inside the subagent trace file"
date: 2026-06-15 00:00:00-0800
description: "Part 3 of the anatomy series. When Claude Code delegates to a subagent, the parent session records only a rollup — the subagent's real work lives in a separate trace file. Where it is, how it links back, and why isSidechain is the field that matters."
categories: ["foundation"]
tags: ["claude-code", "agent-sdk", "jsonl", "sessions", "subagents"]
og_image: https://frederick-douglas-pearce.github.io/assets/img/inside-the-subagent-trace-file-og.png
og_card_source: social/images/2026-06-15-linkedin-inside-the-subagent-trace-file/og-card.png
featured: false
claude_code_version_verified: v2.1.150
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

- **A manifest beside each trace.** Every `agent-<agentId>.jsonl` has a small `agent-<agentId>.meta.json` companion — a few hundred bytes. It's an index card for the run: the subagent's `agentType`, the human-readable `description` from the parent's `Agent` call, the `toolUseId` that spawned it, and a `worktreePath` when the subagent ran in an isolated git worktree. That `toolUseId` is the one piece of the subagent → parent relationship carried in data rather than reconstructed from disk: it names the exact parent `Agent` `tool_use` this run answers, which the file's location alone can't tell you. The manifest also lets Claude Code — and your own tooling — list and route subagents without opening and parsing every trace. One wrinkle worth flagging: the manifest spells the key `toolUseId`, while the session lines use `toolUseID`. Same value, different casing, in files that sit next to each other.
- **A `tool-results/` sibling.** Alongside `subagents/` you'll often see a `tool-results/` directory. It isn't subagent-specific — it's where Claude Code spills _large_ tool outputs that would otherwise bloat a single JSONL line. When a tool result is big, the `tool_result` content in the session carries a `<persisted-output>` wrapper with a truncated preview, and the full payload lands in `tool-results/`, named after the tool call that produced it. That's a tool-invocation concern more than a subagent one, so it gets its full treatment in Part 5 — it's flagged here only so the directory listing makes sense.

A word on versions: this post is verified against Claude Code v2.1.150, and the trace-file internals below hold there. The two sidecars are a reminder that the on-disk _layout_ keeps evolving independently of the line format — `tool-results/` predates this post's baseline, and the per-subagent `meta.json` shows up in current sessions. The [reference docs](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/subagent-traces.md) track the directory layout as it shifts; the rest of this post stays inside the trace file itself.

## What's actually in the file

Open `agent-99999999-...-999999999001.jsonl` and you'll find it looks _almost_ exactly like a parent session: the same line shape, the same `type` values, `assistant` lines with `message.content` and `message.usage`, `user` lines carrying tool results. If you've read Part 2, you can already parse it.

Here's a four-line slice of that trace — the prompt, the first tool call, and the final summary, with the four `Read`s and two `add_issue_comment`s in between elided. The full sixteen-line run pairs with the parent invocation [in the fixtures](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/fixtures/synthetic/anatomy-subagent-trace.jsonl):

```jsonl
{"type":"user","sessionId":"77777777-7777-7777-7777-777777777003","uuid":"bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbb0001","parentUuid":null,"isSidechain":true,"agentId":"99999999-9999-9999-9999-999999999001","promptId":"prompt_synthetic_001","cwd":"/home/dev/example-project","version":"2.1.150","timestamp":"2026-05-22T16:45:02.300Z","message":{"role":"user","content":"Read issue #5 and draft acceptance criteria for each open item."}}
{"type":"assistant","sessionId":"77777777-7777-7777-7777-777777777003","uuid":"aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaa0001","parentUuid":"bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbb0001","isSidechain":true,"agentId":"99999999-9999-9999-9999-999999999001","attributionAgent":"pm","attributionMcpServer":"github","attributionMcpTool":"get_issue","cwd":"/home/dev/example-project","version":"2.1.150","timestamp":"2026-05-22T16:45:03.110Z","message":{"id":"msg_synthetic_sub_001","type":"message","role":"assistant","model":"claude-sonnet-4-6","content":[{"type":"text","text":"I'll read issue #5 first."},{"type":"tool_use","id":"toolu_synthetic_sub_001","name":"mcp__github__get_issue","input":{"owner":"example","repo":"example","issue_number":5}}],"usage":{"input_tokens":900,"output_tokens":64,"cache_creation_input_tokens":9000,"cache_read_input_tokens":0},"stop_reason":"tool_use"}}
{"type":"user","sessionId":"77777777-7777-7777-7777-777777777003","uuid":"bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbb0002","parentUuid":"aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaa0001","isSidechain":true,"agentId":"99999999-9999-9999-9999-999999999001","promptId":"prompt_synthetic_001","sourceToolAssistantUUID":"aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaa0001","cwd":"/home/dev/example-project","version":"2.1.150","timestamp":"2026-05-22T16:45:04.512Z","message":{"role":"user","content":[{"type":"tool_result","tool_use_id":"toolu_synthetic_sub_001","content":"Issue #5: Migrate JSONL format docs to reference/. Open items: data-dictionary, subagent-traces, tool-invocation, two coordinating PRs."}]},"toolUseResult":{"status":"success","durationMs":1402}}
{"type":"assistant","sessionId":"77777777-7777-7777-7777-777777777003","uuid":"aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaa0008","parentUuid":"bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbb0008","isSidechain":true,"agentId":"99999999-9999-9999-9999-999999999001","attributionAgent":"pm","cwd":"/home/dev/example-project","version":"2.1.150","timestamp":"2026-05-22T16:47:13.804Z","message":{"id":"msg_synthetic_sub_008","type":"message","role":"assistant","model":"claude-sonnet-4-6","content":[{"type":"text","text":"Drafted acceptance criteria for issue #5 covering scope, success conditions, and test plan. See comment on the issue."}],"usage":{"input_tokens":980,"output_tokens":312,"cache_creation_input_tokens":0,"cache_read_input_tokens":200},"stop_reason":"end_turn"}}
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
  "totalTokens": 36000,
  "totalToolUseCount": 7,
  "usage": {
    "input_tokens": 6000,
    "output_tokens": 2000,
    "cache_creation_input_tokens": 12000,
    "cache_read_input_tokens": 16000
  },
  "toolStats": {
    "Read": 4,
    "mcp__github__get_issue": 1,
    "mcp__github__add_issue_comment": 2
  }
}
```

That's genuinely useful — at a glance you know the `pm` agent ran for ~132 seconds, burned ~36K tokens, and made 7 tool calls across `Read`, `get_issue`, and `add_issue_comment`. For a lot of questions, that's enough, and you never have to open the trace file.

But notice what it can't tell you. It says `Read` was called four times — not _which files_. It says `add_issue_comment` was called twice — not _what the comments said_, or whether the first attempt failed and the second was a retry. It gives one cumulative token number — not which turn was expensive. It records the final summary string — not the reasoning that produced it. `toolStats` is an aggregate; the trace file is the transcript.

|             | Parent `toolUseResult` (rollup)              | Subagent trace file (evidence)                                  |
| ----------- | -------------------------------------------- | --------------------------------------------------------------- |
| Granularity | One line covering the whole run              | Every model turn, every tool call, every result                 |
| Tokens      | One cumulative `totalTokens` + a `usage` sum | Per-`assistant`-line `message.usage`                            |
| Tools       | Per-tool **counts** (`{"Read": 4}`)          | Every `tool_use`/`tool_result` pair, full `input` and `content` |
| Duration    | One `totalDurationMs` scalar                 | Per-line `timestamp`s — diff them yourself                      |
| Reasoning   | Absent                                       | `thinking` blocks (when extended thinking is on)                |

This is exactly why most parsers stop at the parent envelope and treat a subagent as a single opaque tool call. The data is _there_ — it just lives in a different file, and you have to know to go get it. Anything that measures what a subagent actually did, rather than what the parent claims it did, has to read the trace.

## What you won't find in a trace file

Subagent traces are more homogeneous than parent sessions. Across the Claude Code subagent files sampled for the [reference doc](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/subagent-traces.md) (v2.1.150), only three `type` values appear: `assistant`, `user`, and the occasional `attachment`.

Conspicuously absent: `file-history-snapshot`, `system`, `permission-mode`, `ai-title`, `last-prompt`. Those are session-level concerns, and they stay in the parent file. The most consequential of these is `file-history-snapshot` — the backbone of `/rewind` that Part 2 covered. If a subagent edits code, the _edit_ happens in the subagent's run, but the **snapshot line is written to the parent session**, not the trace file. So a tool reconstructing edit history from snapshots reads the parent and will see subagent edits there; a tool reconstructing _which agent made an edit_ has to correlate the snapshot's timing against the trace. The rewind machinery is centralized in the parent; it doesn't fork per subagent.

The practical upshot: a Claude Code trace file is mostly long runs of alternating `assistant`/`user` lines. Anything that parses parent sessions can parse a trace with the same code path, given five adjustments — `isSidechain: true` on every line, `agentId` on every line, `attributionAgent` on every `assistant` line, `promptId` on every `user` line, and `sourceToolAssistantUUID` on tool-result lines only.

## The one gap worth flagging: nesting

Everything above is verified against **Claude Code v2.1.150**, and one of its properties is load-bearing for the simple layout: **Claude Code restricts subagents from invoking further subagents.** Because of that restriction, every subagent in a Claude Code session originates from the parent, and every trace file sits directly under `<session-uuid>/subagents/`. The flat layout isn't a design choice you can rely on universally — it's a consequence of the runtime forbidding nested invocation. No nested calls, so no nesting.

The [Agent SDK](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/subagent-traces.md#nesting) writes session files in the same JSONL format but may _not_ carry that restriction — subagents there may be able to invoke their own subagents. If they can, the on-disk shape of a multi-level call tree is **not yet verified**: it could be a flat `subagents/` directory holding the whole tree, a nested `subagents/<agentId>/subagents/...` layout, or something else.

I'm naming this as a real gap, not hedging the whole post: for Claude Code, the flat single-level layout is solid. But if you're writing a parser meant to handle both runtimes, don't hard-code a fixed directory depth. Walk the directory structure, and reconstruct the call tree from `agentId` relationships in the data rather than from the shape of the path. That posture costs you nothing on flat Claude Code sessions and saves you from a fragile assumption the day a nested SDK trace shows up.

## One gotcha before Part 4

There's a trap baked into the two-file split, and it deserves a flag here even though its full treatment is the next post's job.

A subagent's token usage is reported in **two places for the same work**: on every `assistant` line _inside_ the trace file (`message.usage`, per turn), and in the parent's `toolUseResult.usage` / `totalTokens` (rolled up across the whole run). These are the **same tokens, counted twice**. Sum both sources and your session-cost number is inflated — and inflated in a way that doesn't look obviously wrong, which is what makes it dangerous.

The "right" way depends on which question you're asking: do you need a quick total from the parent alone, the full breakdown that reads trace files but excludes the parent rollup, or just the subagent's cost on its own? And, what about the four token kinds, `service_tier`, and per-model pricing? That's a whole post. [Part 4 — "Token accounting is harder than it looks"](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/.claude/specs/series-outline.md) is where the double-count hazard gets the full treatment. For now, know that the same tokens live in both files, and don't add them together.

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

The first snippet answers "how many turns did this subagent take?" — a number the parent rollup never gives you. The second one expands the parent's `toolStats` counts back into an ordered list of what the subagent did, which is the difference between "called `Read` four times" and "read these four files, in this order, before commenting." That expansion — from rollup back to transcript — is one of many reasons trace files are worth opening.

## What's next

We've now seen both halves of a delegation: the parent's rollup (Part 2) and the subagent's full trace (this post). The recurring theme is that the same activity is recorded twice, at two granularities, in two files — and the token gotcha above is the sharpest edge of that fact.

[Part 4](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/.claude/specs/series-outline.md) takes the gotcha seriously. "What did this session actually cost?" sounds like a sum, but between the four token kinds, cache reads priced differently from cache creation, `service_tier`, per-model pricing, and the double-count we just flagged, it's the question this whole series has been circling. Token accounting is harder than it looks — and the data to get it right is all sitting in these files.

The sources behind this post:

- **Reference grounding:** [`reference/subagent-traces.md`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/subagent-traces.md)
- **Series planning:** [`series-outline.md`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/.claude/specs/series-outline.md)
- **Synthetic fixtures** — valid JSONL, so the `jq` snippets run against them without a real session: the [parent invocation](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/fixtures/synthetic/anatomy-agent-invocation.jsonl) and the [subagent trace](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/fixtures/synthetic/anatomy-subagent-trace.jsonl)

If your own traces show a `type` value, an attribution field, or a nesting layout I haven't described — especially from the Agent SDK — that's exactly the kind of thing that updates the reference docs and sharpens later posts. Please let me know by creating an issue in the `claude-code-sessions` repo linked above.

---

_Drafted with Claude Code (verified against v2.1.150). The ideas, claims, and any errors are mine._
