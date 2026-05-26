# claude-code-sessions

The canonical public reference for Claude Code's JSONL session data format — what's in those files at `~/.claude/projects/`, what the fields mean, how the format evolves, and how to work with it safely.

**Status:** Early scaffold. Posts and reference docs are not yet populated. See [`.claude/specs/roadmap-v0.md`](.claude/specs/roadmap-v0.md) for the initial work plan.

## What this repo contains

| Path | Purpose |
|---|---|
| `posts/` | Markdown sources for an ongoing blog series. Jekyll frontmatter; synced to a personal GitHub Pages site. |
| `reference/` | Canonical format documentation — data dictionary, schema notes, format version history. Authoritative; sibling projects link here rather than duplicate. |
| `fixtures/sanitized/` | Real session data scrubbed by the sanitizer. Every file must have a `.scrubbed` sidecar proving it passed validation. |
| `fixtures/synthetic/` | Fabricated session data for cases real data can't (or shouldn't) cover. |
| `tooling/sanitizer/` | CLI that scrubs raw session JSONL for safe publication. Treats secret detection as a security boundary. |
| `tooling/fixture-validator/` | CI gate that refuses to publish fixtures lacking proof of sanitization. |
| `.claude/skills/jsonl-format-watch/` | Skill that tracks upstream changes to the JSONL format and queues them for review. |
| `.claude/specs/research/jsonl-format-watch.md` | The queue file the skill writes into. |

## Why this exists

Claude Code records every session as JSONL at `~/.claude/projects/<slug>/*.jsonl`. The format is rich — tool calls, token usage, subagent traces, hook events — but it isn't well-documented publicly. Two projects already depend on parsing it correctly:

- **[AgentFluent](https://github.com/frederick-douglas-pearce/agentfluent)** — diagnoses agent quality from session traces
- **[CodeFluent](https://github.com/frederick-douglas-pearce/codefluent)** — measures human AI fluency from interactive sessions

Rather than duplicate format documentation across both projects, this repo serves as the canonical reference. AgentFluent's and CodeFluent's documentation link here.

## Security posture

Session JSONL files contain prompts, file paths, code, and occasionally secrets. **No raw session data is ever committed to this repo.** The sanitizer and fixture-validator enforce this; the CLAUDE.md spells out the rules.

If you find a fixture in this repo that contains real personal data, file an issue immediately.

## Licensing

Dual-licensed:
- **Code** (tooling/, scripts, CI) — [MIT](LICENSE)
- **Prose** (posts/, reference/) — [CC-BY-4.0](LICENSE-prose.md)

## Related

- [AgentFluent](https://github.com/frederick-douglas-pearce/agentfluent)
- [CodeFluent](https://github.com/frederick-douglas-pearce/codefluent)
