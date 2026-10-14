# Plan: #295, run the hook-capture strategies

Status: architect-reviewed and approved 2026-10-13 (D1-D5 accepted as recommended). Kit built in
`tooling/fixture-hooks/capture/`. Claude Code under test: **v2.1.299**.

**The exact procedure lives in [`RUNBOOK-295.md`](../../tooling/fixture-hooks/capture/RUNBOOK-295.md)**, which
supersedes Phase 1 below where they differ (it adds the S1b `unittest` wording, the one-time
**Yes** on prompts, and the sanitize commands).

## Goal

Replace every docs-sourced claim in #295 and the #285 checklist with an observed
answer, on one Claude Code version, in as few manual sessions as possible. Fred
drives the sessions. Claude builds and smoke-tests the kit beforehand and does the
analysis after, reading only `analyze.py` output and sanitized files.

## What changed since the issue was written

Re-reading the current docs turned up four things that change the plan:

1. **A fifth capture source: the debug log.** From v2.1.296, `--debug-file <path>`
   writes one line per command hook per firing:
   `Hooks: PreToolUse:Read [<command>] finished with status 0 (31ms)`, or
   `timed out after <N>ms`, `cancelled`, `failed to start`. That is per-hook
   identity and duration with no code. The docs promise it for command hooks only,
   and it carries no `tool_use_id`. The aside's comparison table needs this row.
2. **Agent hooks bill as `"subagent"`.** Per the `subagent_completed` docs, the
   metrics `query_source` category `"subagent"` "also counts requests from
   agent-based hooks." Prompt hooks are undocumented. Note the two vocabularies:
   events use `repl_main_thread`/`compact`/agent name, metrics use
   `main`/`subagent`/`auxiliary`.
3. **A prompt hook's `ok: false` on `PreToolUse` ends the turn by default**
   (since v2.1.210) unless `continueOnBlock: true`. S3 sets it.
4. **`--setting-sources project,local`** drops user settings for one session,
   removing the two global guards from the measurement sessions so telemetry
   counts describe only the hook under test.

Confirmed from docs, unchanged: `http` hook non-2xx, connection failure and
non-JSON 2xx are non-blocking errors; a timed-out `command`/`http` hook on
`PreToolUse` "doesn't block the tool call"; hooks run before permission prompts;
`settings.json` hooks fire inside subagents; hook processes do not inherit `OTEL_*`;
`allowedHttpHookUrls` restricts only "when defined"; `claude-haiku-5-5` is a valid
model id.

## Fred's decisions (all accepted 2026-10-13)

| # | Decision | Recommendation |
| --- | --- | --- |
| D1 | Isolate sessions with `--setting-sources project,local` | Yes. The scratch session then runs without `block_secret_reads.py`, acceptable in a throwaway directory with nothing sensitive in it. Pre-flight P1 confirms plugins are dropped too |
| D2 | Telemetry transport | OTLP `http/json` to a local stdlib sink with an attribute **allowlist**, not `OTEL_LOGS_EXPORTER=console`. Console output's destination in the TUI is undocumented, and the sink keeps identity attributes off disk |
| D3 | API key for the S3 judge client | A Console key in a `chmod 600` file named by `JUDGE_KEY_FILE`. **Not** `ANTHROPIC_API_KEY` in the launching shell: Claude Code would switch the whole session to API-key auth. Cost: a few cents |
| D4 | Does S1b (a scripted small coding task) satisfy "measured on at least one real session"? | Yes for #295. Step 5 (dispatcher in front of the global guards for days) deferred until S1's overhead numbers are in |
| D5 | Detailed beta tracing in `-p` mode (S4) | Skip unless S1 leaves hook identity open. `hook_registered` already gives `hook_type`/`hook_source` per configured hook |

## Phase 0: build the kit (Claude, PR `feature/295-hook-capture-kit`)

New directory `tooling/fixture-hooks/capture/`, stdlib Python only, never
registered in this repo. Every writer names its output `<name>-$HOOKCAP_TAG.jsonl`
so sessions never share a file.

| File | Role |
| --- | --- |
| `otlp_sink.py` | `http.server` on `127.0.0.1:4318`. Accepts OTLP/JSON on **any** POST path and records the path. Flattens each log record, metric point and span to one line in `otel-<tag>.jsonl`. **Allowlist:** values kept only for named attributes (`event.name`, `event.timestamp`, `event.sequence`, `session.id`, `prompt.id`, hook/tool/api counters and enums, token counts, `query_source`, `model`, `tool_use_id`, `agent.name`). Every other attribute is written as name, type and length only, so new attributes are noticed without their values landing on disk |
| `dispatcher.py` | The dispatcher under test. Logs `enter` as its first statement (epoch ms, before other imports), `exit` in `finally`, and `killed` from a SIGTERM handler. One `os.write` per line on an `O_APPEND` fd. Fields: `ts_ms`, `phase`, `pid`, `session_id`, `tool_use_id`, `agent_id`, `agent_type`, `event`, `tool`, `route`, `decision`, `duration_ms`. Never `tool_input`. **Routes only when `hook_event_name == "PreToolUse"`**; PostToolUse logs and decides nothing |
| `http_guard.py` | `http.server` on `127.0.0.1:8765`. Denies a `Read` whose basename starts with `forbidden-http-`, empty 2xx otherwise. `--mode up\|500\|slow`. Logs timestamp, mode, basename and response code only; no request bodies |
| `judge_client.py` | `command` hook calling the Messages API through the `anthropic` SDK (in the scratch `.venv`) with the same prompt and model as the S3 prompt hook. Logs `usage` and `ok` to `judge-<tag>.jsonl`, never the model's `reason` |
| `analyze.py` | Content-free report. Joins telemetry by `event.sequence` adjacency to `tool_decision` (which carries `tool_use_id`), the debug log by timestamp to the dispatcher's `exit`, and the dispatcher log on `tool_use_id`. From the debug log it keeps only event, tool, status and duration; bracket text (command path, home dir) is dropped. Counts `[3P telemetry]` export-error lines. `--baseline` times 20 runs of `python3 -c pass` |
| `tests/test_contract.py`, `tests/test_hooks.py` | Content-free contract tests for the sink and `analyze.py`, plus route, kill and parallel-append tests for the hooks in the format-scan style: synthetic inputs with planted canary strings; assert none reach the output. Local pytest, not attached to `format-scan-ci` |
| `settings-s1.json`, `settings-s2.json`, `settings-s3.json` | One per session |
| `env.sh` | Telemetry variables (below) |
| `make-sentinels.sh` | Writes every sentinel file with its own name inside; rerun to reset |
| `RUNBOOK-295.md` | The procedure in Phase 1, in RUNBOOK.md's style |

`env.sh`:

```bash
export CLAUDE_CODE_ENABLE_TELEMETRY=1
export OTEL_LOGS_EXPORTER=otlp
export OTEL_METRICS_EXPORTER=otlp
export OTEL_EXPORTER_OTLP_PROTOCOL=http/json
export OTEL_EXPORTER_OTLP_LOGS_ENDPOINT=http://127.0.0.1:4318/v1/logs
export OTEL_EXPORTER_OTLP_METRICS_ENDPOINT=http://127.0.0.1:4318/v1/metrics
export OTEL_LOGS_EXPORT_INTERVAL=1000
export OTEL_METRIC_EXPORT_INTERVAL=5000
```

Dispatcher routes (PreToolUse `Read`, by basename). Each sentinel file contains
`sentinel: <its own name>`, so the visible result shows which file was read.

| Sentinel | Route | Hook returns |
| --- | --- | --- |
| `plain-1.txt`, `p1.txt`…`p4.txt`, `explore.txt` | `no-decision` | exit 0, no stdout |
| `allow.txt` | `allow` | `permissionDecision: "allow"` |
| `ask.txt` | `ask` | `permissionDecision: "ask"` |
| `rewrite.txt` | `rewrite` | `allow` + `updatedInput` with `file_path` → `rewrite-target.txt` |
| `forbidden.txt` | `deny` | `deny`, reason: "Denied by the dispatcher. Do not retry by any other means; stop and report the denial." |
| `denied-by-rule.txt` | `no-decision` | exit 0 (the settings deny rule does the blocking) |
| `slow.txt` | `sleep` | sleeps 20 s |
| `crash.txt` | `crash` | logs `enter`, `os._exit(1)` |

Claude smoke-tests the sink, dispatcher and guard by piping synthetic payloads
before the PR, without starting `claude`.

## Phase 1: Fred runs the sessions

### Setup, once

```bash
mkdir -p ~/scratch/hook-capture/work/notes && cd ~/scratch/hook-capture
git init -q
cp -r <repo>/tooling/fixture-hooks/capture/* .
./make-sentinels.sh            # writes every sentinel with its own name inside
printf 'the quick brown fox\n' > work/notes/a.txt
printf 'jumps over the lazy dog\n' > work/notes/b.txt
printf '*.jsonl\n*.log\n' > .gitignore
```

### Per-session routine

1. Make sure no `claude` is running in this directory, then
   `cp settings-sN.json .claude/settings.json`. Hooks hot-reload, so never swap
   mid-session.
2. Terminal A: `python3 otlp_sink.py --tag sN`.
3. Terminal B:
   ```bash
   source env.sh
   export HOOKCAP_TAG=sN
   uuidgen   # write it down: it names the session file to sanitize
   claude --model sonnet --setting-sources project,local --permission-mode default \
          --debug-file ./debug-sN.log --session-id <uuid>
   ```
4. Trust the directory. Hooks are held back until you do.
5. `/hooks`: confirm only this session's hooks, no plugin or user hooks.
6. Type each prompt; check the visible expectation before the next one. If it is
   wrong, stop and note it. A half-failed run documents nothing.
7. Wait 5 s after the last prompt (log flush), then `/exit`. Stop the sink.

Every Read prompt uses this wording, so the model cannot route around a hook:

> Use the Read tool to read `<file>`. If the call is denied, stop and report the
> denial; do not retry by any other means.

### S1: telemetry + dispatcher (#285 checklist, step 2 mechanics)

`settings-s1.json`: `dispatcher.py` on `PreToolUse` and `PostToolUse`, matcher
`"*"`, `timeout: 5` on **both**; `permissions.deny: ["Read(./denied-by-rule.txt)"]`.

| # | Prompt (file) | Visible expectation | Check after (`analyze.py`) |
| --- | --- | --- | --- |
| 1.0 | `Reply with the single word READY.` | READY | **Pre-flight.** P1: `hook_registered` shows only `projectSettings` hooks (no `userSettings`, no `pluginHook`). P2: sink received batches on `/v1/logs`; no `[3P telemetry]` errors |
| 1.1 | `plain-1.txt` | `sentinel: plain-1.txt` | `source` for a no-decision exit 0 (docs suggest `"config"`); `num_hooks: 1`, `num_success: 1` |
| 1.2 | `allow.txt` | contents | `source: "hook"`, `decision: "accept"` |
| 1.3 | `ask.txt` | a permission prompt; **approve once** (option 1) | `source` after a hook `ask` the user approved (likely `user_temporary`) |
| 1.4 | `rewrite.txt` | `sentinel: rewrite-target.txt` | what the session file's `tool_use` input shows: original or rewritten path (sanitized file) |
| 1.5 | `forbidden.txt` | denial with the dispatcher's reason, no retry | `source: "hook"`, `reject`; whether a JSON deny counts as `num_blocking` (P4) |
| 1.6 | `denied-by-rule.txt` | permission denial | P3: did the dispatcher fire at all? `source: "config"`, `reject` |
| 1.7 | `slow.txt`; **wait 25 s** before the next prompt | ~5 s pause, then contents | `num_cancelled` vs `num_non_blocking_error` (open); debug line `timed out after 5000ms`; dispatcher phases: `enter` + `killed`? `exit` at ~20 s? (open) |
| 1.8 | `crash.txt` | hook error notice, then contents | `num_non_blocking_error: 1`; debug status 1; `enter` only |
| 1.9 | `Use the Read tool to read p1.txt, p2.txt, p3.txt and p4.txt. Issue all four Read calls in a single message, in parallel.` | four contents | every line valid JSON (no torn appends); PostToolUse `enter` times overlap; PreToolUse overlap is **not** guaranteed by the docs (open) |
| 1.10 | `@explore Use the Read tool to read explore.txt and report its contents.` (pick Explore from the @-menu) | subagent reports `sentinel: explore.txt` | dispatcher payload has `agent_id`/`agent_type`; hook telemetry has no agent attribute; `api_request` has `agent.name` |

The subagent transcript lives at `<sessionId>/subagents/agent-<agentId>.jsonl` and
gets sanitized with the main file.

### S1b: a real-ish session (silent allows, overhead)

Same settings and routine, tag `s1b`. One prompt:

> Write a Python script work/wc.py that counts the words in every .txt file under
> work/notes/, add a pytest test in work/test_wc.py, and run the test. Approve
> permission prompts as they come.

Measures: **silent allows**, defined as PreToolUse `no-decision` firings whose
`tool_use_id` reaches a PostToolUse `exit`. **Overhead** per call: debug-log
duration minus in-script `duration_ms`, matched by timestamp; parallel batches
excluded since they cannot be matched. Telemetry `total_duration_ms` as the
outside view, `--baseline` as the floor.

### S2: `http` hook fail-open (step 3)

`settings-s2.json`: one `PreToolUse` `http` hook, matcher `Read`,
`url: http://127.0.0.1:8765/pre`, `timeout: 5`. Terminal C runs
`python3 http_guard.py --mode up`. A fresh file each step so the model cannot
answer from context.

| # | Action, then prompt | Visible expectation | Check after |
| --- | --- | --- | --- |
| 2.1 | `forbidden-http-1.txt` | denied | guard logged the request; `source: "hook"`, `reject` |
| 2.2 | Ctrl+C the guard. `forbidden-http-2.txt` | **contents shown** (fail-open) | any UI notice; `num_non_blocking_error`; is there a debug `Hooks:` line for an http hook (P7)? |
| 2.3 | Start `--mode 500`. `forbidden-http-3.txt` | contents shown | same counters as 2.2? |
| 2.4 | Start `--mode slow`. `forbidden-http-4.txt`; wait 10 s | ~5 s pause, contents | `num_cancelled` vs `num_non_blocking_error` |
| 2.5 | Start `--mode up`. `forbidden-http-5.txt` | denied | recovery needs no Claude Code restart |

### S3: prompt hook vs shared API client (step 4)

Before launching: `export JUDGE_KEY_FILE=~/.config/hook-judge/key`.
`settings-s3.json` registers **both** on `PreToolUse` matcher `Bash`, so they judge
the same call in parallel: a `prompt` hook (`model: "claude-haiku-5-5"`,
`continueOnBlock: true`) and `judge_client.py` with the same model. Both use this
prompt:

> You are a gate for one shell command. The hook input JSON is: $ARGUMENTS. Judge
> one thing only: does `tool_input.command` only read state (list, print,
> inspect) without creating, modifying or deleting any file? If it only reads,
> return {"ok": true}. Otherwise return {"ok": false, "reason": "Blocked by the
> read-only judge. Do not retry by any other means; stop and report the block."}

| # | Prompt | Visible expectation | Check after |
| --- | --- | --- | --- |
| 3.0 | `Reply with the single word READY.` then wait 10 s | READY | warm-up, so title generation (also Haiku) does not land inside a hook bracket |
| 3.1 | `Run: ls` | listing | `api_request` events inside the hook's start/complete `event.sequence` bracket: `query_source`, tokens, `cost_usd`; metrics category; `judge-s3.jsonl` usage for the same call |
| 3.2 | `Run: rm plain-1.txt. If it is blocked, do not retry; stop and report the block.` | block reported, **file still exists** | same, on the deny path |

Expect the token counts to differ: Claude Code wraps the prompt hook's text. The
comparison is about visibility, not equality. Recreate sentinels with
`./make-sentinels.sh` afterward in case 3.2 got through.

### S4 (optional, D5)

Headless `-p` runs of 1.1 and 1.5 with `ENABLE_BETA_TRACING_DETAILED=1`,
`BETA_TRACING_ENDPOINT` at the sink and `OTEL_LOG_TOOL_DETAILS=1`, for
`claude_code.hook` spans. Note the docs: this pair "changes where your logs and
traces go", so S4 never shares a sink file with S1-S3.

## Pre-flight checks (unverified in the docs)

| Id | Question | Where it gets answered |
| --- | --- | --- |
| P1 | Does `--setting-sources project,local` drop user `enabledPlugins` and plugin hooks? | 1.0 (`/hooks`, `hook_registered`) |
| P2 | Does the per-signal OTLP endpoint config reach the sink? | 1.0 |
| P3 | Does a call blocked by a settings deny rule still reach PreToolUse? | 1.6 |
| P4 | Does a JSON `deny` count as `num_blocking`? | 1.5 |
| P5 | What does a timeout send the hook, and which counter moves? | 1.7, 2.4 |
| P6 | Does PreToolUse run concurrently for parallel calls? | 1.9 |
| P7 | Do http hooks get debug `Hooks:` lines? | 2.2 |

## Phase 2: Claude analyzes and writes up

1. Fred sanitizes each session file (and the S1 subagent file) with `ccs-sanitize`,
   `remap_uuids` off so `tool_use_id` survives. Claude runs `analyze.py` on the
   scratch files and reads only its output plus sanitized files.
2. #285: post the observed checklist answers, including `ask` and `updatedInput`.
3. #295: each strategy's claimed strength and cost confirmed or corrected, the
   debug-log row, silent-allow count, overhead, P1-P7 answers, version.
4. Fixtures PR: any new session-file shape (rewritten input, `http` hook error,
   subagent hook lines) into `fixtures/sanitized/` with sidecars, plus the kit
   README's "what the runs established", failed predictions included.
5. Reference: OTel and debug-log cross-reference in
   `reference/data-dictionary.md` § hook-event fields; anything else filed.
6. Go/no-go on the aside; if go, an entry under Asides in
   `.claude/specs/series-outline.md`.

## Data safety

- The sink keeps values only for allowlisted attributes. `OTEL_LOG_TOOL_DETAILS`
  and `OTEL_LOG_USER_PROMPTS` stay off outside S4.
- The debug log is raw (home-dir command paths, hook stdout). Only `analyze.py`'s
  parsed fields leave the scratch directory.
- `dispatch-*.jsonl`, `http-guard-*.jsonl`, `judge-*.jsonl` hold ids, decisions and
  counts only, by construction.
- Nothing from `~/scratch/hook-capture` is committed except via the sanitizer.
