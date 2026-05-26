# JSONL Format Watch

**Purpose:** Queue of observed or announced changes to Claude Code's JSONL session format. Maintained by the `jsonl-format-watch` skill and a human review gate. Drives updates to `reference/` docs, post topics, and (when applicable) cross-posted candidates into sibling projects' research queues.

**Pipeline:**
1. A research pass (manual or scheduled) appends candidates with `Status: queued`.
2. The human reviews each candidate and adds a `Decision` line: `approve`, `defer`, `dismiss`, or `cross-post <project>`.
3. The `jsonl-format-watch` skill dispatches approved candidates — updates reference docs, drafts a post, or cross-posts to sibling projects — and records the outcome in a Promotion block. Status flips to `promoted` or `dismissed`.

The dispatch step is a skill (not a subagent) because subagents cannot invoke other subagents in Claude Code; the cross-post route may need to invoke a research or writing subagent later.

See `.claude/skills/jsonl-format-watch/SKILL.md` for the implementation (currently a stub).

---

## Schema

### Reviewed Sources entry

| Field | Required | Notes |
|---|---|---|
| Date | yes | YYYY-MM-DD when reviewed |
| URL | yes | Full URL |
| Title | yes | Article / changelog / release-note title |
| One-line takeaway | yes | What the source is about |
| Tag | yes | `candidate-added` / `not-actionable` / `already-covered` / `rejected-by-decision` |
| Candidate ref | conditional | If tag=candidate-added, the F-NNN id |

### Candidate entry

Each candidate is a block under `## Candidates Queue` that accumulates annotations as it moves through the pipeline. Scout fields are written once and never edited; later annotations and the human append blocks below.

**Scout fields** (append-only):

| Field | Required | Notes |
|---|---|---|
| ID | yes | `F-NNN`, monotonic |
| Title | yes | Short — what changed |
| Source | yes | URL + date (changelog entry, release notes, observed-in-fixture) |
| Added | yes | YYYY-MM-DD |
| Change type | yes | `field-added` / `field-removed` / `field-renamed` / `envelope-change` / `behavior-change` / `bug-fix` |
| Affected message types | yes | e.g., `assistant`, `user/tool_result`, `subagent-trace`, hook input |
| Summary | yes | 2-3 sentences describing the change and where it's observable |
| Reference impact | yes | Which `reference/` sections need updating |
| Post potential | yes | `foundation` / `format-update` / `security` / `tooling` / `none` |
| Sibling-project impact | optional | If the change affects AgentFluent's or CodeFluent's parsing or signals |

**Decision line** (human, after scout fields — this is the human gate):

```
**Decision (YYYY-MM-DD):** <decision>
```

Where `<decision>` is one of:
- `approve` — update reference + queue post if applicable
- `defer — <reason>` — leave for later (no action; Status unchanged)
- `dismiss — <reason>` — drop the candidate (Status → `dismissed`)
- `cross-post <project> — <reason>` — also file a candidate in the sibling project's research queue

**Promotion block** (`jsonl-format-watch` skill, after Decision):

```
**Promotion (YYYY-MM-DD):** <outcome>
```

Examples:
- `approve → updated reference/data-dictionary.md "user message" section; queued post draft posts/2026-XX-XX-toolUseResult-renames.md`
- `cross-post agentfluent → added candidate to agentfluent .claude/specs/research/anthropic-feature-watch.md`
- `dismiss → already covered in reference/format-version-history.md`

**Status line** (always last):

| Status | Set by | Meaning |
|---|---|---|
| `queued` | scout | initial; awaiting human gate |
| `promoted` | `jsonl-format-watch` skill | downstream action complete |
| `dismissed` | `jsonl-format-watch` skill | human chose to drop |

---

## Reviewed Sources

<!-- Append newest entries at the top of this section -->

| Date | URL | Title | Takeaway | Tag | Candidate ref |
|---|---|---|---|---|---|

---

## Candidates Queue

<!-- Append new candidates at the bottom. Status updates happen in place. -->

_No candidates yet — repo scaffolded 2026-05-26._
