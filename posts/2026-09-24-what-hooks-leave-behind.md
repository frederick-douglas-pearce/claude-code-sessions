---
layout: post
title: "What hooks leave behind"
date: 2026-09-24 00:00:00-0800
description: "Part 6 of the anatomy series. Claude Code documents thirty outbound hook events; a corpus scan of 436,010 lines finds the on-disk record is seven fields on system lines, one field on a denied tool result, and a permission-mode line so thin it cannot be placed in time."
categories: ["claude-code-sessions"]
tags: ["claude-code", "jsonl", "sessions", "hooks", "foundation"]
og_image: https://frederick-douglas-pearce.github.io/assets/img/what-hooks-leave-behind-og.png
og_card_source: social/images/2026-09-24-linkedin-what-hooks-leave-behind/og-card.png
featured: false
claude_code_version_verified: v2.1.278
humanizer_pass: v3.0.0
---

A hook is a shell script Claude Code runs at a fixed moment: before a tool call, after one, when you submit a prompt, when a subagent finishes. Hooks are how you stop Claude from reading your environment files, or run a formatter after every edit, or log what your team's agents are doing. This repo runs two of them, and they are the reason the posts you are reading never quote a raw session file.

Hooks execute outside the model loop. The model does not call them and does not know they ran. Claude Code fires them, reads what they print, and acts on the exit code. That raises a question the previous five posts kept deferring: once a hook has fired, is there anything in the session file to show for it?

[Part 5](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/posts/2026-09-10-the-tool-call-completely.md) ended by promising this post would go looking. I went looking. The answer is more than I expected and less than you need, which makes it worth writing down carefully.

The evidence is a structural scan of every session file on my disk: 3,500 files, 436,010 lines, zero parse errors, spanning 130 Claude Code versions from v2.1.4 to v2.1.278. The scan reads key names and counts. It does not read field values, ever, which turns out to shape the answer as much as anything I found. The [scanner](https://github.com/frederick-douglas-pearce/claude-code-sessions/tree/main/tooling/format-scan) and the [scan output](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/tooling/format-scan/scan-2026-09-19.json) are both in the repo, so every number below can be re-derived.

## The asymmetry

Claude Code's hooks documentation describes an outbound contract. When a configured event fires, Claude Code writes a JSON payload to your script's stdin. The [reference](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/data-dictionary.md#hook-event-fields) catalogues thirty of those events, from `SessionStart` and `PreToolUse` through `WorktreeCreate`, `ElicitationResult`, and `post-session`. Each carries the session id, the transcript path, the working directory, the event name, and usually a payload specific to the event.

That is what goes out. What comes back to disk is smaller by an order of magnitude. Across the whole scan the on-disk hook record is three things:

1. A six-field family on `system` lines, plus a tool-linkage key
2. One field on the `user` line carrying a denied tool result
3. A `permission-mode` line with three keys total

None of the thirty event names appears anywhere in the JSONL. Everything you can learn about a hook firing comes from the harness's own bookkeeping about it.

## Where hook firings land

Hook activity rides on `system` lines. There is no hook-specific top-level type. Of the 10,429 `system` lines in the scan, 3,964 carry this family:

| Field                   | Type    | What it records                       |
| ----------------------- | ------- | ------------------------------------- |
| `hookCount`             | number  | How many hooks matched and ran        |
| `hookInfos`             | array   | Per-hook detail                       |
| `hookErrors`            | array   | Errors raised during execution        |
| `hasOutput`             | boolean | Whether any hook produced output      |
| `preventedContinuation` | boolean | Whether a hook blocked Claude         |
| `stopReason`            | string  | Why continuation stopped              |
| `toolUseID`             | string  | The tool call that triggered the hook |

All seven appear on exactly 3,964 lines. Aggregate key counts cannot prove co-occurrence, though: two disjoint sets of 3,964 lines would produce the same table. Equal counts across seven keys are strong circumstantial evidence of one family on one set of lines, and that is how I am reading it, but the scan does not settle it.

`toolUseID` is the useful one. It joins a `PreToolUse` or `PostToolUse` record back to the tool call that set it off, matching the `tool_use.id` from the assistant line. Note the spelling changes across the boundary: `toolUseID` at the top level of a `system` line, `tool_use_id` inside a content block. Part 5 built its whole tool-cycle join on the second spelling, and this is the first place the other one matters.

There is a puzzle in the count. A `Stop` hook has no triggering tool call, so `toolUseID` has nothing to point at, yet the count matches the rest of the family exactly. Either `Stop`-hook lines fall outside the 3,964, or the key is there with a null value. The scanner counts a key whose value is null, so present-and-null fits both the arithmetic and the semantics. The [fixture](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/fixtures/synthetic/anatomy-hook-trace.jsonl) takes that reading and labels it a hypothesis.

One caveat on all the rates in this post. My corpus is unusually hook-dense, because this repo ships two hooks that fire on nearly every tool call. Read the presence and absence findings as general. Do not read 3,964 out of 10,429 as a typical ratio.

## A blocked call, recorded twice

The interesting case is a hook that says no. Here is the whole shape, from the synthetic fixture:

```jsonl
// from https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/fixtures/synthetic/anatomy-hook-trace.jsonl
{"type":"assistant","sessionId":"00000000-0000-0000-0000-000000000004","uuid":"22222222-2222-2222-2222-222222224002","parentUuid":"11111111-1111-1111-1111-111111114001","isSidechain":false,"userType":"external","cwd":"/home/dev/example-project","gitBranch":"main","version":"2.1.278","timestamp":"2026-09-24T14:02:01.200Z","message":{"role":"assistant","model":"claude-sonnet-4-6","content":[{"type":"text","text":"I'll remove the build directory."},{"type":"tool_use","id":"toolu_synthetic_004","name":"Bash","input":{"command":"rm -rf ./build","description":"Remove stale build artifacts"}}],"usage":{"input_tokens":24,"output_tokens":48,"cache_creation_input_tokens":0,"cache_read_input_tokens":2180},"stop_reason":"tool_use"}}
{"type":"system","subtype":"<unread>","sessionId":"00000000-0000-0000-0000-000000000004","uuid":"44444444-4444-4444-4444-444444444003","parentUuid":"22222222-2222-2222-2222-222222224002","isSidechain":false,"userType":"external","cwd":"/home/dev/example-project","gitBranch":"main","version":"2.1.278","timestamp":"2026-09-24T14:02:01.260Z","isMeta":true,"toolUseID":"toolu_synthetic_004","hookCount":1,"hookInfos":["<unread>"],"hookErrors":[],"hasOutput":true,"preventedContinuation":true,"stopReason":"<unread>"}
{"type":"user","sessionId":"00000000-0000-0000-0000-000000000004","uuid":"33333333-3333-3333-3333-333333334004","parentUuid":"44444444-4444-4444-4444-444444444003","isSidechain":false,"userType":"external","cwd":"/home/dev/example-project","gitBranch":"main","version":"2.1.278","timestamp":"2026-09-24T14:02:01.265Z","sourceToolAssistantUUID":"22222222-2222-2222-2222-222222224002","toolDenialKind":"<unread>","message":{"role":"user","content":[{"type":"tool_result","tool_use_id":"toolu_synthetic_004","is_error":true,"content":"Blocked by a PreToolUse hook."}]}}
```

The denial is written down twice, in two different places, by two different mechanisms. The `system` line says `preventedContinuation: true` and names the tool call via `toolUseID`. The `user` line closes the tool cycle the way any tool result does, with `is_error: true` inside the block, and carries a new top-level key: `toolDenialKind`.

`toolDenialKind` appeared on 227 observations out of 96,608 `tool_result` blocks in the scan. That denominator is block-weighted rather than line-weighted, so 227 is an upper bound on the number of distinct lines: a line carrying two tool results contributes its top-level keys twice. It is a small number either way, roughly two in a thousand.

My scanner counts the key and refuses to read the value, so I do not know whether `toolDenialKind` distinguishes a hook block from a user clicking "no" at a permission prompt, or from an auto-mode classifier denial, or whether it separates anything at all. The name promises a discriminator and the evidence stops at the type. Anyone who wants the real vocabulary can read it out of their own sessions in a line of `jq`, and I would like to hear what the values are.

That field is also not in [`reference/data-dictionary.md`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/data-dictionary.md) at all, which makes it the first thing this post sends back upstream.

## The thinnest line in the format

`permission-mode` lines record a change in permission mode. There are 6,681 of them in the scan. This is the entire line:

```jsonl
// from https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/fixtures/synthetic/anatomy-hook-trace.jsonl
{"type":"permission-mode","sessionId":"00000000-0000-0000-0000-000000000004","permissionMode":"plan"}
```

Three keys, and none of the usual envelope: no `timestamp`, no `uuid`, no `parentUuid`, no `cwd`, no `version`, no `gitBranch`.

Every other line type in the session file carries at least the common envelope, which is what lets you order events and walk the parent chain. This one carries none of it. You can tell that the mode changed and what it changed to. You cannot place the change in time except by where the line sits in the file, and you cannot attach it to the turn that caused it. It also never names a hook, so a mode change triggered by a hook and one triggered by a person typing `/permissions` are indistinguishable.

For most reading that is fine, since file order is real order. For anything that merges sessions, reorders by timestamp, or reconstructs a timeline across files, `permission-mode` drops out. If you are building an audit trail where "when did this session enter bypass mode" is a question someone might ask under pressure, that gap is the one to know about.

## The honest blank

`hook_progress` does not exist on my disk.

The reference doc has carried it since v2.1.150 as a streaming event type that "may still be emitted under specific conditions," documented but unverified. A larger corpus does not rescue it. Zero occurrences across 436,010 lines, 3,500 files, and 130 Claude Code versions. The scan saw 19 distinct top-level types and `hook_progress` was not among them.

The related `progress` type is a different story: 2,747 lines, carrying `toolUseID`, `parentToolUseID`, and `agentId`. So progress streaming does reach disk in some form, while the hook-specific flavor never does. The cleanest reading is that hook progress streams to your terminal and is never persisted. I cannot prove a negative from one corpus, however large, so the claim stays scoped: not observed here, across this range.

## What this means if you are building on it

You can audit that a hook ran and whether it blocked. `hookCount`, `preventedContinuation`, and `toolUseID` give you a defensible record: this many hooks fired on this tool call, and one of them stopped it. For a compliance question shaped like "did the guard run," the file answers.

You cannot audit which hook, or what it said. `hookInfos` holds per-hook detail, and `hasOutput` is a boolean about whether a script printed something rather than what it printed. The one exception is `hookAdditionalContext`, which stores the string a `Stop` or `SubagentStop` hook injected back into the model's context. That is the only place a hook's own words land in the transcript, and it exists because that string became part of the conversation. Output that only influenced a decision leaves a boolean behind.

A hook that allows leaves the same trace as one that denies, minus the `toolDenialKind`. If your threat model includes a hook silently failing open, `hookErrors` is the field to watch, and the scan cannot tell you whether those arrays are usually empty, because that is a value.

## Two corrections to my own reference doc

Part 5 found three places the reference doc was wrong. This one found two more.

`hookAdditionalContext` is not rare. The doc describes it as "Rare." It appears on 2,981 `system` lines against the 3,964 carrying the hook family. Even granting that aggregate counts cannot prove those are the same lines, a field on that many lines is not rare in any useful sense. The description predates a corpus large enough to check it.

`toolDenialKind` is undocumented. It is a real top-level key on `tool_result`-bearing `user` lines and the reference has no row for it. Adding one, with the value vocabulary explicitly marked unknown, is the follow-up.

Both corrections have the same cause as Part 5's three: a claim written against a small sample, never re-checked against a larger one. That is the argument for keeping the scan output in the repo instead of running it ad hoc and quoting the result.

## Why so much of this is "I didn't look"

There is a pattern in what I could not answer: the value of `toolDenialKind`, the value of `stopReason`, the subtype a hook line carries, the contents of `hookInfos`, and whether `hookErrors` is usually empty.

All of them are values, and the scanner's contract is that it never emits one. That constraint exists because this repo's whole premise is that session files hold prompts, paths, command output, and sometimes secrets, so the tool that reads 3,500 of them has to be provably incapable of leaking what it saw. Folding a closed enum like `stop_reason` against a fixed allowlist is safe and the scanner already does it. `toolDenialKind` and `subtype` could get the same treatment, and that is now on the list.

So the shape of this post's answer is partly a property of hooks and partly a property of how I am allowed to look. Both are worth saying out loud. The synthetic fixture applies the same discipline: every unread value carries the literal token `"<unread>"` instead of a plausible guess.

## What's next

Six posts in, every one has treated a session as a self-contained artifact: one file, one session, one conversation. That is not how anyone actually uses Claude Code. You have hundreds of sessions, across projects, across months, tied together by `--continue`, by `/branch`, by sidechains that spawn their own files. Part 7 argues that the session is the wrong unit, and that most per-session metrics mislead for exactly that reason.

The sources behind this post:

- **Reference grounding:** [`reference/data-dictionary.md`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/data-dictionary.md), specifically the [`system` hook-execution fields](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/data-dictionary.md#hook-execution-fields) and the [outbound hook event contract](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/data-dictionary.md#hook-event-fields). The two corrections above are tracked in [issue #68](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/68).
- **Series planning:** [`series-outline.md`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/.claude/specs/series-outline.md)
- **Synthetic fixture:** [`anatomy-hook-trace.jsonl`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/fixtures/synthetic/anatomy-hook-trace.jsonl), with its [generator notes](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/fixtures/synthetic/anatomy-hook-trace.jsonl.generator.md)
- **Verification scan:** [`scan-2026-09-19.json`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/tooling/format-scan/scan-2026-09-19.json), a structural pass over 3,500 session files (436,010 lines, v2.1.4 through v2.1.278), key names and counts only, no message content read. Produced by [`tooling/format-scan/`](https://github.com/frederick-douglas-pearce/claude-code-sessions/tree/main/tooling/format-scan).
- **Hooks themselves:** Claude Code's [hooks documentation](https://code.claude.com/docs/en/hooks), and this repo's own two guards in [`.claude/hooks/`](https://github.com/frederick-douglas-pearce/claude-code-sessions/tree/main/.claude/hooks).

---

_Drafted with Claude Code (verified against v2.1.278). The ideas, claims, and any errors are mine._
