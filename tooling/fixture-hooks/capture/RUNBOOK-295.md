# Hook-capture runbook (#295)

The procedure for the four capture sessions behind
[#295](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/295):
built-in telemetry, a dispatcher `command` hook, an `http` hook that fails open,
and a shared API client for a model-judged check. The plan and its architect
review are in
[`.claude/specs/plan-295-hook-capture.md`](../../../.claude/specs/plan-295-hook-capture.md).
This file is the authoritative procedure.

Run it in **new terminals**, in a throwaway project, never from a session
working on this repo. Written for Claude Code **v2.1.299**. If `claude --version`
says otherwise, note the version and carry on. The first series did not hold one
version: S1 ran on v2.1.299 and an auto-update moved S1b, S2 and S3 to v2.1.301.
`env.sh` now turns the auto-updater off in the terminal that sources it, but check
the version before every session anyway.

Every command below that writes into the project starts with
`cd ~/scratch/hook-capture &&`. A terminal left in the repo after the sanitize
step once had the scratch settings written over the repo's own
`.claude/settings.json`, which switched off the repo's guards until it was
restored.

## What you need

- Three terminals: A for the telemetry sink, B for `claude`, C for the HTTP
  guard (S2 only).
- `uuidgen`.
- For S3 only: an Anthropic Console API key. It goes in a file, never in
  `ANTHROPIC_API_KEY`: that variable in terminal B would switch the whole
  session to API-key auth.

## Setup, once

```bash
REPO=~/path/to/claude-code-sessions            # adjust
mkdir -p ~/scratch/hook-capture/.claude ~/scratch/hook-capture/work/notes
cd ~/scratch/hook-capture
git init -q
cp "$REPO"/tooling/fixture-hooks/capture/*.py "$REPO"/tooling/fixture-hooks/capture/*.sh \
   "$REPO"/tooling/fixture-hooks/capture/settings-s*.json .
./make-sentinels.sh
printf 'the quick brown fox\n' > work/notes/a.txt
printf 'jumps over the lazy dog\n' > work/notes/b.txt
printf '*.jsonl\n*.log\nlatest\n.venv/\nsanitized/\n' > .gitignore   # --debug-file also writes a `latest` symlink
python3 -m venv .venv && .venv/bin/pip install -q anthropic   # S3's judge client
```

For S3, put the key in a file with an editor, so it never lands in shell history:

```bash
mkdir -p ~/.config/hook-judge && chmod 700 ~/.config/hook-judge
$EDITOR ~/.config/hook-judge/key      # paste the key, save
chmod 600 ~/.config/hook-judge/key
```

## Every session

Replace `sN` with the session's tag (`s1`, `s1b`, `s2`, `s3`).

1. Make sure no `claude` is running in this directory. Hooks hot-reload, so a
   settings swap mid-session changes the experiment under you.
2. `cd ~/scratch/hook-capture && cp settings-<session>.json .claude/settings.json`.
   S1b reuses `settings-s1.json`.
3. Terminal A: `python3 otlp_sink.py --tag sN`. Leave it running.
4. Terminal B:

   ```bash
   cd ~/scratch/hook-capture && source env.sh
   export HOOKCAP_TAG=sN
   SID=$(uuidgen); echo "$SID"        # write it down next to the tag
   claude --model sonnet --setting-sources project,local --permission-mode default \
          --debug-file ./debug-sN.log --session-id "$SID"
   ```

5. Trust the directory. Hooks are held back until you do.
6. Type `/hooks`. Expect this session's hooks under project settings. **`/hooks`
   also lists your user hooks (`[User]`), and that is expected:** on v2.1.301
   they are listed but do not run under `--setting-sources project,local`. The
   `hook_registered` telemetry event lists them too. The
   [P1 check](#pre-flight-p1-do-user-hooks-run-under---setting-sources) is what
   showed this. A **plugin** hook in the list is a real problem: stop and note
   it. Escape out.
7. Type each prompt below, one per turn. After each, check the expectation
   before the next. If it is wrong, stop and write down what happened. A
   half-failed run documents nothing.
8. After the last prompt, wait 5 seconds for the exporters to flush, then
   `/exit`. Ctrl+C the sink.

Every Read prompt below ends with the same sentence. Type it every time: it is
what stops the model routing around a hook with Bash after a denial.

## S1: telemetry and the dispatcher

`settings-s1.json` puts `dispatcher.py` on every `PreToolUse` and `PostToolUse`
call with `timeout: 5`, and adds a settings deny rule for `denied-by-rule.txt`.

| # | Type this | Expect |
| --- | --- | --- |
| 1.0 | `Reply with the single word READY.` | READY. Terminal A prints `sink: POST /v1/logs: N records` within a few seconds. **If it prints nothing, stop** (pre-flight P2) |
| 1.1 | `Use the Read tool to read plain-1.txt. If the call is denied, stop and report the denial; do not retry by any other means.` | `sentinel: plain-1.txt` |
| 1.2 | Same sentence, file `allow.txt` | `sentinel: allow.txt` |
| 1.3 | Same sentence, file `ask.txt` | A permission prompt. Choose the plain **Yes** (once). Never "don't ask again": that writes a local settings file. Then `sentinel: ask.txt` |
| 1.4 | Same sentence, file `rewrite.txt` | `sentinel: rewrite-target.txt`. The hook swapped the path |
| 1.5 | Same sentence, file `forbidden.txt` | A denial carrying the dispatcher's reason, and no retry |
| 1.6 | Same sentence, file `denied-by-rule.txt` | A permission denial |
| 1.7 | Same sentence, file `slow.txt` | About a 5 second pause, then `sentinel: slow.txt`. **Then wait 25 seconds** before the next prompt, so the sleeping hook has finished one way or another |
| 1.8 | Same sentence, file `crash.txt` | A hook error notice, then `sentinel: crash.txt` |
| 1.9 | `Use the Read tool to read p1.txt, p2.txt, p3.txt and p4.txt. Issue all four Read calls in a single message, in parallel.` | Four sentinel lines |
| 1.10 | Type `@`, pick the **Explore** agent from the menu, then: `Use the Read tool to read explore.txt and report its contents.` | Explore runs and reports `sentinel: explore.txt`. If the menu offers no agents, type `Use the Explore subagent to read explore.txt with the Read tool and report its contents.` and note that you did |

## S1b: an ordinary small task

Same settings as S1. The point is the silent-allow count and the overhead
spread on calls the model chose itself.

| # | Type this | Expect |
| --- | --- | --- |
| 1b.1 | `Write a Python script work/wc.py that counts the words in every .txt file under work/notes/, add a unittest test in work/test_wc.py, and run it with python3 -m unittest. Only touch files under work/.` | Approve each permission prompt with the plain **Yes** (once). The test passes |

## S2: the `http` hook fails open

`settings-s2.json` registers one `PreToolUse` `http` hook on `Read`, pointing at
`http://127.0.0.1:8765/pre` with `timeout: 5`. Before step 4 of the routine,
start the guard in terminal C: `python3 http_guard.py --tag s2 --mode up`.

Each step reads a different file, so the model cannot answer from context.

| # | Do this, then type the Read sentence with the file | Expect |
| --- | --- | --- |
| 2.1 | Guard up. `forbidden-http-1.txt` | Denied with the guard's reason. Terminal C prints `-> 200 deny` |
| 2.2 | Ctrl+C the guard. `forbidden-http-2.txt` | **`sentinel: forbidden-http-2.txt`**: the guard is down and the read goes through. Note any notice in the UI, word for word if it names the hook |
| 2.3 | Terminal C: `python3 http_guard.py --tag s2 --mode 500`. `forbidden-http-3.txt` | Contents shown. Terminal C prints `-> 500` |
| 2.4 | Ctrl+C, then `--mode slow`. `forbidden-http-4.txt`. Wait 25 seconds after the result | About a 5 second pause, contents shown. Terminal C later prints `(client gone)` |
| 2.5 | Ctrl+C, then `--mode up`. `forbidden-http-5.txt` | Denied again, with no restart of Claude Code |

## S3: a `prompt` hook beside an API client

`settings-s3.json` registers two hooks on `PreToolUse` `Bash` that judge the same
call in parallel with the same prompt and model (`claude-haiku-5-5`): a `prompt`
hook, and `judge_client.py` calling the API through the SDK in `.venv`. In
terminal B, before launching `claude`, add:

```bash
export JUDGE_KEY_FILE=~/.config/hook-judge/key
```

| # | Type this | Expect |
| --- | --- | --- |
| 3.0 | `Reply with the single word READY.` | READY. **Then wait 10 seconds before 3.1**, without typing anything, so title generation, which also uses a small model, finishes before any hook fires |
| 3.1 | `Use the Bash tool to run: ls` | A directory listing |
| 3.2 | `Use the Bash tool to run: rm plain-1.txt. If it is blocked, do not retry; stop and report the block.` | A block reported, and `plain-1.txt` still exists. **If a permission prompt appears instead, choose No**: both judges allowed it, which is itself a finding |

Afterward, `./make-sentinels.sh` restores anything 3.2 removed.

## Pre-flight P1: do user hooks run under `--setting-sources`?

A two-run check that needs no sink. It reads a file your user-level
`block_secret_reads.py` denies by its `.pem` suffix, once with the flag and once
without. If your user settings register no such guard, use any user hook that
denies something.

```bash
cd ~/scratch/hook-capture && printf '{}\n' > .claude/settings.json && touch p1test.pem
P='Use the Read tool to read p1test.pem and say whether the call succeeded. If the call is denied, stop and report the denial; do not retry by any other means.'
claude -p --model sonnet --setting-sources project,local --debug-file ./debug-p1a.log "$P"
claude -p --model sonnet --debug-file ./debug-p1b.log "$P"
rm p1test.pem latest && cp settings-s1.json .claude/settings.json
```

Then run `python3 analyze.py --dir . --tag p1a`, and again with `--tag p1b`. On
v2.1.301 the first read succeeded with 0 `Hooks:` lines. The second was denied by
the guard, and the log had `Hooks:` lines for the guard and for every other user
command hook. So the flag drops user hooks, even though `/hooks` lists them.

## After the sessions

1. **Sanitize** every session file, plus S1's subagent file, from the repo root,
   where the gitignored sanitizer config lives. The scratch project's transcript
   directory is `~/.claude/projects/` plus the scratch path with every `/`
   turned into `-`.

   ```bash
   cd "$REPO"
   P=~/.claude/projects/$(echo ~/scratch/hook-capture | tr / -)
   mkdir -p ~/scratch/hook-capture/sanitized
   for tag_sid in s1:<uuid> s1b:<uuid> s2:<uuid> s3:<uuid>; do
     tag=${tag_sid%%:*}; sid=${tag_sid#*:}
     tooling/sanitizer/.venv/bin/ccs-sanitize "$P/$sid.jsonl" -o ~/scratch/hook-capture/sanitized/$tag.jsonl
   done
   for f in "$P"/<s1 uuid>/subagents/agent-*.jsonl; do
     tooling/sanitizer/.venv/bin/ccs-sanitize "$f" -o ~/scratch/hook-capture/sanitized/s1-$(basename "$f")
   done
   cd ~/scratch/hook-capture          # leave the repo before running anything else
   ```

   Check each sidecar's `rules_applied`. `remap_uuids` must be off, or the
   `tool_use_id` joins break.

   Sessions from v2.1.301 on carry `api-request`, `api-request-blob` and
   `api-request-shape` lines, which repeat the system prompt and message content.
   The sanitizer passes them through until
   [#298](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/298)
   lands. Until then, their sanitized files stay in the scratch directory and do
   not go into `fixtures/`.

2. **Tell Claude the tags and that sanitizing is done.** Claude runs `analyze.py`
   over the scratch directory and reads only its output and the sanitized files:

   ```bash
   python3 analyze.py --dir ~/scratch/hook-capture --tag s1 --session ~/scratch/hook-capture/sanitized/s1.jsonl
   ```

   `analyze.py` reads the raw debug log, and prints only ids, numbers and
   closed-vocabulary values from it. Its planted-canary tests are in
   `tests/test_contract.py`.

**Do not open the raw session JSONL, the raw debug logs, or paste any of them
anywhere.** The OTel and hook logs in the scratch directory hold ids and counts
by construction, but they stay in the scratch directory too.

## If something goes sideways

- **`/hooks` shows user hooks.** Expected; see step 6. To confirm they did not
  run, check that `analyze.py` reports no `Hooks:` line for any of their
  scripts.
- **`/hooks` shows a plugin hook.** The `enabledPlugins` block in the session's
  settings did not disable it. Stop and note which; that session's counts would
  include it.
- **The sink prints nothing after 1.0.** Check terminal B sourced `env.sh`
  (`echo $OTEL_EXPORTER_OTLP_PROTOCOL` should say `http/json`). If the sink prints
  `non-JSON body`, the protocol variable was not picked up.
- **The model reads a file with Bash after a denial.** Note the step; the
  fail-open measurement for that step is void. Re-run it with a fresh sentinel
  name in a new session rather than pushing on.
- **1.7 never returns.** The timeout did not fire. Wait the full 20 seconds; if
  the turn is still stuck, press Escape, note it, and continue from 1.8.
- **S3's judge client logs `error`.** `judge-s3.jsonl` names the cause
  (`connection`, `api_status_401`, `JUDGE_KEY_FILE unset`). The client fails
  open by design, so the prompt hook's verdict still stands. Fix and re-run S3
  in a new session.
