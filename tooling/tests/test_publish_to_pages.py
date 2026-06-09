#!/usr/bin/env python3
"""
Tests for tooling/publish-to-pages.py (issue #78).

Focus is the fail-closed contract and content-compare idempotency — the
silent-wrong-image and partial-deploy failure modes the #77/#78 design exists to
prevent. A green sync that ships wrong bytes is the plan's stated nightmare, so
these paths are the ones worth pinning.

Run:  python3 tooling/tests/test_publish_to_pages.py
Exits non-zero on first failure. No third-party deps.
"""

import importlib.util
import io
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "publish-to-pages.py"

_spec = importlib.util.spec_from_file_location("publish_to_pages", SCRIPT)
ptp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ptp)


POST_TEMPLATE = """\
---
layout: post
title: "A title"
date: 2026-01-01 00:00:00-0800
description: "desc"
categories: ["foundation"]
tags: ["claude-code"]
og_image: https://example.github.io/assets/img/{slug}-og.png
og_card_source: {card_rel}
featured: false
claude_code_version_verified: v9.9.9
---

Body line one.
Body line two.
"""


class Env:
    """A throwaway repo + Pages tree. Overrides the module's REPO_ROOT so
    og_card_source resolves against our temp repo, not the real checkout."""

    def __init__(self, tmp: Path):
        self.repo = tmp / "repo"
        self.posts_src = self.repo / "posts"
        self.cards = self.repo / "social" / "images"
        self.pages_posts = tmp / "pages" / "_posts"
        self.pages_assets = tmp / "pages" / "assets" / "img"
        for d in (self.posts_src, self.cards, self.pages_posts, self.pages_assets):
            d.mkdir(parents=True, exist_ok=True)
        ptp.REPO_ROOT = self.repo  # resolve_og_source reads this global

    def add_post(self, slug, card_rel, card_bytes=b"PNGDATA", make_card=True):
        if make_card and card_rel is not None:
            card = self.repo / card_rel
            card.parent.mkdir(parents=True, exist_ok=True)
            card.write_bytes(card_bytes)
        src = self.posts_src / f"2026-01-01-{slug}.md"
        body = POST_TEMPLATE.format(slug=slug, card_rel="" if card_rel is None else card_rel)
        src.write_text(body)
        return src

    def run(self, sources, dry_run=False):
        buf = io.StringIO()
        with redirect_stdout(buf):
            ptp.run(sources, self.pages_posts, self.pages_assets, dry_run)
        return buf.getvalue()


# --- test cases ----------------------------------------------------------------


def test_happy_path(env):
    src = env.add_post("anatomy", "social/images/2026-01-03-linkedin-anatomy/og-card.png", b"CARD-A")
    env.run([src])

    published = (env.pages_posts / src.name).read_text()
    assert "og_card_source" not in published, "og_card_source must be stripped on publish"
    assert "claude_code_version_verified" not in published, "version field must be stripped"
    assert "og_image:" in published, "og_image must be preserved"
    assert "Body line one." in published and published.endswith("\n")

    img = env.pages_assets / "anatomy-og.png"
    assert img.read_bytes() == b"CARD-A", "OG card must be copied to <assets>/<og_image basename>"


def test_idempotent_rerun(env):
    src = env.add_post("retry", "social/images/2026-01-04-linkedin-retry/og-card.png", b"CARD-R")
    env.run([src])
    out2 = env.run([src])  # second run, nothing changed upstream
    assert "0 change(s)" in out2, f"re-run should write nothing, got:\n{out2}"
    assert "CHANGED" not in out2


def test_missing_og_card_source(env):
    src = env.add_post("nocard", card_rel=None)  # no og_card_source value
    assert_raises("missing `og_card_source`", env.run, [src])


def test_escaping_og_card_source(env):
    src = env.add_post("escape", "../../../etc/passwd", make_card=False)
    assert_raises("escapes the repo root", env.run, [src])


def test_missing_card_file(env):
    # field present + in-repo, but the file was never rendered
    src = env.add_post("ghost", "social/images/2026-01-05-linkedin-ghost/og-card.png", make_card=False)
    assert_raises("og card source not found", env.run, [src])


def test_missing_source_file(env):
    ghost = env.posts_src / "2026-01-01-does-not-exist.md"
    assert_raises("source not found", env.run, [ghost])


def test_dry_run_writes_nothing(env):
    src = env.add_post("dry", "social/images/2026-01-06-linkedin-dry/og-card.png", b"CARD-D")
    out = env.run([src], dry_run=True)
    assert "[dry-run]" in out
    assert not (env.pages_posts / src.name).exists(), "dry-run must not write the post"
    assert not (env.pages_assets / "dry-og.png").exists(), "dry-run must not write the image"


def test_target_collision(env):
    # Two distinct posts whose og_image basenames collide on one target.
    a = env.add_post("dup", "social/images/2026-01-07-linkedin-a/og-card.png", b"A")
    # second post: different filename + card, same og_image slug -> same target
    src_b = env.posts_src / "2026-01-02-dup.md"  # different date -> different post dest
    (env.repo / "social/images/2026-01-08-linkedin-b").mkdir(parents=True, exist_ok=True)
    (env.repo / "social/images/2026-01-08-linkedin-b/og-card.png").write_bytes(b"B")
    src_b.write_text(POST_TEMPLATE.format(slug="dup", card_rel="social/images/2026-01-08-linkedin-b/og-card.png"))
    assert_raises("target collision", env.run, [a, src_b])
    # fail-closed means nothing was written
    assert not any(env.pages_assets.iterdir()), "collision must abort before any write"
    assert not any(env.pages_posts.iterdir()), "collision must abort before any write"


# --- runner --------------------------------------------------------------------


def assert_raises(needle, fn, *args):
    try:
        fn(*args)
    except ptp.PublishError as e:
        assert needle in str(e), f"expected {needle!r} in error, got: {e}"
        return
    raise AssertionError(f"expected PublishError containing {needle!r}, but no error was raised")


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failures = 0
    for t in tests:
        with tempfile.TemporaryDirectory() as tmp:
            try:
                t(Env(Path(tmp)))
                print(f"  ok   {t.__name__}")
            except AssertionError as e:
                failures += 1
                print(f"  FAIL {t.__name__}: {e}")
            except Exception as e:  # noqa: BLE001 - surface unexpected errors
                failures += 1
                print(f"  ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
