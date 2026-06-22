# Session-data blog series — outline (Parts 1-7, plus Part 8 coda)

**Status:** Drafted 2026-06-04. Source of truth for the spine of the session-data series. Parts 1 and 2 are recorded post-hoc from what shipped; Parts 3-7 were produced by the marketer agent from a parent-supplied shortlist (sharpened titles, scope, audience hooks, and bridges).

**Relation to other docs:**

- Supersedes the "W1 — first foundational post" scope in [`.claude/specs/roadmap-v0.md`](roadmap-v0.md) for series planning purposes. The roadmap remains the source of truth for the broader work items (sanitizer, Pages sync, format-watch port).
- Adjacent backlog post — "To subagent or not, how to decide" — is tracked at issue #64 with an unblock condition (needs data anchor, not docs).
- Audience for all posts leans Claude Code user. Agent SDK targeting is intentionally deferred until Fred has hands-on SDK session data on disk (~2026-06-15+).

---

## Part 1 — Anatomy of a Claude Code session

> **Status:** Shipped 2026-05-26. Issue #6. Verified against Claude Code v2.1.150.

**Scope.** The foundational post. Where session JSONL files live (`~/.claude/projects/`), why most people have never opened one, and what understanding their contents changes about how you think about Claude Code's features — `--continue`, `/rewind`, where token costs really come from, why session data is a first-class artifact rather than a byproduct. Establishes the file-location convention, the high-level message-type taxonomy, and the post→reference linkage pattern the rest of the series follows.

**Audience hook.** Most readers have used Claude Code without ever opening one of these files. The hook is the discovery itself — there's a detailed local record of everything, sitting on the reader's disk right now.

**Bridge.** Establishes that there is structure worth understanding; Part 2 walks the structure line by line.

---

## Part 2 — Reading a Claude Code session, line by line

> **Status:** Shipped 2026-06-04. Issue #59. Verified against Claude Code v2.1.150.

**Scope.** The structural tour. Every type of line in a session JSONL, the snake_case/camelCase split that reveals two layers (Anthropic API content wrapped in Claude Code's harness bookkeeping), `assistant` line internals (content blocks, `message.usage`, `stop_reason`), `user` line internals and why tool results live inside user messages rather than getting their own type, the `toolUseResult` envelope, the "skipped" types (`file-history-snapshot` as the rewind backbone, `system`, `permission-mode`, `ai-title`, `last-prompt`, `attachment`, streaming/telemetry types). Closes with three `jq` snippets readers can run against their own session files.

**Audience hook.** The visual quirk — `snake_case` and `camelCase` fields side by side in the same line — is the entry point. Once the reader sees that as a tell rather than inconsistency, the format stops looking messy and starts providing architectural insight.

**Bridge.** Part 2's third `jq` snippet surfaces a field called `agentId` and explicitly promises that value is "the literal handle that takes you to the subagent's full trace file at `~/.claude/projects/<slug>/<session-uuid>/subagents/agent-<agent_id>.jsonl` — which is where Part 3 picks up." Part 3 must honor that promise.

---

## Post 3 — Inside the subagent trace file

**Scope.** Part 2 closed with a single `jq` snippet whose output carries a field called `agentId` — and promised that value is "the literal handle that takes you to the subagent's full trace file." This post cashes that promise. It opens the file at `~/.claude/projects/<slug>/<session-uuid>/subagents/agent-<agentId>.jsonl`, reads it against what the parent already reported, and names the structural differences: `isSidechain: true` as the canonical discriminator, why `sessionId` is NOT shared between parent and subagent (each subagent invocation gets its own — the parent's session UUID appears only as a directory name), the attribution field family (`attributionAgent`, `promptId`, `sourceToolAssistantUUID`) and its strict per-line-type presence pattern, and the single most important thing to understand about this format: the parent's `toolUseResult` envelope is a rollup summary; the trace file is the actual evidence. The post also names the restricted type set in Claude Code traces (no `file-history-snapshot`, no `system`, no `permission-mode` inside subagent files) and flags the open verification gap for Agent SDK nested invocations. Token double-counting is introduced briefly here as a necessary gotcha but deferred to Post 4 for the full treatment. Closes with a `jq` snippet that opens one subagent file and counts its turns.

The nesting caveat is worth including because Claude Code restricts subagents from invoking further subagents while the Agent SDK may not — a parser that assumes flat layout because it's never seen nested invocations is fragile. Name the gap without overstating it.

**Audience hook.** Part 2 ended by handing the reader a string that looked like a UUID in a terminal output — but didn't explain what it was a key to. That loose end is the hook: there's a separate file, there's a lot in it the parent never shows you, and knowing the difference matters for anything that tries to measure what a subagent actually did versus what the parent claims it did.

**Bridge.** The trace file shows per-step token usage across every model turn the subagent took. The parent rollup shows one cumulative number. Neither alone is enough to answer the question "what did this session actually cost?" — and that question is messier than it looks. Part 4 is the accounting post.

---

## Post 4 — Token accounting is harder than it looks

**Scope.** The data is all there. The arithmetic is where it gets subtle. This post works through the four token kinds (`input_tokens`, `output_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens`) and why treating them as interchangeable produces wrong dollar figures. Then it introduces `service_tier` and per-model price variance as the second and third confounders. The main event is the double-count hazard: the subagent's tokens appear on each interior `assistant` line inside the trace file AND as a rolled-up `toolUseResult.usage` on the parent's user line — sum both and you've counted the same work twice. The post lays out the three aggregation patterns from `subagent-traces.md` in prose (cheap total from parent only, full breakdown with trace files, just the subagent's cost) and names which to use for which question. The cache efficiency angle belongs here and strengthens the post: `cache_read_input_tokens` vs. `cache_creation_input_tokens` ratios are a direct read from the JSONL and tell you whether long sessions are amortizing their context cost. Include it — it's concrete, it's grounded in fields already introduced in Part 2, and it adds a useful frame beyond "here's why your dollar figure is wrong."

Part 1 introduced the "naive summing produces wrong dollar figures" caveat briefly. This post is where the caveat gets a complete treatment. That's the right sequencing: Part 1 named the problem, Post 4 solves it.

**Audience hook.** Most people who've built any kind of session cost tracker have made at least one of these mistakes. The double-count trap in particular is subtle enough that it can persist undetected — the inflated totals don't look obviously wrong. Opening with "here's a number you've probably computed wrong" lands with practitioners who've actually tried to do this.

**Bridge.** Once you understand what a session costs and where the tokens actually went, the natural next question is: what were all those tool calls doing? Token accounting is the "how much" question; tool-use analysis is the "doing what" question. Part 5 is the full tool-use walkthrough.

---

## Post 5 — The tool call, completely

**Scope.** Posts 1 and 2 introduced `tool_use` / `tool_result` pairing and the `toolUseResult` envelope. This post gives it a complete, standalone treatment grounded in `reference/tool-invocation.md`. The structural tour: the two-line cycle and why it's the smallest semantically complete unit of agent activity in the format; `tool_use_id` as the pairing key and what a missing pair means (almost always an interrupted session); `stop_reason: "tool_use"` as the forward-looking signal; the two shapes of `message.content` on `user` lines. Then the per-tool `toolUseResult` breakdown — not every tool, but a representative cross-section showing the range: `Read` (minimal or absent envelope), `Bash` (most diagnostic-rich: `code`, `interrupted`, `stderr`), `Edit` (carries the diff in `structuredPatch`), `Agent` (covered in Post 3 but with a different lens here: the `prompt` echo and `toolStats` for characterizing what the subagent did without opening the trace file). The post closes with the parallel tool call pattern: one `assistant` line, multiple `tool_use` blocks, and why wall-clock duration analysis requires distinguishing serial from parallel turns. The `jq` for both the parent histogram and the subagent rollup comparison (already in `tool-invocation.md`) gets narrative treatment.

The `is_error` vs. partial-success nuance from the error patterns section belongs here — it's a concrete "parsers that throw away output on error lose information" point that fits the format-archaeology voice.

**Audience hook.** Part 2 showed that `toolUseResult` is "where most of the high-information signal lives." That's the promise. This post is the fulfillment: here is every signal, what it means, and which one to reach for depending on the question.

**Bridge.** Session data records what Claude Code did. But hooks — PreToolUse, PostToolUse, UserPromptSubmit — fire while Claude Code is working. The question is whether those hook events leave any trace in the session JSONL. Part 6 goes looking.

---

## Post 6 — What hooks leave behind (and what they don't)

> **Note:** The scope of this post is provisional. Before drafting begins, a 30-minute recon session against real session files should verify: (1) whether hook-denied tool calls produce any distinct line type or `is_error` signature in the JSONL; (2) whether hook output surfaces as a `system` line, a `user` message, or not at all; (3) whether `permission-mode` transitions correlated with hook denials are reliably captured; (4) whether `hook_progress` lines appear under any reproducible condition. If the recon answer to all four is "thinner than expected," the post still ships — naming the gap is on-voice — but the framing shifts from "here's what you'll find" to "here's what I went looking for." The parent should decide before drafting whether to run the recon or to write the gap-naming version directly.

**Scope.** The hooks documentation describes an outbound JSON contract — Claude Code sends hook events to scripts via stdin. But hooks fire outside the model loop: they're not model turns, not tool calls, not user messages. This post asks what (if anything) a hook leaves behind in the session JSONL. The data-dictionary already documents `hook_progress` as a streaming event type that "may still be emitted under specific conditions" but wasn't observed in v2.1.150 sample sessions. `permission-mode` lines record permission transitions but don't name which hook (if any) caused them. Denied tool calls presumably produce some representation — the question is whether `is_error: true` on a `tool_result`, a `system` event, or nothing at all is the format's signature for a hook block. The post works through each hook event type from the data-dictionary's hook section against what's observable post-hoc in JSONL. Some signals are likely present (`permission-mode` transitions), some are conditional (`hook_progress`), some may be absent entirely (hook scripts' stdout). The post names each finding honestly, including the gaps.

The honest-gap framing is the voice move here. The format-archaeology series has been "here's what's in the file." This post is "here's what I went looking for and what I found" — and if the recon turns up genuine blanks, that's the story: certain things hooks do don't land in JSONL at all, which matters for anyone building an audit tool.

**Audience hook.** Anyone who's written a hook and wondered whether the session transcript reflects what happened will recognize the question. The answer being "partly, and here's which parts" is more useful than silence.

**Bridge.** Parts 1 through 6 have treated sessions as individual artifacts — one file, one session, one conversation. But Claude Code users don't have one session. They have hundreds, across projects, across months. The question that the series has been building toward isn't "what's in a session?" It's "what can you learn when you have all of them?" Part 7 is the answer.

---

## Post 7 (capstone) — The conversation is the unit

**Scope.** The capstone shifts register from reference to opinion. Parts 1–6 documented what's in a session file. This post argues for a different unit of analysis: the conversation, not the session. The structural grounding is real — `parentUuid` chains, `isSidechain` sidechains, the rewind checkpoints, `/branch` and `/fork-session` producing sibling sessions with shared parent-session history — and Parts 2 and 3 have laid the vocabulary. But the argument is about measurement: per-session metrics (token count, tool call count, duration) mislead if a single user intent spans multiple sessions via `--continue`. The CodeFluent framing enters here as the applied lens: fluency isn't one session, it's a pattern across sessions — how a person uses the tool, how their interaction patterns shift over time, which behaviors they've internalized. That only becomes visible when you treat the `parentUuid` graph across multiple files as a single artifact.

The post also names the reverse limitation: not every continuation is meaningful depth. A user who runs `--continue` reflexively without a clear thread isn't exhibiting a long conversation, just a lazy session-start habit. The data can show that too.

The capstone closes the series without closing the format — the reference docs will keep updating, new type values will show up in readers' own sessions, the Agent SDK verification gap will eventually close. The closer is an invitation to the format-archaeology posture rather than a summary of what was covered.

**Audience hook.** There's a specific failure mode this post names: tools (and people) that measure per-session activity and make performance claims from it. If a session ends because the user hit `Ctrl+C` and resumed the next morning, the "session" is a meaningless unit for most questions. Readers who've built session analytics and suspected this problem will find the explicit naming useful.

**Bridge.** No next-post bridge needed — this is the capstone. The closer is an invitation for readers to apply the conversational frame to their own sessions and surface what they find.

---

## Post 8 (coda) — Same format, different driver: the Agent SDK vs. Claude Code sessions

> **Status:** Planned 2026-06-22. Extends the spine, does not replace it. Blocked on the foundation reference work (this repo's [#132](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/132)) landing first, so the post can cite the new reference rows and the synthetic SDK fixture rather than get ahead of them.

**Why this is a coda, not a renumber.** The original outline deferred Agent SDK targeting "until Fred has hands-on SDK session data (~2026-06-15+)," and Parts 3 and 7 both leave an explicit "Agent SDK verification gap" thread dangling (Part 7's closer: "the Agent SDK verification gap will eventually close"). As of 2026-06-22 that condition is met. AgentFluent's empirical probe (its #518/#522) put real SDK bytes on disk. This post picks up exactly that dangling thread. It is purely additive: Parts 5/6/7 are untouched, and the capstone's "closes the series without closing the format" framing is what makes room for a coda.

**Scope.** The headline is reassuring and the point of the post: **the Agent SDK writes the same JSONL format to the same place** (`~/.claude/projects/<cwd-slug>/<id>.jsonl`), with the same subagent-trace and large-output spill layout the series already documented. So the post is a similarities-and-differences tour, not a new format walkthrough. Similarities: co-located sessions, identical `user`/`assistant` schema, the same `<id>/subagents/agent-<agentId>.jsonl` linkage and `<id>/tool-results/` spill (Parts 2/3/5 already cover these). Differences, all small: `entrypoint == "sdk-py"` as the reliable intrinsic discriminator between an SDK session and an interactive one (with `sdk-ts` inferred for the TS SDK), `promptSource: "sdk"` as a corroborating marker on prompt lines, and `resolvedModel` on the `toolUseResult` rollup (the concrete child model). The honest-gap move (on-voice for the series): one delegation level is verified to match Claude Code; deeper SDK nesting remains the open verification gap Part 3 named, and the post says so rather than overclaiming. Grounded in the new `reference/` rows from #132 and a synthetic SDK fixture.

**Audience hook.** This is the first post in the series that speaks to the Agent SDK reader directly (now justified by hands-on data). The hook is the relief: if you've learned to read Claude Code sessions, you already know how to read SDK sessions. Here is the short list of what changes and the one field (`entrypoint`) that tells the two apart.

**Bridge.** Coda. No next-post bridge. The closer reinforces the capstone's posture: the format keeps evolving (SDK drift is tracked in this repo's [#133](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/133)), and the format-archaeology habit travels across drivers.

---

## Cross-post writing rules

- Every reference to a file in the repo (`reference/subagent-traces.md`, `fixtures/synthetic/anatomy-subagent-trace.jsonl`, etc.) must use a full GitHub URL — posts deploy to a separate Pages site and relative paths break. Established pattern in Parts 1 and 2; maintain throughout.
- Audience leans Claude Code user. Agent SDK is referenced only as a verification gap or deferred-scope flag — not targeted as primary audience until Fred has hands-on SDK session data (~2026-06-15+). At write time, individual posts may want to drop or rephrase SDK hedges if they imply an SDK-aware reader.
- Cadence target: ~1 post every 1.5 weeks. Bridges should set up the next post without time commitments.

---

## How to use this doc

- The pm agent reads this and produces one GitHub issue per unshipped post (Parts 3-7, 5 total), with full acceptance criteria expanded from the scope/hook/bridge per post. Issue #59 (Part 2) is the canonical template.
- The outline stays as the narrative source — don't fold its content into individual issues' descriptions, link from the issues back to this file instead.
- Updates to scope go in this file first, then propagate to the relevant issue.
- Parts 1 and 2 are recorded for completeness; their entries are descriptive of what shipped, not planning input.
