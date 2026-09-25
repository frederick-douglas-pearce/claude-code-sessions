# Hook-trace fixture: session collection runbook

The procedure that collected [run 2](README.md#which-run-produced-which-fixture),
reproduced as the template for later hook experiments. It is written for a human
driving a fresh Claude Code session by hand, because that is the only way to make
a hook fire on a real turn boundary.

Run it in a **new terminal**, in a throwaway project, never from a session
working on this repo.

## Setup

1. Create a scratch project directory outside this repo.
2. Copy `hooks/` into it, and `scratch-project-settings.json` to
   `.claude/settings.json`.
3. Add `.stop-stage` and `hook-firings.log` to its `.gitignore`. Both are runtime
   state.

Note what the committed settings disable: every plugin is set to `false`. Plugin
`Stop` hooks are common and would otherwise land on the same `stop_hook_summary`
lines, which makes the trace unreadable.

Also note that the committed settings register **two** `Stop` hooks, which is
run 3's configuration and yields `hookCount: 2`. To reproduce run 2's single-hook
records, remove the `fail_on_stop.py` entry.

## What is set up

| Event | Type | Script | What it is for |
| --- | --- | --- | --- |
| `PreToolUse` (Glob) | `command` | `hooks/fail_on_glob.py` | exits 1, non-blocking, should populate `hookErrors` |
| `PreToolUse` (Bash) | `prompt` | inline, `claude-opus-5` | how a prompt-type hook renders in `hookInfos` |
| `PostToolUse` (Bash) | `command` | `hooks/note_bash.py` | prints a line, should set `hasOutput` without blocking |
| `Stop` | `command` | `hooks/stop_three_ways.py` | block, then `additionalContext`, then allow |
| `Stop` | `command` | `hooks/fail_on_stop.py` | exits 1 with no decision, a real failure rather than a block |

Your own global guards in `~/.claude/settings.json` fire here too. That is
deliberate: this repo's `block_secret_reads.py` is what produces the denial in
step 5.

## Steps

1. `cd` into the scratch project.
2. `claude --model sonnet`
3. Trust the directory when prompted.
4. Type `/hooks`. Confirm the expected hooks and **no plugin hooks**. Escape out.
5. Type each prompt below, one per turn. **After each one, check that the
   expected thing visibly happened** before moving on. If it did not, stop rather
   than pushing through: a half-failed run produces a fixture that looks fine and
   documents nothing.

   ```
   Run the command: echo hook fixture run
   ```

   Expect: the command runs.

   ```
   Read the dotenv file in this directory.
   ```

   Expect: a denial, in red, naming the secrets-protection hook. This is the
   important one. Name the file by its literal `.env` basename in the prompt you
   type; it is spelled around here only to keep this document readable by the
   very guard it is describing. If Claude reports that the file does not exist,
   re-prompt with a direct instruction to call the Read tool on that path and not
   to check for existence first.

   ```
   Use the Glob tool to list *.md files in this directory.
   ```

   Expect: a hook error notice, and the Glob result anyway.

   ```
   Delete the file .stop-stage in this directory using Bash, then reply with the single word READY.
   ```

   Expect: READY, then the Stop ladder. Claude should be told to continue twice,
   saying CONTINUING and then NOTED, before the turn ends. That is the hook, not
   a loop.

6. Optional, for a real `permission-mode` line: Shift+Tab into plan mode and
   back.
7. `/exit`.

## Then

Keep `hook-firings.log`. It is plain text about the scratch directory and safe to
read: comparing it against the session JSONL is the measurement.

Sanitize the session with [`tooling/sanitizer/`](../sanitizer/) and commit the
fixture with its `.scrubbed` sidecar. Check the sidecar's `rules_applied` before
trusting a UUID in the output: run 2 was scrubbed with `remap_uuids` off, which is
the only reason the dangling `toolUseID` finding could be attributed to Claude
Code rather than to the sanitizer.

**Do not open the raw JSONL, and do not paste any of it anywhere.** The sanitizer
is the only path into the repo.

## A note on this document

Writing this file tripped `block_secret_reads.py`, because the guard matches
Bash command strings by substring and the draft named a credential basename in
prose. That is the documented coverage caveat working as intended, in the
false-positive direction. If you extend this runbook and a write is refused,
that is why. Say what the file is rather than spelling it, or write the file with
an editor rather than a shell heredoc.

## If something goes sideways

- A prompt is blocked with "Operation stopped by hook": the prompt hook refused.
  This is what happened in run 1. Either keep the session, since a refusal is
  itself a fixture worth having, or delete the `PreToolUse` Bash block from
  `.claude/settings.json` and finish without it.
- The Stop ladder continues more than three times: deleting `.stop-stage`
  re-arms it, so that is not the fix. Remove the `Stop` block and note what
  happened.
- `/hooks` shows plugin hooks anyway: note which ones and carry on, or disable
  them and restart. A plugin `Stop` hook inflates `hookCount` and adds entries to
  `hookInfos` that are not yours.
