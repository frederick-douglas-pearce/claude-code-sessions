# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

`claude-code-sessions` is the canonical public reference for Claude Code's JSONL session data format. Three deliverables coexist in this repo:

1. **Posts** (`posts/`) — an ongoing blog series for human readers, synced from this repo to a Jekyll-based GitHub Pages site.
2. **Reference** (`reference/`) — authoritative format documentation; the data dictionary, schema notes, and format-version history that sibling projects link to.
3. **Tooling** (`tooling/`) — the sanitizer that scrubs raw session data for safe publication, the format-scan scanner that watches for format drift, the publish/OG helpers that sync posts to the Pages site, and the fixture validator (planned) that gates fixtures.

This repo is **upstream** of [AgentFluent](https://github.com/frederick-douglas-pearce/agentfluent) and [CodeFluent](https://github.com/frederick-douglas-pearce/codefluent). Both link to this repo's reference docs rather than duplicating format documentation.

## Security posture — read this first

Claude Code session JSONL files contain prompts, file paths, code snippets, command output, and occasionally secrets. The rule is absolute:

- **No raw session JSONL is ever committed.** Period.
- Files in `fixtures/sanitized/` must have a `.scrubbed` sidecar produced by `tooling/sanitizer/`.
- Files in `fixtures/synthetic/` are generated, not derived from real sessions, and ship with a `.generator.md` sidecar.
- Posts that show sample data reference fixtures from `fixtures/`, never inlined raw output.
- **The sanitizer config is also sensitive.** `.ccs-sanitize.yaml` holds literal PII strings (real home dir, email, name, etc.) — it is gitignored, and `block_secret_reads.py` also denies `Read`/`Edit`/`NotebookEdit`/`Grep`/`Glob`/`Bash` targeting it (Write stays allowed for `--init` and rewrite-from-scratch). Bootstrap with `ccs-sanitize --init` (writes the example template AND the live config; does NOT touch `.gitignore`), then fill in your match values. The sanitizer's built-in pre-run guard refuses to scrub if the resolved config is not gitignored (exit 3). That fires only inside a git repository; outside one the guard warns and proceeds. `--no-check` is a deliberate override of the guard, not the fix for exit 3 (gitignoring the config is), and the test suite is its main legitimate user. The sidecar's `config_source` field records only the basename, so sidecars stay safe to commit. Full threat model + defense layers: [PRD §12b](.claude/specs/prd-sanitizer.md#12b-config-storage-and-safety).

If you (Claude Code) are asked to "show what's in a session," read from `fixtures/`, not from `~/.claude/projects/`.

Mechanical enforcement is in place via `.claude/hooks/block_secret_reads.py` (PreToolUse, denies tool calls targeting known credential basenames, raw session JSONL under `~/.claude/projects/`, and the live sanitizer config) and `detect_secrets_in_output.py` (PostToolUse, scans tool output for known credential API-key patterns — Anthropic/OpenAI/GitHub PAT/AWS/GCP/PEM). See `.claude/hooks/README.md`. Coverage caveats: the PostToolUse scanner is pattern-based for credentials and does not catch arbitrary PII (names, emails, custom identifiers), and Bash-string matching is substring-based — variable indirection (`cat $cfg`) or globbing can defeat it. Runtime discipline remains yours for those cases; the diff-level backstop (no raw JSONL, no secrets in fixtures) is yours at commit time.

## Conventions

### Posts

- Format: Jekyll-flavored markdown (matching the target Pages site)
- Required frontmatter: `layout`, `title`, `date`, `description`, `categories`, `tags`, `og_image`, `featured`, `claude_code_version_verified` (the Claude Code version the post was last fact-checked against)
- **`posts/` frontmatter tracks the Pages site's conventions directly** (issue #14), so the publish transform stays thin:
  - `date` carries a time + UTC offset: `YYYY-MM-DD HH:MM:SS-TZTZ` (e.g. `2026-05-26 00:00:00-0800`)
  - `categories` and `tags` are quoted-string arrays: `["claude-code-sessions"]`, `["claude-code", "jsonl"]`
  - **`categories` names the series, not the kind of post** — always `["claude-code-sessions"]` here. The Pages site builds its blog filter chips from categories, and a second repo publishes into the same `_posts/` namespace, so the category is what separates the two series. Kind (`foundation`, `analysis`, `format-update`, `security`, `tooling`) is a tag; see [`posts/README.md`](posts/README.md#categories-and-tags)
  - `featured: false` unless a post is explicitly featured
  - `claude_code_version_verified` is **upstream-only**: it drives the re-verification cadence here but Pages ignores it, so `tooling/publish-to-pages.py` strips this one field on publish and copies everything else verbatim
- **Code fences and the Prettier gate.** The `posts/` Prettier gate (issue #76) formats fenced code in recognized languages. Author to it, don't fight it:
  - JSON shown as a **pretty-printed structure** → fully expand objects (one key per line) in a ` ```json ` fence. Prettier's `objectWrap: preserve` leaves expanded objects alone, so they stay gate-clean *and* render as clean, syntax-highlighted, no-overflow multiline blocks. (A partially hand-wrapped object gets collapsed onto a single line, which can overflow on narrow screens — expand it instead.)
  - A **raw session dump** where one record is one (long) line → use a ` ```jsonl ` fence. Prettier doesn't reformat `jsonl`, and Jekyll/Rouge renders it as plaintext, which is appropriate for a verbatim dump.
  - The repo's `.prettierrc` (`printWidth: 150`, `trailingComma: es5`, `@shopify/prettier-plugin-liquid`) **hand-mirrors the Pages site's Prettier config** so source == deployed. There's no automated link between the two — if the Pages config changes, update `.prettierrc` here to match, or posts will format differently than they deploy.
- Each post links to relevant `reference/` sections for evergreen detail; reference docs are the source of truth, posts are the narrative layer
- Posts more than ~3 minor Claude Code versions behind their `claude_code_version_verified` should be re-verified
- **AI-assistance disclosure footer is required.** Every post under `posts/` ends with a horizontal rule and the line:
  `_Drafted with Claude Code (verified against <version>). The ideas, claims, and any errors are mine._`
  where `<version>` matches the post's `claude_code_version_verified`. Short-form derivatives (LinkedIn, Medium, X, dev.to) carry the shorter form: `_Drafted with Claude Code. Ideas and any errors are mine._` (no version clause). The marketer agent (`~/.claude/agents/marketer.md`) is also instructed to include this. Use underscores (`_…_`) for the emphasis, not asterisks — the `posts/` Prettier gate (issue #76) normalizes emphasis to underscores, so authoring with `*…*` would fail the check.

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

## Branching & PR workflow

`main` is always publishable. Now that infrastructure work is underway, changes are split by what they touch:

- **PR required** — anything under `tooling/`, `.claude/hooks/`, `.github/`, or `fixtures/`. These are the code/infra and data surfaces where a bad change has blast radius.
- **Direct commit to `main` allowed** — content and docs: `posts/`, `social/`, `reference/`, README/CLAUDE.md copy edits, and typo fixes. (A PR is still welcome for substantial reference rewrites.)
- **Exception — material doc catch-ups go via issue + PR.** When README, CLAUDE.md, or component docs have drifted *materially* behind shipped state — a multi-file sweep correcting stale status/claims, not a typo or one-line edit — open a tracking issue and land it via PR for posterity (e.g. #127 / #128). Routine doc edits still commit direct.

Workflow for PR-required changes:

- **Branches:** `feature/<issue#>-short-description` or `fix/<issue#>-short-description` (e.g. `feature/12-secret-detection-hooks`).
- Commit freely on the branch; **squash-merge** to `main` via PR. Every PR references its issue.
- Open PRs with the sections in [`.github/PULL_REQUEST_TEMPLATE.md`](.github/PULL_REQUEST_TEMPLATE.md): Summary, Test plan, **Security review**, Breaking changes.
- **CI is being wired incrementally.** Live workflows (`.github/workflows/`): Prettier (posts), OG card guard, Pages sync, and Sanitizer CI (pytest on a 3.11/3.12/3.13 matrix, `python -m build`, `twine check --strict`, and a clean-environment wheel smoke test; the aggregate `sanitizer-ci` job is the required check). Still pending: the fixture validator and a hook-test runner — until those land, the data-safety and hook gates are review-enforced, not automated. Run the relevant local checks first — e.g. `python3 .claude/hooks/tests/test_hooks.py` for hook changes, and the `pytest` suites under `tooling/sanitizer/` and `tooling/format-scan/` for tooling changes.

### Release tags

Release tags are **component-scoped**, never a bare `v*`: the sanitizer releases as `sanitizer-v<version>` (e.g. `sanitizer-v0.3.0`). This is a monorepo holding posts, reference docs, and three tools, so a bare `v0.3.0` is ambiguous and a `v*` filter in the PyPI release workflow (#163) would fire the publish job on an unrelated repo-level or Pages tag. Any future component that publishes gets its own prefix.

### Security gate (repo-specific)

Because this repo documents a format that can carry secrets, every PR — and every direct content commit — must confirm:

- **No raw session JSONL committed:** only synthetic fixtures, or sanitized fixtures with a `.scrubbed` sidecar.
- **No secrets** in fixtures, posts, or examples. The `.claude/hooks/` guards cover live working sessions, not committed diffs — this is the diff-level backstop.

Vulnerability reports go to [`SECURITY.md`](SECURITY.md), which owns the disclosure path (private GitHub Security Advisories, never a public issue for a scrubbing bypass), the supported-version policy, and the yank-not-delete response play. The sanitizer README owns the complementary half: the determinism contract and what each version bump promises. Each cross-links the other; do not restate one in the other.

Commit messages follow the Commit conventions above.

## Sibling project relationship

[AgentFluent](https://github.com/frederick-douglas-pearce/agentfluent) and [CodeFluent](https://github.com/frederick-douglas-pearce/codefluent) both parse `~/.claude/projects/*.jsonl`. They share data sources with this repo but produce different outputs:

- **AgentFluent** — agent quality diagnostics
- **CodeFluent** — human AI fluency coaching
- **This repo** — format documentation and the security tooling around it

If you're working on AgentFluent or CodeFluent and find new format details, they belong here (in `reference/`) and get linked from those projects. Don't re-document fields in those projects' CLAUDE.md files going forward.

## Tech stack

- **Posts:** Markdown (Jekyll-compatible frontmatter), Prettier-gated
- **Reference:** Markdown
- **Tooling:** Python — the sanitizer (`tooling/sanitizer/`, shipped with a `pytest` suite), the format-scan drift scanner (`tooling/format-scan/`), and the publish/OG helpers (`tooling/*.py`). The fixture-validator is still planned.
- **CI:** GitHub Actions — Prettier, OG card guard, Pages sync, and Sanitizer CI (test matrix + packaging checks) are live; fixture validation is planned.

## Status

Active. The foundation post series is publishing (several posts live in `posts/`), `reference/` is being filled in section by section, and the sanitizer (`tooling/sanitizer/`) and format-scan scanner (`tooling/format-scan/`) are built and test-covered. The fixture-validator is the main remaining tooling gap.

The original roadmap lives at [`.claude/specs/roadmap-v0.md`](.claude/specs/roadmap-v0.md) — it captures the five work items (W1-W5) and is now largely historical, with most of its scope shipped (the first posts, the sanitizer, Pages sync) or in progress. Read the roadmap for original intent; track current work in [GitHub issues](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues).
