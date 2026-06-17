# claude-code-sessions

The canonical public reference for Claude Code's JSONL session data format — what's in those files at `~/.claude/projects/`, what the fields mean, how the format evolves, and how to work with it safely.

**Status:** Active. The foundation post series is publishing (several posts live in [`posts/`](posts/)), `reference/` is being filled in section by section, and the sanitizer ([`tooling/sanitizer/`](tooling/sanitizer/)) and format-drift scanner ([`tooling/format-scan/`](tooling/format-scan/)) are built and test-covered. See [`.claude/specs/roadmap-v0.md`](.claude/specs/roadmap-v0.md) for the original work plan and [open issues](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues) for current work.

## What this repo contains

| Path | Purpose |
|---|---|
| `posts/` | Markdown sources for an ongoing blog series. Jekyll frontmatter; synced to a personal GitHub Pages site. |
| `reference/` | Canonical format documentation — data dictionary, schema notes, format version history. Authoritative; sibling projects link here rather than duplicate. |
| `fixtures/sanitized/` | Real session data scrubbed by the sanitizer. Every file must have a `.scrubbed` sidecar proving it passed validation. |
| `fixtures/synthetic/` | Fabricated session data for cases real data can't (or shouldn't) cover. |
| `tooling/sanitizer/` | CLI that scrubs raw session JSONL for safe publication. Treats secret detection as a security boundary. |
| `tooling/format-scan/` | Local, content-free scanner that reports the *shape* of session data on disk and diffs it against `reference/` to surface undocumented format drift. |
| `tooling/fixture-validator/` | _(planned)_ CI gate that refuses to publish fixtures lacking proof of sanitization. |
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

## Supplemental study

Readers studying for Anthropic's [Claude Certified Architect program](https://anthropic.skilljar.com/claude-certified-architect-foundations-access-request) (currently gated to Anthropic Partner organizations) may find this series useful as supplemental study material — the JSONL session format and tool invocation primitives documented here are foundational to that material. This repo is not affiliated with or endorsed by Anthropic.

## Licensing

Dual-licensed:
- **Code** (tooling/, scripts, CI) — [MIT](LICENSE)
- **Prose** (posts/, reference/) — [CC-BY-4.0](LICENSE-prose.md)

## Related

- [AgentFluent](https://github.com/frederick-douglas-pearce/agentfluent)
- [CodeFluent](https://github.com/frederick-douglas-pearce/codefluent)
