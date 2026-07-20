# Token accounting mechanics (Claude Code sessions)

**Purpose:** Durable reference for how the four token-usage categories behave **per turn** in Claude Code (and subagent) sessions, with empirical calibration from real local traces. Grounds the Part 4 post ("Token accounting is harder than it looks") and the anatomy-fixture realism work ([#103](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/103)).

**Status:** Research / analysis. May graduate into `reference/` (data-dictionary § Usage and token accounting) once Part 4 formalizes it.

> **CORRECTION (2026-07-19).** An earlier version of this doc described the parent rollup as **double-counting** the subagent's tokens (the same work summed in both the trace and the rollup, ~2× inflation). That was backwards. The parent's `toolUseResult.usage` is a **single assistant turn's snapshot** (the subagent's last turn), not a run total, so reading it in place of summing the trace **under**counts processed tokens by a median of ~5.8×. The paired fixtures were re-cut to match ([#144](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/144)): the rollup is now `3/300/1500/27000` = 28,803 (turn 8 only), while the trace sums to `20/1000/29000/150000` = 180,020. The canonical treatment is [`reference/subagent-traces.md` § Token accounting](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/subagent-traces.md#token-accounting). The two bullets below have been corrected in place.

**Provenance:**

- **Documented mechanics** — Anthropic prompt-caching docs (via the `claude-api` skill, cached 2026-05-26) + [`reference/data-dictionary.md`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/data-dictionary.md) § Usage and token accounting.
- **Empirical calibration** — content-free aggregate measurement of **746 real subagent traces** under `~/.claude/projects/` on this machine, 2026-06-11. **No per-session values, UUIDs, prompts, or content were read or recorded — only aggregate token-count statistics** (medians/percentiles across many traces), consistent with the `tooling/format-scan/scan.py` content-free contract.

---

## 1. The four usage fields (documented mechanics)

`message.usage` (and the rolled-up `toolUseResult.usage`) carry four token counts. They are **disjoint** — every prompt token lands in exactly one:

| Field                         | What it counts                                | Price vs. base input            |
| ----------------------------- | --------------------------------------------- | ------------------------------- |
| `input_tokens`                | Uncached prompt tokens, processed full-price  | 1×                              |
| `cache_creation_input_tokens` | Tokens **written** to the prompt cache        | 1.25× (5-min TTL) / 2× (1h TTL) |
| `cache_read_input_tokens`     | Tokens **read** from the prompt cache         | ~0.1×                           |
| `output_tokens`               | Tokens generated                              | model-dependent (e.g. 5× input on Sonnet-tier) |

**Total prompt size = `input_tokens` + `cache_creation_input_tokens` + `cache_read_input_tokens`.** Critically, `input_tokens` is the **uncached remainder only** — when a session caches aggressively (Claude Code does), this number is tiny even when the real context is enormous.

### Per-turn behavior in a multi-turn run

Prompt caching is a prefix match, and the cache breakpoint sits at the end of the most-recently-appended turn, so each request re-reads the entire prior conversation prefix:

- **Turn 1** writes the cacheable prefix (system prompt + tools + first user content): `cache_creation` is **large**, `cache_read` is **0** for a truly fresh cache — or a non-zero **warm-cache read** if a prior invocation's cache is still alive within the 5-minute TTL.
- **Turns 2..N** read the whole accumulated prefix (`cache_read` ≈ cumulative cached context, **growing every turn**) and write only the new increment (`cache_creation` small, tapering). `input_tokens` stays tiny (the newest content not yet behind a breakpoint).

**Load-bearing consequence:** per-turn `cache_read` is **≥ turn-1 `cache_creation` and rises** across the run, while `cache_creation` is front-loaded then tapers. A fixture (or mental model) where `cache_read` is *smaller* than turn-1 `cache_creation`, or *shrinks* over the run, has the mechanism backwards.

### Pricing ratios (for cost reasoning)

base input **1×** · cache **write** 1.25× (5-min) / 2× (1h) · cache **read** ~**0.1×** · output **separate** (model-dependent). A run dominated by cache reads is far cheaper per token than its raw token count implies — the central nuance of session-cost computation.

---

## 2. Empirical calibration (746 real subagent traces, 2026-06-11)

Per-assistant-turn-position **medians** (the source run also captured p10/p90):

| Turn position | input | output | cache_creation | cache_read |
| ------------- | ----: | -----: | -------------: | ---------: |
| Turn 1        |     3 |      2 |         13,239 |      4,715 |
| Turn 2        |     3 |      3 |         13,717 |      4,694 |
| Turn 3        |     3 |      5 |         10,040 |     12,712 |
| Turn 4+       |     1 |     36 |          1,515 |     45,153 |

Per-run **totals** (median across 746 traces; ~17 turns median):

| Field                         | Median per run |
| ----------------------------- | -------------: |
| `input_tokens`                |           ~37  |
| `output_tokens`               |        ~3,286  |
| `cache_creation_input_tokens` |       ~97,558  |
| `cache_read_input_tokens`     |      ~475,848  |
| turns                         |           ~17  |

Ranges are wide — `cache_read` per run spans ~41K (p10) to ~2.1M (p90) — because runs vary enormously by length and tool use. The **shape**, not the absolute magnitude, is the durable finding.

### Key takeaways

1. **`cache_read` dominates** — ~82% of all tokens in a typical run. The headline cost is cache reads (~0.1×), not "input."
2. **`input_tokens` is negligible** (~tens per run). Claude Code caches almost everything, so the full-price input number is near-zero — counterintuitive and a common source of cost-estimate error.
3. **`cache_creation` is front-loaded** (~13K on turns 1–2, tapering to ~1.5K) — system prompt + tools written once, then small increments.
4. **`cache_read` grows monotonically** as the conversation accumulates (near-0 → ~45K/turn by mid-run).
5. **Magnitude ordering:** `cache_read` ≫ `cache_creation` ≫ `output` ≫ `input`.

---

## 3. Implications

### Anatomy fixtures ([#103](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/103))

The post-#98/#99 anatomy fixture used `input 6,000 / output 2,000 / cache_creation 12,000 / cache_read 16,000` — off from reality by **~8–160× per category**, and with `cache_read` *smaller* than `cache_creation` (backwards). The realistic 8-turn model (scaled to the fixture's 7-tool-call run) preserves the real shape: tiny `input`, front-loaded `cache_creation`, growing-and-dominant `cache_read`. Proposed numbers tracked in #103; whatever lands must satisfy the corrected invariants (the parent rollup equals the subagent's **final** turn, not the trace sum; `totalTokens` = sum of that turn's four fields). The original #98/#99 "trace sums to the rollup" invariant embodied the double-count bug and was retired when the fixtures were re-cut under #144.

### Part 4 — "Token accounting is harder than it looks"

This is the empirical backbone for Part 4. Data-supported headline points:

- A run's reported `input_tokens` can be **~20** while it processes **hundreds of thousands** of tokens — almost all cache reads.
- **Cost ≠ token count:** the four kinds price at 1× / 1.25× / 0.1× / output-rate. A cache-read-dominated run is cheap per token.
- The parent rollup is a **single-turn snapshot**, not the run total, so reading it as the subagent's cost **under**counts by a median of ~5.8× (see Part 3 / [`reference/subagent-traces.md`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/subagent-traces.md) § Token accounting); a subagent's real processed tokens come from summing its trace turn by turn, never from the rollup.

---

## 4. Method & reproducibility

The measurement walked `~/.claude/projects/**/subagents/agent-*.jsonl`, extracted each `assistant` line's `message.usage`, bucketed by turn position, and reported medians/percentiles **across** traces — aggregate statistics only. No `message.content`, prompts, paths, UUIDs, or per-session token values were emitted or committed. This mirrors `tooling/format-scan/scan.py`'s content-free contract (which emits size-byte statistics the same way). The one-off script was not committed; the aggregates in §2 are the durable artifact. If a reusable per-turn token probe is ever wanted, it belongs in the format-scan tooling under the same no-values discipline.

**Re-verify when:** Claude Code changes its caching/breakpoint strategy; a new model tier shifts the pricing ratios; or the `usage` field set changes (watch via the [format-watch queue](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/.claude/specs/research/jsonl-format-watch.md)).
