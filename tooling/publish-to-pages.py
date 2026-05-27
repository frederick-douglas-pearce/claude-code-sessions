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
- Drops `claude_code_version_verified` (Pages Jekyll ignores it; lives only upstream).
- Adds time + timezone suffix to `date:` if absent (default: 12:00:00-0800).
- Quotes bare-word elements in `tags:` / `categories:` arrays.
- Adds `featured: false` if missing.
- Body copied verbatim — links in posts/ already use full GitHub URLs.

The frontmatter parser is intentionally naive (single-line key: value pairs only),
matching the current post template. See issue tracked for aligning the upstream
template with Pages conventions to eventually make this script a no-op.
"""

import re
import sys
from pathlib import Path

DROP_FIELDS = {"claude_code_version_verified"}
DEFAULT_TIME_SUFFIX = "12:00:00-0800"


def parse_frontmatter(block: str) -> dict:
    fields: dict[str, str] = {}
    for line in block.splitlines():
        if ":" in line and not line.startswith(" "):
            key, _, value = line.partition(":")
            fields[key.strip()] = value.strip()
    return fields


def quote_array(value: str) -> str:
    """[foo, bar baz] -> ["foo", "bar baz"]  (idempotent for already-quoted input)"""
    match = re.fullmatch(r"\[(.*)\]", value.strip())
    if not match:
        return value
    items = [x.strip().strip('"').strip("'") for x in match.group(1).split(",") if x.strip()]
    return "[" + ", ".join(f'"{x}"' for x in items) + "]"


def transform(fields: dict) -> dict:
    out = {k: v for k, v in fields.items() if k not in DROP_FIELDS}

    date = out.get("date", "").strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        out["date"] = f"{date} {DEFAULT_TIME_SUFFIX}"

    for key in ("tags", "categories"):
        if key in out:
            out[key] = quote_array(out[key])

    out.setdefault("featured", "false")
    return out


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

    new_fields = transform(parse_frontmatter(fm_block))
    new_fm = "\n".join(f"{k}: {v}" for k, v in new_fields.items())

    dest = dest_dir / src.name
    dest.write_text(f"---\n{new_fm}\n---\n{body}")
    print(f"wrote {dest}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("usage: publish-to-pages.py <source.md> <pages_posts_dir>")
    main(Path(sys.argv[1]), Path(sys.argv[2]))
