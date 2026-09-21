# anatomy-hook-trace.jsonl — generator notes

**Authored:** 2026-09-19 by hand (Fred Pearce, via Claude Code)
**Used by:** Part 6 — "What hooks leave behind" (issue #68)
**Verified against Claude Code:** v2.1.278

## What this fixture illustrates

Everything a hook firing leaves in session JSONL, gathered into one short
session. Hooks execute outside the model loop, so none of the seven lines below
is a hook event itself. They are the harness's bookkeeping about hooks, written
after the fact.

Seven lines:

1. A `permission-mode` line — the thinnest line type in the format
2. A plain `user` prompt
3. An `assistant` turn carrying a `tool_use` that a `PreToolUse` hook will deny
4. A `system` line carrying the hook-execution field family, with
   `preventedContinuation: true`
5. The `user` line carrying the denied `tool_result`, with a top-level
   `toolDenialKind`
6. An `assistant` turn adapting to the block, `stop_reason: "end_turn"`
7. A second `system` line, this one a `Stop`-style hook that injected context
   back rather than blocking (`hookAdditionalContext`, `preventedContinuation:
   false`)

## The `<unread>` marker

Five string values in this fixture are the literal token `"<unread>"`. That is
deliberate and it is the fixture's most important convention.

The evidence behind this fixture is a structural scan that reads **key names and
counts only**, never field values — that is the scanner's security contract (see
[`tooling/format-scan/`](../../tooling/format-scan/README.md)). So for these
five, the key name and the carrier type are scan-verified while the value
vocabulary is genuinely unknown to me:

| Field | What is verified | What is not |
|---|---|---|
| `subtype` (both `system` lines) | key present on every `system` line; string | which subtype a hook line carries |
| `stopReason` | key present on hook lines; string | its value vocabulary |
| `hookInfos` | key present; array | the element shape |
| `hookAdditionalContext` | key present; string | the injected content, which is user data |
| `toolDenialKind` | key present on some `tool_result` lines; string | whether it separates a hook deny from a user reject |

Putting an invented enum value in those slots would assert something the
evidence does not support, so the fixture carries an obvious non-value instead.
`"<unread>"` is greppable, cannot be mistaken for a real Claude Code value, and
matches the deliberately-synthetic spirit of `toolu_synthetic_004`. A reader who
wants the real vocabulary has to read their own sessions.

`hookErrors` is `[]` rather than `"<unread>"` because an empty error list is a
real and safe value: this fixture's hooks ran without raising.

## Key structural points readers should see

- **`permission-mode` carries three keys**: `type`, `sessionId`,
  `permissionMode`. No `timestamp`, no `uuid`, no `parentUuid`. It cannot be
  ordered against the rest of the session except by position in the file, and it
  never names the hook that triggered the change. Line 1 is the whole line.
- **Hook bookkeeping rides on `system` lines**, not on a hook-specific type.
  The field family (`hookCount`, `hookInfos`, `hookErrors`, `hasOutput`,
  `preventedContinuation`, `stopReason`) appears together.
- **`toolUseID` is the join key** from a `PreToolUse`/`PostToolUse` hook record
  back to the tool call that triggered it. It is top-level on the `system` line,
  matching the `tool_use.id` from line 3. Note the capitalisation: `toolUseID`
  here against `tool_use_id` inside the content block.
- **`toolUseID` is present and `null` on line 7**, which is a reasoned choice
  rather than an observation. In the scan behind Part 6, `toolUseID` appears on
  exactly 3,964 `system` lines, the same count as every other hook-execution
  key. A `Stop` hook has no triggering tool call to point at, so either
  `Stop`-hook lines fall outside that 3,964, or the key is present with a null
  value. The scanner counts a key whose value is null, so present-and-null is
  consistent with the counts and with the semantics; the fixture takes that
  reading. Equal counts cannot prove co-occurrence on the same lines, so this
  stays a hypothesis.
- **A denial shows up twice**: once as `preventedContinuation: true` on the
  `system` line, and once as `toolDenialKind` plus `is_error: true` on the
  `tool_result`. Neither alone tells the whole story.
- **`hasOutput` is a boolean, not the output.** Whether a hook printed something
  is recorded. What it printed is not, except for the `Stop`-hook case on line 7.
- **Line 7 shows the non-blocking half** of the response contract: a hook that
  fed context forward instead of denying.

## Synthetic conventions used

UUID family scheme extends the one from `anatomy-minimal-session.jsonl` and
`anatomy-tool-use-cycle.jsonl`:

- `sessionId`: `00000000-0000-0000-0000-000000000004` (the `…0001`–`…0003`
  slots are taken by the three earlier anatomy fixtures)
- `user` UUIDs prefixed `1111…`; `assistant` `2222…`; user-with-tool-result
  `3333…`; **`system` `4444…`**, which is new with this fixture
- `tool_use.id`: `toolu_synthetic_004`
- `permissionMode: "plan"` is drawn from the enum Claude Code's hook payload
  documents for `permission_mode`. The JSONL line's own value vocabulary was not
  scan-read; the two are assumed to share an enum, which is an inference, not an
  observation.
- The blocked command (`rm -rf ./build`) is deliberately the kind of thing a
  real `PreToolUse` guard would stop, and deliberately harmless in context

## Deliberate omissions

- No `hookErrors` populated case. A hook that raises is a real scenario
  (`hookErrors` appears on all 3,964 hook-bearing `system` lines in the scan
  behind Part 6, but the scan cannot tell a populated array from an empty one).
- No `UserPromptSubmit` or `SessionStart` hook firing. Those leave the same
  `system`-line family, so a second example would repeat line 4 without adding
  structure.
- No subagent hook firing. `agentId` appears on 71 `system` lines in the same
  scan; the subagent linkage story belongs to
  [`anatomy-subagent-trace.jsonl`](anatomy-subagent-trace.jsonl) and Part 3.
- No `hook_progress` line. That type was absent from all 436,010 lines scanned,
  which is one of Part 6's findings — inventing one here would contradict it.

## How to regenerate

Authored by hand. To produce a similar fixture: substitute UUIDs, the tool name
and input, the timestamps, and keep the `"<unread>"` markers wherever the value
vocabulary has not actually been observed. Validate as JSONL:

```bash
python3 -c "import json,sys; [json.loads(l) for l in open('anatomy-hook-trace.jsonl')]"
```
