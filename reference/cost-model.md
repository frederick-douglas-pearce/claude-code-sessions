# Cost model — the complete lever catalog

**Verified against Claude Code v2.1.150.** Rates and multipliers cross-checked against Anthropic's [pricing page](https://platform.claude.com/docs/en/about-claude/pricing) on **2026-06-26**. Rates are external and volatile; treat every dollar figure and multiplier here as "verified on that date" and re-confirm against the live pricing page before relying on it.

**Scope.** First-party Claude API usage as recorded in Claude Code / Claude Agent SDK session JSONL (`~/.claude/projects/**/*.jsonl`). Cloud-platform (Bedrock / Vertex / AWS-CCU) and Managed-Agents billing are out of scope and catalogued in [Section E](#e-out-of-scope-but-real-no-first-party-jsonl-signal).

This is the canonical cost reference for the Claude-session tooling family. [AgentFluent](https://github.com/frederick-douglas-pearce/agentfluent) and [CodeFluent](https://github.com/frederick-douglas-pearce/codefluent) link here rather than duplicating it. It enumerates **every input that affects the dollar cost of a Claude request**, where (if anywhere) that input is observable in the session JSONL, and whether [pydantic/genai-prices](https://github.com/pydantic/genai-prices) (the best-known open pricing dataset) currently models it. For the field-level shape of `usage`, see [`data-dictionary.md` § Usage and token accounting](data-dictionary.md#usage-and-token-accounting); this doc is the cost layer on top of those fields.

> **The format evolves.** Claude Code may add, rename, or restructure `usage` fields. Treat every field path below as verified on the date above and re-confirm against a current session before relying on it. `usage` parsing should ignore unknown fields, not assume presence.

---

## 0. Where cost data lives in the JSONL

Cost-relevant data is carried on **`type: "assistant"`** records. The shape (fields relevant to cost only):

```jsonc
{
  "type": "assistant",
  "timestamp": "2026-06-26T...Z",          // used for date-aware pricing (effective rates)
  "message": {
    "model": "claude-opus-4-7",            // (B) selects the rate table
    "usage": {
      "input_tokens": 2741,                // (A) base input
      "output_tokens": 329,                // (A) output (incl. thinking tokens)
      "cache_read_input_tokens": 0,        // (A) cache hit, 0.1x
      "cache_creation_input_tokens": 19227,// (A) SUM of the two TTLs below
      "cache_creation": {                  // (A) the TTL split — REQUIRED to price cache writes correctly
        "ephemeral_5m_input_tokens": 0,    //     5-minute write, 1.25x
        "ephemeral_1h_input_tokens": 19227 //     1-hour write, 2x
      },
      "output_tokens_details": {           // (F) thinking-token breakdown (subset of output_tokens)
        "thinking_tokens": 0
      },
      "server_tool_use": {                 // (D) non-token tool surcharges (counts only)
        "web_search_requests": 0,          //     $10 / 1,000
        "web_fetch_requests": 0            //     free
        // "code_execution_requests": N    //     appears only when used; billed by container-hour (NOT here)
      },
      "service_tier": "standard",          // (C) "standard" | "priority" | "batch"
      "speed": "standard",                 // (C) "standard" | "fast"  (fast = fast-mode premium)
      "inference_geo": "not_available"     // (C) "global"(default) | "us"(1.1x) | "not_available" | ""
    }
  }
}
```

`message.usage.iterations[]` repeats the same per-message fields for multi-turn internal iterations; the top-level `usage` is the billable rollup. The `iterations` shape (scalar vs array) is not yet settled in this reference — see [#140](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/140).

The same `usage` shape appears on the subagent rollup (`toolUseResult.usage` on a parent `user` line), but the rollup has **two** defects, not one. The larger: it is a **single-turn snapshot** (the subagent's final turn), not a run total, so it is insufficient even for *token* accounting — summing it undercounts real processed tokens by a median ~5.8x. The lesser: it carries no `model`, and per-token rates are per-model, so it could not be priced even if the quantity were right. For a subagent's spend, sum the trace's per-turn `message.usage` (deduped by `message.id`) and price each turn at its own `message.model`. See [`subagent-traces.md` § Token accounting](subagent-traces.md#token-accounting) and [`data-dictionary.md` § Common pitfalls](data-dictionary.md#common-pitfalls-in-cost-computation).

---

## A. Token-rate dimensions (per-token)

These are priced as `tokens × rate ÷ 1e6`. Rate depends on the model ([Section B](#b-model-tier-selects-the-rate-table)).

| Lever | Multiplier vs base input | JSONL location | genai-prices field |
|---|---|---|---|
| Base input | 1× | `usage.input_tokens` | ✅ `input_mtok` |
| Output | — (own rate) | `usage.output_tokens` | ✅ `output_mtok` |
| Cache read (hit) | 0.10× | `usage.cache_read_input_tokens` | ✅ `cache_read_mtok` |
| Cache write — **5 minute** TTL | 1.25× | `usage.cache_creation.ephemeral_5m_input_tokens` | ⚠️ single `cache_write_mtok` (= 5m value) |
| Cache write — **1 hour** TTL | 2× | `usage.cache_creation.ephemeral_1h_input_tokens` | ❌ **not modeled** |

Notes:

- `cache_creation_input_tokens` = `ephemeral_5m_input_tokens` + `ephemeral_1h_input_tokens`. Pricing the sum at a single rate **under-reports cost whenever 1h writes are present** — and in Claude Code sessions the 1-hour TTL is commonly the dominant share by token volume.
- Fallback when the `usage.cache_creation` sub-object is absent (older sessions): treat the full `cache_creation_input_tokens` as 5m.
- Output tokens include extended-thinking tokens; see [Section F](#f-count-affecting-not-rate-do-not-apply-as-multipliers).
- **Who chooses the TTL.** The 5-minute TTL is the API default, but the client (Claude Code) sets the cache breakpoints and their TTLs, automatically, with no user-facing setting. The likely mechanism (inferred, not documented by Anthropic): a 1-hour breakpoint on the stable prefix (system prompt, tool definitions, project instructions, early context) and a 5-minute breakpoint on the volatile tail, which is why the 1-hour share dominates by volume even though 5-minute writes occur more often. The split is observable per turn in the JSONL via the two `cache_creation` sub-keys.

### Base rates (USD per 1M tokens, verified 2026-06-26)

| Model | Base input | 5m write (1.25×) | 1h write (2×) | Cache hit (0.1×) | Output |
|---|---|---|---|---|---|
| Fable 5 | 10 | 12.50 | 20 | 1.00 | 50 |
| Opus 4.5 / 4.6 / 4.7 / 4.8 | 5 | 6.25 | 10 | 0.50 | 25 |
| Opus 4 / 4.1 *(retired/deprecated)* | 15 | 18.75 | 30 | 1.50 | 75 |
| Sonnet 4 / 4.5 / 4.6 | 3 | 3.75 | 6 | 0.30 | 15 |
| Haiku 4.5 | 1 | 1.25 | 2 | 0.10 | 5 |
| Haiku 3.5 *(retired)* | 0.80 | 1.00 | 1.60 | 0.08 | 4 |

---

## B. Model tier (selects the rate table)

| Lever | JSONL location | genai-prices |
|---|---|---|
| Model → rate table | `message.model` | ✅ `match` patterns per model |

Aliases (`opus`, `…[1m]` suffixes, dated variants like `claude-opus-4-5-20251101`) must resolve to the canonical rate table. `<synthetic>` is a Claude Code sentinel for internal messages — **skip it before pricing** (not a real API call).

---

## C. Per-request multipliers (stack on Section A)

| Lever | Effect | JSONL location | genai-prices |
|---|---|---|---|
| **Fast mode** | premium flat rates (below) | `usage.speed == "fast"` | ❌ not modeled |
| **Batch API** | 0.5× input & output | `usage.service_tier == "batch"` | ❌ not modeled |
| **Priority tier** | commitment pricing | `usage.service_tier == "priority"` | ❌ not modeled |
| **Data residency (US)** | 1.1× on *all* token categories | `usage.inference_geo == "us"` | ❌ not modeled |
| **Long-context (>200K)** | model-dependent premium tier | *derived*: `input + cache_read + cache_write` vs model context window | ✅ `tiers:[{start, price}]` |

Stacking rules (per pricing page):

- Fast mode applies across the full context window (incl. >200K) and **stacks with** prompt-caching multipliers and data residency; **not available with** Batch.
- Batch and prompt-caching discounts combine.
- Data residency 1.1× applies to input, output, cache writes, and cache reads (Opus 4.6 / Sonnet 4.6 and later only; earlier models reject the `inference_geo` param).

**Long-context status (important):** the current 1M-window models — Opus 4.6/4.7/4.8, Sonnet 4.6, Fable 5 — bill the **full window at standard (flat) pricing**; there is **no >200K premium** for them. genai-prices encodes the *historical* transition where applicable via a dated `constraint` (e.g. Opus 4.6 moved to flat-1M on 2026-03-13). A request only incurs a >200K premium on a model that actually has the tier at that date.

### Fast-mode rates (USD per 1M tokens)

| Model | Input | Output |
|---|---|---|
| Opus 4.6 / 4.7 | 30 | 150 |
| Opus 4.8 | 10 | 50 |

(Prompt-caching multipliers and data residency apply on top of fast-mode rates.)

---

## D. Server-side tool surcharges (non-token, additive)

These are **separate line items**, not token rates. The request *count* is in the JSONL; the *cost* is not always reconstructable from a single session (see code execution).

| Lever | Rate | JSONL location | Observable? | genai-prices |
|---|---|---|---|---|
| Web search | $10 / 1,000 searches | `usage.server_tool_use.web_search_requests` | ✅ fully | ❌ not modeled |
| Web fetch | free | `usage.server_tool_use.web_fetch_requests` | n/a (no cost) | n/a |
| Code execution | $0.05 / hour / container; **1,550 free hr/month**; 5-min minimum | `usage.server_tool_use.code_execution_requests` (count only) | ⚠️ **partial** — billed by container-*hour* against a monthly org-level free tier; per-session JSONL has the request count but **not the duration or the monthly aggregate** | ❌ not modeled |

> genai-prices has a per-request field (`requests_kcount`, used today for Perplexity) that *could* express the web-search surcharge, but it is **not populated for Anthropic**. Code-execution's hour-based, free-tiered billing has no representation.

---

## E. Out-of-scope-but-real (no first-party JSONL signal)

Catalogued for completeness; not observable in Claude Code / Agent SDK session files and therefore out of scope for a session-JSONL cost estimator.

| Lever | Effect | Why out of scope |
|---|---|---|
| Bedrock / Vertex regional & multi-region endpoints | +10% over global | Partner-operated; billed by the cloud provider, not in first-party JSONL |
| Claude Platform on AWS | CCU conversion ($0.01/CCU) | Marketplace invoicing; not in JSONL |
| Managed Agents session runtime | $0.08 / session-hour | Managed-Agents product; not in Claude Code session JSONL |

---

## F. Count-affecting, NOT rate (do not apply as multipliers)

These change the **number of tokens**, which is already reflected in the `usage.*_tokens` counts. **Do not** add them as price multipliers — that would double-count.

| Factor | Effect | Already captured by |
|---|---|---|
| New tokenizer (Opus 4.7+) | up to +35% tokens for the same text | `usage.input_tokens` / `output_tokens` already reflect it |
| Tool-use system prompt + tool definitions | adds input tokens (per-model overhead table on pricing page) | `usage.input_tokens` |
| Extended thinking | billed as output tokens | `usage.output_tokens` (breakdown in `usage.output_tokens_details.thinking_tokens`) |

---

## G. Underivable from session data (stated limitation)

| Factor | Why |
|---|---|
| Volume / enterprise / negotiated discounts | Applied at the account/billing layer; never present in session JSONL. A list-price estimator reports **list price**, which may overstate an enterprise account's actual spend. |
| Subscription (Pro/Max) usage-cap accounting | The Pro/Max 5-hour and weekly caps are documented as "usage" but Anthropic does not publish the unit (tokens vs cost-equivalent vs messages), and the JSONL exposes no mapping from `usage` tokens to the cap. A session-data tool cannot say how a session counted against a subscription cap. |

---

## Coverage in open pricing datasets (genai-prices)

genai-prices (MIT) is the best-known open pricing dataset and the one the sibling tools build on. For Anthropic it currently models **only**: `input_mtok`, `output_mtok`, `cache_read_mtok`, `cache_write_mtok` (single, 5m-equivalent), context-length `tiers`, and date/time `constraint`s. Everything below is a **gap a downstream consumer must supply** (via a local overlay) and/or request upstream:

| Gap | Section | Live cost impact for users |
|---|---|---|
| 1-hour cache write (2×) | A | **High** (commonly the dominant TTL) |
| Fast mode premium rates | C | High *if used* |
| Batch (0.5×) / Priority tier | C | Medium (batch ≠ interactive, but SDK users may batch) |
| Data residency US (1.1×) | C | Low–Medium |
| Web search ($10/1k) | D | Medium *if used* |
| Code execution ($/hr) | D | Partial — see Section D |

Out-of-scope ([E](#e-out-of-scope-but-real-no-first-party-jsonl-signal)) and count-affecting ([F](#f-count-affecting-not-rate-do-not-apply-as-multipliers)) levers need **no rate modeling**; they are documented so consumers neither attempt to price them nor double-count them.

---

## Worked example (correct cache-write handling)

A single Opus 4.7 request: `input_tokens=2741`, `output_tokens=329`, `cache_read_input_tokens=0`, `cache_creation.ephemeral_5m_input_tokens=0`, `cache_creation.ephemeral_1h_input_tokens=19227`, `speed=standard`, `service_tier=standard`, `inference_geo` not US.

```
input  : 2741   × $5.00  / 1e6 = $0.0137050
output : 329    × $25.00 / 1e6 = $0.0082250
1h write:19227  × $10.00 / 1e6 = $0.1922700   ← priced at 2× base, NOT 1.25×
5m write:0      × $6.25  / 1e6 = $0.0000000
cache rd:0      × $0.50  / 1e6 = $0.0000000
                               -----------
                         total = $0.2142000
```

Pricing the 19,227 cache-write tokens at the 5m rate ($6.25) instead would report a $0.1421 total, a **$0.072 (-37.5% on cache-write cost)** under-report on this one request.
