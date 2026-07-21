---
layout: post
title: "Every lever that moves the bill"
date: 2026-06-27 00:00:00-0800
description: "An aside off Part 4. cache_creation_input_tokens is the sum of two TTLs that price differently. That's the most expensive gap, but it's not the only one. A complete picture of every input that moves the effective cost of a Claude Code turn."
categories: ["foundation"]
tags: ["claude-code", "jsonl", "tokens", "cost"]
og_image: https://frederick-douglas-pearce.github.io/assets/img/every-lever-that-moves-the-bill-og.png
og_card_source: social/images/2026-06-27-linkedin-every-lever-that-moves-the-bill/og-card.png
featured: false
claude_code_version_verified: v2.1.150
---

[Part 4](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/posts/2026-06-24-token-accounting-is-harder-than-it-looks.md) named three confounders that corrupt session cost estimates: the four token kinds price differently, `service_tier` shifts the rate, and per-model pricing means the same token count can cost several times more or less depending on which model generated it. That was deliberately scoped. It described the levers that corrupt the _count_. It barely touched the ones that shift the _rate_.

This aside is the complete picture. Every field in the session JSONL that moves the effective cost of a turn, grounded in the canonical lever catalog at [`reference/cost-model.md`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/cost-model.md).

---

## The gap Part 4 left open

Part 4 used `cache_creation_input_tokens` throughout. It noted the 1.25x premium, named the `cache_creation` sub-object in passing, and moved on. That brevity hid something.

`cache_creation_input_tokens` is the _sum_ of two separate fields:

```json
{
  "cache_creation": {
    "ephemeral_5m_input_tokens": 0,
    "ephemeral_1h_input_tokens": 19227
  }
}
```

Those two TTLs price differently. The 5-minute write is roughly 1.25x base input. The 1-hour write is roughly 2x. Pricing the flat `cache_creation_input_tokens` field at a single 1.25x rate under-reports whenever 1-hour writes are in the mix.

In Claude Code sessions, the 1-hour TTL is commonly the dominant share by token volume. One observed corpus had roughly two-thirds of all cache-write tokens landing in the 1-hour bucket. The worked example in `cost-model.md` is concrete: a single Opus 4.7 request with 19,227 tokens in the 1-hour bucket costs $0.214 priced correctly and $0.142 priced at the 5-minute rate. That $0.072 gap per request compounds quickly across a session with heavy caching.

The `cache_creation` sub-object is the fix. It's already in your sessions. The question is whether your cost tool reads it.

---

## Who chose the 1-hour TTL?

A natural question once you see the split: did I configure this? No. There is no user-facing setting for cache TTLs in Claude Code. No environment variable, no flag.

The 5-minute TTL is the Anthropic API default. Claude Code, as the API client, sets the cache breakpoints and their TTLs automatically.

The likely mechanism (inferred from observed data, not documented by Anthropic) is a 1-hour breakpoint on the stable prefix (system prompt, tool definitions, CLAUDE.md, early context) and a 5-minute breakpoint on the volatile tail (the per-turn delta). The stable prefix is large and written once; subsequent turns read it cheaply. The per-turn delta is small and changes every turn, so the short TTL keeps the writes inexpensive even when they fire frequently.

This is why 1-hour tokens dominate by _volume_ even though 5-minute writes probably fire more _often_: the stable prefix is simply much larger than any per-turn delta.

You can see this directly in your own sessions. Each `assistant` line's `usage.cache_creation` sub-object shows the split per turn. The `jq` to surface it:

```bash
# Per-turn 5m vs. 1h cache write split.
# Needs jq; on Windows, install via "winget install jqlang.jq" and adapt the pipe.
cat ~/.claude/projects/<slug>/<session-uuid>.jsonl \
  | jq -r '
    select(.type? == "assistant"
           and (.isSidechain? // false) == false
           and (.isApiErrorMessage? // false) == false)
    | [
        .timestamp,
        (.message.usage.cache_creation.ephemeral_5m_input_tokens // 0),
        (.message.usage.cache_creation.ephemeral_1h_input_tokens // 0)
      ]
    | @tsv
  '
```

On a typical Claude Code session you will see the 1-hour column spike on the first turn (when the stable prefix is written for the first time) and hold near zero on subsequent turns (because it is now read, not written). The 5-minute column will show smaller repeated writes as the conversation tail grows. Summed over the session, the 1-hour total usually wins by volume.

Anthropic does not publish the breakpoint placement strategy, and there is no knob to change it. The split is observable; the mechanism is inferred. Both the strategy and the pricing impact are candidates for a documentation request or a `/feedback` call.

One additional data point that pins the stakes: the two TTLs _price_ at 2x vs. 1.25x, but they count _identically_ toward API rate limits. Only uncached input tokens and cache-creation tokens count toward the input tokens per minute (ITPM) limit; cache reads do not count at all. So the TTL choice shifts your bill but does not change how fast you run into rate-limit walls.

---

## The remaining levers

Beyond the cache-write TTL split, the `usage` object carries several more fields that shift the effective rate. The full catalog is in [`reference/cost-model.md`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/cost-model.md); here is the short version.

**Fast mode** (`usage.speed == "fast"`). Premium flat rates that apply to the full request. As of the cost-model verification, Opus 4.6 / 4.7 cost 6x input and 6x output versus standard; Opus 4.8 rates are lower. Fast mode stacks with caching and data residency, and is not available with Batch. The `speed` field is on every `assistant` line that uses it; a cost tool that reads only `model` + `service_tier` misses this entirely.

**Batch API** (`usage.service_tier == "batch"`). Roughly 0.5x on input and output. Worth noting if you're building anything that runs offline or asynchronous work through the API.

**Priority tier** (`usage.service_tier == "priority"`). Commitment pricing, different from both standard and batch. The `service_tier` field distinguishes all three.

**Data residency** (`usage.inference_geo == "us"`). A 1.1x multiplier on _all_ token categories, including cache writes and cache reads. Applies on Opus 4.6 / Sonnet 4.6 and later. The `inference_geo` field records `"global"` (default), `"us"`, `"not_available"`, or `""`. A cost tool that applies per-model rates and stops there under-reports by 10% for any US-residency request.

**Server-side tool surcharges** (`usage.server_tool_use`). These are not token rates. They are separate line items billed outside the per-million calculation. Web search is $10 per 1,000 requests, recorded as `web_search_requests` in the `server_tool_use` sub-object. Web fetch is free. Code execution is billed by container-hour against a monthly org-level free tier. The session records the count in `code_execution_requests`, but not the duration or the monthly aggregate, so the dollar cost of code execution is not reconstructable from a single session file.

No open pricing dataset currently models fast mode, batch, data residency, or server-tool surcharges for Anthropic. The best-known one ([pydantic/genai-prices](https://github.com/pydantic/genai-prices)) covers the four base token types and context-length tiers, with a single `cache_write_mtok` field that represents the 5-minute rate. The 1-hour TTL is not modeled at all. Any session cost tool that builds on that dataset without a local overlay is missing several of these levers.

---

## Two things that look like levers but are not

Worth naming explicitly, because both produce counting errors when mishandled.

**Thinking tokens** (`usage.output_tokens_details.thinking_tokens`). These are already _inside_ `output_tokens`. They are billed at the output rate as part of that total. Adding `thinking_tokens` on top of `output_tokens` double-counts; the `output_tokens_details` sub-object is a breakdown, not an addition. The field exists to tell you how much of your output spend went to reasoning. It has no separate billing line.

**The Opus 4.7+ tokenizer change**. The newer tokenizer can produce up to roughly 35% more tokens for the same text. This is a count effect. It is already reflected in whatever `input_tokens` and `output_tokens` your session records. Do not apply it as an additional multiplier. The numbers in the file are already the right numbers; the rate table you apply to them is unchanged.

---

## The honest ceiling

Even a cost tool that handles the cache-write TTL split correctly, reads `speed` and `inference_geo` and `server_tool_use`, and applies the right per-model rate to every turn is still computing a list-price estimate. It is not computing your bill.

Enterprise and negotiated discounts are applied at the billing layer. They never appear in session JSONL. A session-data cost tool cannot know about them.

Those billed dollars do exist, just not in the session file. Anthropic exposes them through the Usage and Cost Admin API (`/v1/organizations/cost_report`), the recommended source of truth for what an organization actually paid: costs in USD, reconcilable against your Anthropic bill, grouped by workspace and by a `description` field that parses out model and data residency. The discounts from the previous paragraph live at that billing layer, and this is the API where they surface. What it cannot give you is the other half. It reports daily totals at the organization and workspace level, with no per-session, per-turn, or per-subagent attribution, and it needs an Admin API key and an organization, so an individual account cannot call it at all. The two answer different questions and neither replaces the other. The Cost API tells you what you paid, in aggregate, after discounts. The JSONL tells you which session, which turn, and which subagent drove it, at list price. Reconstructing real spend for a specific run means pairing them: the JSONL for the breakdown, the Cost API for the authoritative total to check it against.

The Pro and Max subscription usage caps add a different kind of opacity. Anthropic documents the caps as "usage" limits, but does not publish the unit: whether the cap is measured in tokens, in cost-equivalents, or in messages. The JSONL exposes no mapping from `usage.*_tokens` to whatever that unit is. A session-data tool cannot say how a given session counted against a subscription cap.

So the right framing for any JSONL-derived cost estimate is: this is list-price, assuming no discounts, and it will match your actual spend only if you are paying list prices on a non-subscription plan. For most individual users that is close enough. For enterprise accounts or anyone on a subscription cap, it is a lower bound on list price and an unknown relationship to actual spend.

There is a version of this problem that ends with a blunt dollar cap enforced from outside: engineering teams getting monthly budgets and stopping when they hit the ceiling, because reading true agentic cost is genuinely this hard. The alternative, reading it from the JSONL with the right lever catalog, is why this post exists. The ceiling is real; it is not a reason to stop short of it.

---

## Where to go from here

For the core accounting (the subagent rollup undercount trap, the four token kinds, and the aggregation patterns for parent-plus-subagent sessions), the reference is [Part 4](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/posts/2026-06-24-token-accounting-is-harder-than-it-looks.md).

For the complete lever catalog with per-model rate tables, stacking rules, and the worked example: [`reference/cost-model.md`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/cost-model.md).

The next numbered post is Part 5, the full tool-use walkthrough: the `tool_use` / `tool_result` pairing, what `toolUseResult` carries across the range of tool types, and the parallel call pattern that complicates any timing analysis.

The sources behind this post:

- **Reference grounding:** [`reference/cost-model.md`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/cost-model.md), the complete lever catalog
- **Reference grounding:** [`reference/data-dictionary.md` § Usage and token accounting](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/data-dictionary.md#usage-and-token-accounting) and [§ Common pitfalls in cost computation](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/data-dictionary.md#common-pitfalls-in-cost-computation)
- **External reference:** [Anthropic Usage and Cost Admin API](https://platform.claude.com/docs/en/manage-claude/usage-cost-api), the authoritative source for billed organization spend
- **Series planning:** [`series-outline.md`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/.claude/specs/series-outline.md)

---

_Drafted with Claude Code (verified against v2.1.150). The ideas, claims, and any errors are mine._
</content>
</invoke>
