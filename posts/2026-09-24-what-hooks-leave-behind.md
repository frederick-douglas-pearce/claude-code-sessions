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

[Part 5](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/posts/2026-09-10-the-tool-call-completely.md) ended by promising this post would go looking. I went looking, twice. The first pass answered the question with a structural scan of my session files and got several things wrong in ways the scan could not detect. The second pass built four hooks on purpose, ran them, and sanitized the result.

This post rests on two pieces of evidence. The first is a structural scan of every session file on my disk: 3,680 files, 465,452 lines, zero parse errors, spanning 131 Claude Code versions from v2.1.4 to v2.1.280. The second is three [sanitized fixtures](https://github.com/frederick-douglas-pearce/claude-code-sessions/tree/main/fixtures/sanitized) collected from sessions built to make specific hooks fire, which is where every field value in this post comes from. The [scanner](https://github.com/frederick-douglas-pearce/claude-code-sessions/tree/main/tooling/format-scan) and the [scan output](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/tooling/format-scan/scan-2026-09-23.json) are both in the repo, so every count below can be re-derived.

## The asymmetry

Claude Code's hooks documentation describes an outbound contract. When a configured event fires, Claude Code hands the hook a JSON payload: on stdin for a shell command, as a request body for an HTTP hook, as an interpolated argument for a prompt. The [reference](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/data-dictionary.md#hook-event-fields) catalogues thirty of those events, from `SessionStart` and `PreToolUse` through `WorktreeCreate`, `ElicitationResult`, and `post-session`. Each carries the session id, the transcript path, the working directory, the event name, and usually a payload specific to the event.

That is what goes out. What comes back to disk is smaller by an order of magnitude, and it is not evenly distributed across those thirty events. Across the whole scan the on-disk hook record takes three forms:

1. A `system` line with `subtype: "stop_hook_summary"`, carrying a family of hook-execution fields
2. One field on the `user` line carrying a denied tool result
3. A `permission-mode` line with three keys total

The first of those is the bulk of it, and the subtype is the part to notice. What looks like a general record of hook execution is a summary written by one class of hook.

None of the thirty event names appears in any _field_. One of them reaches disk anyway, inside the text of an error message. That is the first of several places where what you need is written down as prose inside a message rather than as a field you can parse, and it is the pattern worth carrying through the rest of this post. Everything else you can learn about a hook firing comes from the harness's own bookkeeping about it.

## The record is a Stop-hook summary

Hook activity rides on `system` lines. There is no hook-specific top-level type. What there is, and it is easy to read past, is a `subtype` that names the event.

Of the 10,878 `system` lines in the scan, 4,162 record hook activity, and **4,159 of them carry `subtype: "stop_hook_summary"`.** Three lines out of 4,162 are anything else, and I had to build a session to produce those three.

So this family is the trace a `Stop` or `SubagentStop` hook leaves, and anything generalised from it is a generalisation from one class of hook.

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

Six sit on all 4,159 lines. `hookAdditionalContext` is on 3,176 of them and absent from the other 983, which makes it optional rather than part of the family.

Be careful not to overinterpret that table. Matching totals are not shared lines. One key counted 4,159 times against another counted 4,159 times is equally consistent with a single family on a single set of lines and with two disjoint sets of the same size, and nothing in a key-count scan tells those apart. The scanner computes per-line co-occurrence for the keys it treats as hook markers, which is how I can say that `hookCount`, `hookInfos`, `hookErrors`, `preventedContinuation` and `hookAdditionalContext` share lines and mean it. For `hasOutput` and `stopReason` I have matching totals and three fixtures showing them alongside the rest. That is strong evidence. It is not the corpus-wide measurement the other five have.

`toolUseID` sits on these lines too, but it is not a member of the family. It is on 6,906 lines, more than the family has, so it is a general key that happens to co-occur. On a Stop-hook line it holds a UUID matching no `tool_use.id` anywhere in the file, which follows from a `Stop` hook having no triggering tool call. It is a per-firing identifier, not a join key.

One caveat on the rates. My corpus is hook-dense, though this repo ships only two hooks of its own: a `PreToolUse` and a `PostToolUse` guard. They leave **no `system` line at all** and contribute nothing to the 4,159. The density comes from `Stop` hooks supplied by plugins, which run a review at the end of every turn. So read the presence and absence findings here as general, and do not read 4,159 out of 10,878 as a typical ratio.

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

Four of those fields are worth reading closely, because in each case the key name and the key count together give you the wrong idea.

**`hookInfos` names the hook.** A key-count scan can tell you this field exists and how often, which is what makes it look like a dead end. Each entry carries the `command` as configured, plus `durationMs`. For a shell hook that is the script path, which is usually enough to identify it. A second hook on the same event adds a second entry, so `hookCount: 2` comes with two named commands.

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

`stopReason` was the empty string in all four. And there is a fifth key I have not mentioned: `level`, which reads `"suggestion"` on these lines and `"warning"` on the ones two sections down.

## Where a denial actually lands

You would expect a denial to be written down twice: once by the hook that blocked the call, once by the tool cycle closing around it. That is what the `system` line exists for everywhere else. I built a session that denies a tool call to look at both halves, and the `system` half is not there.

A denied tool call produces one record: the `user` line that closes the tool cycle, the way any tool result does, with `is_error: true` inside the block and one extra top-level key. Here it is from the fixture, with two long strings elided:

```jsonl
// from https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/fixtures/sanitized/hook-trace-denial-and-stop-ladder.jsonl
{"parentUuid":"d42f0466-...","isSidechain":false,"promptId":"4c709ecf-...","type":"user","message":{"role":"user","content":[{"type":"tool_result","content":"PreToolUse:Read hook error: Blocked by AgentFluent secrets-protection hook (.claude/hooks/block_secret_reads.py). This file is a likely credential source ...","is_error":true,"tool_use_id":"toolu_01DYtoF7bT1QigmsCvMAwdei"}]},"uuid":"f5f8b633-...","timestamp":"2026-09-22T21:01:29.198Z","toolUseResult":"Error: PreToolUse:Read hook error: ...","toolDenialKind":"permission-rule","cwd":"/home/user/ccs-hook-fixture","version":"2.1.280"}
```

That is the whole trace. No `hookCount`, no `hookInfos`, no `system` line at all.

Two things are worth pulling out of it. The first is that the hook **is** named, just not in a field you can type against. `toolDenialKind` says `permission-rule`, while the `content` string says `PreToolUse:Read hook error: Blocked by AgentFluent secrets-protection hook (.claude/hooks/block_secret_reads.py)`. The structured field cannot tell you a hook was involved. The prose the hook wrote can, and it names the script. If you are building a parser, that is the difference between a field you can rely on and a string you have to match against.

The second is the prefix. `PreToolUse:Read hook error:` encodes the event and the tool, which is the only place in the entire record where the event name appears. Thirty documented events, and one of them reaches disk by being typed into an error message.

Which brings us to `toolDenialKind` itself. The field is on 233 lines out of 101,553 `tool_result` blocks, roughly two in a thousand, and stating that honestly took two attempts. The obvious probe counts keys per `tool_result` block, so a line carrying two results contributes its keys twice, which makes a block-weighted figure an upper bound on lines rather than a count of them. The scanner now counts both ways over a stated population. They agree at 233, so no denial line carried a second result and the figure is exact.

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

**`hasOutput` is a boolean about whether output happened, not what it was.** A real limit, and a smaller one than it looks, because `hookInfos`, `hookErrors`, `hookAdditionalContext` and `content` between them carry a great deal of what a hook actually said.

## Four corrections to my own reference doc

Part 5 found three places the reference doc was wrong. This pass found four more.

- `hookAdditionalContext` is not "Rare." It is on 3,176 lines. It is also an array, not a string.
- `toolDenialKind` has no row at all. It needs one, with `permission-rule` named and the remaining values marked unknown.
- The hook-execution section describes its fields as "present as a family on the same lines." Five are, measured. `hookAdditionalContext` is optional and `toolUseID` is not a member.
- The hook coverage assumes shell scripts on stdin. Five implementation types exist. That is [issue #250](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/250).

All four have the same cause as Part 5's three: a claim written against what a structural scan could see, never checked against a session built to test it.

## What the scan could not have told me

It is worth being specific about that, because the scan is not a weak instrument. It reads 3,680 files and 465,452 lines in 26 seconds, it has never miscounted anything I have caught it on, and every number in this post comes from it. It is also the reason I believed five wrong propositions at once.

- That the hook-execution family was seven fields on the same lines. Matching key totals are not shared lines, and a key-count scan cannot tell the two apart.
- That `toolUseID` belonged to the family. Its total is larger than the family's, which is visible in the counts and easy to skim past.
- That a blocked tool call was recorded twice. That came from a synthetic fixture built on the same assumption, which is a scan's error laundered through an example.
- That you could not tell which hook ran. The scan reads key names, never values, so `hookInfos` looks empty from the outside.
- That no event name reaches disk. None reaches a _field_. One is written into the text of an error message, where a field-oriented probe does not look.

The common shape: a structural scan tells you what is present, and every one of those was a question about what the present thing means. Four hooks, three runs and a sanitizer is what answered them.

## Why the blind spots moved

A scanner that never emits a value it read cannot tell you the value of `toolDenialKind`, the value of `stopReason`, the subtype a hook line carries, or the contents of `hookInfos`.

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
