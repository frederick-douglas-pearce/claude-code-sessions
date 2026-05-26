# anatomy-minimal-session.jsonl — generator notes

**Authored:** 2026-05-26 by hand (Fred Pearce, via Claude Code)
**Used by:** W1 post — "Anatomy of a Claude Code session" (issue #6)
**Verified against Claude Code:** v2.1.150

## What this fixture illustrates

The shortest possible complete session JSONL: one user prompt, one assistant text response. No tool use, no streaming, no subagents. Two lines total.

This fixture is the answer to "what does the simplest case look like?" and is the right first example for a reader who has never opened one of these files before.

## Key structural points readers should see

- One JSON object per line — the JSONL format. Each line is independently parseable.
- Both lines share the same `sessionId` — that's how you correlate everything in a session.
- The second line's `parentUuid` points to the first line's `uuid` — that's the message graph.
- `cwd` and `version` are recorded per-message (not just at session start) — they can change mid-session if the user `cd`s or the Claude Code version is upgraded.
- The assistant line has `message.usage` with token counts; the user line does not. Token accounting is per-assistant-message.
- The user message's `message.content` is a plain string here. (The other allowed shape — array of content blocks — is illustrated in `anatomy-tool-use-cycle.jsonl`.)

## Synthetic conventions used

All identifiers follow a deliberate "obviously synthetic" pattern so no one mistakes this fixture for real data:

- `sessionId`: zero-padded with a tail digit (`00000000-0000-0000-0000-000000000001`)
- Per-message `uuid`: type-prefixed by digit family — user lines start with `1111…`, assistant with `2222…`, tool-result-bearing user lines with `3333…`
- `cwd`: `/home/dev/example-project` (a fictional but realistic-looking path)
- `version`: real Claude Code version (`2.1.150`) — readers verifying this fixture should use the same or a later release
- Timestamps: real ISO 8601 UTC format; date deliberately in May 2026 to anchor the verification context

## Deliberate omissions

- No `hook_progress`, `file-history-snapshot`, or other "skipped types" — those are not part of the message-level walkthrough this post does. They appear in later posts.
- Cache token fields are zero (first turn of a new session — no cache to read or warm). Cache behavior is a Part 2 topic.

## How to regenerate

This fixture was authored by hand, not generated. To produce a similar minimal fixture, copy this file and substitute new synthetic UUIDs and a fresh timestamp. Verify the result is valid JSONL (`python3 -c "import json,sys; [json.loads(l) for l in open(sys.argv[1])]" anatomy-minimal-session.jsonl`).
