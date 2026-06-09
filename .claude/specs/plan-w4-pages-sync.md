# W4 — GitHub Pages sync automation (plan)

**Epic:** [#2](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/2) · **Roadmap:** [W4 in roadmap-v0.md](roadmap-v0.md) · **Status:** in progress
**Architect review:** [#2 comment](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/2#issuecomment-4652639220)
**Status:** #14 ✅ · #76 ✅ · #77 contract resolved ✅ · **next: #78 (resolver + OG copy), then #79 (Action + PAT).**

Automate publishing posts from this repo's `posts/` to the separate Jekyll Pages repo
(`frederick-douglas-pearce.github.io`), replacing the manual `tooling/publish-to-pages.py` run.
This doc is the canonical plan; the linked issues track execution.

## Locked decisions (owner-approved — do not relitigate)

1. **Push directly to Pages `main`** — the post is already reviewed/merged here before sync fires; no PR on the Pages repo.
2. **Prettier handled by a pre-merge CI gate in THIS repo** (not by reformatting inside the Action). Catches issues before the post is live, keeps source==deployed, never silently reformats prose.
3. **MVP scope:** new/updated posts + their OG image. Deletions and configurable multi-branch targets are deferred (design for them, don't build them).

## Hard constraints (learned operating the manual process)

- **Pages `main` has multiple automated writers** — a daily ESG-news-classifier cron pushes to it too. Any push to Pages `main` MUST use a bounded `pull --rebase` + re-push retry loop. An event-triggered blog push has no "next run" to reconcile a lost race, so it must retry then fail loud. (Manual reference pattern: memory `project-pages-push-pattern`; ESG reference impl `website_export.py`.)
- **Pages Prettier check:** `npx prettier . --check` on push AND pr to `main`, using `prettier@3` + `@shopify/prettier-plugin-liquid`. Config: `printWidth: 150`, `trailingComma: es5`. A dirty post turns the check red even though Deploy (separate job) still ships. Bit the retry post 2026-06-08.
- **Pages layout:** posts at `_posts/<date>-<slug>.md`; OG image at `assets/img/<slug>-og.png` (the 1200×630 png, not `@2x`). The post's `og_image` frontmatter already holds the absolute target URL.
- **OG card source** lives at `social/images/<card-date>-linkedin-<post-slug>/og-card.png` — note the `-linkedin-` infix the post filename lacks **and that the card date is authored independently of the post date** (Part 1's card is `2026-05-28` against a `2026-05-26` post, so a post-date construct fails on the first existing post). `og-card.toml`'s `slug` is the *card* slug, not the post slug, and older card dirs have no `.toml`. **Naive slug-mapping/globbing is unsafe** (ships wrong image with a green Action). **Resolved by #77:** each post now carries an explicit `og_card_source` pointer (see Design contracts below); resolution reads that field, never reconstructs a path.
- **`publish-to-pages.py` today** transforms frontmatter only (drops `claude_code_version_verified`, adds time suffix to `date`, quotes `tags`/`categories`, adds `featured: false`, ensures trailing newline). It does **not** copy the OG image.
- **No secrets exist on either repo yet.** Auth will be a fine-grained PAT, `contents:write` on the Pages repo only, secret `PAGES_SYNC_TOKEN` here, behind a GitHub Environment.

## Deliverables & execution order

| Order | Issue | What |
|---|---|---|
| 1 | [#14](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/14) | ✅ **Done** (merged 2026-06-08). Align upstream post frontmatter template with Pages conventions. Shrinks the transform to ~"strip `claude_code_version_verified`" and shrinks #78's test surface. |
| 2 | [#76](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/76) | ✅ **Done** (merged 2026-06-08). **Deliverable A** — pre-merge Prettier CI on `posts/` here. Fixes today's failure class. |
| 3 | [#77](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/77) | ✅ **Contract resolved** (Option A — `og_card_source` pointer). 3 posts backfilled, og-card SKILL.md documents the contract. Feeds #78. |
| 4 | [#78](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/78) | **Deliverable C** — extend `publish-to-pages.py`: OG copy (resolve via `og_card_source` per #77, fail-closed), **add `og_card_source` to the stripped-on-publish fields**, content-compare, fail-closed, `--dry-run`. |
| 5 | [#79](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/79) | **Deliverable B** — the `pages-sync.yml` Action. Needs the PAT to go live; build + dry-run first. |

#14 + #76 are independent and unblocked — the agreed starting point.

### Design contracts (architect must-fix, folded into the issues)

- **OG-image resolution — exact, never a glob.** Target = basename of the post's `og_image` frontmatter → `assets/img/<post-slug>-og.png`. Source = the post's **`og_card_source` frontmatter field**, interpreted repo-root-relative (`social/images/<card-date>-linkedin-<post-slug>/og-card.png`); read directly, never reconstructed from date/slug, never globbed, never via `og-card.toml`. **Fail closed** if the field is absent, escapes the repo (`..`/absolute), or names a missing file. **(Resolved on #77 — Option A, post-frontmatter pointer.** Rejected: post-date path-construct — breaks on Part 1's date drift; `og-card.toml` `post_slug` lookup — wrong end of the link + only 1/3 cards have a toml; anchored-suffix+uniqueness — assumes global slug uniqueness that the epic's multi-branch goal erodes. [Architect ruling](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/77#issuecomment-4655440290).)
- **Change detection — content-compare, not push-diff.** Transform all posts, push only bytes-differ ones. Gives idempotency (no empty commits) for free and extends to deletions. (Details: #78.)
- **Push robustness** — bounded rebase-retry + **loud notification** on final failure, not a silent exit. (Details: #79.)

## Open questions resolved by architect

- Prettier CI scope: `posts/` only for MVP. ✔
- Transform stays in Python (DRY), called by the Action. ✔
- #14 lands first. ✔
- PAT vs CLAUDE.md posture: no conflict (those rules govern session JSONL + sanitizer config, not deploy creds). Fine-grained, single-repo, Environment-gated, never echoed, no `pull_request`-from-fork trigger. ✔
- Don't close #15 (local `--check` flag) until #76 is proven; #76 likely supersedes it.

## Forward-compat for the full epic (design now, build later)

- Change-detection contract should accept "delete posts removed upstream" without restructuring.
- Target repo/branch/paths as workflow inputs (single source of truth) for later multi-branch.
- Filename/URL stability on rename is explicitly **out of MVP**.

## Owner action required

Create a fine-grained PAT (`contents:write`, Pages repo only) and add it as secret `PAGES_SYNC_TOKEN` in this repo, behind a GitHub Environment. Exact steps to be provided when #79 starts.

## Interim manual process

Until this lands, deploy by hand per the runbook in memory `project-pages-push-pattern` (Prettier-format source upstream → detached worktree at `origin/main` → `publish-to-pages.py` → copy `og-card.png` to `assets/img/<slug>-og.png` → `prettier --check` → push with rebase-retry → remove worktree).
