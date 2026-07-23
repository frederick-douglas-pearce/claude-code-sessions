---
layout: post
title: "What should a better leaderboard have measured?"
date: 2026-07-25 00:00:00-0800
description: "Meta, Amazon, and Uber each learned what happens when you rank engineers by tokens. The failure wasn't the metric. It was that nobody had a numerator. What session data can and can't supply for the question that's left."
categories: ["foundation"]
tags: ["claude-code", "jsonl", "sessions", "cost", "metrics"]
og_image: https://frederick-douglas-pearce.github.io/assets/img/what-should-a-better-leaderboard-have-measured-og.png
og_card_source: social/images/2026-07-25-linkedin-what-should-a-better-leaderboard-have-measured/og-card.png
featured: false
claude_code_version_verified: v2.1.150
---

In the spring of 2026, three companies ran the same experiment within weeks of each other. Meta stood up an internal dashboard, nicknamed "Claudeonomics," that ranked its heaviest AI users, the top 250 out of roughly 85,000 employees, by token consumption. Engineers competed for the top spots, some by leaving idle agents running to pad their numbers, and Meta pulled the dashboard in April as the projected annual cost climbed toward the billions. Amazon built a version called KiroRank on its internal Kiro platform, watched employees game it the same way, and shut it down at the end of May, with a senior VP telling staff not to "use AI just for the sake of using AI." Uber never ran a public ranking, but it knew its per-engineer spend well enough to exhaust its entire 2026 budget for these tools in four months and respond with a hard ceiling: a $1,500 monthly cap per tool.

The standard read on all three is a measurement failure. Bad metric, predictable gaming, chastened correction. I don't think that's right. None of these companies were blind to cost. Uber's cap proves it, a company that can price a monthly ceiling per engineer has already solved the arithmetic. Meta and Amazon ranked tokens because they were solving a different problem, getting engineers to adopt the tools at all, and volume was the only unit anyone had on hand to reward that. The metric worked exactly as designed. Tokenmaxxing wasn't a bug in the measurement. It was the correct response to the incentive as built.

Nobody was measuring what the tokens bought.

## Value per unit cost isn't a new idea

Companies don't rank factory floors by raw material consumed. They ask what the material became. AI coding tools got a pass on that question for a year, because adoption was the actual goal and volume was the only legible signal anyone had while everything downstream of it stayed hard to see. Strip the AI framing off and this is ordinary business thinking, value per unit cost, that got skipped in the rush to get people using the tools. Tokenmaxxing is what happens when you incentivize a proxy without anyone asking what it's a proxy for.

There's a tell in how the story ended. When Amazon retired KiroRank, it replaced the metric with something it called "normalized deployments," an attempt to measure whether the AI-generated code actually did something rather than how many tokens it burned. That's the whole problem in miniature: the moment you stop counting the input and try to count the output, you discover the output is much harder to see.

Cost is the denominator of that fraction. This post is mostly about the numerator, but the denominator deserves one honest paragraph before we move past it.

## The denominator isn't the hard part anymore

[Part 4](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/posts/2026-06-24-token-accounting-is-harder-than-it-looks.md) worked through why naive token summation produces the wrong number: four token kinds priced roughly 50x apart, and a subagent rollup that undercounts real processed tokens by a median of about 5.8x if you read the parent's snapshot instead of summing the subagent's own trace. [The follow-up aside](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/posts/2026-06-27-every-lever-that-moves-the-bill.md) went further: the cache-write field splits into two TTLs that price at 1.25x and 2x, and fast mode, batch pricing, data residency, and server-side tool surcharges each shift the rate again. All of it is computable, per turn, directly from fields the session JSONL already carries.

Both posts land on the same honest ceiling, and it's worth restating here rather than assuming it. Even done correctly, a session-data cost figure is a list-price lower bound, not a bill. Enterprise discounts never show up in the JSONL, and neither does the dollar cost of code execution container-hours. What you get is accurate and incomplete at the same time, and that's fine, as long as you say so.

The point of restating this: the engineering problem of "what did this cost" is basically solved for anyone willing to do it right. That's not new ground this post is breaking. It's the foundation the rest of the post assumes.

## The numerator isn't in the file

Say it plainly, early, and without qualification, because the temptation to fudge this is strong. Whatever engineers actually shipped isn't in `~/.claude/projects/`. Shipped features aren't there. Defect rates aren't there. Review burden isn't there. Whether the code survived six months in production isn't there. Session JSONL is a record of what happened during a conversation with Claude Code, not a record of what happened after the conversation ended.

Any post claiming otherwise is selling something.

That's a hard boundary, not a caveat to be softened in the next paragraph. It shapes everything that follows: session data can support proxies for effort and efficiency. It cannot supply the value side of the fraction. Anyone building a "better leaderboard" needs to know exactly where that line sits before they draw one number past it.

## What session data can support

None of the following is value. All four are readable, directly, from fields the series has already documented, and each one is a proxy for effort or efficiency rather than for whether the effort was worth having.

1. **Cache reuse trajectory.** Reads climbing while writes shrink, the pattern Part 4 walked through turn by turn, says a session or subagent run is reusing its context rather than rebuilding it. That's an efficiency signal. A well-run session that produces nothing useful and a well-run session that ships a fix can show the identical curve.

2. **Model-to-task fit.** A top-tier model doing work a smaller one could have handled shows up as `message.model` mismatched against the shape of the task, which the cost-levers aside's per-model rate spread makes expensive to miss. It's a cost signal with no value story attached on its own.

3. **Retry and error density.** Repeated tool calls, `is_error` results, edits re-issued after a failed attempt, all legible from the `toolUseResult` envelope. High retry density suggests friction. It doesn't distinguish a hard problem handled patiently from a session flailing at the wrong approach.

4. **Delegation shape.** How much work moves to subagents, how often, how deep, readable from `Agent` tool-use counts and their `toolStats`. The Part 4 caveat applies without exception here: any total drawn from a subagent has to come from its trace file, never the parent's rollup, or the delegation-shape number inherits the same undercount that corrupts a naive cost figure.

Each of these is worth watching. None of them, alone or combined, tells you whether the work was good.

## What git and GitHub add

This is the strongest proxy available for the question session data can't answer: did the work hold up. Churn on recently touched lines, revert rate, PR review iteration counts, time to merge, defects that link back to a commit. None of it lives in `~/.claude/projects/`. All of it lives in the repository and the platform hosting it.

The join between the two is a real, and genuinely open, engineering problem. The session file records enough to attribute a commit to a session in principle. `cwd` and `gitBranch` are per-line fields, `gitBranch` recording the git branch active in `cwd` at the time the line was written, and `timestamp` gives every line an ISO 8601 moment (see [`reference/data-dictionary.md` § Common fields](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/data-dictionary.md#common-fields) for the exact field semantics). Put those three together with the commit history on the matching branch in the matching window and you have a candidate commit for a session.

A candidate, not a certainty. Branch plus time window is a heuristic, not an identity. Multiple sessions can touch the same branch inside the same window. A branch can span far more commits than any single session accounts for. Nothing about `cwd` or `gitBranch` guarantees a clean one-to-one mapping between a session and the commit it produced, and I'm not aware of anyone who has published a validated accuracy figure for this join. That's the honest state of it.

It's a direction under active work, not an armchair proposal. [AgentFluent](https://github.com/frederick-douglas-pearce/agentfluent) and [CodeFluent](https://github.com/frederick-douglas-pearce/codefluent) are both early into exactly this join, reading `gitBranch` and commit timestamps to connect a session to what it produced. Neither has solved it, and the point here isn't that they have. It's that the road is being walked, carefully, by people who know the join is a heuristic.

## The limits, not a disclaimer

Everything above is a section, not a footnote, because it changes what any of this is fit for.

Proxies are gameable once measured, and the lesson applies recursively to everything proposed here. Rank a team on cache-reuse ratio and expect padded cache writes to appear. Rank on rework rate and expect fewer, larger, riskier commits that dodge revert counting without actually reducing rework. Rework signals themselves conflate healthy iteration with waste: a pull request that goes through six review rounds might be careful craftsmanship on something that mattered, or it might be a mess. Git history alone can't tell you which.

Attribution to a single engineer is neither reliable, given the join is a heuristic to begin with, nor advisable, since individual attribution is exactly the failure mode that started this post. Everything above should be read at the team and repo level. That's a deliberate choice, not an oversight.

And the honest close: no thresholds are offered here. I'm not going to tell you what a good cache-reuse curve looks like or what rework rate should worry you, because a defensible baseline needs a corpus of session data paired with real, longitudinal outcomes, and that doesn't exist publicly yet. Anyone who hands you a number today is guessing, confidently.

## Where this leaves you

If you're the executive who just killed a leaderboard and still owes someone an answer for what replaces it: cost, computed correctly, read alongside cache efficiency, model fit, retry density, delegation shape, and rework signals from git and GitHub, at the team and repo level, with no ranking and no threshold pretending to be a verdict. That's not a scoreboard. It's a dashboard you have to actually read.

If you're the practitioner who already fixed your denominator: that was necessary, not sufficient. An accurate cost figure is a fact. It isn't a decision. The numerator is still missing, and no post, including this one, gets to hand it to you for free.

## Sources

The three leaderboard episodes, from primary reporting:

- **Meta ("Claudeonomics"):** [Meta killed its employee AI token dashboard](https://fortune.com/2026/04/09/meta-killed-employee-ai-token-dashboard/) (Fortune)
- **Amazon (KiroRank):** [Amazon drops its internal AI leaderboard for staff working on Kiro](https://finance.yahoo.com/sectors/technology/articles/amazon-drops-internal-ai-leaderboard-161639454.html) (Yahoo Finance) and [Amazon bins an internal AI leaderboard for its Kiro employees](https://www.pcgamer.com/software/ai/amazon-bins-an-internal-ai-leaderboard-for-its-kiro-employees-because-they-were-burning-through-too-many-costly-tokens/) (PC Gamer)
- **Uber ($1,500 cap):** [Uber caps employee AI spending after blowing through budget in four months](https://techcrunch.com/2026/06/02/uber-caps-employee-ai-spending-after-blowing-through-budget-in-four-months/) (TechCrunch) and [Uber caps usage of AI tools like Claude Code to manage costs](https://www.bloomberg.com/news/articles/2026-06-02/uber-caps-usage-of-ai-tools-like-claude-code-to-cut-costs) (Bloomberg)

The cost-side grounding lives in this series: [Part 4 — Token accounting is harder than it looks](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/posts/2026-06-24-token-accounting-is-harder-than-it-looks.md) and [Every lever that moves the bill](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/posts/2026-06-27-every-lever-that-moves-the-bill.md), both resting on [`reference/data-dictionary.md`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/data-dictionary.md).

---

_Drafted with Claude Code (verified against v2.1.150). The ideas, claims, and any errors are mine._
