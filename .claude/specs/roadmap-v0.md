# Roadmap v0

**Status:** Initial roadmap. Captured 2026-05-26 during the scaffolding session.

**Purpose:** This document is the input for issue creation. The PM agent (or a human) should turn each work item below into a GitHub issue with full acceptance criteria. The items are listed in priority order with explicit dependencies.

**Audience:** Future Fred (or future Claude session in this repo) reading this to know where to start; the PM agent generating issues from it.

---

## Context (what's already in place)

Repo scaffolded at https://github.com/frederick-douglas-pearce/claude-code-sessions. Structure:

- `posts/` — Jekyll-flavored markdown for the blog series (empty)
- `reference/` — canonical format docs (`data-dictionary.md` is a skeleton with TODOs)
- `fixtures/sanitized/`, `fixtures/synthetic/` — empty; gated by sanitizer + validator
- `tooling/sanitizer/`, `tooling/fixture-validator/` — README stubs only
- `.claude/skills/jsonl-format-watch/` — stub SKILL.md
- `.claude/specs/research/jsonl-format-watch.md` — empty queue template
- Dual licensed (MIT + CC-BY-4.0); .gitignore in place; first commit `8595c49`

This repo is **upstream** of AgentFluent and CodeFluent. The relationship and conventions are documented in `CLAUDE.md`. Read that before working in this repo.

---

## Work items

### W1 — First foundational post: "Anatomy of a Claude Code session"

**Priority:** P0 — highest-leverage item. Defines the project's voice, the post↔reference linkage pattern, and the use of synthetic fixtures.

**Why:** Until there's at least one published post, the project has nothing public-facing. This post is also the trojan horse for everything downstream: readers who finish it become candidates for AgentFluent and CodeFluent.

**Suggested scope:**
- Walks through a complete session JSONL file end-to-end
- Covers the file location convention (`~/.claude/projects/<slug>/*.jsonl`)
- Explains the message-type taxonomy at a high level (assistant, user, the skipped types)
- Shows a representative example for each major message type
- Links to `reference/data-dictionary.md` sections (populated as part of W3, or stubbed inline if W3 hasn't run yet)
- Uses synthetic fixture data only (sanitizer not required for W1)

**Acceptance criteria (rough):**
- Lives at `posts/2026-MM-DD-anatomy-of-a-claude-code-session.md`
- Required Jekyll frontmatter present, including `claude_code_version_verified`
- Synthetic fixture(s) committed to `fixtures/synthetic/` with `.generator.md` sidecar(s)
- Every reference to a JSONL field links to the corresponding reference section (or notes "reference doc forthcoming")
- Reading time: ~10-15 minutes for a developer audience

**Dependencies:** None. Can ship without W3 (uses inline definitions where reference is missing), but better with it.

**Open questions for PM:**
- Should the first post target Agent SDK developers, Claude Code subagent users, or both? (Likely both — they share the format.)
- Where does the "why you should care" framing go — opening paragraph, or sidebar?

---

### W2 — Sanitizer design + v0 implementation

**Priority:** P0 — gates every "sanitized" fixture and is the security boundary for the whole project.

**Why:** Without the sanitizer, all fixtures must be synthetic. Synthetic is fine for most cases but limits what real-world phenomena the blog can illustrate (e.g., a multi-hour real subagent trace). This is also the artifact most likely to attract its own audience — "sanitize your Claude Code sessions before sharing" is a real need.

**Suggested scope:**
- **Phase 1 (design):** PRD in `.claude/specs/prd-sanitizer.md` covering rule taxonomy, sidecar format, jitter strategy, CLI shape, packaging story
- **Phase 2 (implementation):** Python CLI (uv-managed) implementing the design

**Acceptance criteria (rough):**
- PRD addresses every open question listed in `tooling/sanitizer/README.md`
- CLI usable as `ccs-sanitize <input.jsonl> -o <output.jsonl>` (or equivalent)
- Layered rules: paths → identifiers → secrets → optional jitter
- Outputs `.scrubbed` sidecar with rule-level counts and (configurable) substitution detail
- Test suite covers known-bad inputs from `tests/fixtures/`
- Fails closed: any rule error aborts; no partial scrubs

**Dependencies:** None for design. Implementation depends on design landing.

**Open questions for PM:**
- See `tooling/sanitizer/README.md` "Dependencies on this scaffold" section
- Should the sanitizer publish as its own PyPI package, or live only in this repo?
- Where does the secret-pattern library live — copied from AgentFluent, or referenced as a dependency?

---

### W3 — Migrate JSONL format docs from AgentFluent's CLAUDE.md → `reference/`

**Priority:** P1 — independent content-lift work. Makes `data-dictionary.md` actually useful and unblocks deeper references from W1's post.

**Why:** AgentFluent's CLAUDE.md currently contains the most complete JSONL format documentation Fred has written. Over time, those notes belong here as the canonical reference. This is the first concrete demonstration that this repo is upstream of the other two.

**Suggested scope:**
- Populate the TODO sections of `reference/data-dictionary.md` from AgentFluent's CLAUDE.md (specifically the "JSONL Data Format" section)
- Add "Verified against Claude Code v<X>" headers to each populated section
- Create `reference/subagent-traces.md` and `reference/tool-invocation.md` from the same source material
- Open a coordinating PR on AgentFluent that replaces its JSONL Data Format section with a short summary + link to this repo

**Acceptance criteria (rough):**
- `data-dictionary.md` sections populated: file location, common fields, message types (assistant/user/skipped), content blocks, tool invocation pattern, subagent traces, usage and token accounting, hook event fields
- Each section has a verification header
- AgentFluent CLAUDE.md JSONL Data Format section reduced to a ~10-line summary + link
- Cross-link is bidirectional: this repo's `reference/README.md` mentions AgentFluent + CodeFluent; AgentFluent's CLAUDE.md links here

**Dependencies:** None on this repo's side. Requires a coordinated PR on AgentFluent.

**Open questions for PM:**
- Should W3 happen before or after W1's first post? (Suggested order: start W3 alongside W1 — the post naturally surfaces what needs to be in the reference.)
- How granular should the verification headers be — per section, per field, or per document?

---

### W4 — Sync GitHub Action to the Jekyll Pages repo

**Priority:** P1 — gates posts becoming visible to readers on Fred's personal site.

**Why:** Without the sync action, posts live only in this repo. The action is what makes "publishing" feel automatic.

**Suggested scope:**
- GitHub Action triggered on push to `main` that affects `posts/**`
- Transforms post frontmatter / file layout to match the Pages repo's expectations
- Pushes to the Pages repo (on a branch for PR review, or directly to main — configurable)
- Idempotent: handles new posts, updates, and (eventually) deletions

**Acceptance criteria (rough):**
- Action runs on push and on manual dispatch
- Sync target configurable (different Pages branches, etc.)
- Auth via fine-scoped PAT stored as a repo secret
- Dry-run mode for testing changes without pushing

**Dependencies:**
- Needs at least one post (W1) to test against
- Needs a read of the Pages repo's structure (Fred can supply this from `/home/fdpearce/Documents/Projects/git/github_pages`)

**Open questions for PM:**
- What's the Pages site's expected post directory and frontmatter?
- Should the sync push directly to Pages main, or open a PR on Pages for review?
- How to handle post URLs that need to stay stable when filenames change?

---

### W5 — Port the format-watch skill from AgentFluent's `promote-candidates`

**Priority:** P2 — deferred per the scaffold decision. Picks up once content settles.

**Why:** Until there's reference content and at least one post, the dispatch routes (reference-update, post-draft, cross-post) have nothing meaningful to act on.

**Suggested scope:**
- Port the structure of AgentFluent's `.claude/skills/promote-candidates/SKILL.md` to this repo
- Adapt routes: drop PM/architect routes, add reference-update + post-draft + cross-post
- Add a research entry point (similar to AgentFluent's `anthropic-research` subagent) that watches Claude Code CHANGELOG, Agent SDK CHANGELOGs, Anthropic blog/postmortems, and observed format changes in fixtures
- Update `.claude/skills/jsonl-format-watch/SKILL.md` from stub to full skill
- First test: walk a recent format change (e.g., TodoWrite → Task tools) through the pipeline end-to-end

**Acceptance criteria (rough):**
- SKILL.md spelled out per AgentFluent's promote-candidates pattern (adapted)
- Research entry exists (subagent or skill phase) for the four upstream sources
- At least one candidate moved through queue → decision → promoted as an end-to-end test
- Cross-post route documented for AgentFluent and CodeFluent (initially manual; automation later)

**Dependencies:**
- Benefits from W3 (so reference-update has somewhere to land)
- Benefits from W1 (so post-draft has the convention to follow)

**Open questions for PM:**
- Should this be a subagent + skill pair (matching AgentFluent's `anthropic-research` + `promote-candidates`) or just a skill?
- Cron schedule (or just manual triggers for v0)?

---

## Out of scope for v0

Explicitly deferred until traffic or contributor activity warrants:

- `CONTRIBUTING.md` — defer until contributors arrive (mirrors AgentFluent's stance per `[[project-contributor-policy-tracking]]`)
- Sanitizer GUI / interactive review mode
- Multi-author workflows
- Comments or engagement features on the published site
- Translation / i18n
- ~~Sanitizer publishing as a standalone PyPI package (in-repo only for v0; can be extracted later)~~
  **Superseded 2026-08-16.** The standalone audience appeared (CCDC contributors, [#75](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/75)),
  so the sanitizer publishes to PyPI at `0.3.0`. See PRD [D-5a](prd-sanitizer.md#d-5-amendment)
  and [`plan-sanitizer-pypi.md`](plan-sanitizer-pypi.md).
- Automation of cross-post route (manual in v0; automate after the pattern proves out)

---

## Suggested ordering for the next session

1. **Start W2 (sanitizer design pass)** — design-only deliverable, ~1-2 focused sessions; doesn't block other work
2. **Start W1 (first post) in parallel** — drafting the post naturally surfaces what `reference/data-dictionary.md` needs, which feeds W3
3. **W3 (reference migration)** happens organically as W1 progresses
4. **W2 implementation** after the design PRD lands
5. **W4 (Pages sync)** once W1 is publish-ready
6. **W5 (format-watch port)** once content has settled and there's real material to watch

---

## How to use this doc

- The PM agent should read this and produce GitHub issues for each work item, with full acceptance criteria expanded from the rough outlines above
- A human (or Claude session in this repo) can also file issues directly using these items as templates
- After issues are filed, this roadmap stays as the narrative source — don't fold it into individual issues' descriptions, link from the issues back to this file instead
