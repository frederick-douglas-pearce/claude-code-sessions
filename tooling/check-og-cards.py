#!/usr/bin/env python3
"""Pre-merge guard: every post under posts/ has a resolvable OG card.

The Pages-sync Action (`.github/workflows/pages-sync.yml` → `tooling/publish-to-pages.py`)
resolves each post's `og_card_source`, copies the rendered card into the Pages
repo, and **fails closed** if it can't. But that only runs at publish time — on a
push to `main` — so a post merged without its (manually rendered) OG card turns the
sync red on `main`, after the fact. (It did, for the Part 3 post: the draft reached
`main` via a squash-merge before its card existed.)

This guard runs the publisher's OWN Phase-1 validator (`build_plan`) on PRs, so the
same fail-closed conditions — missing/empty `og_card_source`, an absolute or
repo-escaping path, a missing source file, a missing `og_image`, and cross-post
image-target collisions — surface on the PR instead of on `main`. By reusing
`build_plan` rather than re-deriving the rules, the guard cannot drift from what
publish actually enforces; if a future format adds a fail-closed condition there,
the guard inherits it for free.

It guards card *presence*, not *generation*: rendering stays the manual `og-card`
skill step (`.claude/skills/og-card/SKILL.md`). Stdlib only; needs no Pages repo,
checkout, or PAT — `build_plan` is Phase 1 (no writes), so the Pages target dirs are
passed as inert placeholders used only as plan keys.

Usage:
    python3 tooling/check-og-cards.py [posts/NNNN-*.md ...]

Defaults to every dated post (`posts/[0-9][0-9][0-9][0-9]-*.md`), matching the
publisher's own selection so the two see the same file set (and the guard skips
`posts/README.md`). Exit 0 if all resolve, 1 with a per-post report otherwise.
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

# Reuse publish-to-pages.py verbatim so the guard can't drift from the publisher.
# The script's filename is hyphenated (not importable by name), so we load it the
# same way its own tests do. (Renaming it to `publish_to_pages.py` to drop this
# dance across all three consumers is a sensible separate `refactor(tooling):` PR.)
_SCRIPT = Path(__file__).resolve().parent / "publish-to-pages.py"
_spec = importlib.util.spec_from_file_location("publish_to_pages", _SCRIPT)
ptp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ptp)

# Inert stand-ins for the Pages target dirs. `build_plan` is Phase 1 (no writes)
# and uses these only as resolved dict keys, so they need not exist. Two posts
# whose `og_image` basenames collide map to the same key under _PAGES_ASSETS —
# which is exactly how `build_plan` detects a real cross-post collision.
_PAGES_POSTS = Path("/__pages__/_posts")
_PAGES_ASSETS = Path("/__pages__/assets/img")


def _bare(err: ptp.PublishError, name: str) -> str:
    """`build_plan` tags errors as '<post>: <msg>'; drop the prefix for the report."""
    msg = str(err)
    prefix = f"{name}: "
    return msg[len(prefix):] if msg.startswith(prefix) else msg


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Guard: every post under posts/ has a resolvable OG card "
        "(runs publish-to-pages.py's own fail-closed validator).",
    )
    ap.add_argument(
        "posts",
        nargs="*",
        type=Path,
        help="posts to check (default: every posts/[0-9][0-9][0-9][0-9]-*.md)",
    )
    args = ap.parse_args(argv)

    posts = list(args.posts) or sorted((ptp.REPO_ROOT / "posts").glob("[0-9][0-9][0-9][0-9]-*.md"))
    if not posts:
        print("no posts found to check", file=sys.stderr)
        return 0

    # Per-post: run the real validator on each post alone, so we collect EVERY
    # failing post. (`build_plan` raises on the first failure, so a single
    # whole-batch call would stop at one and hide the rest.)
    results: list[tuple[str, str | None]] = []
    ok_sources: list[Path] = []
    for src in posts:
        try:
            ptp.build_plan([src], _PAGES_POSTS, _PAGES_ASSETS)
            results.append((src.name, None))
            ok_sources.append(src)
        except ptp.PublishError as e:
            results.append((src.name, _bare(e, src.name)))

    # Whole-batch over the individually-valid posts: the one condition a per-post
    # pass can't see is two posts colliding on the same Pages image target.
    collision: str | None = None
    if len(ok_sources) > 1:
        try:
            ptp.build_plan(ok_sources, _PAGES_POSTS, _PAGES_ASSETS)
        except ptp.PublishError as e:
            collision = str(e)

    for name, err in results:
        print(f"  [{'FAIL' if err else 'ok'}] {name}" + (f" — {err}" if err else ""))
    if collision:
        print(f"  [FAIL] cross-post image collision — {collision}")

    n_fail = sum(1 for _, e in results if e) + (1 if collision else 0)
    if n_fail:
        sys.stdout.flush()  # ensure the per-post report precedes the stderr summary in CI logs
        print(
            f"\n{n_fail} OG-card problem(s). This is the same fail-closed resolution the "
            "Pages-sync\nAction runs at publish time — fixing it here keeps it off `main`. "
            "Render the card\nwith the og-card skill (.claude/skills/og-card/SKILL.md) and "
            "set the post's\n`og_card_source`, or correct the pointer.",
            file=sys.stderr,
        )
        return 1

    print(f"\nAll {len(posts)} post(s) have a resolvable OG card.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
