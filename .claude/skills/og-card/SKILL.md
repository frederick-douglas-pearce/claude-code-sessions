---
name: og-card
description: Render an Open Graph share card (1200x630 PNG + 2x retina) for a new post in the claude-code-sessions blog series. Use when a post in posts/ is approaching publishable state and needs an og:image. Produces og-card.svg, og-card.png, og-card@2x.png in social/images/<slug>/.
---

# og-card

Encapsulates the OG share-card authoring + rendering pipeline so each post produces its `og-card.{svg,png,@2x.png}` set deterministically from a structured TOML brief.

## When to invoke

A post in `posts/` is close to publishable and needs an unfurl image. Cards are LinkedIn-first; the 1200x630 PNG is the canonical og:image and the 2x is a retina variant.

## Inputs

The skill consumes a single TOML brief at `social/images/<YYYY-MM-DD>-linkedin-<slug>/og-card.toml`:

```toml
slug = "2026-06-04-linkedin-reading-a-claude-code-session-line-by-line"

# 1 or 2 strings. Two strings = wrapped title (use for >34 chars or natural comma break).
title = ["Reading a Claude Code session,", "line by line"]

# Single line, ~45 chars or fewer.
subhead = "Two naming styles. One boundary made visible."

# Pretty-printed JSON, 2-space indent. ~12-16 lines fits comfortably at 20px/22 line-height.
json_sample = """
{
  "type": "user",
  "parentUuid": "11111111-…-1001",
  "sessionId": "00000000-…-0001"
}
"""

# Free-form authoring rationale; not consumed by render.py.
notes = """
Why this JSON, what to emphasize, any wrap decisions.
"""
```

The brief is **committable** — it lives alongside the outputs as a build input, so the card can be re-rendered without re-prompting.

## Steps

1. **Pick the slug** following `<YYYY-MM-DD>-linkedin-<short-name>`. Match the post's publication date and a slug derived from the title.

2. **Author the brief** at `social/images/<slug>/og-card.toml` with title, subhead, and JSON sample. The JSON sample is the visual hero — pick a snippet that shows the post's central insight in 12–16 pretty-printed lines.

3. **Render** by invoking the script with the brief path:

   ```bash
   python3 .claude/skills/og-card/render.py social/images/<slug>/og-card.toml
   ```

   The script writes `og-card.svg`, `og-card.png` (1200x630), and `og-card@2x.png` (2400x1260) to the brief's directory. PNGs are flattened to RGB on `#0f0f14` and verified via `file`.

4. **Spot-check** by reading the 1200x630 PNG back. Confirm:
   - Title fits the canvas; if it overflows, split into two lines at a natural comma break.
   - No code line overruns the right window edge (the script warns at ~58 chars at deep indent).
   - Colon spacing renders as `": "` not `":"` (the `xml:space="preserve"` gotcha).
   - `file og-card.png` reports `8-bit/color RGB`, not `RGBA`.

## Gotchas (baked into render.py; documented here for the author)

- **Inkscape is snap-confined to `$HOME`.** The script passes absolute paths via `Path.resolve()`. Don't invoke Inkscape from outside `$HOME` or with relative paths — it silently fails with "doesn't exist" against the literal path string.

- **`xml:space="preserve"` on the code `<g>` is required.** Without it, trailing whitespace inside `<tspan>` collapses and `": "` runs into the value (`"type":"assistant"` instead of `"type": "assistant"`). The template includes this; do not remove it.

- **Line budget: ~16 code lines at font-size 20 / line-height 22.** Beyond that, the JSON either overruns the window bottom or crowds the wordmark. Either shrink the font (manual edit of `render.py` constants) or compress the JSON (inline single-key nested objects).

- **Long inline lines need a char-width check.** At 20px JetBrains Mono, ~58 characters at the deepest indent level (6 spaces) is the practical limit before right-edge overrun. The script warns when this is exceeded.

- **RGBA → RGB flatten is mandatory.** Inkscape exports RGBA even with no transparency. LinkedIn's Post Inspector composites RGBA on white during preview generation, which muddies dark cards (whites turn greenish; JSON syntax highlighting washes out). The script flattens onto `#0f0f14` via PIL and verifies via `file`.

## Layout note: Part 1 vs canonical

The canonical geometry follows Part 2 (`social/images/2026-06-04-linkedin-reading-a-claude-code-session-line-by-line/og-card.svg`): title 56px, window 712x410 at (244, 174), code 20px / line-height 22, `xml:space="preserve"` on the code group.

Part 1's card (`social/images/2026-05-28-linkedin-anatomy-of-a-claude-code-session/og-card.svg`) predates this skill and uses different numbers (60px title, window at y=150 height 416, no `xml:space`). This skill does **not** regenerate Part 1's card; the canonical layout is for Part 2 onward.

## Out of scope (v0)

- Auto-uploading PNGs to the Pages repo (W4 territory).
- Multiple aspect-ratio variants (LinkedIn vs X vs Bluesky).
- Theming beyond the dark palette.
- Selective per-token coloring (e.g., emphasizing one key in a different shade). All keys are cyan, all string values green, all numbers yellow, all punctuation gray.

## Canonical palette / sizing reference

| Element        | Value                                                       |
|----------------|-------------------------------------------------------------|
| Canvas         | 1200×630, background `#0f0f14`                              |
| Window         | 712×410 at (244, 174), `#16161d`, `rx=14`                   |
| Title bar      | `#1d1d26`, traffic lights `#ff5f56` / `#ffbd2e` / `#27c93f` |
| JSON keys      | `#2698ba`                                                   |
| String values  | `#11d68b`                                                   |
| Numbers        | `#efcc00`                                                   |
| Punctuation    | `#8a8a99`                                                   |
| Title          | 56px, weight 300, white                                     |
| Subhead        | 28px, weight 400, `#c0c0c8`                                 |
| Code           | 20px / line-height 22, JetBrains Mono                       |
| Wordmark       | 22px, `#8a8a99`, "Frederick Pearce · Data. AI. Human."      |
