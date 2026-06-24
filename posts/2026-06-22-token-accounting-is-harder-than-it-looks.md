---
layout: post
title: "Token accounting is harder than it looks"
date: 2026-06-22 00:00:00-0800
description: "Part 4 of the anatomy series. The four token kinds, the subagent double-count trap, and why turning session JSONL into accurate cost figures needs model identity, service_tier, and an external pricing table rather than a single sum."
categories: ["foundation"]
tags: ["claude-code", "jsonl", "sessions", "tokens", "cost"]
og_image: https://frederick-douglas-pearce.github.io/assets/img/token-accounting-is-harder-than-it-looks-og.png
og_card_source: social/images/2026-06-22-linkedin-token-accounting-is-harder-than-it-looks/og-card.png
featured: false
claude_code_version_verified: v2.1.150
---

Your last Claude Code session used some number of tokens. You've probably seen it, in `/cost`, in the status line, in a context meter ticking toward full, or maybe even in a session file. That single number hides a wide spread: the cheapest token in a session (cache reads) and the most expensive (output) differ in price by roughly 50x. Add the four kinds of tokens into one total and you learn almost nothing about what the session actually cost.

Getting cost right is harder than it seems. Sum the token counts in this post's subagent fixture the obvious way and you get 360,040. The real figure is 180,020. The naive sum counts the same work twice, because a subagent's tokens show up in its own turns and again in the parent's rollup. That double-count is the first of three traps. The other two are about price, not count: a cache read charged as if it were output, which prices the cheapest token as the most expensive, and a subagent on a cheaper model billed at the caller's rate. The data to avoid all three is sitting in the session file, waiting for the right accounting.

This matters even if you are on a Pro or Max subscription and never see a per-token bill. Two reasons. First, the API is what applications and businesses run on, and there you pay by the token. The same four-token accounting is the difference between a predictable bill and a surprising one, and the habits you build reading your own sessions transfer directly to anything you ship. Second, the ratio of cache reads to cache writes is a signal about how a session is structured, not just a billing line. A session that mostly reads from cache is reusing its context efficiently. One that rewrites its context every turn is doing avoidable work. That optimization is worth it, regardless of who is paying.

This is the "how much" post, the one [Part 3](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/posts/2026-06-11-inside-the-subagent-trace-file.md) was building toward when it flagged the double-count gotcha and said Part 4 is the fix. We're going to work through it with the same two fixtures from Parts 2 and 3: the [parent invocation](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/fixtures/synthetic/anatomy-agent-invocation.jsonl) and the [subagent trace](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/fixtures/synthetic/anatomy-subagent-trace.jsonl). Their numbers check out exactly, which is the point. This is not a hypothetical.

## The four token kinds, and why the difference matters

Part 2 introduced the `usage` object. Here it is from the subagent trace's first `assistant` turn:

```json
{
  "input_tokens": 3,
  "output_tokens": 60,
  "cache_creation_input_tokens": 13000,
  "cache_read_input_tokens": 0
}
```

Four fields, four distinct billing categories. Just adding them together gives you a number that can't tell you what you were actually charged.

Here is what each one means:

**`input_tokens`** is the fresh prompt tokens: the portion of the context that was not read from cache or written to cache. This is the baseline. Call it 1x.

**`output_tokens`** is what the model generated. Output is priced at several times the input rate. The exact multiplier varies by model, but generating a token costs meaningfully more than reading one in. A turn that generates just 300 output tokens costs as much as about 1,500 input tokens would.

**`cache_creation_input_tokens`** is the count of tokens written to the prompt cache on this turn. This costs a premium on top of the base input rate, roughly 1.25x. You pay a little extra now so future turns can read cheaply.

**`cache_read_input_tokens`** is the count of tokens served from cache. This is priced at roughly one-tenth the base input rate. Reading 27,000 tokens from cache costs about the same as reading 2,700 fresh tokens.

These three input fields are not just your new message. Together they account for everything the model reads on that turn: the system prompt, the tool definitions, the entire conversation so far, and whatever you just typed. Every one of those tokens lands in exactly one bucket: read from cache, written to cache, or left as fresh uncached input. That last bucket is usually small. `input_tokens` can be only a few tokens when the turn's full context runs to tens of thousands of tokens. In the `usage` object above, that context was about 13,000 tokens, nearly all written to cache, with just 3 left as fresh input.

Now look at the subagent run as a whole. Across 8 model turns, the `pm` agent consumed 20 fresh input tokens, produced 1,000 output tokens, wrote 29,000 tokens to cache, and read 150,000 tokens from cache. Add the four kinds together and you get 180,020, the same `totalTokens` the parent rollup reports. But the cost picture is nothing like "180,020 tokens at input price."

The 150,000 cache reads are cheap, the 29,000 cache writes a little more, the 1,000 output tokens the costly line, the 20 fresh input tokens negligible. Notice the inversion: the cache reads dominate the count while being the cheapest per token, and the output tokens look like a rounding error in the count while being the most expensive. That is the whole problem with a single total. The cost per token spread runs about 50x: a cache read at roughly a tenth the price of fresh input, an output token several times more.

The payoff of distinguishing the four kinds is concrete: this run is overwhelmingly cache reads, so its real cost is far below what "180K tokens at input price" implies. The JSONL tells you that directly, but only if you read all four fields.

## The second confounder: `service_tier`

The data dictionary documents a `service_tier` field on the `usage` object. It records which billing tier served the request, usually `"standard"`, sometimes `"priority"` or another non-standard tier. That matters because non-standard tiers are priced differently, so two turns with identical token counts can cost different amounts. The minimal fixtures here don't include the field (they're synthetic, trimmed to the four token kinds), but your own sessions carry it on every turn.

The rule: check `service_tier` before applying any pricing. The JSONL records it per turn. A cost computation that ignores the field will misprice priority-tier usage.

## The third confounder: per-model pricing

This is illustrated in the fixtures, because they involve two different models.

The parent's own `assistant` turn, the one that decided to delegate and emitted the `Agent` tool call, ran on `claude-opus-4-7`. Its usage:

```json
{
  "input_tokens": 42,
  "output_tokens": 89,
  "cache_creation_input_tokens": 3450,
  "cache_read_input_tokens": 8200
}
```

The subagent's eight turns all ran on `claude-sonnet-4-6`. Its cumulative usage, per the rollup and confirmed by summing the trace:

```json
{
  "input_tokens": 20,
  "output_tokens": 1000,
  "cache_creation_input_tokens": 29000,
  "cache_read_input_tokens": 150000
}
```

Same four fields, different models, different per-token prices. Opus and Sonnet do not cost the same per million tokens, and the gap is large. If you aggregate across both and apply a single rate, you will be wrong, and the direction of the error depends on which model is more expensive for which token type.

The `message.model` field on every `assistant` line is why this is fixable. The JSONL records the model per turn. A cost computation that reads `message.model`, looks up the current per-model rate for each token type, computes per-turn costs, and then sums those will be accurate. One that applies a flat rate will not be.

I'm not going to print specific dollar-per-million figures here, because pricing is external, it changes, and it differs across model families. What the JSONL gives you is the volumes and the model identities. Turning those into dollars needs an external pricing table. The data is in the file; the prices are not.

## The main event: the double-count

Here is the trap Part 3 flagged and deferred.

The `pm` subagent's tokens appear in two places:

1. On each of the 8 `assistant` lines _inside_ `anatomy-subagent-trace.jsonl`, in `message.usage`, one object per turn.
2. On the parent's `user` line in `anatomy-agent-invocation.jsonl`, in `toolUseResult.usage`, a rollup covering the whole run.

These are the same tokens, reported twice.

Here is the parent's `toolUseResult.usage`, exactly as it appears in the fixture:

```json
{
  "input_tokens": 20,
  "output_tokens": 1000,
  "cache_creation_input_tokens": 29000,
  "cache_read_input_tokens": 150000
}
```

And here are the per-turn values from the 8 `assistant` lines in the subagent trace:

| Turn          | input  | output    | cache_creation | cache_read  |
| ------------- | ------ | --------- | -------------- | ----------- |
| 1 (get_issue) | 3      | 60        | 13,000         | 0           |
| 2 (Read 1)    | 3      | 40        | 4,000          | 13,000      |
| 3 (Read 2)    | 3      | 40        | 3,000          | 17,000      |
| 4 (Read 3)    | 2      | 40        | 2,500          | 20,000      |
| 5 (Read 4)    | 2      | 40        | 2,000          | 22,500      |
| 6 (comment 1) | 2      | 220       | 1,500          | 24,500      |
| 7 (comment 2) | 2      | 260       | 1,500          | 26,000      |
| 8 (summary)   | 3      | 300       | 1,500          | 27,000      |
| **Sum**       | **20** | **1,000** | **29,000**     | **150,000** |

The sums match the rollup exactly. And 20 + 1,000 + 29,000 + 150,000 = 180,020, the same `totalTokens` the parent line reports.

Sum both sources and you report 360,040 tokens for work that consumed 180,020. The inflation is roughly 2x.

If you have never opened a subagent trace file, you don't know the rollup is a re-statement of what's already in the trace. The numbers look plausible. A session that delegated one subagent run quietly doubles its reported token count.

One thing worth stating explicitly. The parent's _own_ assistant turn, the one on `claude-opus-4-7` that emitted the `Agent` call, is separate from all of this. Its usage (`input_tokens` 42, `output_tokens` 89, `cache_creation_input_tokens` 3,450, `cache_read_input_tokens` 8,200) is real parent-session cost, distinct from the subagent work, and it is _not_ part of the double-count. The double-count is specifically the subagent rollup on the parent's `user` line versus the per-turn usage inside the subagent trace. The parent's own model turns are not duplicated anywhere.

## The three aggregation patterns

The [reference doc](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/subagent-traces.md#token-accounting) names three patterns. In prose:

**Pattern A, quick session total, no trace-file IO.** Read only the parent session. Sum `message.usage` on parent `assistant` lines plus `toolUseResult.usage` on parent `user` lines that carry a subagent rollup. This is accurate and fast, and you never open a subagent file. The tradeoff is that you can't break the subagent's cost down by turn; you get its total as one opaque number. For a quick "how much did this session cost?" that's usually fine.

**Pattern B, full breakdown with per-turn subagent detail.** Read the parent session's `assistant` lines for the parent-model cost. For any subagent invocation, read the subagent trace file's per-turn `message.usage` _instead of_ the parent rollup for that subagent. Concretely: include `toolUseResult.usage` on parent `user` lines for non-subagent tool calls, but exclude it for subagent-result lines, because those are already covered by summing the trace. This buys per-turn breakdown at the cost of file IO. It also lets you separate Opus cost from Sonnet cost, or pinpoint which turn in the subagent run was expensive.

**Pattern C, just the subagent's cost.** Sum `message.usage` across the subagent trace file's `assistant` lines. Or, equivalently, read `toolUseResult.usage` from the parent's result line for that subagent. Either source gives the same number; they're verified to match in the fixtures and should match in production. Use whichever is more convenient for the question you're asking.

The discipline that ties all three together: pick one source per subagent, never both.

## Cache efficiency as a direct read from the JSONL

There's a useful signal buried in the four token kinds that goes beyond cost. The ratio of `cache_read_input_tokens` to `cache_creation_input_tokens` across a session's turns tells you whether the session is amortizing its context cost.

In the subagent trace the pattern is visible turn by turn. Turn 1 writes 13,000 tokens and reads 0, because the cache is cold at the start of the run. Turn 2 reads 13,000 and writes 4,000, because the context from turn 1 is now cached. By turn 8 the subagent is reading 27,000 tokens from cache and writing only 1,500. The incremental writes shrink as the run progresses; the reads grow.

```bash
# Cache write vs. read, per assistant turn in a subagent trace.
# Run against the fixture or your own trace file.
# Needs jq; on Windows, install via "winget install jqlang.jq" and adapt the pipe.
cat ~/.claude/projects/<slug>/<session-uuid>/subagents/agent-<agentId>.jsonl \
  | jq -r '
    select(.type? == "assistant" and .isSidechain? == true)
    | [
        .timestamp,
        (.message.usage.cache_creation_input_tokens // 0),
        (.message.usage.cache_read_input_tokens // 0)
      ]
    | @tsv
  '
```

For the fixture that prints turn 1 writing 13,000 and reading 0, through turn 8 writing 1,500 and reading 27,000. A subagent that is mostly reading from cache on its later turns is far cheaper per turn than its token volume suggests. A subagent writing heavily on every turn, or showing no reads after the first turn, may have a caching problem worth investigating.

The same analysis applies to parent-session `assistant` lines. A long coding session with high `cache_read_input_tokens` across its later turns is working efficiently. A session where every turn carries high `cache_creation_input_tokens` is repeatedly writing context that isn't being reused. The JSONL gives you this without any external tooling.

## Putting it together: the right `jq` for session cost

Here is a snippet that avoids the double-count and respects the token-type distinction. It produces a per-turn breakdown for a parent session, one row per `assistant` line, with the model and all four token kinds, so you can bring your own pricing table:

```bash
# Per-turn token breakdown from the parent session, skipping sidechain lines.
# Columns: timestamp, model, input, output, cache_creation, cache_read.
# Needs jq; on Windows see "winget install jqlang.jq".
cat ~/.claude/projects/<slug>/<session-uuid>.jsonl \
  | jq -r '
    select(.type? == "assistant" and (.isSidechain? // false) == false)
    | [
        .timestamp,
        (.message.model // "unknown"),
        (.message.usage.input_tokens // 0),
        (.message.usage.output_tokens // 0),
        (.message.usage.cache_creation_input_tokens // 0),
        (.message.usage.cache_read_input_tokens // 0)
      ]
    | @tsv
  '
```

That gives you the parent's own model turns. To get the session total including subagent work (Pattern A above), add:

```bash
# Subagent rollup totals from parent user lines.
# These are the rolled-up subagent costs: use these OR the trace file, not both.
cat ~/.claude/projects/<slug>/<session-uuid>.jsonl \
  | jq -r '
    select(.type? == "user" and (.isSidechain? // false) == false)
    | select(.toolUseResult?.usage != null)
    | [
        .timestamp,
        "subagent-rollup",
        (.toolUseResult.usage.input_tokens // 0),
        (.toolUseResult.usage.output_tokens // 0),
        (.toolUseResult.usage.cache_creation_input_tokens // 0),
        (.toolUseResult.usage.cache_read_input_tokens // 0)
      ]
    | @tsv
  '
```

Combine the two outputs and you have a complete per-turn register: every parent model turn with its model identity, and every subagent invocation as a single rollup row. Multiply each row's token counts by the per-type, per-model rate for that row's model, and you have an accurate cost estimate.

What you should not do: pipe both of those queries _and_ the subagent trace file through a single sum. That's the double-count.

## What the data gives you, and what it doesn't

The session JSONL is precise on volumes. The fields are there, they're reliable at v2.1.150, and they separate the four token kinds per turn. The `message.model` field names the model per turn. The `service_tier` field names the billing tier.

What's not in the JSONL is prices. There is no dollars-per-million field anywhere in the format. Turning token volumes into dollars needs an external pricing table, and that table changes. The right posture for any tool that computes session costs: read the volumes from JSONL, read the prices from an external source you keep current, and combine them at query time. Hard-coding rates into a parser makes that parser wrong every time Anthropic adjusts pricing.

[AgentFluent](https://github.com/frederick-douglas-pearce/agentfluent) and [CodeFluent](https://github.com/frederick-douglas-pearce/codefluent) both handle the aggregation patterns described here. If you're building your own cost tooling, the [data-dictionary's cost-computation section](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/data-dictionary.md#common-pitfalls-in-cost-computation) is the reference-level treatment; this post is the narrative one.

## What's next

Token accounting answers "how much." The next question, the one every cost total eventually provokes, is "what was all that for?"

The session JSONL records every tool call, every result, every structured output. Tool-use data is where the behavioral signal lives: which tools, how often, in what order, with what inputs and outputs. Part 5 gives the tool call its complete treatment, from the basic `tool_use`/`tool_result` pairing through the full range of what `toolUseResult` carries for different tool types, and what it means when a tool call fails partway.

The sources behind this post:

- **Reference grounding:** [`reference/data-dictionary.md` — Usage and token accounting](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/data-dictionary.md#usage-and-token-accounting), [Common pitfalls in cost computation](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/data-dictionary.md#common-pitfalls-in-cost-computation)
- **Reference grounding:** [`reference/subagent-traces.md` — Token accounting](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/subagent-traces.md#token-accounting)
- **Series planning:** [`series-outline.md`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/.claude/specs/series-outline.md)
- **Synthetic fixtures** — the `jq` snippets above run against these without a real session: the [parent invocation](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/fixtures/synthetic/anatomy-agent-invocation.jsonl) and the [subagent trace](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/fixtures/synthetic/anatomy-subagent-trace.jsonl)

If you find a token field, a `service_tier` value, or a usage pattern I haven't described here, the [reference docs](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/data-dictionary.md) are the right place to track it, and a `claude-code-sessions` issue is the right way to surface it.

---

_Drafted with Claude Code (verified against v2.1.150). The ideas, claims, and any errors are mine._
