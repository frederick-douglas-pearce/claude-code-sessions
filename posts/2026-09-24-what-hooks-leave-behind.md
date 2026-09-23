---
layout: post
title: "What hooks leave behind"
date: 2026-09-24 00:00:00-0800
description: "Part 6 of the anatomy series. Claude Code documents thirty outbound hook events; a corpus scan of 465,452 lines finds the on-disk record is a Stop-hook summary, a single field on a denied tool result, and a permission-mode line so thin it cannot be placed in time."
categories: ["claude-code-sessions"]
tags: ["claude-code", "jsonl", "sessions", "hooks", "foundation"]
og_image: https://frederick-douglas-pearce.github.io/assets/img/what-hooks-leave-behind-og.png
og_card_source: social/images/2026-09-24-linkedin-what-hooks-leave-behind/og-card.png
featured: false
claude_code_version_verified: v2.1.280
humanizer_pass: v3.0.0
---

A hook is an action Claude Code is required to take at a fixed moment in its lifecycle: before a tool call, after one, when you submit a prompt, when a subagent finishes. Most often that action is a shell command, which is what this repo runs and what most examples show. It can also be an HTTP POST to a service you run (v2.1.63), a call to an MCP tool (v2.1.118), a prompt evaluated by a fast model (v2.0.30), or a subagent that inspects the situation and returns a verdict. Hooks are how you stop Claude from reading your environment files, or run a formatter after every edit, or log what your team's agents are doing. This repo runs two of them, and they are the reason the posts you are reading never quote a raw session file.

Anthropic's guidance for when to reach for one is clear. If you want Claude to do something most of the time, put it in a prompt or in CLAUDE.md. If you want it to happen every time, make it a hook. The docs call this deterministic control: "certain actions always happen rather than relying on the LLM to choose to run them." An instruction in a prompt or in CLAUDE.md is context the model weighs. A hook is the one part of the system that fires whether the model agrees or not.

The guarantee is narrower than it sounds. A hook guarantees that it runs, not what it concludes. A prompt-type hook fires on schedule and then asks a model, so its verdict is as negotiable as any other model output. Only the firing is certain.

Hooks also execute outside the main model loop. The model does not call them and does not know they ran. Claude Code's harness fires them and acts on what comes back, an exit code or a JSON verdict. That raises a question the previous five posts kept deferring: once a hook has fired, is there anything in the session file to show for it?

[Part 5](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/posts/2026-09-10-the-tool-call-completely.md) ended by promising this post would go looking. I went looking, twice. The first pass answered the question with a structural scan and got several things wrong in ways the scan could not detect. The second pass built four hooks on purpose, ran them, and sanitized the result. Everything below is the second answer.

The evidence is two things. A structural scan of every session file on my disk: 3,680 files, 465,452 lines, zero parse errors, spanning 131 Claude Code versions from v2.1.4 to v2.1.280. And three [sanitized fixtures](https://github.com/frederick-douglas-pearce/claude-code-sessions/tree/main/fixtures/sanitized) collected from sessions built to make specific hooks fire, which is where every field value in this post comes from. The [scanner](https://github.com/frederick-douglas-pearce/claude-code-sessions/tree/main/tooling/format-scan) and the [scan output](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/tooling/format-scan/scan-2026-09-23.json) are both in the repo, so every count below can be re-derived.

## The asymmetry

Claude Code's hooks documentation describes an outbound contract. When a configured event fires, Claude Code hands the hook a JSON payload: on stdin for a shell command, as a request body for an HTTP hook, as an interpolated argument for a prompt. The [reference](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/data-dictionary.md#hook-event-fields) catalogues thirty of those events, from `SessionStart` and `PreToolUse` through `WorktreeCreate`, `ElicitationResult`, and `post-session`. Each carries the session id, the transcript path, the working directory, the event name, and usually a payload specific to the event.

That is what goes out. What comes back to disk is smaller by an order of magnitude, and it is not evenly distributed across those thirty events. Across the whole scan the on-disk hook record is three things:

1. A `system` line carrying a family of hook-execution fields
2. One field on the `user` line carrying a denied tool result
3. A `permission-mode` line with three keys total

None of the thirty event names appears in any _field_. One of them reaches disk anyway, inside an error message, which is the sort of thing this post keeps running into. Everything else you can learn about a hook firing comes from the harness's own bookkeeping about it.

## The record is a Stop-hook summary

Hook activity rides on `system` lines. There is no hook-specific top-level type. What there is, and what I missed the first time, is a `subtype` that names the event.

Of the 10,878 `system` lines in the scan, 4,162 record hook activity. **4,159 of them carry `subtype: "stop_hook_summary"`.** Not a general record of hook execution. A summary written when a `Stop` or `SubagentStop` hook runs.

That reframes everything. The field family this post was originally built around is not the trace a hook leaves. It is the trace one specific class of hook leaves.

The fields on those lines:

| Field                   | Type    | What it records                            | Lines |
| ----------------------- | ------- | ------------------------------------------ | ----- |
| `hookCount`             | number  | How many hooks matched and ran             | 4,159 |
| `hookInfos`             | array   | Per-hook detail, including the command     | 4,159 |
| `hookErrors`            | array   | Errors raised, and block reasons           | 4,159 |
| `hasOutput`             | boolean | Whether any hook produced output           | 4,159 |
| `preventedContinuation` | boolean | Whether a hook blocked Claude              | 4,159 |
| `stopReason`            | string  | Why continuation stopped                   | 4,159 |
| `hookAdditionalContext` | array   | Text a hook injected back into the context | 3,176 |

Six of those co-occur on exactly the same lines. The seventh does not: `hookAdditionalContext` is present on 3,176 of the 4,159 and absent from the other 983, so it is optional rather than part of the family.

The first version of this post asserted that seven keys co-occurred and then admitted the scan could not prove it, because aggregate key counts cannot distinguish one family on one set of lines from two disjoint sets of the same size. That caveat was correct and the assertion beside it was wrong. The scanner now computes per-line co-occurrence directly, and there are three shapes in the corpus, not one:

| Shape                                                                                        | Lines |
| -------------------------------------------------------------------------------------------- | ----- |
| `hookCount` + `hookInfos` + `hookErrors` + `preventedContinuation` + `hookAdditionalContext` | 3,176 |
| `hookCount` + `hookInfos` + `hookErrors` + `preventedContinuation`                           | 983   |
| `preventContinuation` alone                                                                  | 3     |

`toolUseID` is not on that list, and the original table was wrong to include it. It appears on 6,906 lines, which is more lines than the hook family has, so it is a general key that happens to co-occur rather than a member of the family. On a Stop-hook line it holds a UUID that matches no `tool_use.id` anywhere in the file. A `Stop` hook has no triggering tool call, so there is nothing for it to point at, and it points at nothing: a per-firing identifier rather than a join key. The original post built a small puzzle out of the count matching, and the puzzle dissolved once the counts were measured properly instead of compared.

One caveat on the rates, and this is the other thing I got wrong. I wrote that my corpus is hook-dense because this repo ships two hooks that fire on nearly every tool call. Those two hooks are `PreToolUse` and `PostToolUse` guards, and they leave **no `system` line at all**. They contribute nothing to the 4,159. That density comes from `Stop` hooks supplied by plugins, which run a review at the end of a turn. The number is real and the explanation attached to it was not.

## What a Stop hook actually writes

Here is one, from a session built to fire it. The hook ran, produced no output, and allowed the turn to end:

```json
{
  "type": "system",
  "subtype": "stop_hook_summary",
  "hookCount": 1,
  "hookInfos": [{ "command": "python3 \"$CLAUDE_PROJECT_DIR/hooks/stop_three_ways.py\"", "durationMs": 149 }],
  "hookErrors": [],
  "hookAdditionalContext": [],
  "preventedContinuation": false,
  "stopReason": "",
  "hasOutput": false,
  "level": "suggestion",
  "toolUseID": "ac6bb6b4-9582-44d3-bdb3-4505c128a6e9"
}
```

Four things in that record contradict what the first version of this post said.

**`hookInfos` names the hook.** I wrote that you cannot audit which hook ran. You can. Each entry carries the `command` as configured, plus `durationMs`. For a shell hook that is the script path, which is usually enough to identify it. A second hook on the same event adds a second entry, so `hookCount: 2` comes with two named commands.

**`hookErrors` is not only errors.** When the same hook blocks, its reason lands here:

```json
{
  "hookErrors": ["fixture hook: one-time block. Reply with the single word CONTINUING and nothing else."],
  "hasOutput": true,
  "preventedContinuation": false
}
```

And when a hook genuinely fails, the message is prefixed:

```json
{
  "hookErrors": ["Failed with non-blocking status code: fixture hook: deliberate Stop-hook failure, no decision returned"]
}
```

That prefix is the only thing separating "this hook decided something" from "this hook broke". If you are monitoring `hookErrors` for failures, a hook that blocks on purpose will read as an error unless you split on the prefix.

**`hookAdditionalContext` is an array, not a string.** The reference doc described it as the string a hook injected. It is a list of them, empty in the common case, and it is the one place a hook's own words reach the transcript intact, because that text became part of the conversation.

**`preventedContinuation` was `false` in every outcome I produced, including the block.** All four: a plain allow, a block, an injected-context pass, and a deliberate failure. The semantics explain it for `Stop` hooks, where blocking means "do not stop yet" and continuation is therefore not what got prevented. But it means the field is not the signal you want if you are asking "did a hook interfere here", and I never managed to observe it `true`. The synthetic fixture in this repo sets it `true` on a blocked tool call, and that value is a guess, labelled as one.

`stopReason` was the empty string in all four. `level` is a key the original post missed entirely: `"suggestion"` on these lines, `"warning"` on the ones in the next section but one.

## Where a denial actually lands

The first version of this post had a section called "A blocked call, recorded twice", which claimed a `PreToolUse` denial writes both a `system` line and a `user` line. I built a session that denies a tool call to show it, and the `system` line is not there.

A denied tool call produces one record: the `user` line that closes the tool cycle, the way any tool result does, with `is_error: true` inside the block and one extra top-level key. Here it is from the fixture, with two long strings elided:

```jsonl
// from https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/fixtures/sanitized/hook-trace-denial-and-stop-ladder.jsonl
{"parentUuid":"d42f0466-...","isSidechain":false,"promptId":"4c709ecf-...","type":"user","message":{"role":"user","content":[{"type":"tool_result","content":"PreToolUse:Read hook error: Blocked by AgentFluent secrets-protection hook (.claude/hooks/block_secret_reads.py). This file is a likely credential source ...","is_error":true,"tool_use_id":"toolu_01DYtoF7bT1QigmsCvMAwdei"}]},"uuid":"f5f8b633-...","timestamp":"2026-09-22T21:01:29.198Z","toolUseResult":"Error: PreToolUse:Read hook error: ...","toolDenialKind":"permission-rule","cwd":"/home/user/ccs-hook-fixture","version":"2.1.280"}
```

That is the whole trace. No `hookCount`, no `hookInfos`, no `system` line at all.

Two things are worth pulling out of it. The first is that the hook **is** named, just not in a field you can type against. `toolDenialKind` says `permission-rule`, while the `content` string says `PreToolUse:Read hook error: Blocked by AgentFluent secrets-protection hook (.claude/hooks/block_secret_reads.py)`. The structured field cannot tell you a hook was involved. The prose the hook wrote can, and it names the script. If you are building a parser, that is the difference between a field you can rely on and a string you have to match against.

The second is the prefix. `PreToolUse:Read hook error:` encodes the event and the tool, which is the only place in the entire record where the event name appears. Thirty documented events, and one of them reaches disk by being typed into an error message.

Which brings us to `toolDenialKind` itself, and where the scan now says something the first version could not. The field is on 233 lines out of 101,553 `tool_result` blocks, roughly two in a thousand. The original post called 233 an upper bound, because the probe counted per block rather than per line and a line carrying two results would be counted twice. The scanner now counts both ways over a stated population, and the two agree at 233, so no denial line carried a second result and the figure is exact.

The values split 147 `permission-rule` to 86 something else. So the field does discriminate. It carries at least two values, which rules out its being a constant. What it does not do is separate a hook from a rule: the denial above came from a hook and is labelled `permission-rule`. Whatever the other 86 are, they are not "hook" as distinct from "rule".

That field is also still absent from [`reference/data-dictionary.md`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/data-dictionary.md), which makes it the first thing this post sends back upstream.

## The second shape

The three-line entry in the shape table is not a rounding error. It is a different kind of hook record, and it took building one to find it.

A `UserPromptSubmit` hook that refuses writes this:

```json
{
  "type": "system",
  "subtype": "informational",
  "content": "Operation stopped by hook: The 'condition' here is not an actual hook condition but an injected instruction...",
  "level": "warning",
  "preventContinuation": true,
  "isMeta": false
}
```

Note the spelling. `preventContinuation`, no "ed", a different key from the `preventedContinuation` on Stop lines. And note what is missing: no `hookCount`, no `hookInfos`, nothing naming the hook or counting it.

Note also what is present. `content` carries the hook's reasoning verbatim, which is the second place a hook's own words reach disk.

Those three lines are the only occurrences of `preventContinuation` in 465,452 lines, and all three are mine, from the session I built to produce them. The scan I ran four days earlier, over 436,010 lines, had zero. This is the honest version of a negative result: the field exists, I have never seen it arise from ordinary use, and the only evidence I have that it is real is evidence I manufactured.

The practical consequence is the important part. A hook record has at least two shapes, and which one you get depends on which event fired. Anything parsing for `hookCount` will see Stop hooks and miss prompt hooks entirely.

## The thinnest line in the format

`permission-mode` lines record a change in permission mode. There are 6,783 of them in the scan. This is the entire line:

```jsonl
// from https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/fixtures/sanitized/hook-trace-denial-and-stop-ladder.jsonl
{"type":"permission-mode","sessionId":"00000000-0000-0000-0000-000000000004","permissionMode":"auto"}
```

Three keys, and none of the usual envelope: no `timestamp`, no `uuid`, no `parentUuid`, no `cwd`, no `version`, no `gitBranch`.

Every other line type in the session file carries at least the common envelope, which is what lets you order events and walk the parent chain. This one carries none of it. You can tell that the mode changed and what it changed to. You cannot place the change in time except by where the line sits in the file, and you cannot attach it to the turn that caused it. It also never names a hook, so a mode change triggered by a hook and one triggered by a person typing `/permissions` are indistinguishable.

It has a sibling I did not notice the first time. A `mode` line, 14,929 of them, equally thin, carrying `mode` rather than `permissionMode`. In the fixtures the two arrive together, `mode: "normal"` immediately before `permissionMode: "auto"`, which suggests they are two halves of one state record rather than two independent events.

For most reading this is fine, since file order is real order. For anything that merges sessions, reorders by timestamp, or reconstructs a timeline across files, both types drop out. If you are building an audit trail where "when did this session enter bypass mode" is a question someone might ask under pressure, that gap is the one to know about.

## The honest blank

`hook_progress` does not exist on my disk.

The reference doc has carried it since v2.1.150 as a streaming event type that "may still be emitted under specific conditions," documented but unverified. A larger corpus does not rescue it. Zero occurrences across 465,452 lines, 3,680 files, and 131 Claude Code versions. The scan saw 19 distinct top-level types and `hook_progress` was not among them.

The related `progress` type is a different story: 2,747 lines, carrying `toolUseID`, `parentToolUseID`, and `agentId`. So progress streaming does reach disk in some form, while the hook-specific flavor never does. The cleanest reading is that hook progress streams to your terminal and is never persisted. I cannot prove a negative from one corpus, however large, so the claim stays scoped: not observed here, across this range.

## What this means if you are building on it

**You can audit that a hook ran, which hook, and how long it took**, as long as it was a `Stop` or `SubagentStop` hook. `hookCount` plus `hookInfos` gives you a defensible record: this many hooks fired, these commands, these durations. For a compliance question shaped like "did the guard run," the file answers.

**You cannot audit that structurally for any other event.** A `PreToolUse` hook that denies a call leaves one typed field on a user line, and that field says `permission-rule` whether a hook or a rule produced it. A `PostToolUse` hook that runs cleanly leaves nothing I have been able to find. This repo's two guards fire on most tool calls in most sessions and are structurally invisible.

**What you can do instead is match strings, which is worse but not nothing.** The denial's `content` begins `PreToolUse:Read hook error:` and then names the script. That is the only place any of the thirty event names reaches disk, and it gets there by being part of a message rather than a field. A parser built on it is a parser built on wording the harness is free to change.

**You can read what a blocking hook said**, in three places, none of them obvious. A Stop hook's block reason lands in `hookErrors`, mixed in with real failures and separated from them only by a `"Failed with non-blocking status code: "` prefix. A prompt hook's refusal lands in `content` on an `informational` line. A tool denial's reason lands in the `tool_result` content and again in `toolUseResult`. All readable. None where the reference doc would send you.

**Do not use `preventedContinuation` as the "a hook interfered" signal.** It was `false` on every outcome I produced, including a block. Whatever it means, it is not that.

**`hasOutput` is a boolean about whether output happened, not what it was.** That much of the original post survives. But it is less of a limit than I made it sound, because `hookInfos`, `hookErrors`, `hookAdditionalContext`, and `content` between them carry a great deal of what a hook actually said.

## Corrections to my own reference doc, and to this post

Part 5 found three places the reference doc was wrong. This pass found more, and most of them are corrections to the first version of this post rather than to the doc.

Against the reference doc:

- `hookAdditionalContext` is not "Rare." It is on 3,176 lines. It is also an array, not a string.
- `toolDenialKind` has no row at all. It needs one, with `permission-rule` named and the remaining values marked unknown.
- The hook-execution section describes its fields as "present as a family on the same lines." Six are. `hookAdditionalContext` is optional and `toolUseID` is not a member.
- The doc's hook coverage assumes shell scripts on stdin. Five implementation types exist. That is [issue #250](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/250).

Against the first version of this post:

- The seven-field family is six fields plus an optional one, and `toolUseID` was never part of it.
- The record is a Stop-hook summary, named as such by a `subtype` I had not read.
- A blocked tool call is recorded once, not twice.
- `hookInfos` names the hook, so "you cannot audit which hook" was wrong.
- The hook-density caveat blamed two hooks that leave no trace at all.
- "None of the thirty event names appears anywhere in the JSONL" was too strong. One does, in the text of a denial message.

Both sets have the same cause as Part 5's three: a claim written against what a structural scan could see, never checked against a session built to test it. The scan was necessary and not sufficient. What closed the gap was four hooks, three runs, and a sanitizer.

## Why the blind spots moved

The first version of this post had a section explaining that it could not tell you the value of `toolDenialKind`, the value of `stopReason`, the subtype a hook line carries, or the contents of `hookInfos`, because the scanner's contract is that it never emits a value it read from a session.

That constraint is still there, and it still matters: this repo's whole premise is that session files hold prompts, paths, command output, and sometimes secrets, so the tool that reads 3,680 of them has to be provably incapable of leaking what it saw. But the constraint turned out to be narrower than the blind spot. Two things moved it.

Folding. A value can be counted without being emitted, by matching it against a fixed allowlist the scanner declares and bucketing everything else as `<other>`. The scanner already did this for `stop_reason`. It now does it for `subtype` and `toolDenialKind`, which is how this post can tell you that 4,159 of 4,159 family lines are `stop_hook_summary`, and that `toolDenialKind` splits 147 to 86, without either number requiring that a corpus byte reach the output.

Fixtures. Everything a fold cannot reach, a purpose-built session can. Four hooks, three runs, and a sanitizer produced three committed fixtures with real values in them, and those fixtures are where every field example above comes from. The synthetic fixture this post used to rely on wrote `"<unread>"` wherever it did not know, which was honest and not very useful.

What is still unread: the 86 `toolDenialKind` values that are not `permission-rule`. The fold tells you they exist and refuses to say what they are. If you have sessions with denials in them, that is one line of `jq`, and I would like to know.

## What's next

Six posts in, every one has treated a session as a self-contained artifact: one file, one session, one conversation. That is not how anyone actually uses Claude Code. You have hundreds of sessions, across projects, across months, tied together by `--continue`, by `/branch`, by sidechains that spawn their own files. Part 7 argues that the session is the wrong unit, and that most per-session metrics mislead for exactly that reason.

The sources behind this post:

- **Reference grounding:** [`reference/data-dictionary.md`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/data-dictionary.md), specifically the [`system` hook-execution fields](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/data-dictionary.md#hook-execution-fields) and the [outbound hook event contract](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/data-dictionary.md#hook-event-fields). The corrections above are tracked in [issue #243](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/243) and [issue #250](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/250).
- **Series planning:** [`series-outline.md`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/.claude/specs/series-outline.md)
- **Sanitized fixtures**, the source of every field value above: [`hook-trace-stop-hook-error.jsonl`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/fixtures/sanitized/hook-trace-stop-hook-error.jsonl), [`hook-trace-denial-and-stop-ladder.jsonl`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/fixtures/sanitized/hook-trace-denial-and-stop-ladder.jsonl), and [`hook-trace-prompt-hook-refusal.jsonl`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/fixtures/sanitized/hook-trace-prompt-hook-refusal.jsonl), each with a `.scrubbed` sidecar.
- **Synthetic fixture:** [`anatomy-hook-trace.jsonl`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/fixtures/synthetic/anatomy-hook-trace.jsonl), with its [generator notes](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/fixtures/synthetic/anatomy-hook-trace.jsonl.generator.md). Written before the sanitized fixtures existed, so its unknown values carry the literal token `"<unread>"`.
- **Verification scan:** [`scan-2026-09-23.json`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/tooling/format-scan/scan-2026-09-23.json), a structural pass over 3,680 session files (465,452 lines, v2.1.4 through v2.1.280), key names, counts, and folded enum values only, no message content read. Produced by [`tooling/format-scan/`](https://github.com/frederick-douglas-pearce/claude-code-sessions/tree/main/tooling/format-scan).
- **Hooks themselves:** Claude Code's [hooks documentation](https://code.claude.com/docs/en/hooks), and this repo's own two guards in [`.claude/hooks/`](https://github.com/frederick-douglas-pearce/claude-code-sessions/tree/main/.claude/hooks).

---

_Drafted with Claude Code (verified against v2.1.280). The ideas, claims, and any errors are mine._
