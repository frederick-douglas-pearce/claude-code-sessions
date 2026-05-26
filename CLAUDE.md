# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

`claude-code-sessions` is the canonical public reference for Claude Code's JSONL session data format. Three deliverables coexist in this repo:

1. **Posts** (`posts/`) — an ongoing blog series for human readers, synced from this repo to a Jekyll-based GitHub Pages site.
2. **Reference** (`reference/`) — authoritative format documentation; the data dictionary, schema notes, and format-version history that sibling projects link to.
3. **Tooling** (`tooling/`) — the sanitizer that scrubs raw session data for safe publication, and the validator that gates fixtures.

This repo is **upstream** of [AgentFluent](https://github.com/frederick-douglas-pearce/agentfluent) and [CodeFluent](https://github.com/frederick-douglas-pearce/codefluent). Both link to this repo's reference docs rather than duplicating format documentation.

## Security posture — read this first

Claude Code session JSONL files contain prompts, file paths, code snippets, command output, and occasionally secrets. The rule is absolute:

- **No raw session JSONL is ever committed.** Period.
- Files in `fixtures/sanitized/` must have a `.scrubbed` sidecar produced by `tooling/sanitizer/`.
- Files in `fixtures/synthetic/` are generated, not derived from real sessions, and ship with a `.generator.md` sidecar.
- Posts that show sample data reference fixtures from `fixtures/`, never inlined raw output.

If you (Claude Code) are asked to "show what's in a session," read from `fixtures/`, not from `~/.claude/projects/`.

Hooks may be added later to enforce mechanically (mirroring AgentFluent's `block_secret_reads.py` + `detect_secrets_in_output.py` pattern). Until then, the discipline is yours to maintain.

## Conventions

### Posts

- Format: Jekyll-flavored markdown (matching the target Pages site)
- Required frontmatter: `layout`, `title`, `date`, `description`, `categories`, `tags`, `claude_code_version_verified` (the Claude Code version the post was last fact-checked against)
- Each post links to relevant `reference/` sections for evergreen detail; reference docs are the source of truth, posts are the narrative layer
- Posts more than ~3 minor Claude Code versions behind their `claude_code_version_verified` should be re-verified

### Reference docs

- Source of truth for field-level format documentation
- Every section that names a JSONL field includes a "Verified against Claude Code v<X>" note
- Format version history (`reference/format-version-history.md`, planned) tracks observed field additions/removals/renames over time

### Fixtures

- `sanitized/` — derived from real sessions, scrubbed, with `.scrubbed` sidecar
- `synthetic/` — fabricated for illustration; document the generator alongside in `<filename>.generator.md`
- Filename convention: `<scenario>-<short-description>.jsonl` (e.g., `subagent-trace-pm-invocation.jsonl`)
- Synthetic is the **safe default**. Use sanitized only when realistic data shape can't be reproduced synthetically.

### Format-watch skill

- Lives at `.claude/skills/jsonl-format-watch/`
- Writes to `.claude/specs/research/jsonl-format-watch.md`
- Tracks upstream JSONL format changes (new fields, renames, envelope changes), independent of whether they have product implications for AgentFluent/CodeFluent
- When a watched change has sibling-project implications, the dispatch step cross-posts a candidate into the sibling project's `anthropic-feature-watch.md` (manual for v0)

## Commit conventions

[Conventional Commits](https://www.conventionalcommits.org/):

- `feat:` — new tool, new published post, new reference section
- `fix:` — corrections to existing posts, reference, or tooling
- `docs:` — meta-docs (README, CLAUDE.md, CONTRIBUTING)
- `chore:` — CI, scaffolding, dependencies
- `refactor:` — restructuring without behavior change

Scopes:
- `feat(posts):` / `fix(posts):` for post work
- `feat(reference):` / `fix(reference):` for reference docs
- `feat(sanitizer):` / `fix(sanitizer):` for tooling
- `chore(skills):` / `chore(specs):` for `.claude/` paths

## Sibling project relationship

[AgentFluent](https://github.com/frederick-douglas-pearce/agentfluent) and [CodeFluent](https://github.com/frederick-douglas-pearce/codefluent) both parse `~/.claude/projects/*.jsonl`. They share data sources with this repo but produce different outputs:

- **AgentFluent** — agent quality diagnostics
- **CodeFluent** — human AI fluency coaching
- **This repo** — format documentation and the security tooling around it

If you're working on AgentFluent or CodeFluent and find new format details, they belong here (in `reference/`) and get linked from those projects. Don't re-document fields in those projects' CLAUDE.md files going forward.

## Tech stack

- **Posts:** Markdown (Jekyll-compatible frontmatter)
- **Reference:** Markdown
- **Sanitizer (planned):** Python — separate design pass before implementation
- **CI (planned):** GitHub Actions for fixture validation and Pages sync

## Status

Pre-content scaffolding. The repo structure exists; populated content does not. Immediate next steps:
1. First foundational post (anatomy of a Claude Code session)
2. Sanitizer design + implementation
3. Reference data dictionary populated (migrating from AgentFluent's existing notes with verification + version stamping)
4. Sync workflow to the personal Pages repo
