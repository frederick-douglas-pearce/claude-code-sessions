---
layout: post
title: "What should a better leaderboard have measured?"
date: 2026-07-25 00:00:00-0800
description: "Meta, Amazon, and Uber each learned what happens when you rank engineers by tokens. Session data records everything up to the moment work is handed off and nothing after it. What that boundary actually permits, and why the missing numerator was never the tool's to supply."
categories: ["foundation"]
tags: ["claude-code", "jsonl", "sessions", "cost", "metrics"]
og_image: https://frederick-douglas-pearce.github.io/assets/img/what-should-a-better-leaderboard-have-measured-og.png
og_card_source: social/images/2026-07-25-linkedin-what-should-a-better-leaderboard-have-measured/og-card.png
featured: false
claude_code_version_verified: v2.1.152
---

In the spring of 2026, three companies ran the same experiment within weeks of each other. Meta stood up an internal dashboard nicknamed "Claudeonomics" that ranked its heaviest AI users, the top 250 of roughly 85,000 employees, by token consumption. Engineers competed for the top spots, some by leaving idle agents running to pad their numbers, and Meta pulled it in April as projected annual cost climbed toward the billions. Amazon built KiroRank on its internal Kiro platform, watched employees game it the same way, and shut it down at the end of May, with a senior VP telling staff not to "use AI just for the sake of using AI." Uber never ran a public ranking, but exhausted its entire 2026 budget for these tools in four months and responded with a hard ceiling: $1,500 per tool per month.

The standard read is a measurement failure. Bad metric, predictable gaming, chastened correction. I don't think that's right. None of these companies were blind to cost, and Uber's cap proves it: a company that can price a monthly ceiling per engineer has already solved the arithmetic. Meta and Amazon ranked tokens because they were solving a different problem, getting engineers to adopt the tools at all, and volume was the most straightforward unit to reward. Tokenmaxxing wasn't a measurement bug. It was the natural response to the incentive as built.

Nobody was measuring, at least publicly, what the tokens bought.

## The tell is in how the story ended

Companies don't rank factory floors by raw material consumed. They ask what the material became. AI coding tools got a pass on that question for a year because adoption was the goal and there was real resistance to overcome, particularly from senior engineers. Strip the AI framing off and this is ordinary value-per-unit-cost thinking, skipped in the rush to get people using the tools.

Watch what Amazon reached for when it retired KiroRank: "normalized deployments," an attempt to count whether the AI-generated code was used in production. That's the problem in miniature, though not for the obvious reason. Deployments are a real outcome, and a company that size is almost certainly running them as a KPI already. What a deployment count can't do is tell you which change inside it was worth shipping. Reach for the outcome you already have and you inherit the granularity it came with. Hold onto that, it comes back at the end.

## The denominator is solved

[Part 4](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/posts/2026-06-24-token-accounting-is-harder-than-it-looks.md) worked through why naive token summation produces the wrong cost proxy: four token kinds priced roughly 50x apart, and a subagent rollup that undercounts real processed tokens by a median of about 6x if you read the parent's snapshot instead of the subagent's own trace. [The follow-up aside](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/posts/2026-06-27-every-lever-that-moves-the-bill.md) went further, splitting the cache-write field into two TTLs priced at 1.25x and 2x, then adding fast mode, batch pricing, data residency, and server-side tool surcharges. All of it computable per turn, from fields the JSONL already carries.

Both posts land in the same place. Done right, the number is correct at list price, per turn, from fields already on disk. The JSONL doesn't carry your enterprise discount rate or the dollar cost of code execution container-hours, but neither is an unknown: a discount is a multiplier you were told when you signed, and container-hours arrive on their own line of the bill. Those are external factors, not measurement error. "What did this cost" is solved for anyone willing to do it right. That's the floor this post stands on, not new ground it breaks.

## The record ends at handoff

Session JSONL is a remarkably complete record of how the work was built. The code that was committed. The defects Claude found while reading the codebase, along with the tests, the documentation, and the refactors it proposed.

Complete, with one boundary worth naming: the file records what Claude Code handled. A fix a teammate hand-wrote, a review comment resolved without asking Claude, leaves no trace. That's mostly fine here, since the denominator only counts Claude's tokens either way. It stops being fine the moment you credit a session with a feature other people wrote parts of.

What isn't there at all is anything that happened after the work left the session. Whether the feature got used. Whether the defect Claude flagged was load-bearing or cosmetic. Whether the code survived six months in production, or six days. Whether the thing was worth building at all. The file is complete up to the moment of handoff and empty after it.

Session data isn't missing the artifact. It's missing the artifact's value. Every proxy below describes how work was produced, never how it landed.

## What's actually in the file

Sorted by what each is a proxy for, because they aren't the same kind of signal and flattening them is part of how you end up with a leaderboard.

**Efficiency.** Cache reuse trajectory, reads climbing while writes shrink, the pattern Part 4 walked through turn by turn. It says a session is reusing context rather than rebuilding it. Clean signal, narrow meaning: a well-run session that produces nothing and a well-run session that ships a fix show the identical curve.

**Friction.** Repeated tool calls, `is_error` results, edits re-issued after a failed attempt, all legible from the `toolUseResult` envelope. High retry density says something isn't going smoothly. It can't distinguish a hard problem handled patiently from a session flailing at the wrong approach.

**Calibration.** The interesting category. It asks one question in several forms: did the escalation match the difficulty?

- A top-tier model doing work a smaller one could have handled, visible as `message.model` against the shape of the task.
- Plan mode entered on a one-line change, or never entered on a forty-file refactor. `ExitPlanMode` is an ordinary tool call, and session lines carry a `mode` marker.
- Subagents spawned for work the main loop could have done, or never spawned on a sweep that needed fan-out, readable from `Agent` tool-use counts.
- Verification order, the most concrete signal here. Whether a `Read` or `Grep` follows an `Edit`. Whether a test command runs before a commit. Pure tool sequence, no external data, and it turns "is the work checked" into a countable rate. CodeFluent ships it as `test_before_commit_rate` and `review_before_accept_rate`.
- Conventions re-explained every session instead of written into a `CLAUDE.md`, a skill, or a slash command, each of which leaves its own trace on the turns it runs under. The sharpest version is the enforcement gap CodeFluent's config scan looks for: a `CLAUDE.md` that states a rule with no hook enforcing it.

None of these mean much alone, and nobody can tell you whether planning was worth it for one task. That objection kills calibration if you read it session by session, so don't. The measurable thing is the correlation across many sessions: does plan-mode usage rise with task size, does model tier track difficulty? Difficulty has its own noisy proxies in the file: files touched, turn count, distinct tools, retry density. The correlation between two noisy signals beats either one alone.

## The one axis that touches both sides

Time is the one axis coupled to both sides of the fraction: shipping sooner is worth more, and taking longer usually costs more. The instrumentation is there. `system` lines carry a `turn_duration` subtype with `durationMs` and `messageCount`, so per-turn wall-clock and turn density are first-class rather than reconstructed from `timestamp` arithmetic, and subagent runs report `totalDurationMs` on the parent envelope.

The hard part is deciding what one unit of work is. A session file isn't one: a file can span days of intermittent use, and a focused stretch of work can span several files. CodeFluent segments it this way. Pool a project's messages, sort by timestamp, and cut a new conversation wherever the gap between user prompts exceeds a threshold, sixty minutes by default, aligned to the unit Anthropic's fluency research scored. That bounds the idle problem without pretending to solve it: a ninety-minute gap becomes a boundary rather than duration.

That boundary is also a cost boundary, which is where time stops being an abstraction. Sixty minutes is the extended cache TTL, so a gap wide enough to cut a segment is wide enough to have expired the cache behind it, and the next turn pays a full cache write to rebuild context that a moment earlier was costing a tenth as much to read. On a large context that is a real cost lever.

What's left doesn't go away. Inside a segment you can't separate a long productive think from a distraction, and speed is partly double-counted against the denominator anyway. Measurable, boundable, still not clean. Worth tracking, not worth ranking.

## The join, and what its failure tells you

The proxies for did-the-work-hold-up mostly live outside the session, and they sort by how much friction the data costs to get. [AgentFluent](https://github.com/frederick-douglas-pearce/agentfluent) organizes them in three tiers, which beats treating "git stuff" as one bucket. Tier 1 needs nothing new: within-session rework, the same file edited repeatedly after the work was declared done, plus user mid-flight corrections. Tier 2 reads local `git log`: `feat:` commits followed within a window by `fix:` commits on the same files, revert rate, how many conversations a file absorbs before its edits settle. Tier 3 is opt-in GitHub, richest signal and highest friction: CI failure on first push, the cleanest of the lot because it's a direct quality miss that's hard to fake, and PR review comment density normalized per line changed.

Which leaves the join, and what you get out of it depends on how your team works.

Session lines carry `cwd`, `gitBranch`, and `timestamp` (see [`reference/data-dictionary.md` § Common fields](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/data-dictionary.md#common-fields) for exact semantics). Put those against commit history on the matching branch in the matching window and you get a candidate commit. A candidate, not an identity: multiple sessions can touch one branch inside one window, and a branch can span more commits than any session accounts for.

But Claude Code also writes `pr-link` lines when a pull request is opened from inside a session, carrying `prNumber`, `prUrl`, and `prRepository`. That isn't a heuristic. It's an exact session-to-PR identity recorded on disk, and from a PR number every Tier 3 signal becomes a direct lookup instead of an inference. (Newly documented in [`reference/data-dictionary.md` § `pr-link`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/data-dictionary.md#pr-link), including the caveat that the line carries almost none of the common envelope.)

That sharpens the process argument rather than undermining it. The exact join link exists, and whether you get it depends on how you work. Open your PRs from inside the session and attribution is free and exact. Open them by hand in a browser tab afterward and you're back to guessing from branch and timestamp. The fallback degrades the same way. A branch that lives a week across five conversations hands the timestamp window more candidates than it can separate. A branch cut for one task and merged soon after usually has exactly one. And `feat:` to `fix:` proximity is only computable if commit messages flag their kind up front, by whatever convention your repo already follows.

Coverage works the same way. The gap I flagged earlier, work that never entered Claude's loop, closes when an issue goes in end-to-end and Claude reads the PR thread it opened, reviewer comments included. It stays open when a teammate resolves half those comments off-session, without Claude seeing the diff prior to merge. Everything here assumes the disciplined version, and that's worth stating rather than implying, because it's the same variable the rest of the section turns on.

So the accuracy of the measurement is a function of process discipline, which sounds like a limitation and isn't. **Where the measurement fails, the failure is itself the finding.** You wanted to know whether the work held up and learned instead that the team's process makes the question unanswerable. Worth knowing, and cheaper to discover. A dashboard that quietly favors attributable work is favoring process hygiene, and the circularity is fine, because process hygiene is a thing you want anyway.

Attribution does fail for legitimate reasons too, from deliberate long-lived feature branches to squash merges that collapse the timeline. And none of this is hypothetical. AgentFluent shipped those three tiers across v0.6, v0.7, and v0.8, and [CodeFluent](https://github.com/frederick-douglas-pearce/codefluent) is landing verification-behavior and config-maturity signals on the same data. Neither has closed the outcomes loop completely, which is the next section.

## Every proxy here is gameable

The lesson from Meta and Amazon applies recursively to everything above. Rank a team on cache-reuse ratio and expect padded cache writes. Rank on rework and expect fewer, larger, riskier commits that dodge revert counting without reducing rework. Rework signals conflate healthy iteration with waste on their own: a PR with six review rounds might be careful craftsmanship or a mess, and git history can't tell you which.

Calibration holds up best, which is a low bar but a real distinction. Padding cache writes is cheap. Faking calibration means faking the difficulty signal too, and difficulty signals cost real tokens and touch real files. Gameable at a price, and the price leaves a trace. Attribution to an individual engineer is a different matter: neither reliable, since the exact path depends on a workflow not everyone follows, nor advisable, since individual ranking is the failure mode that started this post. Read all of it at team and repo level.

And no thresholds. I won't tell you what a good cache-reuse curve looks like or what rework rate should worry you, because a defensible baseline needs a corpus of session data paired with real longitudinal outcomes, and that doesn't exist publicly yet. Anyone who hands you a number today needs to back it up with analysis, not just confident guessing.

## Where this leaves you

If you killed a leaderboard and still owe someone an answer: cost computed correctly, read alongside efficiency, friction, calibration, and rework signals from git, at team and repo level, with no ranking and no threshold pretending to be a verdict. That's not a scoreboard. It's a dashboard someone has to actually read. And if you already fixed your denominator, that was necessary, not sufficient. A cost figure is a fact, but not actionable on its own.

Repo level is also where the data already sits, which makes that unit more practical than it sounds. Sessions are stored one directory per working directory, named from the path the session ran in (see [`reference/session-storage.md`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/session-storage.md)), so every teammate who works a given repo accumulates their sessions in a folder that mirrors it. Aggregating by repo is closer to a directory listing than a join. Check `cleanupPeriodDays` before you rely on it, though: transcripts are deleted on startup once they age past the default 30 days, so a longitudinal view is something you collect while the window is open, not something you reconstruct later.

## The numerator was never the tool's to supply

Back to Amazon reaching for deployment counts. That reads as a genuine reach for value rather than a lazy substitute, and it's close to the best any large organization has ready to hand. It just doesn't resolve to the level the question needs.

That isn't a session-data problem. Many organizations cannot answer "what was this feature worth" at feature granularity for _any_ feature, AI-assisted or not. Product analytics tie revenue to surfaces and funnels, not to commits. Roadmaps rank features by expected value before they're built, and almost nobody scores the estimate against what shipped. The numerator isn't missing from the JSONL. It's missing from many companies.

There's a small piece of evidence for that in my own backlog. CodeFluent has an epic for outcome metrics, deferred to v2.0, sitting behind fluency scoring, config-maturity assessment, verification-behavior detection, and agent trace analytics. Every one of those is harder engineering, and none needs anything the tool can't already read off disk. Outcomes aren't deferred because they're difficult. They're deferred because the data to validate them against isn't on my machine.

Which is the one genuinely optimistic thing here. If an organization did carry feature-level value attribution, even roughly, even just "we thought this was worth X and here's what it returned," session data stops being a pile of effort proxies and becomes the other half of a real ratio. You could ask which working patterns delivered the high-value items fastest, and answer it. The cost-side instrumentation is ready. It's waiting on a numerator most teams never built, for reasons that have nothing to do with AI.

That's the leaderboard worth wanting. Nobody killed it in the spring of 2026, because nobody had built it.

## Sources

The three leaderboard episodes, from primary reporting:

- **Meta ("Claudeonomics"):** [Meta killed its employee AI token dashboard](https://fortune.com/2026/04/09/meta-killed-employee-ai-token-dashboard/) (Fortune)
- **Amazon (KiroRank):** [Amazon drops its internal AI leaderboard for staff working on Kiro](https://finance.yahoo.com/sectors/technology/articles/amazon-drops-internal-ai-leaderboard-161639454.html) (Yahoo Finance) and [Amazon bins an internal AI leaderboard for its Kiro employees](https://www.pcgamer.com/software/ai/amazon-bins-an-internal-ai-leaderboard-for-its-kiro-employees-because-they-were-burning-through-too-many-costly-tokens/) (PC Gamer)
- **Uber ($1,500 cap):** [Uber caps employee AI spending after blowing through budget in four months](https://techcrunch.com/2026/06/02/uber-caps-employee-ai-spending-after-blowing-through-budget-in-four-months/) (TechCrunch) and [Uber caps usage of AI tools like Claude Code to manage costs](https://www.bloomberg.com/news/articles/2026-06-02/uber-caps-usage-of-ai-tools-like-claude-code-to-cut-costs) (Bloomberg)

The cost-side grounding lives in this series: [Part 4 — Token accounting is harder than it looks](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/posts/2026-06-24-token-accounting-is-harder-than-it-looks.md) and [Every lever that moves the bill](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/posts/2026-06-27-every-lever-that-moves-the-bill.md), both resting on [`reference/data-dictionary.md`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/data-dictionary.md).

---

_Drafted with Claude Code (verified against v2.1.152). The ideas, claims, and any errors are mine._
