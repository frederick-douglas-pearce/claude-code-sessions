---
layout: post
title: "What hooks leave behind"
date: 2026-09-24 00:00:00-0800
description: "Part 6 of the anatomy series. Claude Code's hooks documentation names thirty-three outbound events; a corpus scan of 465,452 lines finds the on-disk record is a Stop-hook summary, a single field on a denied tool result, and a prompt-hook refusal seen three times."
categories: ["claude-code-sessions"]
tags: ["claude-code", "jsonl", "sessions", "hooks", "foundation"]
og_image: https://frederick-douglas-pearce.github.io/assets/img/what-hooks-leave-behind-og.png
og_card_source: social/images/2026-09-24-linkedin-what-hooks-leave-behind/og-card.png
featured: false
claude_code_version_verified: v2.1.280
humanizer_pass: v3.0.0
---

A hook is an action Claude Code is required to take at a fixed moment in its lifecycle: before a tool call, after one, when you submit a prompt, when a subagent finishes. Most often that action is a shell command, which is what this repo runs and what most examples show. It can also be an HTTP POST to a service you run (v2.1.63), a call to an MCP tool (v2.1.118), a prompt evaluated by a fast model (v2.0.30), or a subagent that inspects the situation and returns a verdict. Hooks are how you stop Claude from reading your environment files, or run a formatter after every edit, or log what your team's agents are doing. This repo runs two of them, and they are the reason the posts you are reading never quote a raw session file.

The guidance for when to reach for one fits in a sentence. If you want Claude to do something most of the time, put it in a prompt or in CLAUDE.md. If you want it to happen every time, make it a hook. The [hooks guide](https://code.claude.com/docs/en/hooks-guide) calls this deterministic control: "certain actions always happen rather than relying on the LLM to choose to run them." An instruction in a prompt or in CLAUDE.md is context the model weighs. A hook is the one part of the system that fires whether the model agrees or not.

The guarantee is narrower than it sounds. A hook guarantees that it runs, not what it concludes. A prompt-type hook fires on schedule and then asks a model, so its verdict is as negotiable as any other model output.

Hooks also execute outside the main model loop. Claude Code's harness fires them and acts on what comes back, an exit code or a JSON verdict. The model never calls one. It learns a hook ran only when the harness passes the hook's output into the conversation: a denial reason where a tool result should be, a reason to keep working instead of stopping, or text the hook adds as context. That is why Claude can tell you it was blocked by a hook and try another route. A hook that allows a call and says nothing never reaches the model at all. That raises a question the previous five posts kept deferring: once a hook has fired, is there anything in the session file to show for it?

[Part 5](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/posts/2026-09-10-the-tool-call-completely.md) ended by promising this post would go looking. I went looking, twice. The first pass answered the question with a structural scan of my session files and got several things wrong in ways the scan could not detect. The second pass built six hooks across three sessions and sanitized the result into three [fixtures](https://github.com/frederick-douglas-pearce/claude-code-sessions/tree/main/fixtures/sanitized), which is where every field value in this post comes from. Five hooks did what I designed them to do. The sixth was misconfigured, and it is the one that turned up a record shape I did not know existed. Every count comes from a rescan after the second pass: 3,680 files, 465,452 lines, zero parse errors, spanning 131 Claude Code versions from v2.1.4 to v2.1.280. The [scan output](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/tooling/format-scan/scan-2026-09-23.json) is in the repo, so you can check any count below against it, and the [scanner](https://github.com/frederick-douglas-pearce/claude-code-sessions/tree/main/tooling/format-scan) can be used to run the same scan over your own session files.

## The asymmetry

Claude Code's [hooks documentation](https://code.claude.com/docs/en/hooks) lists thirty-three events a hook can attach to. They are the fixed moments from the opening paragraph: `PreToolUse` before a tool call, `PostToolUse` after one, `UserPromptSubmit` when you send a prompt, `Stop` when Claude finishes responding, and so on. When one fires, Claude Code sends each hook attached to it a JSON payload: on stdin for a shell command, as a request body for an HTTP hook, as an interpolated argument for a prompt. Every payload carries the session id, the transcript path, the working directory and the event name, and most add fields specific to the event. The [reference](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/data-dictionary.md#hook-event-fields) documents those payloads field by field.

That is what goes out. What comes back to disk is smaller by an order of magnitude, and it is not evenly distributed across the events. Across the whole scan the on-disk hook record takes three forms:

1. A `system` line with `subtype: "stop_hook_summary"`, carrying a family of hook-execution fields
2. One field on the `user` line carrying a denied tool result
3. A `system` line with `subtype: "informational"`, left when a prompt hook refuses, seen three times

The event name every payload carries never reaches disk as a _field_. One event name does reach disk, typed into the text of an error message. That is the first instance of a pattern that runs through this post: the information you want most sits in a message's prose instead of a field you can parse. Everything else you can learn about a hook firing comes from the harness's own bookkeeping about it.

## The record is a Stop-hook summary

Hook activity rides on `system` lines. There is no hook-specific top-level type, only a `subtype` that says what kind of record the line is.

Of the 10,878 `system` lines in the scan, 4,162 record hook activity, and **4,159 of them carry `subtype: "stop_hook_summary"`.** Three lines out of 4,162 are anything else, and it took a purpose-built session to produce those three.

So this family is the trace a `Stop` or `SubagentStop` hook leaves, and anything generalized from it is a generalization from one class of hook.

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

Be careful not to overinterpret that table. Matching totals are not shared lines. One key counted 4,159 times against another counted 4,159 times is equally consistent with a single family on a single set of lines and with two disjoint sets of the same size, and nothing in a key-count scan tells those apart. The scanner computes per-line co-occurrence for the keys it treats as hook markers, which is how I can say that `hookCount`, `hookInfos`, `hookErrors`, `preventedContinuation` and `hookAdditionalContext` share lines and mean it. For `hasOutput`, `stopReason` and `toolUseID` I have matching totals and three fixtures showing them alongside the rest. That is strong evidence. It is not the corpus-wide measurement the other five have.

`toolUseID` sits on these lines too, on exactly 4,159 of them. The same key also appears on 2,747 `progress` lines, which are a different line type; add the two together and you get a number that looks like a mismatch with the family. Despite its name, on a Stop-hook line it links to no tool call. Its value is a UUID that matches no `tool_use.id`, record `uuid` or `message.id` in the session, and none of the six in the denial fixture resolves to anything. It identifies the hook firing and nothing else.

One caveat on the rates. My corpus is hook-dense, though this repo ships only two hooks of its own: a `PreToolUse` and a `PostToolUse` guard. They leave **no `system` line at all** and contribute nothing to the 4,159. The density comes from `Stop` hooks supplied by plugins, which run a review at the end of every turn. Which fields appear on these lines is a property of the format and should hold on any machine. How many lines carry them is a property of my setup, so treat 4,159 out of 10,878 as one data point and expect your own counts to differ.

## What a Stop hook actually writes

Everything below comes from one `Stop` hook I wrote to take a different action on each consecutive turn, so a single session shows the same hook allowing, blocking, and injecting context. A second `Stop` hook that fails on purpose covers the fourth case.

Here is the simplest of them, with the common envelope stripped so the hook fields stand alone. The hook ran, produced no output, and let the turn end:

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

The line in the [fixture](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/fixtures/sanitized/hook-trace-denial-and-stop-ladder.jsonl) also carries the ordinary envelope, omitted above: `parentUuid`, `uuid`, `timestamp`, `cwd`, `version`, `gitBranch`, and the session id in both of its spellings.

The other three outcomes are that same record with a handful of fields changed. This is everything that moves:

| Field                    | allowed | blocked                | injected context        | hook failed                |
| ------------------------ | ------- | ---------------------- | ----------------------- | -------------------------- |
| `hookErrors`             | `[]`    | `["the block reason"]` | `[]`                    | `["prefix + the message"]` |
| `hookAdditionalContext`  | `[]`    | `[]`                   | `["the injected text"]` | `[]`                       |
| `hasOutput`              | `false` | `true`                 | `true`                  | `true`                     |
| `hookInfos[].durationMs` | `149`   | **absent**             | `146`                   | `148`, `155`               |
| `preventedContinuation`  | `false` | `false`                | `false`                 | `false`                    |
| `stopReason`             | `""`    | `""`                   | `""`                    | `""`                       |

Two notes on reading that. The failure column comes from a second session, where I added `fail_on_stop.py` alongside the first hook, so its `hookCount` is 2 and `hookInfos` holds two entries rather than one. And `durationMs` vanishes from `hookInfos` on the blocking turn while being present on every other turn in the same session. I have no explanation for that, and one session is not enough to call it a pattern.

Four of those fields are worth reading closely, because in each case the key name and the key count together give you the wrong idea.

**`hookInfos` names the hook.** A key-count scan can tell you this field exists and how often, which is what makes it look like a dead end. Each entry carries the `command` as configured, plus `durationMs`. For a shell hook that is the script path, which is usually enough to identify it. A second hook on the same event adds a second entry, so `hookCount: 2` comes with two named commands.

**`hookErrors` is not only errors.** A hook that blocks puts its reason in that array, in the same shape as a hook that broke. What separates them is a prefix: a genuine failure arrives as `"Failed with non-blocking status code: "` followed by the message, and a block arrives as the reason alone. If you are monitoring `hookErrors` for failures, a hook that blocks on purpose reads as an error unless you split on that prefix.

**`hookAdditionalContext` is an array, not a string.** The reference doc describes it as the string a hook injected. It is a list of them, empty in the common case, and the text in it is the hook's own words, intact, because that text became part of the conversation.

**`preventedContinuation` was `false` in all four outcomes, including the block.** The semantics explain it for `Stop` hooks, where blocking means "do not stop yet" and continuation is therefore not what got prevented. But it means the field is not the signal you want if you are asking "did a hook interfere here", and across four deliberate outcomes I never observed it `true`. The scan does not read its value, so whether anything in 465,452 lines sets it `true` is open: [issue #260](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/260).

`level` is a fifth key I have not mentioned: it reads `"suggestion"` on all four of these, and `"warning"` on the lines two sections down.

## Where a denial actually lands

You would expect a denial to be written down twice: once by the hook that blocked the call, once by the tool cycle closing around it. That is what the `system` line exists for everywhere else. I built a session that denies a tool call to look at both halves, and the `system` half is not there.

A denied tool call produces one record: the `user` line that closes the tool cycle, the way any tool result does, with `is_error: true` inside the block and one extra top-level key, `toolDenialKind`. Here it is from the fixture, with two long strings elided and the tail of the envelope dropped:

```jsonl
// from https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/fixtures/sanitized/hook-trace-denial-and-stop-ladder.jsonl
{"parentUuid":"d42f0466-...","isSidechain":false,"promptId":"4c709ecf-...","type":"user","message":{"role":"user","content":[{"type":"tool_result","content":"PreToolUse:Read hook error: Blocked by AgentFluent secrets-protection hook (.claude/hooks/block_secret_reads.py). This file is a likely credential source ...","is_error":true,"tool_use_id":"toolu_01DYtoF7bT1QigmsCvMAwdei"}]},"uuid":"f5f8b633-...","timestamp":"2026-09-22T21:01:29.198Z","toolUseResult":"Error: PreToolUse:Read hook error: ...","toolDenialKind":"permission-rule","cwd":"/home/user/ccs-hook-fixture","version":"2.1.280"}
```

That is the whole trace: no `hookCount`, no `hookInfos`, and no `system` line.

Two things are worth pulling out of it. The first is that the hook **is** named, just not in a field you can type against. `toolDenialKind` says `permission-rule`, while the `content` string says `PreToolUse:Read hook error: Blocked by AgentFluent secrets-protection hook (.claude/hooks/block_secret_reads.py)`. The structured field cannot tell you a hook was involved. The prose the hook wrote can, and it names the script.

The second is the prefix. `PreToolUse:Read hook error:` encodes the event and the tool, which is the only place in the entire record where the event name appears.

Which brings us to `toolDenialKind` itself. The field is on 233 lines out of 101,553 `tool_result` blocks, roughly two in a thousand, and getting that right took two attempts. The obvious probe counts keys per `tool_result` block, so a line carrying two results contributes its keys twice, which makes a block-weighted figure an upper bound on lines rather than a count of them. The scanner now counts both ways over a stated population. They agree at 233, so no denial line carried a second result and the figure is exact.

The scan splits the values 147 `permission-rule` to 86 something else. It stops there because the scanner only names a value that a committed fixture shows, and the fixtures show only `permission-rule`. To name the rest I wrote a separate [probe](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/tooling/format-scan/probes/denial_kind.py) and ran it on 2026-10-01, over a corpus that had grown to 550,447 lines and 279 denial lines. It printed each value and checked the start of each result's text against a few fixed phrases, without printing the text itself. There are four values:

| Value                  | Lines | What the result text shows |
| ---------------------- | ----- | -------------------------- |
| `permission-rule`      | 178   | 172 name a hook            |
| `user-rejected`        | 75    | 54 say the user declined   |
| `automode-blocked`     | 19    | all 19 mention permission  |
| `automode-unavailable` | 7     | none matched a phrase      |

So the field records who denied the call: a permission rule, you, or auto mode. A hook counts as a permission rule, alongside the deny rules in your settings. On my machine `permission-rule` almost always means a hook, 172 times out of 178, but only the text can tell you which one you have. All four values first appear at v2.1.199 or later, which fits the v2.1.193 changelog entry that added denial reasons to the transcript.

## The second shape

The three hook lines that are not Stop-hook summaries are a different kind of record. A `UserPromptSubmit` hook that refuses a prompt writes this:

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

`preventContinuation` has no "ed", so it is a different key from the `preventedContinuation` on Stop lines. Nothing on the line names or counts the hook: no `hookCount`, no `hookInfos`. What it does have is `content`, which carries the hook's reasoning verbatim, another place a hook's own words reach disk.

Those three lines are the only `preventContinuation` in 465,452, and I produced all three by accident. The prompt hook that wrote them gave its evaluating model no condition it could judge, so the model treated the prompt as an injected instruction and refused three prompts at submit time. The first-pass scan, four days earlier, found none. I have never seen this record come from ordinary use.

A hook's `system` record has at least two shapes, and which one you get depends on which event fired. Anything parsing for `hookCount` will see Stop hooks and miss prompt hooks entirely.

## The honest blank

`hook_progress` does not exist on my disk.

The reference doc has carried it since v2.1.150 as a streaming event type that "may still be emitted under specific conditions," documented but unverified. A larger corpus does not rescue it. Zero occurrences across 465,452 lines, 3,680 files, and 131 Claude Code versions. The scan saw 19 distinct top-level types and `hook_progress` was not among them.

The related `progress` type is a different story: 2,747 lines, carrying `toolUseID`, `parentToolUseID`, and `agentId`. That is itself a correction, since the reference lists `progress` alongside `hook_progress` among the types it has not observed. So progress streaming does reach disk in some form, while the hook-specific flavor does not appear. The cleanest reading is that hook progress streams to your terminal and is never persisted. I cannot prove a negative from one corpus, however large, so the claim stays scoped: not observed here, across this range.

## What this means if you are building on it

**You can audit that a hook ran, which hook, and how long it took**, as long as it was a `Stop` or `SubagentStop` hook. `hookCount` plus `hookInfos` gives you a defensible record: this many hooks fired, these commands, these durations. For a compliance question shaped like "did the guard run," the file has the answers.

**You cannot audit that structurally for any other event.** A `PreToolUse` hook that denies a call leaves one typed field on a user line, and that field says `permission-rule` whether the call was blocked by a hook or by a deny rule in your permission settings. A `PostToolUse` hook that runs cleanly leaves nothing I have been able to find. This repo's two guards fire on most tool calls in most sessions and are structurally invisible whenever they let the call through.

**What you can do instead is match strings, which is something, but far from ideal.** In the probe, 172 of the 178 `permission-rule` results name a hook somewhere in their text. Only 37 begin with an `<Event>:<Tool> hook error:` prefix like the fixture's `PreToolUse:Read hook error:`, the one place an event name reaches disk. The other 135 say a hook blocked the call without naming the event, and whether the script is named depends on what the hook wrote. A parser built on any of this is built on wording that both the harness and the hook's author are free to change.

**You can read what a blocking hook said**, in three places, none of them obvious. A Stop hook's block reason lands in `hookErrors`, mixed in with real failures and separated from them only by a `"Failed with non-blocking status code: "` prefix. A prompt hook's refusal lands in `content` on an `informational` line. A tool denial's reason lands in the `tool_result` content and again in `toolUseResult`. All three are readable, and none is where the reference doc would send you.

**Do not use `preventedContinuation` as the "a hook interfered" signal.** It was `false` on every outcome I produced, including a block. The prompt hook's `preventContinuation` was `true` on all three refusals, so in those cases the key without the "ed" is the one that tracks the block.

**`hasOutput` only says that a hook produced output.** To read the output itself, look in `hookErrors` and `hookAdditionalContext`. In all eight Stop-hook lines in the fixtures, `hasOutput` was `true` exactly when one of those two arrays held something, so the output was always there to read. The scan counts keys rather than values, so I cannot say that holds across the corpus.

## Six corrections to my own reference doc

Part 5 found three places the reference doc was wrong. The research behind this post turned up six more. Two of them were fixed or half-fixed while the post sat in edit, which is noted where it applies.

- `hookAdditionalContext` was described as "Rare." It is on 3,176 lines. The "Rare" wording is gone from the doc now. The type there is still `string`, and it is an array ([issue #259](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/259)).
- `toolDenialKind` had no row at all. It has one now, with the four values from the probe and a note that three of them still lack a fixture ([issue #276](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/276)).
- The hook-execution section describes its fields as "present as a family on the same lines." Four are, measured, and `hookAdditionalContext` joins them on only 3,176 of the 4,159 ([issue #259](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/259)).
- `toolUseID` is documented as "linking the hook run to the tool call that triggered it." On a Stop-hook line it links to nothing at all ([issue #259](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/259)).
- `progress` is listed among the types the doc has not observed. It is on 2,747 lines. Only `hook_progress` still holds up ([issue #279](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/279)).
- The hook event table stops at thirty, and the coverage around it assumes shell scripts on stdin. There are thirty-three documented events and five implementation types. That is [issue #250](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/250).

Most of them have the same cause as Part 5's three: a claim written against what a structural scan could see, never checked against a session built to test it. The event table is ordinary drift: the documentation grew and the table did not.

## Why the blind spots moved

Every count in this post comes from the scan, and the scan is also why the first pass got so much wrong. It reads key names and never values, so the first-pass scan could not tell you the value of `toolDenialKind`, the value of `stopReason`, the subtype a hook line carries, the contents of `hookInfos`, or whether `toolUseID` points at anything.

That constraint is still there, and it still matters: this repo's whole premise is that session files hold prompts, paths, command output, and sometimes secrets, so the tool that reads 3,680 of them has to be provably incapable of leaking what it saw. But the constraint turned out to be narrower than the blind spot. Three things moved it.

Folding. A value can be counted without being emitted, by matching it against a fixed allowlist the scanner declares and bucketing everything else as `<other>`. The scanner already did this for the assistant message's `stop_reason`. It now does it for `subtype` and `toolDenialKind`, which is how this post can tell you that 4,159 of 4,159 family lines are `stop_hook_summary`, and that `toolDenialKind` splits 147 to 86, without either number requiring that a corpus byte reach the output.

Fixtures. Everything a fold cannot reach, a purpose-built session can. Six hooks, three runs, and a sanitizer produced three committed fixtures with real values in them, and those fixtures are where every field example above comes from. They also corrected this repo's synthetic hook fixture, which had been marking its unknown values honestly while inventing the structure around them.

A probe. The 86 denial lines the scanner left as `<other>` took a [separate probe](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/tooling/format-scan/probes/denial_kind.py), which prints only enum-shaped values and the names of fixed phrases. Its four values are in the denial section above, and the probe is in the repo, so you can run it over your own sessions. The scanner still folds three of them into `<other>`, and will until a committed fixture shows each one. If your sessions carry a value outside those four, I would like to know.

## What's next

Six posts in, every one has treated a session as a self-contained artifact: one file, one session, one conversation. That is not how anyone actually uses Claude Code. You have hundreds of sessions, across projects, across months, tied together by `--continue`, by `/branch`, by sidechains that spawn their own files. Part 7 argues that the session is the wrong unit, and that most per-session metrics mislead for exactly that reason.

The sources behind this post:

- **Reference grounding:** [`reference/data-dictionary.md`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/data-dictionary.md), specifically the [`system` hook-execution fields](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/data-dictionary.md#hook-execution-fields) and the [outbound hook event contract](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/data-dictionary.md#hook-event-fields). Each correction above links its tracking issue; [issue #243](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/243) started the first two and is closed. The unexplained `preventedContinuation` is [issue #260](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/260).
- **Series planning:** [`series-outline.md`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/.claude/specs/series-outline.md)
- **Sanitized fixtures**, the source of every field value above: [`hook-trace-stop-hook-error.jsonl`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/fixtures/sanitized/hook-trace-stop-hook-error.jsonl), [`hook-trace-denial-and-stop-ladder.jsonl`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/fixtures/sanitized/hook-trace-denial-and-stop-ladder.jsonl), and [`hook-trace-prompt-hook-refusal.jsonl`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/fixtures/sanitized/hook-trace-prompt-hook-refusal.jsonl), each with a `.scrubbed` sidecar.
- **Synthetic fixture:** [`anatomy-hook-trace.jsonl`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/fixtures/synthetic/anatomy-hook-trace.jsonl), with its [generator notes](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/fixtures/synthetic/anatomy-hook-trace.jsonl.generator.md). Rebuilt against the sanitized fixtures in [issue #257](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/257), so every shape it shows is one they observe.
- **Verification scan:** [`scan-2026-09-23.json`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/tooling/format-scan/scan-2026-09-23.json), a structural pass over 3,680 session files (465,452 lines, v2.1.4 through v2.1.280), key names, counts, and folded enum values only, no message content read. Produced by [`tooling/format-scan/`](https://github.com/frederick-douglas-pearce/claude-code-sessions/tree/main/tooling/format-scan).
- **Denial-kind probe:** [`denial_kind.py`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/tooling/format-scan/probes/denial_kind.py), the source of the four `toolDenialKind` values and their counts, run on 2026-10-01 over 4,230 session files (550,447 lines). Enum-shaped values and fixed-phrase names only, no message content printed.
- **Hooks themselves:** Claude Code's [hooks reference](https://code.claude.com/docs/en/hooks) and its [hooks guide](https://code.claude.com/docs/en/hooks-guide), which is where the deterministic-control line at the top of this post comes from, and this repo's own two guards in [`.claude/hooks/`](https://github.com/frederick-douglas-pearce/claude-code-sessions/tree/main/.claude/hooks), one of which produced the denial above.
- **The fixture hooks**, and the procedure that ran them: [`tooling/fixture-hooks/`](https://github.com/frederick-douglas-pearce/claude-code-sessions/tree/main/tooling/fixture-hooks), with its [runbook](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/tooling/fixture-hooks/RUNBOOK.md). The three runs did not share a configuration; the README records which produced which fixture.

---

_Drafted with Claude Code (verified against v2.1.280). The ideas, claims, and any errors are mine._
