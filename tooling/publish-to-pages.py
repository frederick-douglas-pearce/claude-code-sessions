#!/usr/bin/env python3
"""
Stopgap: copy a post from posts/ to the Pages site's _posts/, transforming
frontmatter to match Pages-site Jekyll conventions.

Will be superseded by W4 (issue #2 — GitHub Action for automated sync).

Usage:
    python3 tooling/publish-to-pages.py <source.md> <pages_posts_dir>

Example:
    python3 tooling/publish-to-pages.py \\
        posts/2026-05-26-anatomy-of-a-claude-code-session.md \\
        /home/fdpearce/Documents/Projects/git/github_pages/frederick-douglas-pearce.github.io/_posts/

Transformations:
- Drops `claude_code_version_verified` (Pages Jekyll ignores it; it lives only
  upstream, where it drives the post re-verification cadence).
- Body and all other frontmatter copied verbatim.
- Ensures the output ends with a trailing newline.

As of issue #14, upstream `posts/` frontmatter already tracks Pages conventions
(quoted `tags`/`categories`, `date` with time+offset, `featured: false`) and is
kept Prettier-clean by the pre-merge gate (issue #76). So this transform is now
a near no-op: strip the single upstream-only field, copy everything else exactly
as written. We deliberately do a line-level strip rather than parsing and
re-serializing the frontmatter, to preserve the already-clean formatting byte
for byte.
"""

import re
import sys
from pathlib import Path

DROP_FIELDS = {"claude_code_version_verified"}


def strip_dropped_fields(fm_block: str) -> str:
    """Remove top-level frontmatter lines whose key is in DROP_FIELDS."""
    kept = []
    for line in fm_block.splitlines():
        key = line.partition(":")[0].strip() if ":" in line and not line.startswith(" ") else None
        if key in DROP_FIELDS:
            continue
        kept.append(line)
    return "\n".join(kept)


def main(src: Path, dest_dir: Path) -> None:
    if not src.is_file():
        sys.exit(f"source not found: {src}")
    if not dest_dir.is_dir():
        sys.exit(f"destination directory not found: {dest_dir}")

    text = src.read_text()
    match = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.DOTALL)
    if not match:
        sys.exit(f"{src}: no frontmatter block found")
    fm_block, body = match.group(1), match.group(2)

    new_fm = strip_dropped_fields(fm_block)

    out = f"---\n{new_fm}\n---\n{body}"
    if not out.endswith("\n"):
        out += "\n"

    dest = dest_dir / src.name
    dest.write_text(out)
    print(f"wrote {dest}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("usage: publish-to-pages.py <source.md> <pages_posts_dir>")
    main(Path(sys.argv[1]), Path(sys.argv[2]))
