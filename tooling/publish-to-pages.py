#!/usr/bin/env python3
"""
Publish posts from this repo's posts/ to the Jekyll Pages site: transform the
frontmatter to Pages conventions and copy each post's OG card.

Intended to be the single transform implementation the W4 sync Action (issue #2)
shells out to. Separation of concerns: the Action owns auth + the git
rebase-retry push; this script owns the transform, OG-image resolution, and the
content-compare that makes re-runs idempotent. (Issue #78.)

Usage:
    publish-to-pages.py <source.md>... --posts-dir DIR --assets-dir DIR [--dry-run]

Example:
    python3 tooling/publish-to-pages.py \\
        posts/2026-05-26-anatomy-of-a-claude-code-session.md \\
        --posts-dir  /path/to/frederick-douglas-pearce.github.io/_posts/ \\
        --assets-dir /path/to/frederick-douglas-pearce.github.io/assets/img/

What it does, per post:

1. **Transform frontmatter.** Strip the upstream-only fields
   (`claude_code_version_verified`, `og_card_source`); copy the body and every
   other field byte-for-byte. The strip is line-level, not a YAML round-trip, so
   the Prettier-clean formatting from issues #14/#76 survives unchanged.
2. **Resolve + copy the OG card** via the issue-#77 contract: the post's
   `og_card_source` field (repo-root-relative) is the source; the target is
   `<assets-dir>/<basename of the post's og_image URL>`.

Resolution is **fail-closed, never a glob**: a missing field, an absolute or
repo-escaping path, a missing source file, or two posts colliding on one target
all abort the run with zero writes. A wrong image shipped under a green Action is
the exact failure mode this design exists to prevent (issues #77/#78).

Idempotency is **content-compare, not push-diff**: every output is written only
when its bytes differ from what's already in the Pages tree, so a re-run makes no
spurious changes and the Action makes no empty commit.

Atomicity is **validate-all-then-write**: the full plan for ALL posts is built
and validated (Phase 1) before a single byte is written (Phase 2), so one bad
post can't half-publish the batch. Phase 2 is not filesystem-transactional — a
mid-batch failure (e.g. disk full) can leave a partial tree — but the next run's
content-compare plus the Action's rebase-retry self-heal it, and the realistic
failure (a missing card) is caught in Phase 1 before any write.
"""

import argparse
import re
import sys
from collections import namedtuple
from pathlib import Path
from urllib.parse import urlparse

# This script lives at <repo-root>/tooling/publish-to-pages.py, so the repo root
# is two parents up. `og_card_source` is resolved against THIS, independent of
# CWD — the runbook invokes from a detached worktree of the Pages repo.
REPO_ROOT = Path(__file__).resolve().parent.parent

# Upstream-only frontmatter fields, stripped on publish (Pages Jekyll ignores
# them):
#   claude_code_version_verified — drives the re-verification cadence here (#14)
#   og_card_source               — the OG-card pointer (#77); consumed by THIS
#                                  script to find the image, never deployed
DROP_FIELDS = {"claude_code_version_verified", "og_card_source"}

# One intended write. The Phase-1 plan is keyed by resolved destination Path so
# collisions are detectable and a future "delete targets with no source" diff is
# a set-difference, not a restructure.
PlanEntry = namedtuple("PlanEntry", "data kind post_name")


class PublishError(Exception):
    """A fail-closed condition. Aborts the whole run with zero writes."""


def split_frontmatter(text: str) -> tuple[str, str]:
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.DOTALL)
    if not m:
        raise PublishError("no frontmatter block found")
    return m.group(1), m.group(2)


def _top_level_key(line: str) -> str | None:
    """The key of a top-level frontmatter line, or None for indented / non-key lines.

    Line-level (no YAML parser), so the byte-for-byte formatting guarantee from
    #14/#76 is preserved — a line either matches a known key or passes through
    untouched."""
    if line.startswith(" ") or ":" not in line:
        return None
    return line.partition(":")[0].strip()


def read_field(fm_block: str, key: str) -> str | None:
    """Value of a top-level frontmatter key, or None if absent."""
    for line in fm_block.splitlines():
        if _top_level_key(line) == key:
            return line.partition(":")[2].strip()
    return None


def strip_dropped_fields(fm_block: str) -> str:
    """Drop the top-level frontmatter lines whose key is in DROP_FIELDS."""
    return "\n".join(line for line in fm_block.splitlines() if _top_level_key(line) not in DROP_FIELDS)


def transform_bytes(fm_block: str, body: str) -> bytes:
    """The published markdown: stripped frontmatter + verbatim body, trailing \\n."""
    out = f"---\n{strip_dropped_fields(fm_block)}\n---\n{body}"
    if not out.endswith("\n"):
        out += "\n"
    return out.encode()


def resolve_og_source(og_card_source: str | None) -> Path:
    """Resolve `og_card_source` to an existing file inside the repo. Fail closed.

    Rejects shape (absent / absolute / repo-escaping) before touching the FS."""
    if not og_card_source:
        raise PublishError("missing `og_card_source` frontmatter field")
    p = Path(og_card_source)
    if p.is_absolute():
        raise PublishError(f"`og_card_source` must be repo-root-relative, got absolute {og_card_source!r}")
    resolved = (REPO_ROOT / p).resolve()
    try:
        resolved.relative_to(REPO_ROOT)
    except ValueError:
        raise PublishError(f"`og_card_source` escapes the repo root: {og_card_source!r}")
    if not resolved.is_file():
        raise PublishError(f"og card source not found: {og_card_source!r}")
    return resolved


def og_target_name(og_image: str | None) -> str:
    """Pages target basename, from the post's og_image URL. Fail closed."""
    if not og_image:
        raise PublishError("missing `og_image` frontmatter field")
    name = Path(urlparse(og_image).path).name
    if not name:
        raise PublishError(f"could not derive an OG target basename from og_image {og_image!r}")
    return name


def _add(plan: dict, dest: Path, data: bytes, kind: str, post_name: str) -> None:
    """Record an intended write, failing closed on a target collision."""
    dest = dest.resolve()
    if dest in plan:
        prior = plan[dest]
        raise PublishError(f"target collision ({kind}) with {prior.post_name} ({prior.kind}) at {dest}")
    plan[dest] = PlanEntry(data, kind, post_name)


def build_plan(sources: list[Path], posts_dir: Path, assets_dir: Path) -> dict:
    """Phase 1: resolve+validate every post into a dest-keyed plan. No writes.

    Raises PublishError on the first fail-closed condition, before any output is
    written, so a bad post never half-publishes the batch. Each source's failures
    are tagged with its filename in one place, so leaf validators raise bare."""
    plan: dict[Path, PlanEntry] = {}
    for src in sources:
        if not src.is_file():
            raise PublishError(f"source not found: {src}")
        try:
            fm_block, body = split_frontmatter(src.read_text())
            _add(plan, posts_dir / src.name, transform_bytes(fm_block, body), "post", src.name)
            og_src = resolve_og_source(read_field(fm_block, "og_card_source"))
            target = assets_dir / og_target_name(read_field(fm_block, "og_image"))
            _add(plan, target, og_src.read_bytes(), "image", src.name)
        except PublishError as e:
            raise PublishError(f"{src.name}: {e}")
    return plan


def write_if_changed(dest: Path, data: bytes, dry_run: bool) -> bool:
    """Write `data` to `dest` only if the bytes differ. Returns whether changed.

    The parent dir is a precondition (checked up front), never created here — a
    missing Pages dir means the worktree isn't set up, which should fail loud."""
    if dest.exists() and dest.read_bytes() == data:
        return False
    if not dry_run:
        dest.write_bytes(data)
    return True


def run(sources, posts_dir, assets_dir, dry_run) -> int:
    # Phase-1 preconditions: the Pages dirs must already exist. Do NOT mkdir —
    # absence means the worktree isn't checked out, an operator error.
    for label, d in (("posts dir", posts_dir), ("assets dir", assets_dir)):
        if not d.is_dir():
            raise PublishError(f"{label} not found: {d} — is the Pages worktree checked out?")

    plan = build_plan(sources, posts_dir, assets_dir)

    # Phase 2: apply. Content-compare means unchanged outputs write nothing.
    prefix = "[dry-run] " if dry_run else ""
    changed = 0
    for dest in sorted(plan):
        entry = plan[dest]
        if write_if_changed(dest, entry.data, dry_run):
            changed += 1
            print(f"{prefix}{entry.kind:5} CHANGED   {dest}")
        else:
            print(f"{prefix}{entry.kind:5} unchanged {dest}")
    print(f"{prefix}{changed} change(s) across {len(plan)} target(s).")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Transform + publish posts (and their OG cards) to the Jekyll Pages tree.",
    )
    ap.add_argument("sources", nargs="+", type=Path, metavar="source.md", help="post(s) to publish")
    ap.add_argument("--posts-dir", required=True, type=Path, help="Pages _posts/ directory")
    ap.add_argument("--assets-dir", required=True, type=Path, help="Pages assets/img/ directory")
    ap.add_argument("--dry-run", action="store_true", help="resolve + compare, but write nothing")
    args = ap.parse_args(argv)
    return run(args.sources, args.posts_dir, args.assets_dir, args.dry_run)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except PublishError as e:
        sys.exit(f"error: {e}")
