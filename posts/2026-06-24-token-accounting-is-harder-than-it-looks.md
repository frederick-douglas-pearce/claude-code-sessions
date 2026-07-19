---
layout: post
title: "Token accounting is harder than it looks"
date: 2026-06-24 00:00:00-0800
description: "Part 4 of the anatomy series. The four token kinds, the subagent rollup undercount trap, and why turning session JSONL into accurate cost figures needs model identity, service_tier, and an external pricing table rather than a single sum."
categories: ["foundation"]
tags: ["claude-code", "jsonl", "sessions", "tokens", "cost"]
og_image: https://frederick-douglas-pearce.github.io/assets/img/token-accounting-is-harder-than-it-looks-og.png
og_card_source: social/images/2026-06-24-linkedin-token-accounting-is-harder-than-it-looks/og-card.png
featured: false
claude_code_version_verified: v2.1.150
---

Your last Claude Code session used some number of tokens. You've probably seen it, in `/cost`, in the status line, in a context meter ticking toward full, or maybe even in a session file. That single number hides a wide spread: the cheapest token in a session (cache reads) and the most expensive (output) differ in price by roughly 50x. Add the four kinds of tokens into one total and you learn almost nothing about what the session actually cost.

Getting cost right is harder than it seems. Take this post's subagent fixture. The parent session's rollup reports 28,803 tokens for the subagent run, and it is tempting to read that as what the run cost. It isn't. Sum the subagent's own eight turns and the real figure is 180,020, roughly six times larger. The rollup is a single turn's snapshot, not a total across the run, so leaning on it undercounts the work badly. That undercount is the first of three traps. The other two are about price, not count: a cache read charged as if it were output, which prices the cheapest token as the most expensive, and a subagent on a cheaper model billed at the caller's rate. The data to avoid all three is sitting in the session file, waiting for the right accounting.

This matters even if you are on a Pro or Max subscription and never see a per-token bill. Two reasons. First, the API is what applications and businesses run on, and there you pay by the token. The same four-token accounting is the difference between a predictable bill and a surprising one, and the habits you build reading your own sessions transfer directly to anything you ship. Second, the ratio of cache reads to cache writes is a signal about how a session is structured, not just a billing line. A session that mostly reads from cache is reusing its context efficiently. One that rewrites its context every turn is doing avoidable work. That optimization is worth it, regardless of who is paying.

This is the "how much" post, the one [Part 3](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/posts/2026-06-11-inside-the-subagent-trace-file.md) was building toward when it flagged the rollup-versus-trace gotcha and said Part 4 is the fix. We're going to work through it with the same two fixtures from Parts 2 and 3: the [parent invocation](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/fixtures/synthetic/anatomy-agent-invocation.jsonl) and the [subagent trace](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/fixtures/synthetic/anatomy-subagent-trace.jsonl). Their numbers check out exactly, which is the point. This is not a hypothetical.

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

**`cache_creation_input_tokens`** is the count of tokens written to the prompt cache on this turn. Writing costs a premium over base input, and how big a premium depends on the cache's TTL: roughly 1.25x for a 5-minute entry, roughly 2x for a 1-hour one. The `usage.cache_creation` sub-object breaks the count out by TTL (`ephemeral_5m_input_tokens` and `ephemeral_1h_input_tokens`); this flat field is their sum, so pricing it all at 1.25x under-reports whenever 1-hour writes are in the mix, which in practice they often are. You pay a little extra now so future turns can read cheaply.

**`cache_read_input_tokens`** is the count of tokens served from cache. This is priced at roughly one-tenth the base input rate. Reading 27,000 tokens from cache costs about the same as reading 2,700 fresh tokens.

These three input fields are not just your new message. Together they account for everything the model reads on that turn: the system prompt, the tool definitions, the entire conversation so far, and whatever you just typed. Every one of those tokens lands in exactly one bucket: read from cache, written to cache, or left as fresh uncached input. That last bucket is usually small. `input_tokens` can be only a few tokens when the turn's full context runs to tens of thousands of tokens. In the `usage` object above, that context was about 13,000 tokens, nearly all written to cache, with just 3 left as fresh input.

Now look at the subagent run as a whole. Across 8 model turns, the `pm` agent consumed 20 fresh input tokens, produced 1,000 output tokens, wrote 29,000 tokens to cache, and read 150,000 tokens from cache. Add the four kinds together and you get 180,020, the tokens the run actually processed, obtained by summing every turn in the trace. (The parent's rollup reports a far smaller 28,803, for a reason that is the main event below.) But the cost picture is nothing like "180,020 tokens at input price."

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

The subagent's eight turns all ran on `claude-sonnet-4-6`. Here is its usage summed across all eight turns, the run's real processed total (not the rollup, which reports only the final turn):

```json
{
  "input_tokens": 20,
  "output_tokens": 1000,
  "cache_creation_input_tokens": 29000,
  "cache_read_input_tokens": 150000
}
```

Same four fields, different models, different per-token prices. Opus costs more than Sonnet per million tokens across every token type, and the gap is significant. Aggregate across both and apply a single rate, and you will be wrong. Whether you over- or under-count depends on which model's rate you borrowed and how the tokens split between the two.

The `message.model` field on every `assistant` line is why this is fixable. The JSONL records the model per turn. A cost computation that reads `message.model`, looks up the current per-model rate for each token type, computes per-turn costs, and then sums those will be accurate. One that applies a flat rate will not be.

I'm not going to print specific dollar-per-million figures here, because pricing is external, it changes, and it differs across model families. What the JSONL gives you is the volumes and the model identities. Turning those into dollars needs an external pricing table. The data is in the file; the prices are not.

## The main event: the undercount

Here is the trap Part 3 flagged and deferred. It runs the opposite direction from how it looks.

The `pm` subagent's tokens are reported in two places:

1. On each of the 8 `assistant` lines _inside_ `anatomy-subagent-trace.jsonl`, in `message.usage`, one object per turn.
2. On the parent's `user` line in `anatomy-agent-invocation.jsonl`, in `toolUseResult.usage`, next to a `totalTokens` scalar.

It is natural to read the second as the sum of the first: the parent rolling the whole run up into one number. It isn't. That `toolUseResult.usage` is a snapshot of a single turn, the subagent's last one (usually), not a total across the run.

Here is the parent's `toolUseResult.usage`, exactly as it appears in the fixture:

```json
{
  "input_tokens": 3,
  "output_tokens": 300,
  "cache_creation_input_tokens": 1500,
  "cache_read_input_tokens": 27000
}
```

Those four sum to 28,803, which is exactly the `totalTokens` on that same line. Now put it next to the per-turn values from the 8 `assistant` lines in the subagent trace:

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

The rollup is turn 8, and only turn 8. It matches the last row of the table, not the column sums. Sum the trace and the run processed 180,020 tokens. The rollup reports 28,803. Read the rollup as the subagent's cost and you undercount by a factor of about six.

Why does one turn land so far below the run total? Because the Messages API is stateless. Every turn re-sends the whole conversation so far, and almost all of it arrives as cache reads. Turn 8 alone reads 27,000 tokens from cache, because it is re-reading everything the earlier turns built up. `totalTokens` captures that one turn's view of the context. It is a context-size reading, not a tally of the work the run did.

Here is why the mistake is so easy to make: the snapshot lands close to a real number, just not the one you want. Sum the run's _expensive_ tokens alone (input, output, and cache creation, leaving out the cheap cache reads) and you get 30,020, within a few percent of the 28,803 rollup. Each context token is written to cache about once over a run, so the cache-creation total roughly equals the final context size, which is roughly what the last turn snapshots. The rollup looks like it is in the right ballpark, but it's not. Measured across the live corpus behind the [reference doc](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/subagent-traces.md#token-accounting), reading the rollup in place of summing the trace undercounts processed tokens by a median of 5.8x.

One thing worth stating explicitly. The parent's _own_ assistant turn, the one on `claude-opus-4-7` that emitted the `Agent` call, is separate from all of this. Its usage (`input_tokens` 42, `output_tokens` 89, `cache_creation_input_tokens` 3,450, `cache_read_input_tokens` 8,200) is real parent-session cost, distinct from the subagent work. It is genuine parent usage, counted once in the parent session, and none of the undercount above touches it.

The rule: to count a subagent's tokens, sum its trace turn by turn. The parent rollup is a single-turn context-size proxy, not a substitute for that sum, and it understates the run several-fold.

## Getting the number you actually want

The [reference doc](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/subagent-traces.md#token-accounting) lays out which source answers which question. The three questions people actually ask:

**A subagent's real processed tokens, the basis for its cost.** Sum `message.usage` across the subagent trace file's `assistant` lines, turn by turn. Not the rollup, which is one turn and understates the run. On a real trace, first deduplicate the `assistant` lines by `message.id`: a streaming response writes several lines for one logical turn, each a running snapshot rather than an increment, so summing all of them over-counts. (The synthetic trace here has one line per turn and sidesteps that; your own traces won't. The [reference doc](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/subagent-traces.md#streaming-snapshots-and-messageid) has the dedup recipe.)

**Total session tokens.** Sum `message.usage` on the parent's own `assistant` lines, then add each subagent's per-turn trace sum. Include the sidechain trace tokens. Don't substitute the parent rollup for them, or you fold the roughly 6x undercount into your session total.

**A subagent's cost.** Its processed tokens from the trace, priced per turn at that turn's own `message.model` rate. Only the trace records the model per turn; the rollup names no model at all. So cost, like the token total, comes from the trace, never the rollup.

The one thing the rollup is genuinely good for is a quick, approximate read on how large the subagent's context grew, since `totalTokens` snapshots the final turn's context size. Label it as that. Never sum `totalTokens` across invocations, and never price `toolUseResult.usage`.

## Cache efficiency as a direct read from the JSONL

There's a useful signal buried in the four token kinds that goes beyond cost. The ratio of `cache_read_input_tokens` to `cache_creation_input_tokens` across a session's turns tells you whether the session is reusing cached context or rebuilding it every turn.

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

Run against the fixture, this `jq` snippet reproduces the progression above: a cold cache on turn 1, then mostly cache reads by turn 8. A subagent that is mostly reading from cache on its later turns is far cheaper per turn than its token volume suggests. A subagent writing heavily on every turn, or showing no reads after the first turn, may have a caching problem worth investigating.

The same analysis applies to parent-session `assistant` lines. A long coding session with high `cache_read_input_tokens` across its later turns is working efficiently. A session where every turn carries high `cache_creation_input_tokens` is repeatedly writing context that isn't being reused. Unlike cost, this signal needs no external pricing table. It's right there in the token counts.

## Putting it together: the right `jq` for session cost

Here is a snippet that avoids the undercount and respects the token-type distinction. It produces a per-turn breakdown for a parent session, one row per `assistant` line, with the model and all four token kinds, so you can bring your own pricing table:

```bash
# Per-turn token breakdown from the parent session, skipping sidechain
# and failed-call lines (assistant lines flagged isApiErrorMessage: true).
# Columns: timestamp, model, input, output, cache_creation, cache_read.
# Needs jq; on Windows see "winget install jqlang.jq".
cat ~/.claude/projects/<slug>/<session-uuid>.jsonl \
  | jq -r '
    select(.type? == "assistant"
           and (.isSidechain? // false) == false
           and (.isApiErrorMessage? // false) == false)
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

That gives you the parent's own model turns. It does not yet include the subagent work, and this is exactly where the undercount creeps in. The tempting move is to pull the subagent rollups off the parent's `user` lines and add them:

```bash
# Subagent rollups from parent user lines.
# WARNING: each row is a single-turn snapshot, not the run total.
# Fine as an approximate context-size read; wrong for cost.
cat ~/.claude/projects/<slug>/<session-uuid>.jsonl \
  | jq -r '
    select(.type? == "user" and (.isSidechain? // false) == false)
    | select(.toolUseResult?.usage != null)
    | [
        .timestamp,
        "subagent-rollup-snapshot",
        (.toolUseResult.usage.input_tokens // 0),
        (.toolUseResult.usage.output_tokens // 0),
        (.toolUseResult.usage.cache_creation_input_tokens // 0),
        (.toolUseResult.usage.cache_read_input_tokens // 0)
      ]
    | @tsv
  '
```

Those rows are single-turn snapshots. Sum them into a session total and you undercount every subagent's real work, by a median of about 6x on the corpus behind the reference doc. To get a subagent's real processed tokens you have to open its trace file and sum `message.usage` across its turns:

```bash
# A subagent's real processed tokens: sum every turn in its trace.
# On a real trace, dedupe streaming lines by message.id first (see the reference doc).
cat ~/.claude/projects/<slug>/<session-uuid>/subagents/agent-<agentId>.jsonl \
  | jq -s '
    [ .[] | select(.type? == "assistant") | .message.usage ]
    | reduce .[] as $u (
        { input: 0, output: 0, cache_creation: 0, cache_read: 0 };
        {
          input:          (.input          + ($u.input_tokens // 0)),
          output:         (.output         + ($u.output_tokens // 0)),
          cache_creation: (.cache_creation + ($u.cache_creation_input_tokens // 0)),
          cache_read:     (.cache_read     + ($u.cache_read_input_tokens // 0))
        }
      )
  '
```

Run that against the subagent fixture and it returns the run's real totals: 20 input, 1,000 output, 29,000 cache creation, 150,000 cache read. That is the 180,020 the rollup's 28,803 was hiding.

One more thing the rollup can't do: it carries no model. It sums a turn's tokens and even records `service_tier`, but never says which model produced them. Per-token rates are per-model, so a rollup row is unpriceable on its own. The trace is where each turn carries its `message.model`, which is the other reason cost has to come from the trace.

What you should not do: read the rollup and call it the subagent's cost. It is one turn, it names no model, and it understates the run several-fold.

## What the data gives you, and what it doesn't

The session JSONL is precise on token counts. The fields are there, they're reliable at v2.1.150, and they separate the four token kinds per turn. The `message.model` field names the model per turn. The `service_tier` field names the billing tier.

What's not in the JSONL is prices. There is no dollars-per-million field anywhere in the format. Turning token counts into dollars needs an external pricing table, and that table changes. The right posture for any tool that computes session costs: read the token counts from JSONL, read the prices from an external source you keep current, and combine them at query time. Hard-coding rates into a parser makes that parser wrong every time Anthropic adjusts pricing.

[AgentFluent](https://github.com/frederick-douglas-pearce/agentfluent) and [CodeFluent](https://github.com/frederick-douglas-pearce/codefluent) both handle the aggregation patterns described here. If you're building your own cost tooling, the [data-dictionary's cost-computation section](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/data-dictionary.md#common-pitfalls-in-cost-computation) is the reference-level treatment, while this post is the narrative one.

## What's next

Token accounting answers "how much." The next question, the one every cost total eventually provokes, is "what was all that for?"

The session JSONL records every tool call, every result, every structured output. Tool-use data is where the behavioral signal lives: which tools, how often, in what order, with what inputs and outputs. Part 5 gives the tool call its complete treatment, from the basic `tool_use`/`tool_result` pairing through the full range of what `toolUseResult` carries for different tool types, up to the parallel call: one `assistant` line firing several tools at once, and why that complicates any timing analysis.

The sources behind this post:

- **Reference grounding:** [`reference/data-dictionary.md` — Usage and token accounting](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/data-dictionary.md#usage-and-token-accounting), [Common pitfalls in cost computation](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/data-dictionary.md#common-pitfalls-in-cost-computation)
- **Reference grounding:** [`reference/subagent-traces.md` — Token accounting](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/subagent-traces.md#token-accounting)
- **Series planning:** [`series-outline.md`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/.claude/specs/series-outline.md)
- **Synthetic fixtures** — the `jq` snippets above run against these without a real session: the [parent invocation](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/fixtures/synthetic/anatomy-agent-invocation.jsonl) and the [subagent trace](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/fixtures/synthetic/anatomy-subagent-trace.jsonl)

If you find a token field, a `service_tier` value, or a usage pattern I haven't described here, the [reference docs](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/data-dictionary.md) are the right place to track it, and a `claude-code-sessions` issue is the right way to surface it.

---

**Correction (2026-07-19).** An earlier version of this post framed the subagent rollup as a double-count: it claimed the parent's `toolUseResult.usage` and the subagent trace's per-turn usage were the same tokens counted twice, inflating the total by exactly 2x. That was backwards. The rollup is a single assistant turn's snapshot, not a run total, so reading it as the subagent's cost undercounts the run, by a median of about 6x on a live corpus of 691 invocations. The worked example, the aggregation guidance, and the `jq` recipes above have been rewritten to the corrected semantics, and the paired fixtures were re-cut to match ([#144](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/144)). The canonical treatment now lives in [`reference/subagent-traces.md` — Token accounting](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/subagent-traces.md#token-accounting). Thanks to the downstream AgentFluent audit that caught it.

---

_Drafted with Claude Code (verified against v2.1.150). The ideas, claims, and any errors are mine._
