---
name: jsonl-format-watch
description: Tracks changes to Claude Code's JSONL session data format and dispatches approved candidates to update reference docs, draft posts, or cross-post to sibling projects (AgentFluent, CodeFluent).
---

# jsonl-format-watch

**Status:** Stub. The skill's research and dispatch logic will be ported from AgentFluent's `anthropic-research` subagent + `promote-candidates` skill pattern in a follow-up.

## Purpose

When Claude Code's JSONL format changes — new fields, renames, envelope shifts, behavior changes from bug fixes — this skill is responsible for:

1. **Capturing the change** — appending a candidate to `.claude/specs/research/jsonl-format-watch.md`
2. **Reviewing impact** — flagging which `reference/` docs need updates and whether a post is warranted
3. **Cross-posting when relevant** — pushing a candidate into AgentFluent's or CodeFluent's `anthropic-feature-watch.md` when the change affects their parsing or signals

## What it tracks

In scope:

- Field additions to any existing message type
- Field removals or renames (e.g., `TodoWrite` → Task tools)
- Envelope structure changes (e.g., where `toolUseResult` lives relative to its `tool_result` block)
- New message types or content block types
- Hook input contract changes (e.g., `duration_ms` added to PostToolUse input)
- Bug fixes that change observable session shape

Out of scope (handled by sibling projects' own research):

- Claude Code feature changes that don't touch the JSONL format
- API or SDK changes that don't surface in `~/.claude/projects/` data
- Model behavior changes
- UX/CLI ergonomics

## Routes (planned, post-port)

When the human approves a candidate, the skill chooses one or more dispatch routes:

- `reference-update` — update the affected `reference/` sections, bump their version-verified header
- `post-draft` — create a `posts/YYYY-MM-DD-...md` skeleton with frontmatter + linked reference sections
- `cross-post agentfluent` / `cross-post codefluent` — append a candidate to the sibling project's `anthropic-feature-watch.md`
- `dismiss` — no action

Routes are not mutually exclusive — a single change may warrant a reference update *and* a post draft *and* a cross-post.

## Implementation notes (for the port)

When porting from AgentFluent:

- Reuse the structure of `.claude/skills/promote-candidates/SKILL.md` for the dispatch logic
- Drop the PM / architect subagent routes — they don't apply here
- Replace `relevance-strength` field semantics with `change-type` (already in the queue schema)
- The queue file lives at `.claude/specs/research/jsonl-format-watch.md` (not `anthropic-feature-watch.md`)
- Add a research-pass entry point (similar to AgentFluent's `anthropic-research` subagent) that watches:
  - Claude Code CHANGELOG.md
  - Claude Agent SDK CHANGELOG.md files (TypeScript, Python)
  - Anthropic engineering blog posts and postmortems
  - Observed format changes in real-session fixtures
