# fixture-hooks

The hooks that produced the sanitized hook-trace fixtures in
[`fixtures/sanitized/`](../../fixtures/sanitized/), kept here so the experiments
behind [Part 6](../../posts/2026-09-24-what-hooks-leave-behind.md) are
reproducible and so later hook experiments have somewhere to live.

Nothing here runs as part of this repo.

> **Do not register these in this repo's `.claude/settings.json`.** They exist to
> fail, to block, and to write to a side-channel log. Two of them exit non-zero
> on every firing. They belong in a throwaway project, which is where the
> fixtures came from. This repo's own guards are
> [`.claude/hooks/`](../../.claude/hooks/) and are unrelated.

## What is here

| File | Role |
| --- | --- |
| `hooks/_log.py` | Shared side-channel log. Records every firing, whichever way the hook exits |
| `hooks/stop_three_ways.py` | `Stop` hook walking three outcomes once each: block, then `additionalContext`, then allow. Counter-file bounded |
| `hooks/fail_on_stop.py` | `Stop` hook that exits 1 with stderr and no decision, to separate a genuine failure from a block |
| `hooks/fail_on_glob.py` | `PreToolUse` hook that exits 1 without blocking the call |
| `hooks/note_bash.py` | `PostToolUse` hook that prints one fixed line |
| `scratch-project-settings.json` | The hook registration, copied verbatim from the scratch project's `.claude/settings.json` |
| `RUNBOOK.md` | The session-collection procedure |

The log is the control. It records what fired; the session JSONL records what
was kept. The difference between the two is the measurement, and it is how Part 6
can say a `PreToolUse` or `PostToolUse` firing leaves nothing on disk. The tail
of the last run's log:

```
2026-09-22T21:14:04.667+00:00	PostToolUse	Bash	note_bash	printed-output
2026-09-22T21:14:05.836+00:00	Stop	-	stop_three_ways	allow
2026-09-22T21:14:05.837+00:00	Stop	-	fail_on_stop	exit-1-error
```

Three firings. The two `Stop` entries share one `stop_hook_summary` line in the
JSONL. The `PostToolUse` entry has no counterpart at all.

## Which run produced which fixture

Three sessions, and they did not share a configuration. This matters if you
re-run: applying `scratch-project-settings.json` reproduces **run 3**, not the
run the runbook describes.

| Run | Claude Code | Fixture | `hookCount` on `Stop` | Config |
| --- | --- | --- | --- | --- |
| 1 | v2.1.278 | [`hook-trace-prompt-hook-refusal.jsonl`](../../fixtures/sanitized/hook-trace-prompt-hook-refusal.jsonl) | 1 | **not preserved.** Had a `UserPromptSubmit` prompt hook, since removed |
| 2 | v2.1.280 | [`hook-trace-denial-and-stop-ladder.jsonl`](../../fixtures/sanitized/hook-trace-denial-and-stop-ladder.jsonl) | 1 | the runbook's four hooks, `stop_three_ways` alone on `Stop` |
| 3 | v2.1.280 | [`hook-trace-stop-hook-error.jsonl`](../../fixtures/sanitized/hook-trace-stop-hook-error.jsonl) | 2 | as committed here: `fail_on_stop` added alongside `stop_three_ways` |

Run 1's configuration is gone. Its `UserPromptSubmit` prompt hook gave the
evaluating model no condition it could actually judge, so the model read the
prompt as an injected instruction and refused, blocking three of four prompts at
submit time. That accident is the whole content of the run-1 fixture, and it is
the only place in the corpus where `preventContinuation: true` appears.

## What these hooks established

Recorded here because several were surprises, and one was a falsified
prediction:

- **A `PreToolUse` denial writes no `system` line.** `block_secret_reads.py`
  (this repo's real guard, which fires in the scratch project too) produced the
  denial in run 2. The only record is the `user` line carrying `toolDenialKind`.
  This is what #257 corrected in the synthetic fixture.
- **A `Stop`-hook block does not set `preventedContinuation`.**
  `stop_three_ways.py`'s stage-0 docstring predicted that `decision: "block"`
  "should set `preventedContinuation` / `stopReason`". It set neither. The block
  reason landed in `hookErrors`, `preventedContinuation` stayed `false`, and
  `stopReason` stayed `""`. Nothing has ever been observed setting
  `preventedContinuation: true`, which is [#260](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/260).
- **`preventContinuation` and `preventedContinuation` are different fields on
  different line shapes.** The first rides `informational` lines and is the only
  one observed `true`. The second rides `stop_hook_summary` lines. They are easy
  to conflate and mean different things.
- **A `prompt`-type hook is one of five implementation types**, and it renders in
  `hookInfos` like any other. Its refusal text is the evaluating model's own
  prose, not a field. See [#250](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/250).
- **`durationMs` is absent from `hookInfos` on the blocking turn** and present on
  every other turn of the same session. Observed once, unexplained.

## Deliberately not committed

- **`results.md`** from the scratch project. It is `/usage` output: session cost,
  weekly limit percentages, reset times, and a per-plugin breakdown. Personal
  telemetry, not fixture data.
- **`hook-firings.log`** and **`.stop-stage`** as live files. Both are runtime
  state, gitignored in the scratch project. The log tail above is quoted as an
  artifact rather than carried as a file.
- **Raw session JSONL**, per the repo's first rule. The sanitizer is the only
  path from a session into `fixtures/`.

## Adding a hook experiment

1. Add the script under `hooks/`. Import `note` and `read_event` from `_log` so
   the firing is recorded whichever way the hook exits.
2. Register it in a **scratch project**, never here.
3. Write down the prediction before running. `stop_three_ways.py` is worth
   copying for this: its docstring states what each stage should produce, which
   is why the falsified prediction above is recoverable at all.
4. Sanitize the session with [`tooling/sanitizer/`](../sanitizer/) and commit the
   fixture plus its `.scrubbed` sidecar.
5. Record what the run established, including the predictions that failed.
