---
layout: post
title: "How often does Claude retry a tool call?"
date: 2026-06-08
description: "The session JSONL's tool_use_id pairing key (introduced in Part 2) lets you measure how often Claude retries after a tool error — and the answer is different by tool, which is where it gets interesting."
categories: [analysis]
tags: [claude-code, jsonl, sessions, tool-use]
og_image: https://frederick-douglas-pearce.github.io/assets/img/how-often-does-claude-retry-a-tool-call-og.png
claude_code_version_verified: v2.1.150
---

[Part 2 of this series](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/posts/2026-06-04-reading-a-claude-code-session-line-by-line.md) introduced `tool_use_id` as the pairing key that ties every tool call to its result. Every `tool_use` block on an `assistant` line carries an `id`; the corresponding `tool_result` block on the next `user` line carries a `tool_use_id` that matches it. Walk those pairs and you've reconstructed the tool history of an entire session.

The natural next question is: what does that pairing key let you _measure_?

Tool-call retry rate is one of the simplest signals to compute from the JSONL — three fields and a join. The answer is more telling than the simplicity suggests: different tools retry at very different rates, in patterns that say something about both the work being done and each tool's failure modes.

This is a standalone analysis post, not part of the foundation series. It's meant to be short: one signal, one heuristic, one worked example.

---

## Defining "retry" from the JSONL

A retry, for this purpose, is an `assistant` line that invokes a tool by name when a prior invocation of the same tool — in the same session — returned with `is_error: true` on its `tool_result` block.

The exact fields involved:

- `message.content[].type == "tool_use"` and `.name` — the tool being invoked and its name.
- `message.content[].type == "tool_result"` and `.is_error == true` — the result block, nested inside a `user` line, flagging the failure.

[`reference/tool-invocation.md`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/tool-invocation.md#error-patterns) documents both fields. The short version: `is_error` is an optional boolean on `tool_result`; it's absent on the happy path and `true` when the tool reported a failure. The `tool_use_id` key links each `tool_result` back to its originating `tool_use` — that's how you know which tool name corresponds to the error.

Walking the cycle in order:

1. Index each `tool_use` block by its `id` as you see it. Note the tool `name`.
2. When you encounter a `tool_result` with `is_error: true`, look up the tool name via `tool_use_id`.
3. If a later `assistant` line invokes a `tool_use` with the same `name`, that's a retry.

A few edge cases worth naming before moving on. This heuristic — a rule of thumb, not a guarantee — is **error-driven**: it only counts retries triggered by explicit `is_error: true` flags. The model may also retry in response to partial or confusing output without `is_error` being set. A `Bash` command that exits zero but produces unexpected output, for example, might prompt a second `Bash` call that looks identical to a retry but carries no error signal in the JSONL. Separately, a user resubmitting a prompt mid-session can trigger a tool re-invocation that the heuristic would count as a retry when it isn't one in any meaningful sense.

The alternative is to compare consecutive same-tool calls by input similarity, regardless of the error signal — that catches the quiet retries this heuristic misses, at the cost of per-tool tuning to define "similar enough" across very different input schemas. For a first signal, error-driven wins on precision: every result it surfaces is a case where Claude explicitly received an error and tried again.

---

## The `jq` to extract it

Two snippets. The first builds the per-session tool-call list with error flags. The second counts retries per tool name.

```bash
# Per-session tool invocations with their error status.
# Produces one line per tool call: {"name": "Bash", "id": "toolu_...", "is_error": false}
jq -r '
  if .type == "assistant" then
    .message.content[]? | select(.type == "tool_use") |
    {name: .name, id: .id, is_error: false}
  elif .type == "user" then
    .message.content[]? | select(.type == "tool_result") |
    {tool_use_id: .tool_use_id, is_error: (.is_error // false)}
  else empty end
' <session>.jsonl
```

```bash
# Retry count per tool name: tool calls that followed an is_error: true result.
# Works by joining on tool_use_id, then counting same-name calls after any error.
jq -rn '
  [inputs] |
  # Build a map of tool_use_id -> name from assistant lines
  (map(select(.type == "assistant") |
    .message.content[]? | select(.type == "tool_use") |
    {(.id): .name}) | add) as $names |
  # Find all tool_use_ids that returned is_error: true
  ([.[] | select(.type == "user") |
    .message.content[]? |
    select(.type == "tool_result" and .is_error == true) |
    $names[.tool_use_id]] | group_by(.) |
    map({(.[0]): length}) | add // {}) as $errors |
  $errors
' <session>.jsonl
```

Run the second snippet with `jq -rn --slurp` or pipe it with `--null-input` depending on your `jq` version. The `(... // false)` on `is_error` handles the common case where the field is absent on successful results — absence and `false` mean the same thing here.

The `$names` map connects each error result back to the tool that caused it — without it, you'd know an error occurred but not which tool was responsible.

---

## Worked example: one retry, walked end to end

Here's a single retry from a real session — an `Explore` subagent dispatched by the `/simplify` skill, paging through a saved diff file. The cycle comes from a [subagent trace](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/subagent-traces.md) rather than a parent session, but the pairing pattern is identical: same `tool_use` → `tool_result` blocks, same `tool_use_id` linkage.

The first call passes `Read`'s `offset` as an array:

```json
{ "type": "tool_use", "id": "toolu_…7pg", "name": "Read", "input": { "file_path": "/tmp/simplify_481.diff", "offset": [447, 525] } }
```

`offset` is supposed to be a single starting line number. The result comes back flagged:

```json
{
  "type": "tool_result",
  "tool_use_id": "toolu_…7pg",
  "is_error": true,
  "content": "<tool_use_error>InputValidationError: Read failed due to the following issue:\nThe parameter `offset` type is expected as `number` but provided as `array`</tool_use_error>"
}
```

The `tool_use_id` on the result matches the `id` on the call — the pairing key earning its keep. On the next assistant turn, the model fixes the shape:

```json
{ "type": "tool_use", "id": "toolu_…As", "name": "Read", "input": { "file_path": "/tmp/simplify_481.diff", "offset": 447, "limit": 80 } }
```

Same tool, corrected input, succeeds. By the heuristic's definition — a same-name `tool_use` following an `is_error: true` result for that tool — this is one unambiguous retry. The full trace lives at [`fixtures/sanitized/retry-rate-parameter-shape.jsonl`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/fixtures/sanitized/retry-rate-parameter-shape.jsonl); the three blocks above are lines 45, 46, and 47.[^version]

[^version]: The single-retry cycle above was captured against Claude Code v2.1.158; the rest of this post's structural claims (field names, pairing key, error flag) are verified against v2.1.150 as noted in the front matter. The fields in question — `tool_use.id`, `tool_result.tool_use_id`, `is_error` — have been stable across v2.1.150 and v2.1.158.

---

## Aggregating across one session

A single cycle shows the heuristic working. A session-wide distribution shows what it surfaces when you aggregate. From a different real session — sanitizer-PRD work on this repo, with intermixed `Bash`, `Edit`, `Read`, and `Write` activity, fixture at [`retry-rate-mixed-tools.jsonl`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/fixtures/sanitized/retry-rate-mixed-tools.jsonl) — 3 of 56 tool calls returned `is_error: true`:

| Tool    | Errors / Calls |
| ------- | -------------: |
| `Bash`  |         1 / 20 |
| `Edit`  |         2 / 19 |
| `Read`  |         0 / 13 |
| `Write` |          0 / 2 |

The non-zero entries cluster on the tools that operate against mutable state — a `Bash` command that fails because a dependency isn't installed yet, an `Edit` whose target string already changed. `Read` and `Write` can fail in principle but do so rarely. The relative order of `Bash` and `Edit` depends entirely on the work mix; what holds across sessions is the clustering, not the ranking.

---

## What the numbers mean — and don't mean

**The error-driven definition wins on precision.** Across a 46-session corpus, a looser approach — counting any repeat call to the same tool as a "retry," regardless of the error flag — fired 155 times. 119 of those (77%) had no error at all; they were ordinary sequential work mistaken for recovery. The cleanest false positive — a case where the heuristic fires but there's no actual retry — was one run that flagged an agent for "retrying" `mcp__github__get_issue` six times. It wasn't retrying anything; it was reading GitHub issues 465, 466, 467, 468, 469 in order. Five different inputs, zero errors, counted as five retries. Gating on `is_error: true` makes that enumeration vanish from the count, while leaving the genuine array-vs-number recovery above in.

**A non-zero `Bash` retry rate is expected.** `Bash` is where Claude runs builds, tests, installs, and environment checks. These commands fail for reasons that have nothing to do with Claude's reasoning — a dependency not yet installed, a port in use, an output format that changes with tool version. A non-zero `Bash` retry rate isn't a sign that something went wrong; it's a sign that the session involved real operations against a real environment. The model is supposed to try again after these errors. How high "normal" is depends entirely on the work mix — a session doing environment setup will sit much higher than the 1-of-20 (5.0%) in the aggregate table above, which was a content-editing session.

**A high `Edit` retry rate is more diagnostic.** `Edit` uses string matching (`old_string` must appear exactly in the file). Retries here usually mean the file changed between when Claude read it and when it tried to edit it — either because Claude's own earlier `Bash` commands modified it, or because the model read stale context. An `Edit` retry rate above ~20% across many sessions is worth investigating: it's a signal that the session has a context-freshness problem, not just an environment-variability problem.

**Near-zero `Read` rate is normal — but when `Read` does fail, it's usually a parameter-type mismatch.** `Read` errors are uncommon (the aggregate session above had zero), but the worked-example retry is the recurring kind when they do happen: an `offset` or `limit` parameter passed as the wrong type (an array instead of a number, for instance). A `Read` retry rate above a few percent in a dataset is worth inspecting individually — either the model is exploring paths it hasn't confirmed exist, or it's mis-shaping parameters.

**Rate near 1.0 on any tool is an interruption signal, not a style signal.** If you aggregate across many sessions and find one tool with a near-100% retry rate, the likely explanation isn't that Claude is especially bad with that tool — it's that the sessions in that slice were short or interrupted, leaving a small total where any single retry dominates the rate.

**n=1 is below threshold for any strong claim.** The example above is one session, one task type, one environment. The per-tool expectations above are directional based on how each tool operates — not statistical findings from a broad sample. AgentFluent's value is running this analysis across many sessions and surfacing per-tool distributions wide enough to make the rates meaningful.

One more thing the heuristic doesn't distinguish: an immediate retry (Claude sees the error and tries again in the next turn) versus a deferred re-invocation (Claude does other work, then comes back to the same tool much later). Both look identical under this definition. The immediate retry is more clearly a recovery response; the deferred one might be coincidental reuse. If you care about the distinction, you'd need to add a limit on how many turns apart the two calls can be.

---

## Why the rate is worth tracking

Every retry has a cost. The failed call, its error payload, and the corrected call all consume tokens and occupy the context window before any useful result lands — and they add latency to the turn. On a single session that's noise; aggregated across many runs, a tool that retries often is a recurring tax on both spend and wall-clock time.

The more useful point is that the rate is _actionable_, and often the fix is on the tool side, not the model side. A tool that retries a lot frequently has a definition that doesn't constrain the call well enough. The `Read` case above is canonical: `offset` expects a number, the model passed an array, and nothing in the tool's schema or description steered it away. Anthropic's own guidance on [writing effective tools for agents](https://www.anthropic.com/engineering/writing-tools-for-agents) recommends exactly the remedies that move this rate — unambiguously named parameters, descriptions that make implicit context explicit, and examples of correctly formatted inputs surfaced in error responses. A per-tool retry rate, tracked across many sessions, is how you find which tools earn that investment first.

---

## What's next

This kind of analysis — defined heuristically, run across many sessions, surfaced as per-tool diagnostics — is what [AgentFluent](https://github.com/frederick-douglas-pearce/agentfluent) automates at scale. Its `parameter_retry` signal extracts the _corrected_ call alongside the error — so instead of just knowing that `Read` failed, you see the exact input shape that succeeded (`{"file_path": "…", "offset": 447, "limit": 80}`).

The session JSONL has more signals like this one: tool call latency distributions (from `toolUseResult.durationMs`), edit-to-error ratios, the ratio of cache reads to fresh input tokens as a measure of context efficiency. Each is derivable from fields already introduced in Parts 1 and 2. This post is the first in an occasional analysis cadence — concrete measurements from the format, grounded in specific fields, with honest limits on what a single session's numbers can support.

---

_Drafted with Claude Code (verified against v2.1.150). The ideas, claims, and any errors are mine._
