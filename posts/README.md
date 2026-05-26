# posts/

Markdown sources for the `claude-code-sessions` blog series. Synced from this repo to a Jekyll-based GitHub Pages site via [CI workflow TBD].

## Frontmatter convention

Every post requires this frontmatter block:

```yaml
---
layout: post
title: "Post title"
date: YYYY-MM-DD
description: "One-sentence summary used for previews and SEO"
categories: [foundation | format-update | security | tooling]
tags: [claude-code, jsonl, sessions, ...]
claude_code_version_verified: vX.Y.Z
---
```

The `claude_code_version_verified` field records the Claude Code version the post was last fact-checked against. Posts more than ~3 minor versions behind current should be re-verified before being treated as authoritative.

## Categories

- `foundation` — evergreen anatomy and reference posts (e.g., "Anatomy of a Claude Code session")
- `format-update` — drops covering new fields, renames, or bug-fix-driven format changes
- `security` — what's in your sessions and how to handle it
- `tooling` — using and building tools against the format

## Embedding fixture data

Posts that show sample session data **must** reference files in `fixtures/`, not inline raw content. Use Jekyll's `{% include_relative %}` (or whichever helper the target site supports) or a clearly-attributed code fence:

````markdown
```jsonl
// from fixtures/synthetic/subagent-trace-pm-invocation.jsonl
{"type":"assistant",...}
```
````

The discipline: a reader who wants to grep for that data should be able to find it in the repo without searching post HTML.

## Linking to repo files

Posts are deployed to a separate GitHub Pages site, so relative paths to files in this repo (`fixtures/`, `reference/`, `tooling/`, etc.) will not resolve from the published post. **Always use full GitHub URLs** when linking to a file or directory in this repo:

- File: `https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/<path>`
- Directory: `https://github.com/frederick-douglas-pearce/claude-code-sessions/tree/main/<path>`

This applies to inline markdown links **and** to attribution comments inside code fences (the `// from fixtures/...` style above — use the full URL in the comment, not the relative path). Treat any reference to an in-repo file as something the reader will click; they are not in the same repo as the post.

## Filename convention

`YYYY-MM-DD-short-slug.md` (Jekyll-style). The date in the filename should match the `date:` frontmatter field.
