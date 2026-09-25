# anatomy-hook-trace.jsonl — generator notes

**Authored:** 2026-09-19 by hand (Fred Pearce, via Claude Code)
**Revised:** 2026-09-24 to match observed record shapes (issue #257)
**Used by:** Part 6 — "What hooks leave behind" (issue #68)
**Verified against Claude Code:** v2.1.280

## What this fixture illustrates

Everything a hook firing leaves in session JSONL, gathered into one short
session. Hooks execute outside the model loop, so none of the eleven lines below
is a hook event itself. They are the harness's bookkeeping about hooks, written
after the fact.

Eleven lines, three turns:

1. A `permission-mode` line — the thinnest line type in the format
2. A plain `user` prompt
3. An `assistant` turn carrying a `tool_use` that a `PreToolUse` hook will deny
4. The `user` line carrying the denied `tool_result`, with a top-level
   `toolDenialKind`. **This is the only record the denial produces**
5. An `assistant` turn adapting to the block, `stop_reason: "end_turn"`
6. A `system` / `stop_hook_summary` line: the `Stop` hook ran, said nothing,
   did not block
7. A second `user` prompt
8. An `assistant` reply
9. A `system` / `stop_hook_summary` line where the `Stop` hook injected context
   instead of blocking (`hookAdditionalContext` populated, `hasOutput: true`)
10. A third `user` prompt
11. A `system` / `informational` line carrying `preventContinuation: true` —
    a different shape from lines 6 and 9, sharing none of their fields

## What the 2026-09-24 revision corrected

The first version of this fixture predated the sanitized hook-trace fixtures
(#252 / #253). It was built from a key-count scan, which reads key names and
counts and never reads values. That was enough to know which keys exist. It was
not enough to know their types, their values, or which keys share a line, and
the fixture guessed on all three. Six things were wrong:

| What it asserted | What the sanitized fixtures show |
| --- | --- |
| A `system` line accompanies a denied tool call, carrying `preventedContinuation: true` | **No `system` line is written at all.** The `user` line is the whole trace |
| `preventedContinuation: true` | `false` on every hook line observed, including four deliberate `Stop` outcomes |
| `hookInfos` is an array of strings | An array of objects: `{"command": ..., "durationMs": ...}` |
| `hookAdditionalContext` is a string | An array |
| `isMeta: true` on hook lines | **Absent** on all 8 observed `stop_hook_summary` lines; `false` on all 3 `informational` |
| `toolUseID` is present and `null`, because a `Stop` hook has no tool call to point at | Present and **non-null**, holding a UUID that resolves to nothing in the file |

The `"<unread>"` convention the old version used for unknown values was honest
about not knowing, and it is gone now that the values are observed. Its real
limitation is worth recording: it marked the unknown *values* while leaving the
*structure* around them silently invented. A reader could see that `subtype` was
unknown. Nothing signalled that `hookInfos` had the wrong element type or that
line 4 described a record Claude Code does not write.

## Fabricated vs observed

Every **structure** in this fixture is observed. The key set of each `system`
line and of the denial line is an exact match to a key set in
`fixtures/sanitized/hook-trace-*.jsonl`, and the parity check under
[Validation](#validation) pins that.

Every **value** that identifies a person, path, project or session is
fabricated: the UUIDs, `toolu_synthetic_004`, `/home/dev/example-project`, the
hook script names, the prompt text, and the two hook messages. Field values
drawn from observation rather than invented:

| Field | Observed value used here |
| --- | --- |
| `subtype` | `stop_hook_summary`, `informational` |
| `permissionMode` | `auto` |
| `toolDenialKind` | `permission-rule` |
| `level` | `suggestion` on hook lines, `warning` on `informational` |
| `stopReason` | `""` |
| `preventedContinuation` | `false` |
| `content` prefix (line 11) | `Operation stopped by hook: ` |
| `tool_result.content` prefix (line 4) | `PreToolUse:<Tool> hook error: ` |

## Key structural points readers should see

- **`permission-mode` carries three keys**: `type`, `sessionId`,
  `permissionMode`. No `timestamp`, no `uuid`, no `parentUuid`. It cannot be
  ordered against the rest of the session except by position in the file, and it
  never names the hook that triggered the change. Line 1 is the whole line.
- **A denial produces one record, not two.** Line 4 is it. This is
  fixture-attested, not corpus-wide: the real denial in
  [`hook-trace-denial-and-stop-ladder.jsonl`](../sanitized/hook-trace-denial-and-stop-ladder.jsonl)
  writes a `user` line and nothing else. The corpus has 233 lines carrying
  `toolDenialKind`, but a key-count scan tallies keys per line and never looks
  at what sits next to a line, so it cannot say whether any of those 233 had a
  hook `system` line beside it. The earlier "shows up twice" claim in this file
  was a guess that reached a published fixture.
- **The hook that blocked is named only in prose.** `toolDenialKind` says
  `permission-rule`, which does not distinguish a hook from a permission rule.
  The event name and the script path appear inside the `tool_result` content
  string, written there by the hook itself. That is a string to match against,
  not a field to parse.
- **Hook bookkeeping rides on `system` lines**, not on a hook-specific type.
  Seven keys sit on exactly 4,159 lines each in the corpus behind Part 6:
  `hookCount`, `hookInfos`, `hookErrors`, `hasOutput`, `preventedContinuation`,
  `stopReason`, `toolUseID`. `hookAdditionalContext` sits on 3,176.
- **`toolUseID` on a hook line joins to nothing.** It is a UUID, it is never
  null in the fixtures, and it matches no `tool_use.id` (those carry a `toolu_`
  prefix), no record `uuid`, and no `message.id` anywhere in the session. Six
  hook lines in the sanitized ladder carry six distinct values. The sanitized
  fixture was scrubbed with `remap_uuids` off, so this is Claude Code's own
  output and not a sanitizer artifact. It reads as a per-firing identifier. This
  fixture puts those values in a `5555…` family precisely so a reader sees they
  belong to no other line.
- **`session_id` sits alongside `sessionId`** on `stop_hook_summary` lines, the
  same value in both casings. `informational` lines carry only `sessionId`.
- **`hasOutput` is a boolean, not the output.** Whether a hook printed something
  is recorded. What it printed is recorded only in `hookAdditionalContext`, and
  only for the inject-context case on line 9.
- **`informational` is a separate shape.** Line 11 carries `preventContinuation`
  (no "ed"), `content`, `level`, and `isMeta`. It shares **none** of the
  hook-execution family with lines 6 and 9. Two differently-named fields,
  `preventContinuation` and `preventedContinuation`, live on different line
  shapes and must not be conflated.

## Synthetic conventions used

UUID family scheme extends the one from `anatomy-minimal-session.jsonl` and
`anatomy-tool-use-cycle.jsonl`:

- `sessionId`: `00000000-0000-0000-0000-000000000004` (the `…0001`–`…0003`
  slots are taken by the three earlier anatomy fixtures)
- `user` UUIDs prefixed `1111…`; `assistant` `2222…`; user-with-tool-result
  `3333…`; `system` `4444…`; **`toolUseID` `5555…`**, a family deliberately
  disjoint from every `uuid` in the file; `promptId` `6666…`
- `tool_use.id`: `toolu_synthetic_004`
- The blocked command (`rm -rf ./build`) is deliberately the kind of thing a
  real `PreToolUse` guard would stop, and deliberately harmless in context

## Deliberate omissions

- **The 983-line hook-record shape.** The corpus shows three hook-record shapes:
  3,176 lines with `hookAdditionalContext`, 983 without the key at all, and 3
  carrying `preventContinuation`. This fixture reproduces the first and third.
  The 983 is most likely a version boundary, but the scan records only line
  counts per version and cannot locate it, so fabricating a line for that shape
  would repeat the mistake this revision corrects.
- **A blocked `Stop` hook, and a failed one.** Both are real, both are in
  [`hook-trace-denial-and-stop-ladder.jsonl`](../sanitized/hook-trace-denial-and-stop-ladder.jsonl)
  and [`hook-trace-stop-hook-error.jsonl`](../sanitized/hook-trace-stop-hook-error.jsonl)
  with real values, including one detail worth seeing there rather than here:
  `durationMs` is absent from `hookInfos` on the blocking turn and present on
  every other turn of the same session.
- **`turn_duration` lines.** They follow `stop_hook_summary` closely in real
  sessions but are turn bookkeeping, not hook bookkeeping.
- **No `UserPromptSubmit` or `SessionStart` hook firing.** Those leave the same
  `system`-line family, so a second example would repeat line 6 without adding
  structure.
- **No subagent hook firing.** `agentId` appears on 71 `system` lines in the
  same scan; the subagent linkage story belongs to
  [`anatomy-subagent-trace.jsonl`](anatomy-subagent-trace.jsonl) and Part 3.
- **No `hook_progress` line.** That type was absent from all 465,452 lines
  scanned, which is one of Part 6's findings. Inventing one here would
  contradict it.

## Validation

Authored by hand against the observed key sets. Validate as JSONL:

```bash
python3 -c "import json; [json.loads(l) for l in open('anatomy-hook-trace.jsonl')]"
```

The invariant that matters is structural parity with the sanitized fixtures.
Run from the repo root:

```bash
python3 - <<'EOF'
import json, glob, collections

def keysets(paths):
    out = collections.defaultdict(set)
    for p in paths:
        for line in open(p):
            if not line.strip():
                continue
            o = json.loads(line)
            if o.get("type") == "system":
                out[("system", o.get("subtype"))].add(frozenset(o))
            elif "toolDenialKind" in o:
                out[("user", "<denial>")].add(frozenset(o))
    return out

real = keysets(sorted(glob.glob("fixtures/sanitized/hook-trace-*.jsonl")))
syn = keysets(["fixtures/synthetic/anatomy-hook-trace.jsonl"])
for k, sets in sorted(syn.items(), key=str):
    for s in sets:
        assert s in real.get(k, set()), f"{k} has no observed counterpart"
print("structural parity: clean")
EOF
```

Every shape this fixture asserts must match a shape the sanitized fixtures
observe. If the sanitized set is ever regenerated against a newer Claude Code
and the check fails, this fixture is the one that is wrong. This is a candidate
check for the planned [fixture validator](../../tooling/fixture-validator/README.md).
