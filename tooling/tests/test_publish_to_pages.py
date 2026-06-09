#!/usr/bin/env python3
"""
Tests for tooling/publish-to-pages.py (issue #78). Stdlib only.

Run directly:
    python3 tooling/tests/test_publish_to_pages.py
or via pytest. Focus is the fail-closed contract and content-compare
idempotency — the silent-wrong-image and partial-deploy failure modes the
#77/#78 design exists to prevent. A green sync that ships wrong bytes is the
plan's stated nightmare, so these are the paths worth pinning.
"""

from __future__ import annotations

import importlib.util
import io
import tempfile
import unittest
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


class PublishTestCase(unittest.TestCase):
    """A throwaway repo + Pages tree per test. Points the module's REPO_ROOT at
    the temp repo so og_card_source resolves there, not against the real checkout."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self.repo = tmp / "repo"
        self.posts_src = self.repo / "posts"
        self.pages_posts = tmp / "pages" / "_posts"
        self.pages_assets = tmp / "pages" / "assets" / "img"
        for d in (self.posts_src, self.pages_posts, self.pages_assets):
            d.mkdir(parents=True, exist_ok=True)
        ptp.REPO_ROOT = self.repo  # resolve_og_source reads this global at call time

    def tearDown(self):
        self._tmp.cleanup()

    def add_post(self, slug, card_rel, *, write_card=True, card_bytes=b"PNGDATA"):
        """Write a post with og_card_source = `card_rel` (None -> empty field).
        Also renders the card file, unless write_card is False (the "field points
        at a card that was never generated" case)."""
        if card_rel is not None and write_card:
            card = self.repo / card_rel
            card.parent.mkdir(parents=True, exist_ok=True)
            card.write_bytes(card_bytes)
        src = self.posts_src / f"2026-01-01-{slug}.md"
        src.write_text(POST_TEMPLATE.format(slug=slug, card_rel="" if card_rel is None else card_rel))
        return src

    def run_publish(self, sources, dry_run=False):
        buf = io.StringIO()
        with redirect_stdout(buf):
            ptp.run(sources, self.pages_posts, self.pages_assets, dry_run)
        return buf.getvalue()

    def test_happy_path(self):
        src = self.add_post("anatomy", "social/images/2026-01-03-linkedin-anatomy/og-card.png", card_bytes=b"CARD-A")
        self.run_publish([src])

        published = (self.pages_posts / src.name).read_text()
        self.assertNotIn("og_card_source", published, "og_card_source must be stripped on publish")
        self.assertNotIn("claude_code_version_verified", published, "version field must be stripped")
        self.assertIn("og_image:", published, "og_image must be preserved")
        self.assertIn("Body line one.", published)
        self.assertTrue(published.endswith("\n"))
        self.assertEqual(
            (self.pages_assets / "anatomy-og.png").read_bytes(), b"CARD-A",
            "OG card must be copied to <assets>/<og_image basename>",
        )

    def test_idempotent_rerun(self):
        src = self.add_post("retry", "social/images/2026-01-04-linkedin-retry/og-card.png", card_bytes=b"CARD-R")
        self.run_publish([src])
        out2 = self.run_publish([src])  # second run, nothing changed upstream
        self.assertIn("0 change(s)", out2, f"re-run should write nothing, got:\n{out2}")
        self.assertNotIn("CHANGED", out2)

    def test_missing_og_card_source(self):
        src = self.add_post("nocard", None)  # field present but empty
        with self.assertRaises(ptp.PublishError) as cm:
            self.run_publish([src])
        self.assertIn("missing `og_card_source`", str(cm.exception))

    def test_escaping_og_card_source(self):
        src = self.add_post("escape", "../../../etc/passwd", write_card=False)
        with self.assertRaises(ptp.PublishError) as cm:
            self.run_publish([src])
        self.assertIn("escapes the repo root", str(cm.exception))

    def test_missing_card_file(self):
        src = self.add_post("ghost", "social/images/2026-01-05-linkedin-ghost/og-card.png", write_card=False)
        with self.assertRaises(ptp.PublishError) as cm:
            self.run_publish([src])
        self.assertIn("og card source not found", str(cm.exception))

    def test_missing_source_file(self):
        ghost = self.posts_src / "2026-01-01-does-not-exist.md"
        with self.assertRaises(ptp.PublishError) as cm:
            self.run_publish([ghost])
        self.assertIn("source not found", str(cm.exception))

    def test_dry_run_writes_nothing(self):
        src = self.add_post("dry", "social/images/2026-01-06-linkedin-dry/og-card.png", card_bytes=b"CARD-D")
        out = self.run_publish([src], dry_run=True)
        self.assertIn("[dry-run]", out)
        self.assertFalse((self.pages_posts / src.name).exists(), "dry-run must not write the post")
        self.assertFalse((self.pages_assets / "dry-og.png").exists(), "dry-run must not write the image")

    def test_target_collision(self):
        # Two distinct posts whose og_image basenames collide on one image target.
        a = self.add_post("dup", "social/images/2026-01-07-linkedin-a/og-card.png", card_bytes=b"A")
        src_b = self.posts_src / "2026-01-02-dup.md"  # different post filename -> distinct post dest
        (self.repo / "social/images/2026-01-08-linkedin-b").mkdir(parents=True, exist_ok=True)
        (self.repo / "social/images/2026-01-08-linkedin-b/og-card.png").write_bytes(b"B")
        src_b.write_text(POST_TEMPLATE.format(slug="dup", card_rel="social/images/2026-01-08-linkedin-b/og-card.png"))
        with self.assertRaises(ptp.PublishError) as cm:
            self.run_publish([a, src_b])
        self.assertIn("target collision", str(cm.exception))
        self.assertFalse(any(self.pages_assets.iterdir()), "collision must abort before any write")
        self.assertFalse(any(self.pages_posts.iterdir()), "collision must abort before any write")


if __name__ == "__main__":
    unittest.main()
