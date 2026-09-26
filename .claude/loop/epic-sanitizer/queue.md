# Loop run: epic-sanitizer

_mode: calibration_
_graduated-routes: none_
_plan-gate: always_
_iteration-cap: none_
_subagent-cap: none_
_Last updated: 2026-09-01T08:00Z_

| #   | Issue                                                       | Route      | Status   | Depends on | PR  | Notes                                                                                    |
| --- | ----------------------------------------------------------- | ---------- | -------- | ---------- | --- | ---------------------------------------------------------------------------------------- |
| 1   | #195 total output-side oracle for path/identifier rules     | code       | done     | —          | #197 | MERGED 2026-08-22 as `91adca1`; issue closed. Scope narrowed to LITERAL rules; regex → #198 |
| 2   | #190 dict keys are never transformed                        | code       | done     | —          | #209 | MERGED 2026-08-24 as `f8f0c96`; #190 closed. Fork `(e)` detect-only; scrub work split to #208. Publish hold left OPEN by human ruling: decide after #198 |
| 3   | #194 bare-name skip-list exempts user data in tool inputs   | code       | done     | —          | #200 | MERGED 2026-08-23 as `b8c2b0c`; #194 + #199 closed. Status reconciled from stale `in-review` at resume 2026-08-24. PyPI 0.4.0 publish still gated on #190 |
| 4   | #192 verify shipped config template achieves coverage       | code       | routed   | —          | —   | priority:medium                                                                            |
| 5   | #32 evaluate Tier 2 patterns for hook coverage              | code       | routed   | —          | —   | no priority label — ranks below priority:low; opens with an architect-review question set |
| 6   | #42 track demand for optional placeholder: field            | code       | parked   | —          | —   | priority:low; awaiting: user demand for human-readable sidecar placeholders               |
| 7   | #1 Epic: Sanitizer design + v0 implementation               | stub-defer | deferred | —          | —   | Epic tracker — the loop does not close epics; closes when its children do                 |
| 8   | #198 regex path/identifier rules get no output-side oracle  | code       | done     | —          | #221 | MERGED 2026-09-01 as `92d7ae1`; #198 closed. Scope NARROWED in review: regex covers reachable VALUE positions; dict keys stay literal-only and moved to #208. No version bump (0.4.0 unreleased), human ruling. Filed: #217-#220, #222, note on #126 |
| 9   | #201 format-scan drift check for uncovered allow-list positions | code   | queued   | —          | —   | priority:medium; PULLED IN 2026-08-24. AC-10's second clause from #194                     |
| 10  | #202 sourceToolAssistantUUID / leafUuid unremapped under remap_uuids | code | queued  | —          | —   | priority:medium; PULLED IN 2026-08-24. Distinct graph-completeness defect under an opt-in flag |
| 11  | #203 sanitized fixture carries org identifier + Cloudflare cookie | code  | queued   | —          | —   | priority:medium; PULLED IN 2026-08-24. Touches `fixtures/` — PR required, security gate applies |
