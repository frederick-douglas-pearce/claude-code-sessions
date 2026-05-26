# Decision Log

Append-only log of significant product and architecture decisions for `claude-code-sessions`. Each entry captures what was decided, why, and what alternatives were considered.

**Entry prefixes:**
- `D` — decisions (a deliberate choice was made; alternatives were considered)
- `O` — observations (a factual finding worth recording that may inform future decisions but isn't itself a decision)

---

## D001 — Cross-sibling update pattern must handle both push and pull

**Date:** 2026-05-26
**Context:** This repo is upstream of both AgentFluent and CodeFluent. When format changes are detected (via W5's format-watch skill), both sibling projects need to be notified.

**Decision:** The cross-post mechanism from this repo's format-watch skill must support both push and pull patterns, because the two sibling projects have different capabilities:

- **AgentFluent** has the `anthropic-research` subagent and `promote-candidates` skill. It can *pull* updates from this repo's `reference/` and format-watch queue. The cross-post route can deposit a candidate into AgentFluent's `anthropic-feature-watch.md` and AgentFluent's existing machinery picks it up.
- **CodeFluent** has neither the research subagent nor the promote-candidates skill. It cannot pull. The cross-post route must *push* to CodeFluent (e.g., open a PR, create an issue, or write directly to a known file) rather than expecting CodeFluent to discover updates on its own.

**Alternatives considered:**
1. *Require CodeFluent to add its own research/promote skills* — rejected for now. CodeFluent is earlier-stage and adding that machinery prematurely would be overengineering. Revisit when CodeFluent's own skill set matures.
2. *Only support pull (ignore CodeFluent)* — rejected. CodeFluent also parses JSONL and needs format updates. Leaving it out of the loop creates silent divergence risk.
3. *Manual-only for v0* — **accepted as the v0 approach.** The push/pull distinction is documented here so the W5 design accounts for it, but v0 cross-posting is manual for both siblings.

**Impact:** W5 epic body flags this as an open design question. No implementation required now, but the W5 PRD must address it before automation work begins.

**Status (2026-05-26):** Superseded in direction by upcoming D002. The repo owner — who also owns CodeFluent — has noted that adding an `anthropic-research`-equivalent skill to CodeFluent is straightforward, and prefers a **symmetric** integration over the asymmetric push/pull pattern recorded above. A design issue ([#13](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/13)) tracks the research that will produce the concrete symmetric design and the superseding decision entry. Until that design lands, the asymmetric path described above is NOT considered the chosen approach.

---

## O001 — Documented 30-day session cleanup does not match observed behavior

**Date:** 2026-05-26
**Type:** Observation (captures a discrepancy between Claude Code's documented retention policy and what's actually on disk on at least one production machine)

**What the docs say:** Claude Code's session documentation ([code.claude.com/docs/en/sessions](https://code.claude.com/docs/en/sessions)) states that local transcript files at `~/.claude/projects/<project>/<session-id>.jsonl` "are removed after 30 days by default," configurable via the `cleanupPeriodDays` setting.

**What was observed (repo owner's machine, 2026-05-26, Claude Code v2.1.150):**

- 556 total `.jsonl` session files across all projects
- 251 (45%) older than 30 days by mtime
- 199 (36%) older than 60 days
- Oldest file: 2026-01-11 (~4.5 months old)
- `cleanupPeriodDays` was not configured at observation time — the documented 30-day default theoretically applied

The documented cleanup is **not running aggressively in practice** on this machine. Possible explanations, none verified:

- Cleanup may trigger only under specific conditions (Claude Code startup state, particular project activity, idle thresholds)
- The mtime-based check may behave differently than the docs imply (e.g., files in actively-used project directories get a reprieve)
- The retention policy may have changed between Claude Code releases without a corresponding docs update
- The cleanup logic may only purge specific subdirectories (e.g., file-history snapshots) rather than full transcripts

**Action taken:** Repo owner set `cleanupPeriodDays: 3650` (10 years — effectively "never auto-cleanup") in `~/.claude/settings.json` to lock in long-term retention regardless of future Claude Code behavior changes.

**Implications for this project:**

- **Posts and reference docs** should describe the documented policy (30-day default, configurable via `cleanupPeriodDays`) without asserting a specific cleanup *behavior* in practice. The W1 post's section on retention has been softened to recommend explicit configuration rather than rely on the default. See implementation in the W1 post (#6) when it lands.
- **AgentFluent and CodeFluent** both analyze historical session data. This observation suggests they are not as exposed to silent data loss as the docs alone would imply, but the risk is real if a future Claude Code release tightens enforcement of the documented policy. Both sibling projects should consider recommending `cleanupPeriodDays` configuration in their setup docs.
- **If `tooling/sanitizer/` ever offers an "archive before sanitize" mode**, this observation reinforces its value: a user-managed archive is the only retention guarantee.
- **Format-watch (W5)** should treat any future change to actual cleanup behavior — or a docs revision that brings the two into alignment — as a notable upstream event.

**Follow-ups (none filed yet):**

- Could file an issue to document the recommended `cleanupPeriodDays` configuration in an eventual onboarding/setup post or in `reference/data-dictionary.md` under file-location.
- Re-check this observation periodically; if a future Claude Code release actually enforces the documented 30-day cleanup, the language in posts and reference docs needs another revision.

---
