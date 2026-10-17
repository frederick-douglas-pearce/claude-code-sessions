# Model routing research: moving routine work off the main model

Started 2026-10-16. A working research note, not a reference doc: what is known about
routing Claude Code's routine work to cheaper models (or to no model), where each
claim came from, and what is still to be measured. Update it as the experiments
report. Facts about Claude Code carry the date they were checked against the docs.

**Priorities, as set by Fred on 2026-10-16:** cost savings first. Second, showing
what session JSONL (and telemetry) can do, which is capstone material for the series.

**Tracking issues:**
- [#303](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/303) E1, can a hook fail closed. Sub-issue of #295, high priority, blocks the hook-record aside
- [#304](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/304) E2, cheap judges compared
- [#305](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/305) E3, measure where the main model's spend goes, then A/B the interventions; the likely post

## The problem

The main model does routine work in its own turns: formatting fixes, one-line text edits, and the
file search that comes before real work. On an Opus session each such turn is billed at Opus rates
and carries the whole context. That waste is the motivating complaint. Nobody has measured how big
it is yet. #305 phase 1 does that, and its numbers should decide which patterns below get built
first.

## Patterns

| Pattern | What it does | Examples | What the session data can measure |
| --- | --- | --- | --- |
| **0. No model** | Deterministic tools take work the model would otherwise do | `PostToolUse` formatter hook (Prettier, Ruff); ripgrep ranking for file search; regex or path rules as guards | Formatting turns and search turns that disappear from the main thread |
| **A. Decision offload** | A hook asks a cheap model a routine question | pre-edit rule check, skill picker | Main-thread turns saved. The judge's cost shows in telemetry only for `prompt`/`agent` hooks; for a `command` hook calling an external API, only in its own log |
| **B. Context pre-selection** | A hook injects likely files or skills before the main model starts | `UserPromptSubmit` hook returning `additionalContext` | Main-thread tokens and exploratory tool calls saved, set against the hook's cost. The best JSONL showcase |
| **C. Escalation gate** | A cheap model decides whether the expensive path runs | "does this change need a full review?" | How often the expensive path ran, and what it caught |
| **D. Model routing** | Claude Code's own calls go to a cheaper model | subagent `model:`, `opusplan`, a Haiku search agent, gateways | `model` on every assistant line, and cost per model |

Pattern 0 belongs in every comparison as the baseline. The cheapest model call is the one that never
happens, and a formatter hook needs no model at all.

## Claude Code levers (checked against the docs 2026-10-16)

From [model configuration](https://code.claude.com/docs/en/model-config), [subagents](https://code.claude.com/docs/en/sub-agents) and [hooks](https://code.claude.com/docs/en/hooks):

- **Model aliases:** `sonnet`, `opus`, `haiku`, `fable`, `best`, the `[1m]` variants, and `opusplan` (Opus in plan mode, Sonnet for execution). They are set with `/model`, `--model`, `ANTHROPIC_MODEL`, `model` in settings, or `ANTHROPIC_DEFAULT_MODEL` (v2.1.236+).
- **What each alias resolves to:** `ANTHROPIC_DEFAULT_{OPUS,SONNET,HAIKU,FABLE}_MODEL`.
- **Subagents** inherit the main conversation's model unless their frontmatter `model:` is set (`sonnet`, `opus`, `haiku`, `fable`, a full id, or `inherit`). The Agent tool's `model` parameter and `CLAUDE_CODE_SUBAGENT_MODEL` also set it.
- **The built-in Explore subagent runs on the main conversation's model.** It is not a cheap-model search by default. A custom search agent with `model: haiku` is the routing lever. `claude-code-guide` runs on Haiku, and `statusline-setup` on Sonnet.
- **Skills and commands** take a `model` frontmatter field.
- **`prompt` hooks** take a `model` field and default to "the model Claude Code uses for background functionality" (see the [costs doc](https://code.claude.com/docs/en/costs#background-token-usage)). The default `timeout` is 30 s.
- **`agent` hooks** (experimental) take a `model` field; a blocked model falls back to the session's. The default `timeout` is 60 s.
- **`command` hook timeout** defaults to 600 s, lowered to 30 s on `UserPromptSubmit`.
- **Fallbacks:** `fallbackModel` (up to three), and `advisorModel` / `--advisor`.
- **`ANTHROPIC_BASE_URL`** points Claude Code at a gateway. It changes where requests go, not which model answers, unless the gateway rewrites the model.

## External small models

**Jev (TypeSafe AI).** A hosted small model that answers typed questions instead of generating text:
- yes/no with a probability ("Noul")
- choose from a list ("Choice")
- score against a rubric ("Score")

A request carries a `state` (the context) and a set of typed `questions`. Access is through TypeSafe's API, which is gated, or OpenRouter (`jev-latest`, and pinned versions such as `jev-1.13`). There is a Python SDK (`typesafe-sdk`) and a Rust crate (`typesafe_jev`).

TypeSafe's own claims, unverified: about 100 ms per call, $0.042 per million input tokens, free output tokens, and 194× faster and 445× cheaper than a general model on its evaluations. Jev has been in early access since 2026-09, and minor SDK versions have already broken the question types.

Sources (secondary, read 2026-10-16): [Hands-on guide](https://levelup.gitconnected.com/a-hands-on-guide-to-jev-69771edd027a), [How Jev works inside an agent](https://pub.towardsai.net/what-is-jev-how-jev-works-inside-an-ai-agent-c5a3b236f779), [Uses, benchmarks, pricing](https://pub.towardsai.net/jev-ai-explained-uses-benchmarks-pricing-c5a3b236f779), [`typesafe-jev` crate](https://docs.rs/typesafe-jev).

**OpenRouter** also gives access to other small general-purpose models, for contrast with a typed classifier (#304 candidate 5).

**Before any real content goes to a third party,** read and record the provider's data-retention terms here. Until then, only scratch-project content goes to them.

## Practitioner report

A reader's LinkedIn post (2026-10, from the reader whose comment on Part 6 prompted the hook-record
aside; refer to them as "a reader" unless they agree to be named) described five Claude Code hook
tools built on Jev:
- a file finder that ranks relevant files
- a rule check before edits
- a gate deciding whether a change needs a full external review
- a skill picker per prompt
- a check for documented rules no test covers

They reported about 270,000 tokens over the first seven days, roughly a cent at Jev's list price.
They moved from Vercel's AI Gateway to OpenRouter because TypeSafe's API is gated.

**Every tool fails open by design, and a kill-switch file stops all calls.** Commenters raised two
questions:
- Policy and security checks may need to fail closed (#303).
- How are the small model's wrong decisions caught? This needs a decision log, and an eval (#304).

The kill switch is also a silent-allow source: while it is engaged, every hook allows and nothing
records why.

## What #295 already measured (v2.1.299 and v2.1.301)

Evidence: [`tooling/fixture-hooks/capture/README.md`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/tooling/fixture-hooks/capture/README.md).

- A `prompt` hook's model call appears in telemetry as `api_request` with `query_source: hook_prompt`, tokens and `cost_usd`, and it reads from the prompt cache. Three calls on Haiku cost $0.000427 in all.
- An SDK `command` hook without cache control sent about 700 uncached input tokens per call, taking 2.7 to 3.2 s (about 0.9 s of it importing the SDK).
- Two judges in parallel put 2.8 to 3.4 s before every Bash call. Latency, not price, may be the binding cost of model-judged hooks.
- A Python `command` hook costs about 63 ms per firing from Claude Code's side.
- Auxiliary model calls are not small. In one session, `prompt_suggestion` cost $0.048 against $0.171 for the main thread.
- A failed hook (crash, timeout, unreachable server) fails open, and in the session file it looks like an allow.

## Measuring cost honestly

- Price by model and by cache tier: 5-minute and 1-hour cache writes price differently, and cache reads at a discount. Never use a flat token-to-dollar rate. See the Part 4 aside's levers and `reference/data-dictionary.md` § Usage and token accounting.
- Count every model the session used: the main thread, subagents, hook judges (telemetry `query_source`), auxiliary calls, and external APIs from their own logs.
- Model runs are noisy. Compare arms over several runs and report the variance.
- Real sessions are read only through a content-free analyzer with contract tests (the `format-scan` / `analyze.py` pattern), never directly.

## Integration points

- **`claude-hook-validator`**: #303 tells its live layer which failures it can report, and #304's judge comparison feeds its checks on model-judged hooks. Fred is pointing that repo at these issues.
- **AgentFluent**: "routine work on an expensive model" is a candidate diagnostic, and #305 phase 1's analyzer could live there, with this repo documenting the method. A judge's decision log is another diagnostic input.
- **The series**: the hook-record aside (fail-open section, #303). A routing post from #305 is the likely candidate. Pattern B is the main candidate for capstone material on what session data is for.

## Open questions

- How much of the main model's spend is routine work? (#305 phase 1)
- Does a pre-selection hook save more main-thread tokens than it costs, after its own latency? (#305)
- Does a typed classifier match a Haiku `prompt` hook's accuracy on guard decisions? (#304)
- Which hook failures can be made to fail closed? (#303)
- Which model is the "background functionality" model on each provider, and can it be set?
