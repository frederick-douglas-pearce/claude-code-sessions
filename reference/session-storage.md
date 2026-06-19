# Session storage and retention

The other reference docs describe the *content* of session JSONL: the fields, the message types, the tool-invocation envelope, the subagent traces. This one covers the *files themselves*: where Claude Code writes them, how they are named, and how long they survive before Claude Code deletes them on its own.

The headline fact is the last one. By default Claude Code garbage-collects session transcripts after **30 days**, silently, at startup, with no prompt or warning. Anyone who wants to analyze, archive, or contribute their own sessions (the premise of this repo and of the downstream [Claude Code Data Collective](https://github.com/frederick-douglas-pearce/claude-code-data-collective) corpus) is on that 30-day clock unless they change a setting. This doc is the source of truth for that behavior so sibling projects can link here instead of restating it.

For the directory that grows *beside* a session file when it delegates to subagents, see [`subagent-traces.md`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/subagent-traces.md). For the field-level format, see [`data-dictionary.md`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/data-dictionary.md).

---

## Where sessions live

**Verified against Claude Code v2.1.181.** Path and naming confirmed by direct inspection of `~/.claude/projects/` (directory and file names only, no message content read) and against the official [How Claude Code works](https://code.claude.com/docs/en/how-claude-code-works) and [Manage sessions](https://code.claude.com/docs/en/sessions) docs.

Each session is a single JSONL file:

```
~/.claude/projects/<project>/<session-id>.jsonl
```

- **`<project>`** is derived from the working-directory path the session ran in, with the path separators flattened to dashes. A session started in `/home/you/Documents/Projects/git/myrepo` lands under `~/.claude/projects/-home-you-Documents-Projects-git-myrepo/`. One directory per working directory, so all sessions for a repo collect in the same place.
- **`<session-id>`** is a UUID, not a timestamp. You cannot read a session's start time from its filename; that lives in the records inside.
- The root of all of this is `~/.claude` by default. To relocate it, see [Related controls](#related-controls) below.

When a session delegates to subagents (or spills a large tool result), a `<session-id>/` directory is created lazily next to the `.jsonl` file to hold that overflow. Its layout is documented in [`subagent-traces.md`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/subagent-traces.md).

---

## Retention and auto-deletion (the warning)

**Verified against Claude Code v2.1.181.** Behavior per the official [Application data](https://code.claude.com/docs/en/claude-directory), [settings](https://code.claude.com/docs/en/settings), and [worktrees](https://code.claude.com/docs/en/worktrees) docs.

Claude Code deletes old session data for you. The control is the **`cleanupPeriodDays`** setting:

- **Default: 30 days.** Files under the retention-managed paths (including session transcripts in `~/.claude/projects/`) are deleted **on startup** once they are **older than `cleanupPeriodDays`**, measured by **file age** (the file's modification time).
- **Minimum: `1`.** Setting `cleanupPeriodDays` to `0` is rejected with a validation error. There is no built-in "never delete" sentinel; you approximate it with a large value (see below).
- **It also reaps subagent worktrees.** Git worktrees that Claude Code created for subagents and background sessions are removed once they pass the same age threshold, but only when the worktree is clean: no uncommitted changes, no untracked files, and no unpushed commits. A worktree with work in it is left alone.

The practical consequence: if you only realize you wanted a session *after* 30 days have passed, it is already gone. Decide on retention **before** sessions age out, not after.

---

## How to keep sessions longer

**Verified against Claude Code v2.1.181** against the official [settings](https://code.claude.com/docs/en/settings) doc.

Raise `cleanupPeriodDays` in a `settings.json`. For example, `3650` is ten years; `36500` is effectively forever:

```json
{
  "cleanupPeriodDays": 3650
}
```

You can set it at any of the standard settings scopes. From lowest precedence to highest, a value in a higher scope wins:

1. **User** — `~/.claude/settings.json` (applies to all your projects)
2. **Project** — `.claude/settings.json` in the repo (shared, committed)
3. **Local** — `.claude/settings.local.json` in the repo (personal, gitignored)
4. **Command-line** flags for the invocation
5. **Managed** settings (enterprise-deployed; highest)

For "keep everything, everywhere," the User scope is usually the right home, since it covers every working directory at once. Again: set this **before** the sessions you care about reach 30 days, because the cleanup that would delete them runs at the next startup.

---

## Does resuming a session reset the clock?

**Verified empirically against Claude Code v2.1.181.** The official docs do not state whether resuming or continuing a session restarts its retention clock, so this was tested directly rather than assumed.

**Yes, resuming resets the clock** (as long as the resumed session writes at least one new record, which any real turn does).

The mechanism: cleanup keys off **file modification time**, and resuming a session via `claude --continue` / `claude --resume` appends new records to the **same** `<session-id>.jsonl` file. That append updates the file's mtime to the present, which pushes the deletion threshold out another `cleanupPeriodDays` from the moment of the resume.

Test performed: created a session, backdated its file mtime to 40 days old (past the 30-day default), resumed it with one trivial turn, and re-checked the mtime. The file's mtime had advanced from the backdated value to the time of the resume. A session you keep coming back to therefore does not age out; only sessions left untouched for the full window do.

This is empirically observed behavior, not a documented guarantee. Treat it as accurate for v2.1.181 and re-verify if the cleanup implementation changes.

---

## Related controls

**Verified against Claude Code v2.1.181** against the official [Manage sessions](https://code.claude.com/docs/en/sessions), [Application data](https://code.claude.com/docs/en/claude-directory), and [environment variables](https://code.claude.com/docs/en/settings#environment-variables) docs.

These are adjacent to retention but distinct from it. The first relocates where sessions are stored; the rest are the *opposite* of retention, suppressing session writes entirely.

- **`CLAUDE_CONFIG_DIR`** (environment variable) — relocates the Claude Code config root away from `~/.claude`. Set it to store sessions (and the rest of the config tree) somewhere else, for example a backed-up or larger volume.
- **`CLAUDE_CODE_SKIP_PROMPT_HISTORY`** (environment variable) — skips writing transcripts and prompt history in any mode. With this set, there is no session file to retain.
- **`--no-session-persistence`** (CLI flag) — in non-interactive mode, pass this alongside `-p` to run without persisting the session.
- **`persistSession: false`** (Agent SDK) — the SDK equivalent of the flag above; the run produces no persisted session file.

If your goal is to *keep* sessions, none of these are what you want; raise `cleanupPeriodDays` instead. They are listed here so the distinction is explicit: relocating or suppressing storage is a different decision from how long stored sessions live.

---

## Authoritative sources

Claude Code's own docs are the field-level reference; this doc summarizes the storage-and-retention slice of them and adds the empirical resume finding:

- [Settings](https://code.claude.com/docs/en/settings) — `cleanupPeriodDays`, precedence, environment variables
- [Manage sessions](https://code.claude.com/docs/en/sessions) — resume/continue, storage location, `CLAUDE_CONFIG_DIR`, persistence suppression
- [Application data](https://code.claude.com/docs/en/claude-directory) — what lives under `~/.claude` and what the cleanup deletes
- [Worktrees](https://code.claude.com/docs/en/worktrees) — subagent/background worktree cleanup under the same setting
