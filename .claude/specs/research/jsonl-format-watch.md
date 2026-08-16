# JSONL Format Watch

**Purpose:** Queue of observed or announced changes to Claude Code's JSONL session format. Maintained by the `jsonl-format-watch` skill and a human review gate. Drives updates to `reference/` docs, post topics, and (when applicable) cross-posted candidates into sibling projects' research queues.

**Pipeline:**
1. A research pass (manual or scheduled) appends candidates with `Status: queued`.
2. The human reviews each candidate and adds a `Decision` line: `approve`, `defer`, `dismiss`, or `cross-post <project>`.
3. The `jsonl-format-watch` skill dispatches approved candidates — updates reference docs, drafts a post, or cross-posts to sibling projects — and records the outcome in a Promotion block. Status flips to `promoted` or `dismissed`.

The dispatch step is a skill (not a subagent) because subagents cannot invoke other subagents in Claude Code; the cross-post route may need to invoke a research or writing subagent later.

See `.claude/skills/jsonl-format-watch/SKILL.md` for the implementation (v0: built scanner + scout + human gate + manual pm/architect dispatch).

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
| 2026-08-15 | local scan — `tooling/format-scan/scan.py` v0.2.0 (`--json` + `--probe-nesting`), issue #169 / PR #171 | Local corpus measurement of subagent `spawnDepth` by CC version | 2,047 files / 232,471 lines / 1,235 manifests / 78 CC versions (v2.1.109–v2.1.233), 0 parse errors, 0 unattributed manifests. `spawnDepth` appears at exactly v2.1.187 (absent on all 768 manifests at v2.1.186 and earlier, present on all 467 after) — promotes the v2.1.187 CHANGELOG entry from PARTIAL to a confirmed JSONL-shape anchor. Max observed depth is **2** (v2.1.195 5/29, v2.1.226 1/88); nothing at depth 3–5. Depth 2 at v2.1.195 **refutes** the "(was 1)" clause in v2.1.219 as a description of the runtime cap over v2.1.181–v2.1.217; the "5 levels" and "depth 3" caps are unobservable in this corpus. Layout is **flat at every observed depth** (0 nested `subagents/` dirs across 294 session dirs). The SDK's depth-≥2 no-rollup rule (F-017) **does not hold for CC** — all 6 depth-2 spawn sites carry a full `toolUseResult` sibling, as do 449/449 depth-1 controls — so CC cost attribution at depth ≥ 2 is intact and that caveat is SDK-only. `subagent_tokens` coexists with the rollup at both depths (292/449 at depth 1, 1/6 at depth 2) and is not a depth marker in CC. Depth-2 spawn sites live in the depth-1 subagent's own trace file (6/6), depth-1 sites in the parent transcript (449/449). `parentAgentId` never appears on a line anywhere; 1 of 1,235 manifests carries it. Single-user corpus: absence of depth ≥3 is not evidence of a cap. | observation-recorded | F-019 promoted; F-017 and F-022 CC-parity answered |
| 2026-08-14 | https://raw.githubusercontent.com/anthropics/claude-code/refs/tags/v2.1.198/CHANGELOG.md | Claude Code CHANGELOG tag-pinned v2.1.198 (v2.1.143–v2.1.198) | Gap-closing pass for v2.1.171–v2.1.198 (bonus v2.1.143–v2.1.149). v2.1.171 absent from file (no entry). v2.1.172: CC native nested subagent spawning first announced ("Sub-agents can now spawn their own sub-agents (up to 5 levels deep)") — predates F-019's v2.1.217/v2.1.219 citation; corrects F-019 date. v2.1.181: foreground subagent depth-limit bug fix ("they now respect the same 5-level depth limit as background subagents"). v2.1.187: "spawn depth" named explicitly in a bug fix ("resumed subagents now restore their original spawn depth, and forked subagents now count toward the depth cap") — PARTIAL behavioral anchor for scanner-observed `spawnDepth` meta.json key. v2.1.193: "Added auto-mode denial reasons to the transcript" — PARTIAL behavioral anchor for scanner-observed `toolDenialKind` envelope key (new F-025). v2.1.145 (bonus): confirms Stop/SubagentStop hook input gains `background_tasks` and `session_crons` fields — already noted in data-dictionary.md version-specific notes. No explicit announcement of `tool-results/`, `meta.json`, `agent-name`, `custom-title`, `file-history-delta`, or any of the 21 undocumented envelope keys in the primary watchlist except `toolDenialKind` (PARTIAL at v2.1.193). | candidate-added / already-covered | F-025; F-002 and F-019 updated |
| 2026-08-14 | https://raw.githubusercontent.com/anthropics/claude-code/refs/heads/main/CHANGELOG.md | Claude Code CHANGELOG (v2.1.199–v2.1.232; v2.1.171–v2.1.198 absent from file) | Versions v2.1.171–v2.1.198 are not present in the current CHANGELOG (file trimmed to ~33 most-recent versions, a 28-version coverage gap for this run; **closed later the same day** via the tag-pinned v2.1.198 fetch, see the row above). From v2.1.199–v2.1.232: v2.1.210 announces "Session transcript size reduced up to 79x in edit-heavy sessions" (behavioral anchor for the scanner-observed `file-history-delta` type; type name itself silent) and `/status` shows "session kind: `interactive`, or a background job" (dates `sessionKind` concept in promoted F-011). v2.1.213: `subagent_type: "fork"` subagent introduced; non-teammate agent spawns in interactive sessions run in background by default. v2.1.217/v2.1.219: CC native nested subagent support increased to depth 3 (was 1); `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH` env var announced. v2.1.219: `DirectoryAdded` hook event added (new hook event type, absent from reference/). v2.1.232: `subagent_type: "fork"` on by default, name explicitly stated. No explicit announcement of `tool-results/`, `meta.json`, `parentAgentId`, `spawnedWithWorktree`, `worktreeBranch`, `worktreeCleanlyRemoved`, `agent-name` type, `custom-title` type, or the undocumented envelope keys (`agentName`, `attributionPlugin`, `backup`, `classifierMetaLines`, `customTitle`, `interruptedByShutdown`, `interruptedMessageId`, `isVisibleInTranscriptOnly`, `messageCount`, `queuePriority`, `snapshotMessageId`, `toolDenialKind`, `toolEndsTurn`, `trackingPath`). | candidate-added | F-018, F-019, F-020 |
| 2026-08-14 | https://raw.githubusercontent.com/anthropics/claude-agent-sdk-typescript/main/CHANGELOG.md | Claude Agent SDK TypeScript CHANGELOG (v0.3.142–v0.3.232) | All v0.3.x versions are new since the June 2026 review at v0.2.162. v0.3.216: `tool_result_meta` sidecar added to user messages carrying `non_execution_kind` and `user_feedback`; also `user_message_uuid` and `request_sent_wall_ms` on success result messages. v0.3.202: `parent_agent_id` field added to subagent session messages "for building agent trees from disk metadata" (announced counterpart to scanner-observed `parentAgentId`). v0.3.214: `aborted: true` on assistant messages truncated by `interrupt()`; `source: "fork"` added to `SessionStart` hooks; `system/init` gains plugin manifest `version`. v0.3.162: `stop_reason: "refusal"` confirmed in "transcripts" (JSONL) — the word "transcripts" partially confirms CC JSONL parity for F-015. v0.3.152: `hookSpecificOutput.sessionTitle` on `SessionStart` hook response (extends hook response schema beyond F-014's `additionalContext`); `MessageDisplay` hook event (corroborates F-015). v0.3.203: `background_tasks_changed` system message. v0.3.142: Task tools replace deprecated `TodoWrite`. | candidate-added / already-covered | F-021, F-022, F-023, F-024; F-015 dated |
| 2026-08-14 | https://raw.githubusercontent.com/anthropics/claude-agent-sdk-python/main/CHANGELOG.md | Claude Agent SDK Python CHANGELOG (v0.1.75–v0.2.138) | v0.2.101: `system/task_updated` event exposed as typed `TaskUpdatedMessage` with fields `task_id`, `patch`, `status`, `session_id`, `uuid` — a new system message subtype likely present in CC sessions (Task tools active in CC per CHANGELOG). v0.2.126: `terminal_reason` and typed `model_usage` (with `canonicalModel`, `provider`) added to `ResultMessage` — SDK result metadata layer, not session-line format. v0.1.76: `api_error_status` on `ResultMessage`. No other session-JSONL format changes beyond the SDK result layer. | candidate-added | F-024 |
| 2026-08-14 | https://www.anthropic.com/engineering | Anthropic Engineering Blog (Aug 2026) | No new engineering posts in the last 30 days. Most recent is "An update on recent Claude Code quality reports" (Apr 23, 2026). Not actionable for format watch. | not-actionable | — |
| 2026-08-14 | https://www.anthropic.com/news | Anthropic News (Jul–Aug 2026) | "The Making of Claude Code" (Jul 6, 2026) — historical narrative, not format-relevant. No format announcements in the last 30 days. | not-actionable | — |
| 2026-06-23 | agentfluent `research/agent-sdk-probe/FINDINGS.md` (#530) + `tests/fixtures/nested_session/` | Agent SDK nested (multi-level) subagent probe | Forced `main → delegator → leaf` chain (SDK 0.2.106 / CLI 2.1.185): nested SDK delegation records a **flat** `subagents/` dir (no `subagents/<id>/subagents/…`); call tree is by-data via a cross-file `toolUseId` join; `toolUseResult` rollup is top-level-only (inline `subagent_tokens` trailer at depth ≥ 2); `totalToolUseCount` own-direct; one `sessionId` shared across all levels (Claude Code divergence). Resolves `subagent-traces.md` open-item #1. | candidate-added | F-017 |
| 2026-06-22 | agentfluent `research/agent-sdk-probe/FINDINGS.md` (#518, #522) | Agent SDK session-data probe | Empirical Python Agent SDK probe (SDK 0.2.106 / CLI 2.1.185): SDK writes the same JSONL to the same place, same subagent/spill layout. Confirms `entrypoint: "sdk-py"` and `promptSource: "sdk"` discriminators; surfaces net-new `resolvedModel` on `toolUseResult`. Facts documented here per the canonical-format rule (#132). | candidate-added | F-016 |
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
- **Summary:** A new directory `~/.claude/projects/<slug>/<session-uuid>/tool-results/` sits as a sibling to `subagents/`. It holds one file per oversized tool result, named by the producing tool call (`toolu_*.txt`, `mcp-github-{list,search,get}_*.txt|json`). All 89 observed files are >20 KB (min 20,152 B, median ~64 KB, max ~840 KB), strongly implying a ~20 KB spill threshold: large tool output is written here instead of being inlined in the `tool_result` block. **Upstream evidence (2026-06-09):** GitHub issue #23948 (filed v2.1.17, closed duplicate) confirms the sidecar path `tool-results/<tool-use-id>.txt` and shows the in-JSONL reference is plain text in `tool_result.content` wrapped in `<persisted-output>` tags with a "Preview (first 2KB)" message — NOT a dedicated JSON pointer field. The feature predates v2.1.150 (present at least since v2.1.17); introduction version unknown. The CHANGELOG shows no explicit announcement for this feature across v2.1.150–v2.1.170, indicating it was a silent addition at some earlier version. **Scanner-confirmed (2026-06-09):** the `scan.py --probe-tool-results` pass found `<persisted-output>` / `</persisted-output>` wrapper tags (118 / 98 occurrences) plus a `Preview (first …)` message (103) and `tool-results/<id>` path references (171) inside `tool_result.content` — so the in-JSONL reference is a plain-text wrapper *in the content string*, carrying a truncated preview, NOT a dedicated JSON pointer key. Full output lives in the `tool-results/` sidecar. This candidate is now verified (structure + pointer); ready to dispatch.
- **Reference impact:** `reference/subagent-traces.md` (File layout diagram shows only `subagents/`); `reference/data-dictionary.md` (File location); likely a new `reference/tool-results.md` or a tool-invocation section.
- **Post potential:** `format-update` / `tooling` — primary home is **Part 5 ("The tool call, completely," #67)**; also forces a fix to the **Part 3** directory-layout diagram (#65).
- **Sibling-project impact:** AgentFluent/CodeFluent that read `tool_result.content` for large outputs will get a truncated/pointer payload unless they also read the sidecar.
- **Decision (2026-06-10):** approve — verified (structure + pointer); reference + Part 5 home, forces Part 3 diagram fix
- **Promotion (2026-06-10):** approve → filed #87 (cluster A — sidecar dirs); Part 3 post update tracked in #88
- **Status:** promoted

### F-002: per-subagent `meta.json` sidecar

- **Source:** local scan, 2026-06-09 (561 files under `subagents/`)
- **Added:** 2026-06-09
- **Change type:** `envelope-change`
- **Affected message types:** subagent traces (new sidecar file alongside `agent-<id>.jsonl`)
- **Summary:** Each subagent invocation now also writes a tiny `agent-<id>.meta.json` (20–249 bytes) next to its `.jsonl` trace. Top-level keys observed: `agentType` (all 561), `description` (544), `toolUseId` (254), `worktreePath` (10). It is a lightweight manifest/index card for the subagent run — letting tooling enumerate and route subagents without parsing the full trace. Note the casing split: `meta.json` uses `toolUseId` while session lines use `toolUseID` (see F-010). **Upstream evidence (2026-06-09):** No explicit announcement found in the CHANGELOG for v2.1.150–v2.1.170. Silent addition; introduction version unknown. **Behavioral anchor (2026-08-14):** v2.1.187 CHANGELOG names "spawn depth" as a tracked concept ("resumed subagents now restore their original spawn depth, and forked subagents now count toward the depth cap") — PARTIAL behavioral anchor for the `spawnDepth` meta.json key; field name itself SILENT across v2.1.143–v2.1.198.
- **Reference impact:** `reference/subagent-traces.md` (File layout — currently shows `subagents/` containing only `agent-<id>.jsonl`).
- **Post potential:** `foundation` — directly relevant to **Part 3 (#65)**; the subagents/ layout now has two files per invocation.
- **Sibling-project impact:** AgentFluent can list/characterize subagents cheaply from `meta.json` instead of opening every trace.
- **Decision (2026-06-10):** approve — reference subagent-traces; subagents/ now writes two files per invocation (Part 3)
- **Promotion (2026-06-10):** approve → filed #87 (cluster A — sidecar dirs); Part 3 post update tracked in #88
- **Status:** promoted

### F-003: hook-execution records on `system` lines

- **Source:** local scan, 2026-06-09
- **Added:** 2026-06-09
- **Change type:** `field-added`
- **Affected message types:** `system`
- **Summary:** `system` lines now carry hook-execution bookkeeping: `hookCount`, `hookInfos`, `hookErrors`, `preventedContinuation`, `stopReason`, `hasOutput` (each on ~986 lines). This means hook activity **does** leave a JSONL trace — recorded as `system` events — which is the core question Part 6 was scoped to answer. Field *values* not read; presence + carrier-type only. **Upstream evidence (2026-06-09):** No explicit announcement in CHANGELOG v2.1.150–v2.1.170. The v2.1.163 entry notes `Stop`/`SubagentStop` can return `hookSpecificOutput.additionalContext`, suggesting active hook output evolution, but the `system`-line recording of hook metadata appears to be a silent addition. Introduction version unknown.
- **Reference impact:** `reference/data-dictionary.md` (`system` type; Hook event fields section).
- **Post potential:** `format-update` — this is the empirical anchor for **Part 6 ("What hooks leave behind," #68)**; reshapes that post from "here's what I went looking for" toward "here's what's there."
- **Sibling-project impact:** AgentFluent hook/quality diagnostics can read hook outcomes from `system` lines.
- **Decision (2026-06-10):** approve — empirical anchor for Part 6; reference data-dictionary (system + hooks)
- **Promotion (2026-06-10):** approve → filed #89 (cluster B — hook traces)
- **Status:** promoted

### F-004: API retry metadata on `system` lines

- **Source:** local scan, 2026-06-09
- **Added:** 2026-06-09
- **Change type:** `field-added`
- **Affected message types:** `system`
- **Summary:** `system` lines carry `retryInMs`, `retryAttempt`, `maxRetries` (~22 lines) — records of API-level retries (backoff). Distinct from the *tool-call* retry pairing analyzed in the shipped retry aside (#53); this is transport/model retry, recorded by the harness. **Upstream evidence (2026-06-09):** No explicit announcement in CHANGELOG v2.1.150–v2.1.170. Silent addition; introduction version unknown.
- **Reference impact:** `reference/data-dictionary.md` (`system` type).
- **Post potential:** `analysis` — feeds the retry/failure-rate line (#54) with a second, harness-level retry signal.
- **Sibling-project impact:** AgentFluent reliability signals.
- **Decision (2026-06-10):** approve — reference (system); pairs with the retry/failure line (#54)
- **Promotion (2026-06-10):** approve → filed #90 (cluster C — failure & retry signals)
- **Status:** promoted

### F-005: compaction records (`system` + `user`)

- **Source:** local scan, 2026-06-09
- **Added:** 2026-06-09
- **Change type:** `field-added`
- **Affected message types:** `system` (`compactMetadata`, `logicalParentUuid`); `user` (`isCompactSummary`, `isVisibleInTranscriptOnly`, `origin`, `promptSource`)
- **Summary:** Context-compaction now leaves a trace: a `system` line carries `compactMetadata` and a `logicalParentUuid` (a parent pointer distinct from `parentUuid` — relevant to thread reconstruction), and the injected summary appears as a `user` line flagged `isCompactSummary` / `isVisibleInTranscriptOnly`, with `origin` / `promptSource` distinguishing synthesized vs. typed prompts (24 lines each). **Upstream evidence (2026-06-09):** GitHub issue #16944 (closed) confirms the exact shape: `system` line with `subtype: "compact_boundary"` (not just `type: "system"`) carrying `compactMetadata: {trigger: "auto"|"manual", preTokens: <number>}`. `isCompactSummary: true` on injected summary user line confirmed. Observed in v2.1.1 per the issue; predates v2.1.150. No announcement in CHANGELOG v2.1.150–v2.1.170; silent/established feature. Scanner should look for `subtype: "compact_boundary"` specifically to confirm `logicalParentUuid` presence on that line vs. adjacent lines.
- **Reference impact:** `reference/data-dictionary.md` (`system`, `user`, Common fields — `logicalParentUuid`).
- **Post potential:** `foundation` — material for the **Part 7 capstone ("The conversation is the unit," #69)**: `logicalParentUuid` and compaction summaries are exactly the cross-session/thread-continuity machinery that post argues about.
- **Sibling-project impact:** Anything reconstructing conversation threads must handle `logicalParentUuid` and skip/account for compaction-summary user lines.
- **Decision (2026-06-10):** approve — Part 7 capstone material; reference (system/user, logicalParentUuid)
- **Promotion (2026-06-10):** approve → filed #91 (cluster D — conversation continuity / compaction)
- **Status:** promoted

### F-006: `attributionSkill` on `assistant` (sidechain) lines

- **Source:** local scan, 2026-06-09 (6,680 lines)
- **Added:** 2026-06-09
- **Change type:** `field-added`
- **Affected message types:** `assistant` (subagent traces)
- **Summary:** A skill-attribution field `attributionSkill` appears on `assistant` lines, parallel to the documented `attributionAgent`/`attributionMcp*` family. Indicates the turn ran under an invoked skill. Extends the attribution family in `subagent-traces.md`. **Upstream evidence (2026-06-09):** CHANGELOG v2.1.157 notes plugins in `.claude/skills` directories are automatically loaded; v2.1.154 introduces dynamic workflows. The `attributionSkill` field was not explicitly announced but is consistent with skill/plugin infrastructure growth across v2.1.154–v2.1.157. Introduction version unknown; likely coincides with skill/plugin expansion.
- **Reference impact:** `reference/subagent-traces.md` (Attribution fields table).
- **Post potential:** `foundation` — Part 3 adjacent (attribution family).
- **Sibling-project impact:** AgentFluent can attribute work to skills, not just agent types.
- **Decision (2026-06-10):** approve — extends the attribution family in subagent-traces; Part 3 adjacent
- **Promotion (2026-06-10):** approve → filed #92 (cluster E — attribution + new types)
- **Status:** promoted

### F-007: new top-level `type` values — `mode`, `agent-name`

- **Source:** local scan, 2026-06-09 (`mode` 1,121 lines; `agent-name` 401 lines)
- **Added:** 2026-06-09
- **Change type:** `envelope-change` (new top-level type values)
- **Affected message types:** new types `mode` (carries `mode`) and `agent-name` (carries `agentName`)
- **Summary:** Two undocumented top-level `type` values: `mode` and `agent-name`. Purpose inferred from carried keys (a mode marker; an agent-name record) but not confirmed. Note: `custom-title` and `pr-link` also appeared and are **already tracked in #56** — fold those into that issue, not this candidate. **Upstream evidence (2026-06-09):** CHANGELOG v2.1.154 introduces dynamic workflows / multi-agent orchestration ("Claude orchestrates tens to hundreds of agents"); v2.1.162 adds `claude agents --json` with `waitingFor` field. The `mode` type likely records session mode state (e.g., auto mode, ultracode mode introduced v2.1.154) and `agent-name` likely records agent naming in the multi-agent system. Both are plausibly introduced around v2.1.154 with the dynamic-workflows feature, but not explicitly announced in the CHANGELOG.
- **Reference impact:** `reference/data-dictionary.md` (Skipped types / observed top-level types); coordinate with #56.
- **Post potential:** `foundation` — the "discover top-level type values you haven't catalogued" thread from Part 2.
- **Sibling-project impact:** parsers branching on `type` should tolerate these.
- **Decision (2026-06-10):** approve — reference observed-types; coordinate with #56 (custom-title/pr-link)
- **Promotion (2026-06-10):** approve → filed #92 (cluster E — attribution + new types); coordinated with #56
- **Status:** promoted

### F-008: API-error records on `assistant` lines

- **Source:** local scan, 2026-06-09
- **Added:** 2026-06-09
- **Change type:** `field-added`
- **Affected message types:** `assistant` (`isApiErrorMessage`, `apiError`, `apiErrorStatus`); `system` (`cause`)
- **Summary:** `assistant` lines can be flagged `isApiErrorMessage` with `apiError` / `apiErrorStatus` detail (5–81 lines); a related `cause` appears on `system`. Records API failures inline in the transcript — relevant to anyone computing success rates or filtering "real" model turns from error turns. **Upstream evidence (2026-06-09):** CHANGELOG v2.1.166 mentions "Claude retries once on fallback model for unexpected non-retryable API errors" suggesting active API-error handling development. TypeScript SDK v0.2.162 adds `stop_reason: 'refusal'` + `stop_details` on assistant (different from `isApiErrorMessage` but same surface area). No explicit announcement for `isApiErrorMessage` in CHANGELOG v2.1.150–v2.1.170; silent addition.
- **Reference impact:** `reference/data-dictionary.md` (`assistant` type; error handling notes).
- **Post potential:** `tooling` / `analysis` — pairs with the retry/failure line.
- **Sibling-project impact:** AgentFluent must exclude API-error assistant lines from token/turn metrics.
- **Decision (2026-06-10):** approve — reference (assistant); sibling metric-correctness impact
- **Promotion (2026-06-10):** approve → filed #90 (cluster C — failure & retry signals)
- **Status:** promoted

### F-009: background-agent counter on `system` lines

- **Source:** local scan, 2026-06-09 (28 lines)
- **Added:** 2026-06-09
- **Change type:** `field-added`
- **Affected message types:** `system`
- **Summary:** `pendingBackgroundAgentCount` on `system` lines points to background/async agent execution leaving a JSONL signal. Low volume; purpose needs confirmation. Likely related to the `meta.json` `worktreePath` observation (F-002) — background agents in worktrees. **Upstream evidence (2026-06-09):** CHANGELOG v2.1.154 explicitly introduces dynamic workflows and background agents: "Dynamic workflows introduced: Claude orchestrates tens to hundreds of agents" and `claude agents` with background shell session support (`! <command>`). v2.1.169 mentions "background agents ignoring project-level environment settings" (fixed). The `pendingBackgroundAgentCount` field on `system` lines is very likely introduced with or shortly after v2.1.154. Introduction version estimated ~v2.1.154.
- **Reference impact:** `reference/data-dictionary.md` (`system` type).
- **Post potential:** `none`/`format-update` (watch) — note for now.
- **Sibling-project impact:** TBD.
- **Decision (2026-06-10):** defer — low volume, purpose unconfirmed; re-observe before documenting
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
- **Decision (2026-06-10):** approve — reference common fields / tool-invocation
- **Promotion (2026-06-10):** approve → filed #93 (cluster F — reference hygiene + re-verify)
- **Status:** promoted

### F-011: misc envelope additions across many types

- **Source:** local scan, 2026-06-09
- **Added:** 2026-06-09
- **Change type:** `field-added`
- **Affected message types:** multiple — `slug` (assistant/attachment/progress/system/user, ~32k lines), `sessionKind` (assistant/attachment/system/user), `messageId` + `isSnapshotUpdate` (`file-history-snapshot`), `data` (`progress`)
- **Summary:** A cluster of new common/envelope keys: `slug` (project slug now embedded in lines, not only the directory name), `sessionKind` (a session-classification marker), and on `file-history-snapshot` a `messageId` + `isSnapshotUpdate` (distinguishing incremental snapshot updates from full snapshots). Individually minor; worth one catalog pass so the Common-fields table stays current. **Upstream evidence (2026-06-09):** No explicit announcement in CHANGELOG v2.1.150–v2.1.170. Silent additions. The `data-dictionary.md` § File-history snapshots already documents `messageId` and `isSnapshotUpdate` on `file-history-snapshot` (from v2.1.150 baseline), so those two sub-fields may already be covered — scanner should confirm if these differ from what's already in reference.
- **Reference impact:** `reference/data-dictionary.md` (Common fields; `file-history-snapshot`).
- **Post potential:** `none` (reference hygiene).
- **Sibling-project impact:** low.
- **Decision (2026-06-10):** approve — reference hygiene; first confirm messageId/isSnapshotUpdate aren't already documented
- **Promotion (2026-06-10):** approve → filed #93 (cluster F — reference hygiene + re-verify)
- **Status:** promoted

### F-012: reference baseline drift — v2.1.150 → v2.1.168

- **Source:** local scan, 2026-06-09 (47 distinct versions on disk; newest v2.1.168)
- **Added:** 2026-06-09
- **Change type:** `behavior-change`
- **Affected message types:** all (verification cadence, not a single field)
- **Summary:** All `reference/` docs and shipped posts are "Verified against v2.1.150," but on-disk data already spans up to v2.1.168, and the drift above (F-001…F-011) accumulated across that range. This candidate tracks the re-verification sweep: bump the verified-against headers as each reference section is updated, and update `tooling/format-scan/baseline-v2.1.150.json` to a new baseline once the deltas are documented. **Upstream evidence (2026-06-09):** Latest CHANGELOG entry is v2.1.170 (bug fixes including a transcript-saving fix for VS Code/env contexts). The new re-verification target should be v2.1.170. Between v2.1.150 and v2.1.170, no single version explicitly announces a comprehensive format change; changes are scattered and mostly silent.
- **Reference impact:** all `reference/` "Verified against" headers; the format-scan baseline file.
- **Post potential:** `none` (process); could seed a `reference/format-version-history.md` (long planned).
- **Sibling-project impact:** n/a.
- **Decision (2026-06-10):** approve — umbrella re-verification + baseline bump; could seed format-version-history.md
- **Promotion (2026-06-10):** approve → filed #93 (cluster F — reference hygiene + re-verify)
- **Status:** promoted

### F-013: `post-session` hook lifecycle event (new hook event type)

- **Source:** Claude Code CHANGELOG v2.1.169, https://raw.githubusercontent.com/anthropics/claude-code/refs/heads/main/CHANGELOG.md, 2026-06-09
- **Added:** 2026-06-09
- **Change type:** `field-added` (new hook event type in the outbound hook schema)
- **Affected message types:** hook event payloads (outbound JSON to hook scripts); potentially `system` lines if hook-execution is recorded (F-003)
- **Summary:** v2.1.169 adds a `post-session` lifecycle hook for self-hosted runners — "snapshot uncommitted work or export logs." This is a new entry in the outbound hook event schema (`hook_event_name: "post-session"` or similar). The data-dictionary's Hook event fields table documents 27 event types as of v2.1.150; `post-session` (and likely a `pre-session`/`SessionEnd` companion) is not in that list. If hook-execution bookkeeping lands on `system` lines (F-003), a `post-session` hook firing would also appear there.
- **Reference impact:** `reference/data-dictionary.md` (Hook event fields — Event types table; add `post-session` row).
- **Post potential:** `format-update` — feeds Part 6 on hooks.
- **Sibling-project impact:** AgentFluent hook monitoring should handle `post-session` events.
- **Decision (2026-06-10):** approve — upstream-confirmed (v2.1.169); reference hook table; Part 6
- **Promotion (2026-06-10):** approve → filed #89 (cluster B — hook traces)
- **Status:** promoted

### F-014: `Stop`/`SubagentStop` `hookSpecificOutput.additionalContext` (new hook response field)

- **Source:** Claude Code CHANGELOG v2.1.163, https://raw.githubusercontent.com/anthropics/claude-code/refs/heads/main/CHANGELOG.md, 2026-06-09
- **Added:** 2026-06-09
- **Change type:** `field-added` (new field in the hook response/output contract)
- **Affected message types:** hook response payloads (outbound JSON from hook scripts back to Claude Code); potentially `system` lines carrying hook output
- **Summary:** v2.1.163 adds `hookSpecificOutput.additionalContext` to the `Stop` and `SubagentStop` hook response contract. This extends the hook output schema — scripts handling `Stop`/`SubagentStop` events can now return structured context back to Claude Code. The data-dictionary's hook section documents the request shape (what Claude Code sends to hooks) but the response schema (what hooks return) is not yet documented. This field is the first confirmed named key in the response payload beyond exit code.
- **Reference impact:** `reference/data-dictionary.md` (Hook event fields — add a "Hook response schema" section documenting `hookSpecificOutput` and `additionalContext`).
- **Post potential:** `format-update` — Part 6 on hooks; the response contract was previously undocumented here.
- **Sibling-project impact:** AgentFluent hooks writing `Stop`/`SubagentStop` handlers can now return context.
- **Decision (2026-06-10):** approve — reference hook response schema; Part 6
- **Promotion (2026-06-10):** approve → filed #89 (cluster B — hook traces)
- **Status:** promoted

### F-015: Agent SDK TS format additions — `stop_reason: 'refusal'`, `MessageDisplay` hook, `system/memory_recall`

- **Source:** Claude Agent SDK TypeScript CHANGELOG, https://raw.githubusercontent.com/anthropics/claude-agent-sdk-typescript/main/CHANGELOG.md, 2026-06-09
- **Added:** 2026-06-09
- **Change type:** `field-added` (three distinct additions; grouped because all are SDK-only and Claude Code parity is unconfirmed)
- **Affected message types:** `assistant` (refusal fields); hook event payloads (`MessageDisplay`); `system` (`memory_recall` subtype, `memory_paths` on `system/init`)
- **Summary:** Three SDK TypeScript additions that may or may not have landed in Claude Code: (1) v0.2.162 adds `stop_reason: 'refusal'` and `stop_details` on assistant messages — a new stop-reason value not in the data-dictionary; (2) v0.2.152 adds `MessageDisplay` hook event — lets hooks transform or hide assistant message text (new event type absent from the hook event table); (3) v0.2.105 adds `system/memory_recall` event type and `memory_paths` field on `system/init` — new `system` subtypes for memory operations. All three affect the JSONL/hook schema if they've reached the Claude Code CLI. Claude Code parity status is not confirmed from the CHANGELOG alone — requires a scanner pass or targeted search. **Update (2026-08-14):** TS SDK v0.3.162 (CHANGELOG reviewed 2026-08-14) states that refusal error messages carry `stop_reason: "refusal"` and `stop_details` "on assistant message and **transcripts**" — the word "transcripts" implies JSONL session files, partially confirming CC JSONL parity. TS SDK v0.3.152 also confirms `MessageDisplay` hook event in the SDK. Scanner confirmation of both in CC sessions is still the recommended gate before acting.
- **Reference impact:** `reference/data-dictionary.md` (`assistant` stop_reason enum; Hook event fields table — `MessageDisplay` row; `system` type — `memory_recall` subtype and `init` subtype `memory_paths` field).
- **Post potential:** `format-update` — if confirmed in Claude Code, feeds Part 6 (hooks) and data-dictionary updates.
- **Sibling-project impact:** AgentFluent should handle `stop_reason: 'refusal'` to avoid miscounting error turns as normal completions.
- **Decision (2026-06-10):** defer — Claude Code parity unconfirmed; verify via scanner before acting
- **Status:** queued

### F-016: `resolvedModel` on the `toolUseResult` Agent envelope

- **Source:** observed-in-fixture — AgentFluent Agent SDK probe (`research/agent-sdk-probe/FINDINGS.md`, agentfluent #522), Python SDK `claude-agent-sdk` 0.2.106 / `claude` CLI 2.1.185, captured 2026-06-22
- **Added:** 2026-06-22
- **Change type:** `field-added`
- **Affected message types:** `user`/`tool_result` — the parent's top-level `toolUseResult` envelope (Agent tool)
- **Summary:** The `toolUseResult` envelope on a parent `Agent`-tool line carries a new `resolvedModel` field: the concrete model the subagent actually ran, after alias resolution (e.g., `"claude-haiku-4-5-20251001"`). It sits alongside the documented Agent-tool rollup keys (`agentId`, `agentType`, `totalTokens`, `toolStats`, `usage`, …) and lets a parser read the child's model from the parent envelope without opening the trace file. First observed in the Agent SDK probe; not previously documented in this reference. Claude Code interactive parity (whether CC also emits `resolvedModel`) is not yet confirmed by a local scan — likely present, since the SDK reuses the Claude Code format, but unverified.
- **Reference impact:** `reference/data-dictionary.md` (`toolUseResult` envelope table); `reference/subagent-traces.md` (Agent SDK parity note).
- **Post potential:** `format-update` — feeds the Agent SDK coda (outline Part 8) and the token/model-routing thread.
- **Sibling-project impact:** AgentFluent can read the concrete child model from the parent envelope for model-routing/cost attribution without descending into the trace file.
- **Decision (2026-06-22):** approve — net-new field; document in reference (data-dictionary + subagent-traces) with the SDK version pin
- **Promotion (2026-06-22):** approve → documented in `reference/data-dictionary.md` (toolUseResult envelope) and `reference/subagent-traces.md` (Agent SDK parity) via #132; cited `fixtures/synthetic/agent-sdk-invocation.jsonl`. CC interactive parity left as a follow-up scan item.
- **Status:** promoted

### F-017: nested (multi-level) Agent SDK subagent layout — flat dir, by-data linkage, top-level-only rollup

- **Source:** observed-in-fixture — AgentFluent Agent SDK probe (`research/agent-sdk-probe/FINDINGS.md`, agentfluent #530), Python SDK `claude-agent-sdk` 0.2.106 / `claude` CLI 2.1.185, captured 2026-06-22; corroborated by the committed anonymized fixture `tests/fixtures/nested_session/`.
- **Added:** 2026-06-23
- **Change type:** `behavior-clarified` (resolves an open layout question; no new field on level-1 lines)
- **Affected message types:** subagent trace files + the `<session-uuid>/subagents/` directory layout; `tool_result` content at delegation depth ≥ 2
- **Summary:** A forced two-level SDK chain (`main → delegator → leaf`) settled the long-open flat-vs-nested question: the layout is **flat** — every subagent at every depth is a sibling under one `<session-uuid>/subagents/`, with no `subagents/<id>/subagents/…` nesting. The call tree is recoverable only from data: each subagent's `.meta.json` `toolUseId` names a `tool_use` that, at depth ≥ 2, lives in *another subagent's* trace, so reconstruction needs a cross-file `tool_use.id` index. The rich `toolUseResult` rollup is **top-level only** — present on the main session's level-1 result line, absent at depth ≥ 2 (only an inline `subagent_tokens: <N>` text trailer). `totalToolUseCount` is own-direct (excludes descendants); `totalTokens` is directionally inclusive but not a raw `message.usage` sum (cache accounting). The SDK shares **one `sessionId`** across all levels — a divergence from Claude Code, where each subagent has its own. `entrypoint: "sdk-py"` throughout.
- **Reference impact:** `reference/subagent-traces.md` (Nesting rewrite + new Multi-level/Reconstruction subsections + `sessionId` divergence note + Open-item #1 resolution); `reference/data-dictionary.md` (`toolUseResult` multi-level note + `totalToolUseCount` own-direct clause + `resolvedModel` child-model clause).
- **Post potential:** `format-update` — strong material for the Agent SDK coda (series outline Part 8): "Claude Code can't nest subagents; the SDK can, and here's how the bytes lay out."
- **Sibling-project impact:** AgentFluent's single-level trace→invocation linker assumes parent == main session; a multi-level linker must do the cross-file `toolUseId` join and add a derived `parent_invocation_id` (None = root). Token rollups must not be summed naively across levels.
- **Decision (2026-06-23):** approve — resolves `subagent-traces.md` open-item #1; document in reference (subagent-traces + data-dictionary).
- **Promotion (2026-06-23):** approve → documented in `reference/subagent-traces.md` and `reference/data-dictionary.md`. TS SDK parity + MCP-routing attribution placement remain open.
- **CC parity (2026-08-15, #169):** the #169 scan measured the same three properties on native Claude Code multi-level sessions. Two carry over and one does **not**. **Flat layout: carries over** — 0 nested `subagents/` directories across 294 CC session dirs. **Cross-file `toolUseId` join: carries over** — all 6 observed depth-2 CC spawn sites live in the depth-1 subagent's own trace file, not the parent transcript. **Top-level-only rollup: does NOT carry over** — every depth-2 CC spawn site carries a full `toolUseResult` sibling, so this property is SDK-specific and must be scoped as such wherever it is documented. The inline `subagent_tokens` trailer also behaves differently in CC: it coexists with the rollup at both depths rather than substituting for it. See the F-019 Observation block for the numbers.
- **Status:** promoted

> **Batch note (2026-08-14):** F-018 through F-024 are from the 2026-08-14 upstream scout pass, covering the v2.1.171–v2.1.232 range. IMPORTANT: v2.1.171–v2.1.198 are absent from the current CHANGELOG (file trimmed) and were not surveyed this run, a 28-version coverage gap. See the Correction below: the gap is recoverable and this range still needs a survey pass. F-018–F-020 are upstream-announced CC changes (all from the v2.1.199–v2.1.232 range that was verifiable). F-021–F-023 are SDK TS-announced with CC parity unconfirmed. F-024 covers newly announced system message subtypes from both SDKs. All candidates address the announced-vs-silent question raised by the 2026-08-14 scan (v2.1.4–v2.1.232 corpus).

> **Correction (2026-08-14):** the v2.1.171–v2.1.198 gap noted above **is** closable, contrary to the batch note's original wording and the Reviewed Sources row for the CC CHANGELOG. The changelog is tag-pinned on raw.githubusercontent, so `https://raw.githubusercontent.com/anthropics/claude-code/refs/tags/v2.1.198/CHANGELOG.md` returns the file as it stood at v2.1.198 and covers v2.1.198 back to v2.1.143. Verified 2026-08-14 by direct fetch. One WebFetch closes the whole gap. The scout has been updated with a standing recovery procedure (`.claude/agents/jsonl-format-research.md`, "Recovering trimmed changelog history"). **Gap now surveyed (2026-08-14):** The tag-pinned fetch at v2.1.198 covers v2.1.143–v2.1.198; see that Reviewed Sources row for full findings. v2.1.172 first announces CC native nested subagent spawning; v2.1.193 provides a PARTIAL behavioral anchor for `toolDenialKind` (new F-025). No explicit announcement found for any other watchlist item across v2.1.143–v2.1.198. The public claim that the listed fields were never announced is now airtight for the combined surveyed range (v2.1.143–v2.1.232).

### F-018: v2.1.210 file-history delta compression — behavioral announcement for the `file-history-delta` type

- **Source:** Claude Code CHANGELOG v2.1.210, https://raw.githubusercontent.com/anthropics/claude-code/refs/heads/main/CHANGELOG.md, 2026-08-14
- **Added:** 2026-08-14
- **Change type:** `behavior-change`
- **Affected message types:** `file-history-snapshot` (likely replaced or supplemented by the scanner-observed `file-history-delta` top-level type)
- **Summary:** CHANGELOG v2.1.210 announces "Session transcript size reduced up to 79x in edit-heavy sessions." The mechanism is delta compression of file-history records, consistent with the scanner-observed `file-history-delta` top-level type not yet documented in reference/. The type name `file-history-delta` does not appear in the CHANGELOG — the announcement describes only the behavioral outcome (79x size reduction). This is the first upstream anchor dating the introduction of delta-based file history; the specific JSONL type name remains a SILENT addition. Introduced at v2.1.210 (announced behavioral effect); `file-history-delta` type name SILENT.
- **Reference impact:** `reference/data-dictionary.md` (Skipped types table — add `file-history-delta` row noting delta variant and v2.1.210 behavioral anchor; file-history snapshot subsection — note delta variant introduced approximately v2.1.210).
- **Post potential:** `format-update`
- **Sibling-project impact:** Parsers that read `file-history-snapshot` for `/rewind` reconstruction must also handle `file-history-delta` incremental records, which likely carry the same `trackedFileBackups` payload in a diff/delta form rather than full snapshots.
- **Status:** queued

### F-019: v2.1.219 CC native nested subagent support increased to depth 3

- **Source:** Claude Code CHANGELOG v2.1.217 and v2.1.219, https://raw.githubusercontent.com/anthropics/claude-code/refs/heads/main/CHANGELOG.md, 2026-08-14
- **Added:** 2026-08-14
- **Change type:** `behavior-change`
- **Affected message types:** subagent trace files + `<session-uuid>/subagents/` directory layout; `toolUseResult` envelope on deeply-nested agent results
- **Summary:** CHANGELOG v2.1.217 states "Subagent spawn depth increased; nested agents now up to depth 3 by default" and v2.1.219 confirms "Subagents now spawn up to depth 3 (was 1); set `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH=1` to disable." Claude Code interactive sessions can now produce nested subagent hierarchies up to depth 3 — this was previously documented as an SDK-only capability (F-017). The flat `subagents/` directory layout still holds, but the cross-file toolUseId reconstruction needed for multi-level trees (F-017) now applies to CC native sessions. The `meta.json` keys `parentAgentId` and `spawnDepth` are likely populated for depth-2+ CC subagents; those field names remain SILENT in the CHANGELOG. Also announced in v2.1.219: `DirectoryAdded` hook event (fires after `/add-dir` or SDK `register_repo_root`) — a new hook event type absent from the hook event fields table in reference/. ANNOUNCED in v2.1.217/v2.1.219. **Correction (2026-08-14):** Tag-pinned v2.1.198 CHANGELOG shows v2.1.172 first announced CC native nested subagent spawning ("Sub-agents can now spawn their own sub-agents (up to 5 levels deep)"), predating the v2.1.217/v2.1.219 citations above. v2.1.181 extended the same 5-level cap to foreground subagents ("they now respect the same 5-level depth limit as background subagents"). The v2.1.217/v2.1.219 entries represent a change to the effective default cap for interactive sessions (to 3 levels, with `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH` env var). Full version history: introduced v2.1.172 (up to 5 levels); extended to foreground v2.1.181; "spawn depth" tracking fixed v2.1.187; depth cap changed at v2.1.217/v2.1.219. JSONL shape fields (`spawnDepth`, `parentAgentId`) remain SILENT across the full v2.1.143–v2.1.232 range.
- **Observation (2026-08-15, #169):** Measured from the local corpus with `tooling/format-scan/scan.py` v0.2.0 (`--json` for `meta_json_by_version`, `--probe-nesting` for layout and rollup shape). **Method:** 2,047 `.jsonl` files, 232,471 lines, 0 parse errors, 294 session dirs, 1,235 `subagents/*.meta.json` manifests spanning 78 distinct CC versions from v2.1.109 to v2.1.233. Manifests carry no `version`, so each is attributed to the earliest version on its own sibling trace file (spawn time); 0 manifests were unattributable and 0 traces spanned a CC upgrade, so attribution is unambiguous throughout. A raw glob finds 1,252 manifests; the 17-manifest difference is session dirs with no sibling parent transcript, which both surfaces skip. Single-user, single-machine corpus.
  1. **`spawnDepth` appears at exactly v2.1.187.** Absent on all 768 manifests at v2.1.186 and earlier; present on all 467 manifests at v2.1.187 and later. A hard boundary, not a smear. This is the JSONL-shape anchor for the v2.1.187 CHANGELOG entry ("Fixed subagent depth tracking… resumed subagents now restore their original spawn depth"), which until now was only a PARTIAL behavioral anchor. Thin bucket caveat: v2.1.187 itself is n=3, but the "before" side is well populated (v2.1.185 n=151, v2.1.186 n=7, all absent).
  2. **Max observed `spawnDepth` is 2.** Depth 2 appears at v2.1.195 (5 of 29 manifests) and v2.1.226 (1 of 88). Every other manifest is depth 1. No depth 0, and nothing at depth 3, 4, or 5 anywhere in the corpus.
  3. **The v2.1.172-vs-v2.1.219 contradiction is partially resolved.** The "(was 1)" clause in v2.1.219 is **refuted** as a description of the actual runtime cap immediately prior: depth-2 CC subagents were recorded at v2.1.195, inside the v2.1.181–v2.1.217 window that clause describes as capped at 1. Whether the cap was ever genuinely 5 (v2.1.172) or is genuinely 3 now (v2.1.219) is **unresolvable from this corpus** — nothing exceeds depth 2 in either window, and `spawnDepth` did not exist before v2.1.187, so v2.1.172–v2.1.186 cannot be measured at all. Absence of depth ≥3 is not evidence of a cap: depth-2 manifests are 6 of 1,235 (0.5%), so this user's workflows simply rarely delegate more than one level. What the data supports documenting is that CC records spawn depth from v2.1.187, that depth > 1 is observed in CC from v2.1.195, and that the cap is version-dependent and controlled by `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH`.
  4. **The flat `subagents/` layout holds at every observed depth.** 0 nested `subagents/` directories across all 294 session dirs (`rglob`, so arbitrary depth, not just one level). Depth-2 traces sit in the same flat `<session-uuid>/subagents/` directory as depth-1 traces. This re-grounds the `subagent-traces.md` L97 conclusion on observation: the layout is flat *and* the depth-1 restriction it was inferred from is gone, so the conclusion survives while its stated reason does not.
  5. **The depth-≥2 no-rollup rule does NOT hold for Claude Code — scope it to the SDK.** All 6 depth-2 spawning `Agent` `tool_result` lines carry a `toolUseResult` sibling (a `dict`), exactly as the 449 depth-1 control sites do (449/449). This is the opposite of the SDK behavior in F-017. CC cost attribution at depth ≥ 2 is therefore **not** degraded. Separately, the inline `subagent_tokens` trailer is **not** a depth marker in CC: it appears on 292 of 449 depth-1 sites and 1 of 6 depth-2 sites, coexisting with the rollup rather than replacing it.
  6. **Spawn sites live one level up, in the spawning agent's own file.** All 453 joinable manifests located their spawning `tool_result` (0 unlocated). Depth-1 sites are in the parent transcript (449/449); depth-2 sites are inside the depth-1 subagent's own trace file (6/6). Tree reconstruction is a cross-file `toolUseId` join, as F-017 describes for the SDK.
  7. **`parentAgentId` is meta.json-only and sparse.** Present on 1 of 1,235 manifests (v2.1.226, a depth-2 one), and **never** as a top-level key on any line across all 2,047 files — the CC camelCase counterpart to the TS SDK's `parent_agent_id` (F-022) does not appear on trace lines in this corpus. The cheap line-level tree linkage F-022 hoped for is not available in CC; the `toolUseId` join remains required.
- **Reference impact:** `reference/subagent-traces.md` (Multi-level section — replace "CC restricts to depth 1" with the observed history: `spawnDepth` recorded from v2.1.187, depth > 1 observed from v2.1.195, cap version-dependent and controlled by `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH`; re-ground the L97 flat-layout inference on the 0-nested-dirs observation; scope the depth-≥2 no-rollup rule to the SDK). `reference/data-dictionary.md` (hook event fields table — add `DirectoryAdded` row; subagent traces section — same stale depth-1 claim).
- **Post potential:** `format-update` — materially corrects the CC depth-1 constraint documented in subagent-traces.md; the F-017 finding now applies to CC as well as the SDK.
- **Sibling-project impact:** AgentFluent and CodeFluent parsers must apply the cross-file `toolUseId` join to CC interactive sessions from **v2.1.195** (observed), not v2.1.219. Parsers that assume CC subagents are always depth-1 will miss depth-2+ subagent data. Two corrections to the earlier reading, both from the #169 scan: (a) CC cost attribution at depth ≥ 2 is **fine** — the `toolUseResult` rollup is present at every observed depth, so the SDK's no-rollup caveat does not transfer; (b) `parentAgentId` is **not** available on CC trace lines, so the line-level tree linkage F-022 describes for the SDK cannot be used here.
- **Decision (2026-08-15):** approve — resolved from observation per #169; reference correction tracked in #157, Part 3 post correction in #170
- **Promotion (2026-08-15):** approve → measured via `scan.py` v0.2.0 (`meta_json_by_version` + `--probe-nesting`, added in #169/PR #171); full result in the Observation block above. Contradiction partially resolved: v2.1.219's "(was 1)" refuted by depth-2 manifests at v2.1.195; the "5 levels" and "depth 3" caps are unobservable in this corpus and are recorded as CHANGELOG claims, not measurements. Dispatched to `reference/subagent-traces.md` + `reference/data-dictionary.md` (#157) and `posts/2026-06-11-inside-the-subagent-trace-file.md` (#170).
- **Status:** promoted

### F-020: `subagent_type: "fork"` — first announced `subagent_type` value since the Agent tool launched

- **Source:** Claude Code CHANGELOG v2.1.213 and v2.1.232, https://raw.githubusercontent.com/anthropics/claude-code/refs/heads/main/CHANGELOG.md, 2026-08-14
- **Added:** 2026-08-14
- **Change type:** `field-added` (new documented value for the `Agent` tool's `subagent_type` input field)
- **Affected message types:** `assistant` (`tool_use.input.subagent_type`); `user`/`tool_result` (`toolUseResult.agentType`)
- **Summary:** CHANGELOG v2.1.213 introduces subagent forking as on by default for interactive sessions, and v2.1.232 makes it explicit: "a `subagent_type: 'fork'` subagent inherits the full conversation and prompt cache, and non-teammate agent spawns in interactive sessions now run in the background by default." This adds a new documented value `"fork"` to the `subagent_type` field on the `Agent` tool's input, and by extension `toolUseResult.agentType` on the parent's user line. Fork subagents have distinct context inheritance semantics (full conversation + prompt cache) and are the default spawn type for non-teammate agents since v2.1.213. ANNOUNCED in v2.1.213 (feature); confirmed default in v2.1.232.
- **Reference impact:** `reference/tool-invocation.md` (Agent tool section — add `subagent_type: "fork"` and its context-inheritance semantics). `reference/data-dictionary.md` (`toolUseResult.agentType` note). `reference/subagent-traces.md` (fork subagents — distinct context inheritance).
- **Post potential:** `format-update`
- **Sibling-project impact:** Parsers routing on `agentType` must handle `"fork"`. Cost attribution for fork subagents differs: they inherit the full parent conversation context, making their `cache_read_input_tokens` larger than a fresh subagent and making the `totalTokens` rollup undercount even more severely than the ~5.8x median documented for general subagents.
- **Status:** queued

### F-021: TS SDK v0.3.216 `tool_result_meta` sidecar on user messages — announced origin of scanner-observed `userFeedback`

- **Source:** Claude Agent SDK TypeScript CHANGELOG v0.3.216, https://raw.githubusercontent.com/anthropics/claude-agent-sdk-typescript/main/CHANGELOG.md, 2026-08-14
- **Added:** 2026-08-14
- **Change type:** `field-added`
- **Affected message types:** `user` (tool-result lines)
- **Summary:** TS SDK v0.3.216 adds "a `tool_result_meta` sidecar to user messages" carrying `non_execution_kind` and `user_feedback`. This is a new top-level envelope key on user lines (alongside `message` and `toolUseResult`). The `user_feedback` sub-key is the announced counterpart to the scanner-observed undocumented `userFeedback` key on user lines in the CC corpus. CC parity is unconfirmed from the SDK CHANGELOG alone, but the scanner's prior observation of `userFeedback` in CC sessions strongly suggests it. Also from v0.3.216: `user_message_uuid` and `request_sent_wall_ms` added to success result messages. ANNOUNCED in TS SDK v0.3.216; CC parity requires observational confirmation.
- **Reference impact:** `reference/data-dictionary.md` (user message section — add `tool_result_meta` as a third top-level sibling key alongside `message` and `toolUseResult`, with `non_execution_kind` and `user_feedback` sub-keys; note that the scanner-observed `userFeedback` likely maps to `tool_result_meta.user_feedback`).
- **Post potential:** `format-update`
- **Sibling-project impact:** AgentFluent and CodeFluent can read `tool_result_meta.user_feedback` as a human-feedback signal on tool results — a new quality-tracking signal.
- **Status:** queued

### F-022: TS SDK v0.3.202 `parent_agent_id` on subagent session messages — tree linkage in session lines

- **Source:** Claude Agent SDK TypeScript CHANGELOG v0.3.202, https://raw.githubusercontent.com/anthropics/claude-agent-sdk-typescript/main/CHANGELOG.md, 2026-08-14
- **Added:** 2026-08-14
- **Change type:** `field-added`
- **Affected message types:** subagent trace lines (lines inside `agent-<id>.jsonl` files)
- **Summary:** TS SDK v0.3.202 adds "`parent_agent_id` field to subagent session messages for building agent trees from disk metadata." This is a new field on lines inside subagent trace files, separate from the scanner-observed `parentAgentId` in `meta.json` (F-002) — it names a field on session message lines themselves. The SDK uses snake_case (`parent_agent_id`); CC JSONL likely uses camelCase (`parentAgentId`), consistent with the format's mixed-casing pattern. This provides a direct tree-linkage mechanism as an alternative to the cross-file toolUseId join described in F-017. CC parity unconfirmed. ANNOUNCED in TS SDK v0.3.202.
- **Reference impact:** `reference/subagent-traces.md` (subagent trace fields table — add `parentAgentId` / `parent_agent_id` with tree-building semantics; note as a direct alternative to the toolUseId cross-file join). `reference/data-dictionary.md` (subagent traces section).
- **Post potential:** `format-update`
- **CC parity (2026-08-15, #169):** **negative in this corpus.** Neither `parentAgentId` nor `parent_agent_id` appears as a top-level key on any line across 2,047 CC `.jsonl` files (232,471 lines). The camelCase counterpart exists only in `meta.json`, and even there it is sparse: 1 of 1,235 manifests, on a depth-2 manifest at v2.1.226. So the line-level tree linkage this candidate describes is SDK-only for now, and CC tree reconstruction still needs the cross-file `toolUseId` join from F-017. Worth re-checking on a later scan — a field appearing on 1 manifest at the newest versions in the corpus looks more like a rollout in progress than a settled absence.
- **Sibling-project impact:** AgentFluent can use `parentAgentId` on subagent trace lines to build the agent tree directly without the multi-step toolUseId join **on SDK sessions**; simplifies the multi-level reconstruction described in F-017 and F-019. On CC sessions the field is not on the lines (see CC parity above), so the `toolUseId` join is still required there.
- **Status:** queued

### F-023: TS SDK v0.3.214 `aborted: true` on interrupted assistant messages + `hookSpecificOutput.sessionTitle`

- **Source:** Claude Agent SDK TypeScript CHANGELOG v0.3.214 and v0.3.152, https://raw.githubusercontent.com/anthropics/claude-agent-sdk-typescript/main/CHANGELOG.md, 2026-08-14
- **Added:** 2026-08-14
- **Change type:** `field-added` (two distinct surfaces: assistant message field and hook response extension)
- **Affected message types:** `assistant` (`aborted` / `isAbortedMidStream`); hook response payloads (`hookSpecificOutput.sessionTitle` on `SessionStart`)
- **Summary:** Two separate TS SDK additions grouped here: (1) v0.3.214 adds `aborted: true` to assistant messages "truncated by `interrupt()`" — the announced counterpart to the scanner-observed `isAbortedMidStream` envelope key on assistant lines (the JSONL field name may differ: `isAbortedMidStream` in CC vs `aborted` in the SDK surface, consistent with the format's mixed-casing). CC parity unconfirmed. (2) v0.3.152 adds `hookSpecificOutput.sessionTitle` to the `SessionStart` hook response — lets a `SessionStart` hook set the session title. This extends the hook response schema documented in reference/ (currently only `additionalContext` from F-014 is documented there) with a second named response key on a different hook event. Neither is announced in the CC CHANGELOG. ANNOUNCED in TS SDK v0.3.214 / v0.3.152; CC parity requires scanner confirmation.
- **Reference impact:** `reference/data-dictionary.md` (assistant section — add `aborted`/`isAbortedMidStream`; Hook response schema section — add `hookSpecificOutput.sessionTitle` on `SessionStart` alongside the existing `additionalContext` on `Stop`/`SubagentStop`).
- **Post potential:** `format-update`
- **Sibling-project impact:** Parsers computing turn success rates or completions should exclude `aborted: true` assistant lines (same pattern as `isApiErrorMessage` from F-008).
- **Status:** queued

### F-024: New system message subtypes — `task_updated` (Python SDK v0.2.101), `background_tasks_changed` (TS SDK v0.3.203)

- **Source:** Claude Agent SDK Python CHANGELOG v0.2.101 (https://raw.githubusercontent.com/anthropics/claude-agent-sdk-python/main/CHANGELOG.md); Claude Agent SDK TypeScript CHANGELOG v0.3.203 (https://raw.githubusercontent.com/anthropics/claude-agent-sdk-typescript/main/CHANGELOG.md), 2026-08-14
- **Added:** 2026-08-14
- **Change type:** `field-added` (new `subtype` values on `system` messages)
- **Affected message types:** `system`
- **Summary:** Two new system message subtypes announced in SDK changelogs, distinct from the scanner-observed values catalogued in issue #153 (`turn_duration`, `local_command`, `away_summary`, `api_error`): (1) Python SDK v0.2.101 exposes `system/task_updated` as a typed `TaskUpdatedMessage` with fields `task_id`, `patch`, `status`, `session_id`, `uuid` — emitted when a task's state changes. Task tools (TaskCreate, TaskStop, TaskOutput) are active in CC per multiple CHANGELOG entries, making CC parity of this event type likely. (2) TS SDK v0.3.203 adds `background_tasks_changed` as a system message "with full live background tasks set on membership changes." Both are new `system` subtype values not yet in reference/. CC parity for both requires observational confirmation from the scanner.
- **Reference impact:** `reference/data-dictionary.md` (system section — add `task_updated` and `background_tasks_changed` as known subtypes with their announced fields, pending CC parity confirmation). Cross-reference with issue #153 (enumerating observed system subtype values).
- **Post potential:** `none` (reference hygiene)
- **Sibling-project impact:** AgentFluent task-state tracking can read `system/task_updated` events to monitor task progression without polling; `background_tasks_changed` provides a roster-level view of background task membership.
- **Status:** queued

### F-025: v2.1.193 auto-mode denial reasons written to transcript — behavioral anchor for `toolDenialKind`

- **Source:** Claude Code CHANGELOG v2.1.193, https://raw.githubusercontent.com/anthropics/claude-code/refs/tags/v2.1.198/CHANGELOG.md, 2026-08-14
- **Added:** 2026-08-14
- **Change type:** `behavior-change`
- **Affected message types:** `assistant` or `system` (auto-mode denial records; carrier type unconfirmed — scanner verification needed)
- **Summary:** CHANGELOG v2.1.193 announces "Added auto-mode denial reasons to the transcript, the denial toast, and /permissions recent denials." The word "transcript" here means the session JSONL, confirming that auto-mode denial events are written as JSONL records. The scanner-observed `toolDenialKind` envelope key is the likely carrier for the denial-reason data on those lines. The field name `toolDenialKind` does not appear in the CHANGELOG — only the behavioral outcome is stated (denial reasons visible in transcript/toast/permissions). This is a PARTIAL announcement: user-facing benefit announced (denial reasons recorded in transcript), JSONL field name SILENT. The introduction version is v2.1.193. Carrier type (`assistant` vs `system` vs a new sub-field on an existing type) requires observational confirmation from the scanner.
- **Reference impact:** `reference/data-dictionary.md` (add `toolDenialKind` entry; note v2.1.193 as the behavioral anchor; carrier type to be confirmed by scanner — likely on `assistant` lines for denied tool calls or on a dedicated `system` denial-record line).
- **Post potential:** `tooling` — denial-reason tracking in session JSONL lets AgentFluent/CodeFluent surface which tool calls were auto-denied and why, without relying on UI-layer signals.
- **Sibling-project impact:** AgentFluent auto-mode diagnostics can use `toolDenialKind` to count and classify denials per session; CodeFluent can flag sessions with high denial rates as candidates for permission-posture review.
- **Status:** queued
