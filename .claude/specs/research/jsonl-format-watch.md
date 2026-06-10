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
| 2026-06-09 | https://github.com/anthropics/claude-code/issues/16944 | [DOCS] Document subagent auto-compaction behavior (compactMetadata and preTokens) | Closed issue confirming `system` line with `subtype: "compact_boundary"` carrying `compactMetadata: {trigger, preTokens}` and `isCompactSummary` on subsequent injected summary; observed in v2.1.1+. Corroborates F-005 with specific `compact_boundary` subtype name. | already-covered | F-005 |
| 2026-06-09 | https://github.com/anthropics/claude-code/issues/23948 | Bug: `<persisted-output>` tool results written to session JSONL at full size | Closed duplicate; confirms `tool-results/<tool-use-id>.txt` sidecar path and `<persisted-output>` text wrapper in `tool_result.content`. Reported v2.1.17; indicates feature predates v2.1.150. F-001 pointer field is plain-text path in content, not a JSON key — needs scanner confirmation. | already-covered | F-001 |
| 2026-06-09 | https://raw.githubusercontent.com/anthropics/claude-agent-sdk-typescript/main/CHANGELOG.md | Claude Agent SDK TypeScript CHANGELOG | SDK TS v0.2.162 adds `stop_reason: 'refusal'` + `stop_details` on assistant; v0.2.152 adds `MessageDisplay` hook event; v0.2.108 adds `system/status: 'requesting'` message; v0.2.105 adds `system/memory_recall` and `memory_paths` on `system/init`. SDK-only changes; Claude Code parity TBD. | candidate-added | F-015 |
| 2026-06-09 | https://raw.githubusercontent.com/anthropics/claude-agent-sdk-python/main/CHANGELOG.md | Claude Agent SDK Python CHANGELOG | v0.1.74 adds `HookEventMessage` type; v0.1.65 adds `ServerToolUseBlock` + `AdvisorToolResultBlock`; v0.1.64 introduces SessionStore with JSONL append semantics and `session_store_flush` option. SDK-specific storage protocol, not directly Claude Code JSONL. | not-actionable | — |
| 2026-06-09 | https://raw.githubusercontent.com/anthropics/claude-code/refs/heads/main/CHANGELOG.md | Claude Code CHANGELOG (v2.1.150–v2.1.170) | v2.1.170: fixed sessions not saving transcripts in some VS Code/env contexts (behavior change, not format). v2.1.169: added `post-session` hook lifecycle event (new hook event type in outbound schema). v2.1.163: `Stop`/`SubagentStop` can return `hookSpecificOutput.additionalContext` (new hook response field). v2.1.154: dynamic workflows / background agents introduced (explains `pendingBackgroundAgentCount` F-009 and `mode`/`agent-name` types F-007). No explicit announcement of `tool-results/`, `meta.json`, or hook-execution JSONL fields — those appear to be silent format additions. | candidate-added / already-covered | F-013, F-014; F-007, F-009 version-dated |
| 2026-06-09 | https://www.anthropic.com/news | Anthropic News (May–Jun 2026) | No Claude Code format announcements in last 30 days. Product news (Claude Fable 5, Series H, S-1 filing) not format-relevant. | not-actionable | — |
| 2026-06-09 | https://www.anthropic.com/engineering | Anthropic Engineering Blog | No engineering posts in last 30 days (most recent is Apr 23, 2026 quality report). Not actionable for format watch. | not-actionable | — |
| 2026-06-09 | `tooling/format-scan/scan.py` (local observational scan) | Scan of `~/.claude/projects/` against the v2.1.150 baseline | 836 files / 100,623 lines, data spanning v2.1.4–**v2.1.168**. Surfaced the `tool-results/` sidecar dir, per-subagent `meta.json` sidecars, and ~40 undocumented top-level keys / 4 undocumented top-level types. Keys/counts only — no content read. | candidate-added | F-001…F-012 |

---

## Candidates Queue

<!-- Append new candidates at the bottom. Status updates happen in place. -->

> **Batch note (2026-06-09):** F-001 through F-012 are **observational** candidates from the local scanner — they describe what is on disk, dated only to a version *range* (v2.1.4–v2.1.168). The `jsonl-format-research` scout pass is expected to pin several of these to a specific introducing version and flag any that were announced vs. silent. All field-presence claims are structural (key names + which `type` carries them); no field *values* were read.

### F-001: `tool-results/` — large tool-output externalization

- **Source:** local scan, 2026-06-09 (observed in 40 session dirs)
- **Added:** 2026-06-09
- **Change type:** `envelope-change`
- **Affected message types:** `user`/`tool_result` (the referencing line); new on-disk sidecar directory
- **Summary:** A new directory `~/.claude/projects/<slug>/<session-uuid>/tool-results/` sits as a sibling to `subagents/`. It holds one file per oversized tool result, named by the producing tool call (`toolu_*.txt`, `mcp-github-{list,search,get}_*.txt|json`). All 89 observed files are >20 KB (min 20,152 B, median ~64 KB, max ~840 KB), strongly implying a ~20 KB spill threshold: large tool output is written here instead of being inlined in the `tool_result` block. **Upstream evidence (2026-06-09):** GitHub issue #23948 (filed v2.1.17, closed duplicate) confirms the sidecar path `tool-results/<tool-use-id>.txt` and shows the in-JSONL reference is plain text in `tool_result.content` wrapped in `<persisted-output>` tags with a "Preview (first 2KB)" message — NOT a dedicated JSON pointer field. The feature predates v2.1.150 (present at least since v2.1.17); introduction version unknown. The CHANGELOG shows no explicit announcement for this feature across v2.1.150–v2.1.170, indicating it was a silent addition at some earlier version. Scanner confirmation still needed for the exact `<persisted-output>` text shape in the JSONL.
- **Reference impact:** `reference/subagent-traces.md` (File layout diagram shows only `subagents/`); `reference/data-dictionary.md` (File location); likely a new `reference/tool-results.md` or a tool-invocation section.
- **Post potential:** `format-update` / `tooling` — primary home is **Part 5 ("The tool call, completely," #67)**; also forces a fix to the **Part 3** directory-layout diagram (#65).
- **Sibling-project impact:** AgentFluent/CodeFluent that read `tool_result.content` for large outputs will get a truncated/pointer payload unless they also read the sidecar.
- **Status:** queued

### F-002: per-subagent `meta.json` sidecar

- **Source:** local scan, 2026-06-09 (561 files under `subagents/`)
- **Added:** 2026-06-09
- **Change type:** `envelope-change`
- **Affected message types:** subagent traces (new sidecar file alongside `agent-<id>.jsonl`)
- **Summary:** Each subagent invocation now also writes a tiny `agent-<id>.meta.json` (20–249 bytes) next to its `.jsonl` trace. Top-level keys observed: `agentType` (all 561), `description` (544), `toolUseId` (254), `worktreePath` (10). It is a lightweight manifest/index card for the subagent run — letting tooling enumerate and route subagents without parsing the full trace. Note the casing split: `meta.json` uses `toolUseId` while session lines use `toolUseID` (see F-010). **Upstream evidence (2026-06-09):** No explicit announcement found in the CHANGELOG for v2.1.150–v2.1.170. Silent addition; introduction version unknown.
- **Reference impact:** `reference/subagent-traces.md` (File layout — currently shows `subagents/` containing only `agent-<id>.jsonl`).
- **Post potential:** `foundation` — directly relevant to **Part 3 (#65)**; the subagents/ layout now has two files per invocation.
- **Sibling-project impact:** AgentFluent can list/characterize subagents cheaply from `meta.json` instead of opening every trace.
- **Status:** queued

### F-003: hook-execution records on `system` lines

- **Source:** local scan, 2026-06-09
- **Added:** 2026-06-09
- **Change type:** `field-added`
- **Affected message types:** `system`
- **Summary:** `system` lines now carry hook-execution bookkeeping: `hookCount`, `hookInfos`, `hookErrors`, `preventedContinuation`, `stopReason`, `hasOutput` (each on ~986 lines). This means hook activity **does** leave a JSONL trace — recorded as `system` events — which is the core question Part 6 was scoped to answer. Field *values* not read; presence + carrier-type only. **Upstream evidence (2026-06-09):** No explicit announcement in CHANGELOG v2.1.150–v2.1.170. The v2.1.163 entry notes `Stop`/`SubagentStop` can return `hookSpecificOutput.additionalContext`, suggesting active hook output evolution, but the `system`-line recording of hook metadata appears to be a silent addition. Introduction version unknown.
- **Reference impact:** `reference/data-dictionary.md` (`system` type; Hook event fields section).
- **Post potential:** `format-update` — this is the empirical anchor for **Part 6 ("What hooks leave behind," #68)**; reshapes that post from "here's what I went looking for" toward "here's what's there."
- **Sibling-project impact:** AgentFluent hook/quality diagnostics can read hook outcomes from `system` lines.
- **Status:** queued

### F-004: API retry metadata on `system` lines

- **Source:** local scan, 2026-06-09
- **Added:** 2026-06-09
- **Change type:** `field-added`
- **Affected message types:** `system`
- **Summary:** `system` lines carry `retryInMs`, `retryAttempt`, `maxRetries` (~22 lines) — records of API-level retries (backoff). Distinct from the *tool-call* retry pairing analyzed in the shipped retry aside (#53); this is transport/model retry, recorded by the harness. **Upstream evidence (2026-06-09):** No explicit announcement in CHANGELOG v2.1.150–v2.1.170. Silent addition; introduction version unknown.
- **Reference impact:** `reference/data-dictionary.md` (`system` type).
- **Post potential:** `analysis` — feeds the retry/failure-rate line (#54) with a second, harness-level retry signal.
- **Sibling-project impact:** AgentFluent reliability signals.
- **Status:** queued

### F-005: compaction records (`system` + `user`)

- **Source:** local scan, 2026-06-09
- **Added:** 2026-06-09
- **Change type:** `field-added`
- **Affected message types:** `system` (`compactMetadata`, `logicalParentUuid`); `user` (`isCompactSummary`, `isVisibleInTranscriptOnly`, `origin`, `promptSource`)
- **Summary:** Context-compaction now leaves a trace: a `system` line carries `compactMetadata` and a `logicalParentUuid` (a parent pointer distinct from `parentUuid` — relevant to thread reconstruction), and the injected summary appears as a `user` line flagged `isCompactSummary` / `isVisibleInTranscriptOnly`, with `origin` / `promptSource` distinguishing synthesized vs. typed prompts (24 lines each). **Upstream evidence (2026-06-09):** GitHub issue #16944 (closed) confirms the exact shape: `system` line with `subtype: "compact_boundary"` (not just `type: "system"`) carrying `compactMetadata: {trigger: "auto"|"manual", preTokens: <number>}`. `isCompactSummary: true` on injected summary user line confirmed. Observed in v2.1.1 per the issue; predates v2.1.150. No announcement in CHANGELOG v2.1.150–v2.1.170; silent/established feature. Scanner should look for `subtype: "compact_boundary"` specifically to confirm `logicalParentUuid` presence on that line vs. adjacent lines.
- **Reference impact:** `reference/data-dictionary.md` (`system`, `user`, Common fields — `logicalParentUuid`).
- **Post potential:** `foundation` — material for the **Part 7 capstone ("The conversation is the unit," #69)**: `logicalParentUuid` and compaction summaries are exactly the cross-session/thread-continuity machinery that post argues about.
- **Sibling-project impact:** Anything reconstructing conversation threads must handle `logicalParentUuid` and skip/account for compaction-summary user lines.
- **Status:** queued

### F-006: `attributionSkill` on `assistant` (sidechain) lines

- **Source:** local scan, 2026-06-09 (6,680 lines)
- **Added:** 2026-06-09
- **Change type:** `field-added`
- **Affected message types:** `assistant` (subagent traces)
- **Summary:** A skill-attribution field `attributionSkill` appears on `assistant` lines, parallel to the documented `attributionAgent`/`attributionMcp*` family. Indicates the turn ran under an invoked skill. Extends the attribution family in `subagent-traces.md`. **Upstream evidence (2026-06-09):** CHANGELOG v2.1.157 notes plugins in `.claude/skills` directories are automatically loaded; v2.1.154 introduces dynamic workflows. The `attributionSkill` field was not explicitly announced but is consistent with skill/plugin infrastructure growth across v2.1.154–v2.1.157. Introduction version unknown; likely coincides with skill/plugin expansion.
- **Reference impact:** `reference/subagent-traces.md` (Attribution fields table).
- **Post potential:** `foundation` — Part 3 adjacent (attribution family).
- **Sibling-project impact:** AgentFluent can attribute work to skills, not just agent types.
- **Status:** queued

### F-007: new top-level `type` values — `mode`, `agent-name`

- **Source:** local scan, 2026-06-09 (`mode` 1,121 lines; `agent-name` 401 lines)
- **Added:** 2026-06-09
- **Change type:** `envelope-change` (new top-level type values)
- **Affected message types:** new types `mode` (carries `mode`) and `agent-name` (carries `agentName`)
- **Summary:** Two undocumented top-level `type` values: `mode` and `agent-name`. Purpose inferred from carried keys (a mode marker; an agent-name record) but not confirmed. Note: `custom-title` and `pr-link` also appeared and are **already tracked in #56** — fold those into that issue, not this candidate. **Upstream evidence (2026-06-09):** CHANGELOG v2.1.154 introduces dynamic workflows / multi-agent orchestration ("Claude orchestrates tens to hundreds of agents"); v2.1.162 adds `claude agents --json` with `waitingFor` field. The `mode` type likely records session mode state (e.g., auto mode, ultracode mode introduced v2.1.154) and `agent-name` likely records agent naming in the multi-agent system. Both are plausibly introduced around v2.1.154 with the dynamic-workflows feature, but not explicitly announced in the CHANGELOG.
- **Reference impact:** `reference/data-dictionary.md` (Skipped types / observed top-level types); coordinate with #56.
- **Post potential:** `foundation` — the "discover top-level type values you haven't catalogued" thread from Part 2.
- **Sibling-project impact:** parsers branching on `type` should tolerate these.
- **Status:** queued

### F-008: API-error records on `assistant` lines

- **Source:** local scan, 2026-06-09
- **Added:** 2026-06-09
- **Change type:** `field-added`
- **Affected message types:** `assistant` (`isApiErrorMessage`, `apiError`, `apiErrorStatus`); `system` (`cause`)
- **Summary:** `assistant` lines can be flagged `isApiErrorMessage` with `apiError` / `apiErrorStatus` detail (5–81 lines); a related `cause` appears on `system`. Records API failures inline in the transcript — relevant to anyone computing success rates or filtering "real" model turns from error turns. **Upstream evidence (2026-06-09):** CHANGELOG v2.1.166 mentions "Claude retries once on fallback model for unexpected non-retryable API errors" suggesting active API-error handling development. TypeScript SDK v0.2.162 adds `stop_reason: 'refusal'` + `stop_details` on assistant (different from `isApiErrorMessage` but same surface area). No explicit announcement for `isApiErrorMessage` in CHANGELOG v2.1.150–v2.1.170; silent addition.
- **Reference impact:** `reference/data-dictionary.md` (`assistant` type; error handling notes).
- **Post potential:** `tooling` / `analysis` — pairs with the retry/failure line.
- **Sibling-project impact:** AgentFluent must exclude API-error assistant lines from token/turn metrics.
- **Status:** queued

### F-009: background-agent counter on `system` lines

- **Source:** local scan, 2026-06-09 (28 lines)
- **Added:** 2026-06-09
- **Change type:** `field-added`
- **Affected message types:** `system`
- **Summary:** `pendingBackgroundAgentCount` on `system` lines points to background/async agent execution leaving a JSONL signal. Low volume; purpose needs confirmation. Likely related to the `meta.json` `worktreePath` observation (F-002) — background agents in worktrees. **Upstream evidence (2026-06-09):** CHANGELOG v2.1.154 explicitly introduces dynamic workflows and background agents: "Dynamic workflows introduced: Claude orchestrates tens to hundreds of agents" and `claude agents` with background shell session support (`! <command>`). v2.1.169 mentions "background agents ignoring project-level environment settings" (fixed). The `pendingBackgroundAgentCount` field on `system` lines is very likely introduced with or shortly after v2.1.154. Introduction version estimated ~v2.1.154.
- **Reference impact:** `reference/data-dictionary.md` (`system` type).
- **Post potential:** `none`/`format-update` (watch) — note for now.
- **Sibling-project impact:** TBD.
- **Status:** queued

### F-010: top-level tool-use linkage keys

- **Source:** local scan, 2026-06-09
- **Added:** 2026-06-09
- **Change type:** `field-added`
- **Affected message types:** `progress` (`toolUseID`, `parentToolUseID`); `system` (`toolUseID`); `user` (`sourceToolUseID`)
- **Summary:** Tool-use ids surface at the **top level** (not just inside `message.content[].tool_use.id`): `toolUseID` on `progress`/`system`, `parentToolUseID` on `progress`, `sourceToolUseID` on `user` (parallel to the documented `sourceToolAssistantUUID`). Lets a parser correlate streaming/system events to the tool call they belong to without descending into content. Note casing: top-level `toolUseID` (capital D) vs. `meta.json` `toolUseId` (F-002). **Upstream evidence (2026-06-09):** No explicit announcement in CHANGELOG v2.1.150–v2.1.170. Silent addition; introduction version unknown.
- **Reference impact:** `reference/data-dictionary.md` (Common fields); `reference/tool-invocation.md`.
- **Post potential:** `tooling` — Part 5 adjacent.
- **Sibling-project impact:** cleaner event-to-tool correlation for both siblings.
- **Status:** queued

### F-011: misc envelope additions across many types

- **Source:** local scan, 2026-06-09
- **Added:** 2026-06-09
- **Change type:** `field-added`
- **Affected message types:** multiple — `slug` (assistant/attachment/progress/system/user, ~32k lines), `sessionKind` (assistant/attachment/system/user), `messageId` + `isSnapshotUpdate` (`file-history-snapshot`), `data` (`progress`)
- **Summary:** A cluster of new common/envelope keys: `slug` (project slug now embedded in lines, not only the directory name), `sessionKind` (a session-classification marker), and on `file-history-snapshot` a `messageId` + `isSnapshotUpdate` (distinguishing incremental snapshot updates from full snapshots). Individually minor; worth one catalog pass so the Common-fields table stays current. **Upstream evidence (2026-06-09):** No explicit announcement in CHANGELOG v2.1.150–v2.1.170. Silent additions. The `data-dictionary.md` § File-history snapshots already documents `messageId` and `isSnapshotUpdate` on `file-history-snapshot` (from v2.1.150 baseline), so those two sub-fields may already be covered — scanner should confirm if these differ from what's already in reference.
- **Reference impact:** `reference/data-dictionary.md` (Common fields; `file-history-snapshot`).
- **Post potential:** `none` (reference hygiene).
- **Sibling-project impact:** low.
- **Status:** queued

### F-012: reference baseline drift — v2.1.150 → v2.1.168

- **Source:** local scan, 2026-06-09 (47 distinct versions on disk; newest v2.1.168)
- **Added:** 2026-06-09
- **Change type:** `behavior-change`
- **Affected message types:** all (verification cadence, not a single field)
- **Summary:** All `reference/` docs and shipped posts are "Verified against v2.1.150," but on-disk data already spans up to v2.1.168, and the drift above (F-001…F-011) accumulated across that range. This candidate tracks the re-verification sweep: bump the verified-against headers as each reference section is updated, and update `tooling/format-scan/baseline-v2.1.150.json` to a new baseline once the deltas are documented. **Upstream evidence (2026-06-09):** Latest CHANGELOG entry is v2.1.170 (bug fixes including a transcript-saving fix for VS Code/env contexts). The new re-verification target should be v2.1.170. Between v2.1.150 and v2.1.170, no single version explicitly announces a comprehensive format change; changes are scattered and mostly silent.
- **Reference impact:** all `reference/` "Verified against" headers; the format-scan baseline file.
- **Post potential:** `none` (process); could seed a `reference/format-version-history.md` (long planned).
- **Sibling-project impact:** n/a.
- **Status:** queued

### F-013: `post-session` hook lifecycle event (new hook event type)

- **Source:** Claude Code CHANGELOG v2.1.169, https://raw.githubusercontent.com/anthropics/claude-code/refs/heads/main/CHANGELOG.md, 2026-06-09
- **Added:** 2026-06-09
- **Change type:** `field-added` (new hook event type in the outbound hook schema)
- **Affected message types:** hook event payloads (outbound JSON to hook scripts); potentially `system` lines if hook-execution is recorded (F-003)
- **Summary:** v2.1.169 adds a `post-session` lifecycle hook for self-hosted runners — "snapshot uncommitted work or export logs." This is a new entry in the outbound hook event schema (`hook_event_name: "post-session"` or similar). The data-dictionary's Hook event fields table documents 27 event types as of v2.1.150; `post-session` (and likely a `pre-session`/`SessionEnd` companion) is not in that list. If hook-execution bookkeeping lands on `system` lines (F-003), a `post-session` hook firing would also appear there.
- **Reference impact:** `reference/data-dictionary.md` (Hook event fields — Event types table; add `post-session` row).
- **Post potential:** `format-update` — feeds Part 6 on hooks.
- **Sibling-project impact:** AgentFluent hook monitoring should handle `post-session` events.
- **Status:** queued

### F-014: `Stop`/`SubagentStop` `hookSpecificOutput.additionalContext` (new hook response field)

- **Source:** Claude Code CHANGELOG v2.1.163, https://raw.githubusercontent.com/anthropics/claude-code/refs/heads/main/CHANGELOG.md, 2026-06-09
- **Added:** 2026-06-09
- **Change type:** `field-added` (new field in the hook response/output contract)
- **Affected message types:** hook response payloads (outbound JSON from hook scripts back to Claude Code); potentially `system` lines carrying hook output
- **Summary:** v2.1.163 adds `hookSpecificOutput.additionalContext` to the `Stop` and `SubagentStop` hook response contract. This extends the hook output schema — scripts handling `Stop`/`SubagentStop` events can now return structured context back to Claude Code. The data-dictionary's hook section documents the request shape (what Claude Code sends to hooks) but the response schema (what hooks return) is not yet documented. This field is the first confirmed named key in the response payload beyond exit code.
- **Reference impact:** `reference/data-dictionary.md` (Hook event fields — add a "Hook response schema" section documenting `hookSpecificOutput` and `additionalContext`).
- **Post potential:** `format-update` — Part 6 on hooks; the response contract was previously undocumented here.
- **Sibling-project impact:** AgentFluent hooks writing `Stop`/`SubagentStop` handlers can now return context.
- **Status:** queued

### F-015: Agent SDK TS format additions — `stop_reason: 'refusal'`, `MessageDisplay` hook, `system/memory_recall`

- **Source:** Claude Agent SDK TypeScript CHANGELOG, https://raw.githubusercontent.com/anthropics/claude-agent-sdk-typescript/main/CHANGELOG.md, 2026-06-09
- **Added:** 2026-06-09
- **Change type:** `field-added` (three distinct additions; grouped because all are SDK-only and Claude Code parity is unconfirmed)
- **Affected message types:** `assistant` (refusal fields); hook event payloads (`MessageDisplay`); `system` (`memory_recall` subtype, `memory_paths` on `system/init`)
- **Summary:** Three SDK TypeScript additions that may or may not have landed in Claude Code: (1) v0.2.162 adds `stop_reason: 'refusal'` and `stop_details` on assistant messages — a new stop-reason value not in the data-dictionary; (2) v0.2.152 adds `MessageDisplay` hook event — lets hooks transform or hide assistant message text (new event type absent from the hook event table); (3) v0.2.105 adds `system/memory_recall` event type and `memory_paths` field on `system/init` — new `system` subtypes for memory operations. All three affect the JSONL/hook schema if they've reached the Claude Code CLI. Claude Code parity status is not confirmed from the CHANGELOG alone — requires a scanner pass or targeted search.
- **Reference impact:** `reference/data-dictionary.md` (`assistant` stop_reason enum; Hook event fields table — `MessageDisplay` row; `system` type — `memory_recall` subtype and `init` subtype `memory_paths` field).
- **Post potential:** `format-update` — if confirmed in Claude Code, feeds Part 6 (hooks) and data-dictionary updates.
- **Sibling-project impact:** AgentFluent should handle `stop_reason: 'refusal'` to avoid miscounting error turns as normal completions.
- **Status:** queued
