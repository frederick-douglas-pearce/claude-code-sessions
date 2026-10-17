# capture

The #295 kit for comparing ways to record every hook decision, extended for #303's fail-closed tests. The procedure is
[`RUNBOOK-295.md`](RUNBOOK-295.md), and the design and its review are in
[`.claude/specs/plan-295-hook-capture.md`](../../../.claude/specs/plan-295-hook-capture.md).
Like the rest of `fixture-hooks/`, nothing here is registered in this repo.

| File | Role |
| --- | --- |
| `dispatcher.py` | One `command` hook on every `PreToolUse` and `PostToolUse` call. Picks a route by file name (allow, ask, rewrite, deny, sleep, crash, or no decision) and logs each firing. `--set s4` adds #303's fail-closed routes, and a `.hookcap-off` file acts as a kill switch |
| `otlp_sink.py` | Local OTLP/JSON receiver. Keeps attribute values only on an allowlist |
| `http_guard.py` | The `http` hook's server, with `up`, `500` and `slow` modes |
| `judge_client.py` | A `command` hook that judges a Bash call through the Anthropic SDK, beside a `prompt` hook doing the same |
| `analyze.py` | Joins the hook logs, telemetry, the `--debug-file` `Hooks:` lines and a sanitized session. Prints ids, numbers and closed-vocabulary values only |
| `settings-s1/s2/s3.json`, `env.sh`, `make-sentinels.sh` | Session settings, telemetry environment, sentinel files |
| `settings-s4/s5.json` | #303's sessions: `onFailure: "block"` on `command` and `http` hooks, the in-hook alternatives, missing scripts, and a `prompt` hook timeout, each scoped to one file with `if` |
| `tests/` | Unit and planted-canary contract tests: `python3 -m pytest tooling/fixture-hooks/capture/tests/` |

## What these runs established

From the first series, run 2026-10-15 and 2026-10-16. The step numbers refer to
the runbook. Each row names the version it was seen on and the record that shows
it, so it can be re-checked on a later version. Every row comes from `analyze.py`
output or from key names and closed-vocabulary values in the sanitized files,
never from raw session data.

| # | Finding | Version | Step | Evidence |
| --- | --- | --- | --- | --- |
| 1 | `--setting-sources project,local` stops user hooks from running, but `/hooks` and the `hook_registered` event still list them | 2.1.301 | P1 | debug `Hooks:` lines: 0 with the flag, the guard plus every user command hook without it |
| 2 | A `PreToolUse` hook that crashes, times out, or gets an HTTP error leaves the same JSONL record as a hook that chose to stay silent: `permissionDecision {accept, config, mode}`, with no `hookInfos` or `hookErrors` | 2.1.299, 2.1.301 | 1.7, 1.8, 2.2–2.4 | sanitized JSONL |
| 3 | A crash and an HTTP error show a UI notice. A timeout, `command` or `http`, shows none. The model is told about none of them | 2.1.299, 2.1.301 | 1.7, 1.8, 2.2–2.4 | screen notes |
| 4 | An `http` hook that answers after its timeout is ignored: the guard's late deny was discarded and the read went through | 2.1.301 | 2.4 | `http-guard-s2.jsonl`, sanitized JSONL |
| 5 | `user` lines carry `permissionDecision {decision, source, reasonType}`. `source: hook` separates a hook decision from `config` and `user_temporary`. Documented in [`reference/data-dictionary.md`](../../../reference/data-dictionary.md#permissiondecision-values) ([#299](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/299)) | 2.1.299, 2.1.301 | all | sanitized JSONL |
| 6 | A settings deny rule on `Read` is enforced in the tool's path validation: no `PreToolUse` firing, no `permissionDecision`, no `toolDenialKind`, no `tool_decision` event | 2.1.299 | 1.6 | sanitized JSONL, telemetry, dispatcher log |
| 7 | Hook telemetry counts: a `command` JSON deny is `num_blocking: 1`, but an `http` JSON deny is `num_success: 1, num_blocking: 0`. Errors count as `num_non_blocking_error`, timeouts as `num_cancelled` at about 5020 ms | 2.1.299, 2.1.301 | 1.5, 1.7, 1.8, 2.1–2.5 | telemetry |
| 8 | A timed-out `command` hook is sent SIGTERM | 2.1.299 | 1.7 | dispatcher log |
| 9 | Debug `Hooks:` lines cover `command` hooks only, not `http` or `prompt` hooks. `tool_decision` carries `tool_use_id`, and in S1 all 13 matched a transcript `tool_use` (the 14th call, step 1.6, had no `tool_decision`). The hook execution events and the debug log carry no `tool_use_id`, so a hook firing joins to its call only through `event.sequence` and timestamps | 2.1.299, 2.1.301 | S1, S2, S3 | debug log, telemetry, sanitized JSONL |
| 10 | A Python `command` hook costs a median of about 63 ms per firing, against about 5 ms inside the script and about 15 ms of interpreter startup | 2.1.299, 2.1.301 | S1, S1b | `analyze.py --baseline`, dispatcher log, debug log |
| 11 | Of four parallel `Read` calls, only two `PreToolUse` firings overlapped in time | 2.1.299 | 1.9 | dispatcher log |
| 12 | A rewrite through `updatedInput` leaves the original input in the transcript. The model cannot tell the path was swapped | 2.1.299 | 1.4 | sanitized JSONL |
| 13 | When two hooks deny one call, telemetry counts `num_blocking: 2` but only one reason reaches the screen | 2.1.301 | 3.2 | telemetry, screen notes |
| 14 | A `prompt` hook's call shows as `query_source: hook_prompt` and reads from the prompt cache. Three calls cost $0.000427 in all. The SDK client sent about 700 uncached input tokens per call and took 2.7 to 3.2 s | 2.1.301 | 3.1, 3.2 | telemetry, `judge-s3.jsonl` |
| 15 | A subagent's hook input carries `agent_id` and `agent_type` (`Explore`), and its API calls carry `query_source: agent:builtin:Explore` in telemetry | 2.1.299 | 1.10 | dispatcher log, telemetry |
| 16 | `PostToolUse` `num_hooks` exceeds the configured count (Read and Write by 1, Bash by 2, Agent by 0). Unexplained; likely internal callbacks | 2.1.299, 2.1.301 | S1, S1b | telemetry |
| 17 | New line types `api-request`, `api-request-blob` and `api-request-shape` repeat request content. Sanitizer 0.5.0 passed them through; 0.6.0 drops them by default ([#298](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/298)) | 2.1.301 | S1b, S2, S3 | sanitized JSONL key names |
| 18 | `user` and `assistant` lines carry a snake_case `session_id` equal to `sessionId`. Subagent files do not | 2.1.299, 2.1.301 | all | sanitized JSONL |

The raw logs, telemetry and session files behind these rows stay in the scratch
project. None of them is committed.

## Fixtures

All four sessions are committed. S1 was sanitized with `ccs-sanitize` 0.5.0. It ran on
v2.1.299, before the `api-request*` line types, and carries
`permissionDecision` with all three `source` values seen in the series (`hook`,
`config`, `user_temporary`), `toolDenialKind` on the hook deny, and
`session_id`.

| Fixture | Source |
| --- | --- |
| [`hook-trace-dispatcher-decisions.jsonl`](../../../fixtures/sanitized/hook-trace-dispatcher-decisions.jsonl) | S1, steps 1.0 to 1.10 |
| [`hook-trace-dispatcher-explore-subagent.jsonl`](../../../fixtures/sanitized/hook-trace-dispatcher-explore-subagent.jsonl) | S1's Explore subagent, step 1.10 |
| [`hook-trace-dispatcher-small-task.jsonl`](../../../fixtures/sanitized/hook-trace-dispatcher-small-task.jsonl) | S1b, step 1b.1 |
| [`hook-trace-http-hook-fail-open.jsonl`](../../../fixtures/sanitized/hook-trace-http-hook-fail-open.jsonl) | S2, steps 2.1 to 2.5 |
| [`hook-trace-prompt-hook-and-api-judge.jsonl`](../../../fixtures/sanitized/hook-trace-prompt-hook-and-api-judge.jsonl) | S3, steps 3.0 to 3.2 |

S1b, S2 and S3 ran on v2.1.301 and were sanitized with 0.6.0, which drops their
`api-request*` lines
([#298](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/298)).
Each sidecar's `stripped_lines` counts them. All four sessions carry
`cost-state`, a per-session cost rollup by model, and `atis-latch`; S1b also
carries `file-history-delta` for the two files it wrote. None of the three is
in `reference/` yet (format-watch F-027, F-028 and F-018).

- **S1b** is the baseline: a task the model planned itself, with every call
  passing through the dispatcher, which stayed silent. None of the four
  closing lines names the hook. The Bash listing is credited to `config`
  (`subcommandResults`), and the two writes and the test run to the user
  (`user_temporary`).
- **S2** is the fail-open record. Steps 2.2 to 2.4 (guard down, HTTP 500, late
  answer) close with `{accept, config, mode}`, the same record as a silent
  allow, while 2.1 and 2.5 are hook denies.
- **S3** has two Bash calls the judges allowed and one they blocked
  (`rm plain-1.txt`). Telemetry counted two blocking hooks on that call; the
  session file keeps one reason. Its `cost-state` puts Haiku at $0.000552,
  against $0.000131 in S1b and S2, where Haiku did only background work. The
  difference is close to the $0.000427 telemetry put on the `prompt` hook's
  three calls. The SDK client's calls go to the API outside Claude Code and
  are not in it.
