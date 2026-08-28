---
layout: post
title: "The tool call, completely"
date: 2026-08-25 00:00:00-0800
description: "Part 5 of the anatomy series. The tool_use/tool_result cycle as the format's smallest complete unit, the toolUseResult envelope by tool, and three places a fresh corpus scan found the reference doc wrong: Bash's missing exit code, Read's nested shape, and how parallel tool calls actually show up on disk."
categories: ["claude-code-sessions"]
tags: ["claude-code", "jsonl", "sessions", "tools", "foundation"]
og_image: https://frederick-douglas-pearce.github.io/assets/img/the-tool-call-completely-og.png
og_card_source: social/images/2026-08-25-linkedin-the-tool-call-completely/og-card.png
featured: false
claude_code_version_verified: v2.1.243
---

I ran a fresh corpus scan against [`reference/tool-invocation.md`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/tool-invocation.md) while drafting this post — 2,480 real session files, 289,773 lines, spanning v2.1.5 through v2.1.243, keys and counts only, no message content read. It found three places where the reference doc was wrong. One listed a field that doesn't exist. One gave a detection method that finds four parallel tool calls in a corpus that actually has over nine thousand. The third documented an envelope as flat when it's nested. All three are corrected in the doc now, and all three are below, worked into the walkthrough rather than tacked on as an appendix.

[Part 4](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/posts/2026-06-24-token-accounting-is-harder-than-it-looks.md) closed by asking what all those tool calls were actually doing, once you know what they cost. [Part 2](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/posts/2026-06-04-reading-a-claude-code-session-line-by-line.md) had already promised an answer was coming: `toolUseResult` is "where most of the high-information signal lives," it said, and moved on. This post cashes that promise: the two-line cycle underneath every tool call, what a representative set of tools leave in the envelope, and the three corrections above.

Everything below traces back to [`reference/tool-invocation.md`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/tool-invocation.md), corrected where the scan disagreed with it, plus the two synthetic fixtures the series has used since Part 2: [`anatomy-tool-use-cycle.jsonl`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/fixtures/synthetic/anatomy-tool-use-cycle.jsonl) and [`anatomy-agent-invocation.jsonl`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/fixtures/synthetic/anatomy-agent-invocation.jsonl).

## The two-line cycle

Every tool call Claude Code makes, reading a file, running a command, delegating to a subagent, gets recorded as a pairing: a `tool_use` content block on an `assistant` line, matched to a `tool_result` content block on a later `user` line. The pairing key is `tool_use_id`, and the pair is the smallest semantically complete unit of agent activity the format has. A `tool_use` block alone tells you what Claude intended. A `tool_result` block alone tells you what came back, with no idea what was asked. Only the pair tells you what actually happened, which is a different claim than "they happen to be adjacent."

```jsonl
// from https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/fixtures/synthetic/anatomy-tool-use-cycle.jsonl
{"type":"user","sessionId":"00000000-0000-0000-0000-000000000002","uuid":"11111111-1111-1111-1111-111111112001","parentUuid":null,"isSidechain":false,"cwd":"/home/dev/example-project","version":"2.1.150","timestamp":"2026-05-21T09:15:00.000Z","message":{"role":"user","content":"What's in src/main.py?"}}
{"type":"assistant","sessionId":"00000000-0000-0000-0000-000000000002","uuid":"22222222-2222-2222-2222-222222222002","parentUuid":"11111111-1111-1111-1111-111111112001","isSidechain":false,"cwd":"/home/dev/example-project","version":"2.1.150","timestamp":"2026-05-21T09:15:01.100Z","message":{"role":"assistant","model":"claude-sonnet-4-6","content":[{"type":"text","text":"I'll read the file."},{"type":"tool_use","id":"toolu_synthetic_001","name":"Read","input":{"file_path":"/home/dev/example-project/src/main.py"}}],"usage":{"input_tokens":18,"output_tokens":35,"cache_creation_input_tokens":0,"cache_read_input_tokens":1240},"stop_reason":"tool_use"}}
{"type":"user","sessionId":"00000000-0000-0000-0000-000000000002","uuid":"33333333-3333-3333-3333-333333332001","parentUuid":"22222222-2222-2222-2222-222222222002","isSidechain":false,"cwd":"/home/dev/example-project","version":"2.1.150","timestamp":"2026-05-21T09:15:01.450Z","message":{"role":"user","content":[{"type":"tool_result","tool_use_id":"toolu_synthetic_001","content":"def main():\n    print('Hello, world!')\n\nif __name__ == '__main__':\n    main()\n"}]}}
```

Three lines. Line 1 is a plain user prompt, the string shape of `message.content`. Line 2 is the assistant turn: a `text` block, then the `tool_use` block with `id: toolu_synthetic_001`, closing with `stop_reason: "tool_use"`. Line 3 is the `tool_result`, `tool_use_id` matching the `id` from line 2, `message.content` now the array shape instead of the string one. No `toolUseResult` key at all here. `Read` is light enough that it often doesn't need one; more on that below.

`stop_reason` is the forward-looking half of the pair. Two values dominate a real session: `tool_use`, meaning the model paused to call something and the very next line should carry its result, and `end_turn`, meaning it actually finished. A third, `stop_sequence`, shows up far more rarely. In the scan, the split was 93,832 to 6,724 to 212. Most turns in a working session are Claude reaching for a tool, not finishing a thought.

The two shapes of `message.content` on `user` lines, Part 2's structural twist, show up in almost exactly that proportion, inverted: 68,963 list-shaped against 7,441 string-shaped in the same scan. Seeing the array shape on a `user` line is itself a tell, before you look inside it, that a tool cycle just closed.

One thing to flag now and return to properly later. The fixture above packs a `text` block and a `tool_use` block into the same line's content array, which is legal and does happen. It's also, per the same scan, nearly extinct: 14 multi-block lines out of 289,773. Current Claude Code versions write one JSONL line per content block far more often than not. The consequences for anything that tries to detect parallel tool calls get their own section below.

## The pairing key, and what a missing pair means

`tool_use_id` is unique within a session, not globally. Two different session files can independently mint the same ID, so anything aggregating across sessions has to key on `sessionId` first. Subagent traces mint their own `tool_use_id`s too, in their own space. The parent file only ever shows the `Agent` tool's own pair plus its rollup, never the subagent's internal calls. ([Part 3](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/posts/2026-06-11-inside-the-subagent-trace-file.md) is the trace-file lens; more on that split below.)

The rule of thumb: every `tool_use` should have exactly one matching `tool_result` in the same file, and a missing one almost always means an interrupted session, the cycle never closed before the file stopped growing. The scan mostly confirms that in the direction you'd expect, and also turned up the mirror case: 102 `tool_result` blocks with no matching `tool_use` anywhere in the same file, 98 in parent sessions and 4 inside subagent traces. Rare, and explained by the same mechanism from the other side, a session resumed or a trace picked up mid-pair, with the block that would complete it sitting in a different file.

## What `toolUseResult` carries, tool by tool

Two structural rules hold across every tool. `toolUseResult` sits at the line's top level, beside `message`, not inside it, and it's camelCase where the content blocks around it are snake_case. Not every tool populates it: lightweight tools can omit it entirely, and the content a parser needs is still sitting in `tool_result.content`.

A third rule the reference doc didn't carry until this scan: `toolUseResult` is sometimes a bare string instead of an object. The scan found it on `Bash` (1,075 times), `Read` (607), `Edit` (240), `Write` (139), `WebFetch` (20), and `Grep` (14). Code that reaches straight for `toolUseResult.stdout` will error, or worse, silently return null, on every one of those lines. Check the type before you check the key.

**`Read`** looks like the lightest envelope, and the reference doc had it wrong in a smaller way that's worth naming because it was a shape error rather than a missing field. The doc listed `bytes`, `content`, and `isImage` as top-level keys. At the top level there are exactly two: `type` and `file`. Everything else is nested one level down inside `file`, where the scan found `filePath`, `content`, `numLines`, `startLine`, and `totalLines` on 8,152 results apiece. There is no `bytes` key anywhere, and no `isImage` either. An image read is signalled instead by `file.base64` plus `file.dimensions` (about 110 results each), and a read that hit the token cap sets `file.truncatedByTokenCap` (43).

The nesting is the part to actually use. `startLine`, `numLines`, and `totalLines` together tell you Claude read a slice rather than a whole file, and how much of the file it never saw. That distinction is invisible if you flatten the envelope. The other half of the picture is that `Read` skips the envelope entirely a third of the time: present on 8,866 of 13,589 results, absent on the remaining 4,723, with the content still sitting in `tool_result.content` either way.

**`Bash`** carries the richest envelope, just not the fields the reference doc used to claim. It listed a `code` field, an exit code, as one of the three signals worth reading. That field does not exist: the scan found zero `code` keys across 30,427 `Bash` envelopes and 103 Claude Code versions, and zero `durationMs` or `durationSeconds` either. The real envelope, stable since v2.1.9, is `stdout`, `stderr`, `interrupted`, and `isImage`, joined by `noOutputExpected` from v2.1.71 on. A handful of conditional keys round it out depending on what the command actually did: `returnCodeInterpretation` (the nearest thing to an exit-code signal, present on only 207 of those results), `gitOperation` (963, when the command touched git), `persistedOutputPath` and `persistedOutputSize` (162, when the output was too large to keep inline and got spilled to a file on disk instead), and `backgroundTaskId` (152, for commands launched with `run_in_background`). So the diagnosis still runs through `interrupted` plus `stderr` plus the result content, exactly as advertised. It just doesn't run through an exit code.

**`Edit`** carries the diff. `structuredPatch` showed up on 7,099 of 7,182 `Edit` results in the scan, alongside `filePath`, `oldString`, `newString`, `originalFile`, `userModified`, and `replaceAll`. Anything auditing what Claude actually changed in a file reads off `structuredPatch`; the rest of the keys are provenance.

### Agent — the parent-side lens

Everything in this section is what the _parent_ session records about a subagent run. It is not a tour of the subagent's own trace file: [Part 3](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/posts/2026-06-11-inside-the-subagent-trace-file.md) already walked that ground — `isSidechain`, the trace's own `tool_use_id` space, the per-turn `message.usage` inside `subagents/agent-<agentId>.jsonl`. What follows here is only what's visible without ever opening that file.

Here's the `toolUseResult` object from [`anatomy-agent-invocation.jsonl`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/fixtures/synthetic/anatomy-agent-invocation.jsonl), the same fixture Parts 2 and 4 have both used:

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

Two fields do the parent-side characterization that matters most. `prompt` echoes exactly what the parent asked for, word for word, so you can read task intent without re-walking the assistant line that issued it. `toolStats` gives a coarse shape of what happened, keyed by category (`readCount`, `searchCount`, `bashCount`, `editFileCount`, `otherToolCount`, plus `linesAdded`/`linesRemoved`), never by tool name. In the scan, `prompt` showed up on 1,472 `Agent` results and `toolStats` on 1,029; both are common but conditional, not guaranteed on every invocation.

`totalTokens` and `usage` are the field pair [Part 4](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/posts/2026-06-24-token-accounting-is-harder-than-it-looks.md) spent a whole post on: a single-turn snapshot, not a run total, good for a rough context-size read and nothing else. `totalToolUseCount` is the one number in this envelope that is a true run-level rollup. `agentId` is the handle to the trace file; `agentType` is which subagent ran. That's the whole parent-side picture: enough to know what was asked, roughly what kind of work happened, and where to go for more.

## Errors that still have something to say

`is_error` lives on the `tool_result` block, a boolean, absent on the happy path. What it doesn't tell you is whether the content next to it is worth reading. `Bash` is the canonical case: a command exits non-zero, `stderr` fills with a real diagnostic the model can act on, and `stdout` still holds whatever ran before the failure.

The scan makes this a measured claim rather than a hedge. Of 2,300 `tool_result` blocks flagged `is_error: true`, all 2,300 carried content. Zero were empty. A parser that treats `is_error == true` as a signal to discard the payload throws away something useful on every single error in the corpus, not just some of them.

A session can also end mid-cycle: an `assistant` line's `tool_use` with no `tool_result` anywhere after it. That's the pairing-key section's missing-pair case again — a session-level interruption, not a tool failure.

## When one turn fires several tools

This is the section the corpus scan rewrote. `reference/tool-invocation.md` used to say a parallel turn looks like one `assistant` line carrying multiple `tool_use` blocks in its `message.content` array, and gave a `jq` one-liner that counts blocks per line to find them. I ran that exact snippet against the scan corpus while writing this post. It found 4 parallel turns, out of 68,395 lines carrying a `tool_use` block. That's not a rate anyone should believe for a coding agent, so I went looking for why.

The answer is the block-splitting behavior from the two-line-cycle section, arriving with consequences. Claude Code, in current versions, writes one JSONL line per content block far more often than one line per turn. The blocks that belong to a single model turn, multiple `tool_use` calls included, share a `requestId` (and a `message.id`), not a line. Group by `requestId` instead of counting within a line, and the real picture shows up: 55,008 requests in the corpus carried at least one `tool_use` block. 45,751 of them, 83.2%, were serial: exactly one tool. 9,257, 16.8%, were parallel: two or more, with the largest single request firing 22 tools at once.

Corrected detection groups by the request, not the line:

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

The wall-clock consequence the reference doc gets right stands regardless of which detection method you use. A serial sequence of three `Read` calls takes roughly three times as long as one; a parallel batch of three takes roughly one times as long. Both show up as `readCount: 3` in a subagent's `toolStats`, which can't distinguish them at all. Only walking the actual grouping, now correctly by `requestId`, tells you which kind of turn you're looking at.

## Reading it back out

Two more `jq` recipes worth having on hand, both already in [`reference/tool-invocation.md`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/tool-invocation.md), both fine as documented.

The first builds a tool-name histogram for a whole session, everything Claude reached for, most-used first:

```bash
jq -r 'select(.type == "assistant") | .message.content[]? | select(.type == "tool_use") | .name' "$F" \
  | sort | uniq -c | sort -rn
```

The second pulls the rollup off every `Agent` invocation in a session, for a coarse read on delegation shape without opening a single trace file:

```bash
jq 'select(.toolUseResult?.toolStats?) | .toolUseResult.toolStats' "$F"
```

Both use the defensive `?` operator, on `.message.content[]?` and on `.toolUseResult?`, because real sessions carry lines where those keys are arrays, strings, or absent entirely — the bare-string `toolUseResult` from earlier in this post is exactly the case the second snippet's guard exists for. Without the guards, `jq` throws an indexing error and stops instead of skipping the line.

One caveat carried over from Part 2: `tool_use.name` and `toolStats` don't join. The histogram counts exact tool names; the rollup counts categories. To separate what the parent did from what a subagent did, by tool, you still have to open the subagent's own trace file and run the histogram query against that.

## What this post leaves out

Three things, on purpose. What a subagent's `toolUseResult` looks like from inside its own trace file, as opposed to the parent-side rollup covered above, is [Part 3](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/posts/2026-06-11-inside-the-subagent-trace-file.md)'s territory, not this post's. What any of this actually costs, in tokens or dollars, is [Part 4](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/posts/2026-06-24-token-accounting-is-harder-than-it-looks.md)'s. And tool-call retry rate, which uses this same `tool_use_id` pairing and `is_error` flag to ask a different question, already shipped as its own aside: [How often does Claude retry a tool call?](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/posts/2026-06-08-how-often-does-claude-retry-a-tool-call.md)

## What's next

Session data records what Claude Code did. Hooks (`PreToolUse`, `PostToolUse`, `UserPromptSubmit`) fire while it's working, outside the model loop entirely. The next post goes looking for whatever a hook leaves behind in the JSONL once it's fired: what's there, what's conditional, and what turns out not to be in the file at all.

The sources behind this post:

- **Reference grounding:** [`reference/tool-invocation.md`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/tool-invocation.md), now corrected on the Bash envelope, the Read envelope's shape, and parallel-call detection. The corrections landed via [issue #210](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/210), which also documents the block-splitting behavior underneath the parallel-detection error and the `tool-results/` spill mechanism.
- **Series planning:** [`series-outline.md`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/.claude/specs/series-outline.md)
- **Synthetic fixtures:** [`anatomy-tool-use-cycle.jsonl`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/fixtures/synthetic/anatomy-tool-use-cycle.jsonl), [`anatomy-agent-invocation.jsonl`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/fixtures/synthetic/anatomy-agent-invocation.jsonl)
- **Verification scan:** a structural pass over 2,480 session files (289,773 lines, v2.1.5–v2.1.243) run while drafting this post, keys and counts only, no message content read.

---

_Drafted with Claude Code (verified against v2.1.243). The ideas, claims, and any errors are mine._
