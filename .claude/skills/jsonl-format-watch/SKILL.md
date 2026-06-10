---
name: jsonl-format-watch
description: Tracks changes to Claude Code's JSONL session data format and dispatches approved candidates to update reference docs, draft posts, or cross-post to sibling projects (AgentFluent, CodeFluent).
---

# jsonl-format-watch

**Status:** v0 (scoped port of epic #3). Discovery + queue are built and wired;
dispatch is **human-gated and manual** (pm/architect via the Agent tool). The
automated `promote-candidates`-style dispatcher, the `candidate-verifier`, the
cross-post route, and the cross-sibling design (#13) are deferred — see
[Deferred](#deferred-to-later-epic-3-work).

## Purpose

Catch changes to Claude Code's JSONL session format — new fields, new top-level
`type` values, envelope shifts, new on-disk sidecars/directories, behavior
changes from bug fixes — and route them to `reference/` updates, post topics, and
(when relevant) the sibling projects. Changes are tracked whether or not they
have product implications for AgentFluent/CodeFluent.

## The v0 pipeline

```
  ┌─ DISCOVERY (two surfaces, both append F-NNN candidates) ─┐
  │                                                          │
  │  on-disk drift            upstream announcements         │
  │  tooling/format-scan/     .claude/agents/                │
  │  scan.py  (scanner)       jsonl-format-research (scout)  │
  └───────────────────────────┬──────────────────────────────┘
                              ▼
        .claude/specs/research/jsonl-format-watch.md   (the queue)
                              │
                       ❰ HUMAN GATE ❱   ← Decision line per candidate
                              │
            manual dispatch (parent thread, Agent tool):
            pm → drafts issues/PRD · architect → design spot-check
                              │
            reference-update · post-draft · (cross-post: manual)
```

### 1. Discovery — observational (on disk)

Run the local scanner over `~/.claude/projects/`:

```bash
python3 tooling/format-scan/scan.py --baseline tooling/format-scan/baseline-v2.1.150.json
```

It reports observed top-level `type` values, envelope keys (per type),
content-block types, session subdirectory inventory, `tool-results/` file shape,
and observed Claude Code versions, and diffs them against the documented baseline
so the delta is **undocumented drift**. To confirm the `tool-results/`
externalization wrapper specifically: `scan.py --probe-tool-results`.

**Security:** the scanner reads raw sessions but emits **keys / counts / sizes /
dir names only — never field values or message content** (see the security
contract in `scan.py`'s module docstring, and CLAUDE.md "Security posture"). The
`block_secret_reads` hook intentionally allows Bash session reads, so this
discipline lives in the tool, not the hook. Translate scan deltas into `F-NNN`
candidates in the queue (one per coherent change), citing "local scan" as Source.

### 2. Discovery — upstream (announcements)

Invoke the scout subagent for the web-only half:

```
Agent(subagent_type="jsonl-format-research", prompt="Run a format-watch research pass …")
```

It surveys the Claude Code release notes, the Agent SDK (Python + TypeScript)
changelogs, and Anthropic's engineering blog/news, files net-new `F-NNN`
candidates, and **version-dates** existing observational candidates (announced
vs. silent). It never reads sessions. See `.claude/agents/jsonl-format-research.md`.

### 3. Human gate

For each candidate in `.claude/specs/research/jsonl-format-watch.md`, the human
adds a `**Decision (YYYY-MM-DD):**` line — `approve` / `defer — <reason>` /
`dismiss — <reason>` / `cross-post <project> — <reason>` (schema at the top of
the queue file). **Nothing dispatches without a Decision line.** Upstream-sourced
specifics (issue numbers, versions, exact field shapes) should be treated as
hypotheses and **verified** (a `scan.py` probe, or a sanitized fixture) before
they land in committed `reference/` or posts.

### 4. Dispatch (manual, parent thread)

For each `approve`d candidate, the parent thread (not a subagent — subagents
can't invoke subagents) dispatches via the Agent tool:

- **pm** (`.claude/agents/`-equivalent / `Agent(subagent_type="pm", …)`) — turn
  approved candidates into GitHub issues (cluster related candidates rather than
  one issue per `F-NNN`), with acceptance criteria and the affected `reference/`
  sections / post numbers.
- **architect** — optional design spot-check on issues that touch tooling or
  structure before they're worked.
- Record the outcome in a `**Promotion (YYYY-MM-DD):**` block and flip `Status`
  to `promoted` (or `dismissed`).

The downstream work itself is normal repo work: `reference-update` (update the
section, bump its "Verified against" header), `post-draft`, and — manually for
v0 — `cross-post` a candidate into a sibling project's research queue.

## What it tracks

In scope: field additions/removals/renames on any message type; envelope
structure changes; new top-level `type` or content-block types; new on-disk
sidecars/directories (e.g. `tool-results/`, per-subagent `meta.json`); hook
input/response contract changes; bug fixes that change observable session shape.

Out of scope (sibling projects' own research): Claude Code feature/UX/CLI changes
that leave no JSONL trace; API/SDK changes that don't surface in
`~/.claude/projects/`; model behavior changes.

## Deferred to later epic-#3 work

- **Automated dispatch** — porting AgentFluent's `promote-candidates` skill so
  approved candidates dispatch without manual Agent calls. v0 dispatch is manual.
- **`candidate-verifier`** — an automated premise/dedup grounding pass between
  scout and human. v0 relies on the human + targeted scanner probes.
- **Cross-post route** — automated push into AgentFluent's / CodeFluent's queues.
  Blocked on the cross-sibling integration design (#13). v0 cross-posts manually.
- **Scheduling** — a cron/`/loop` cadence for the discovery passes. v0 is
  on-demand.

## Key files

| File | Role |
|---|---|
| `tooling/format-scan/scan.py` | observational scanner (on-disk drift) |
| `tooling/format-scan/baseline-v2.1.150.json` | documented-taxonomy baseline for the diff |
| `.claude/agents/jsonl-format-research.md` | upstream scout subagent |
| `.claude/specs/research/jsonl-format-watch.md` | the candidate queue + schema |
