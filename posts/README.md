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

## Filename convention

`YYYY-MM-DD-short-slug.md` (Jekyll-style). The date in the filename should match the `date:` frontmatter field.
