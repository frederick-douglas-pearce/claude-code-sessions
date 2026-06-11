#!/usr/bin/env python3
"""
Tests for tooling/check-og-cards.py (issue #101). Stdlib only.

Run directly:
    python3 tooling/tests/test_check_og_cards.py
or via pytest. The guard reuses publish-to-pages.py's `build_plan`, so these
tests pin the guard's own behavior: it reports EVERY failing post (not just the
first), catches cross-post image collisions, and exits non-zero. The fail-closed
resolution itself is tested in test_publish_to_pages.py; here we verify the guard
wraps it correctly.
"""

from __future__ import annotations

import importlib.util
import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

GUARD = Path(__file__).resolve().parent.parent / "check-og-cards.py"
_spec = importlib.util.spec_from_file_location("check_og_cards", GUARD)
cog = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cog)


POST_TEMPLATE = """\
---
layout: post
title: "Test post"
date: 2026-01-01 00:00:00-0800
og_image: https://example.github.io/assets/img/{og_basename}
og_card_source: {card_rel}
claude_code_version_verified: v2.1.150
---

Body line.
"""


class GuardTestCase(unittest.TestCase):
    """A throwaway repo per test. Points the publisher module's REPO_ROOT (which
    the guard imports and resolves cards against) at the temp repo."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name) / "repo"
        self.posts = self.repo / "posts"
        self.posts.mkdir(parents=True, exist_ok=True)
        # The guard resolves via cog.ptp; the default glob reads cog.ptp.REPO_ROOT.
        cog.ptp.REPO_ROOT = self.repo

    def tearDown(self):
        self._tmp.cleanup()

    def add_post(self, slug, card_rel, *, write_card=True, og_basename=None):
        """Write a dated post named to match the publisher glob. `card_rel` is the
        og_card_source value (None -> empty field). Renders the card file unless
        write_card is False. `og_basename` overrides the og_image basename so two
        posts can be made to collide on one Pages image target."""
        if card_rel and write_card:
            card = self.repo / card_rel
            card.parent.mkdir(parents=True, exist_ok=True)
            card.write_bytes(b"PNGDATA")
        src = self.posts / f"2026-01-01-{slug}.md"
        src.write_text(
            POST_TEMPLATE.format(
                og_basename=og_basename or f"{slug}-og.png",
                card_rel="" if card_rel is None else card_rel,
            )
        )
        return src

    def run_guard(self, argv=None):
        """Run the guard; return (exit_code, combined_stdout_stderr)."""
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cog.main([] if argv is None else argv)
        return code, out.getvalue() + err.getvalue()

    # --- happy path -------------------------------------------------------

    def test_all_cards_present_passes(self):
        self.add_post("anatomy", "social/images/2026-01-03-linkedin-anatomy/og-card.png")
        self.add_post("retry", "social/images/2026-01-04-linkedin-retry/og-card.png")
        code, text = self.run_guard()
        self.assertEqual(code, 0, text)
        self.assertIn("resolvable OG card", text)

    def test_default_glob_skips_readme(self):
        # A non-dated .md (like posts/README.md) must not be checked.
        self.add_post("anatomy", "social/images/2026-01-03-linkedin-anatomy/og-card.png")
        (self.posts / "README.md").write_text("# Posts\n\nNot a post.\n")
        code, text = self.run_guard()
        self.assertEqual(code, 0, text)
        self.assertNotIn("README.md", text)

    # --- fail-closed conditions ------------------------------------------

    def test_missing_card_file_fails(self):
        self.add_post("ghost", "social/images/2026-01-05-linkedin-ghost/og-card.png", write_card=False)
        code, text = self.run_guard()
        self.assertEqual(code, 1, text)
        self.assertIn("og card source not found", text)
        self.assertIn("2026-01-01-ghost.md", text)

    def test_missing_field_fails(self):
        self.add_post("nofield", None)  # og_card_source present but empty
        code, text = self.run_guard()
        self.assertEqual(code, 1, text)
        self.assertIn("missing `og_card_source`", text)

    def test_reports_every_failing_post(self):
        # The guard must not stop at the first failure.
        self.add_post("ghost", "social/images/x/og-card.png", write_card=False)
        self.add_post("nofield", None)
        self.add_post("good", "social/images/2026-01-06-linkedin-good/og-card.png")
        code, text = self.run_guard()
        self.assertEqual(code, 1, text)
        self.assertIn("2026-01-01-ghost.md", text)
        self.assertIn("2026-01-01-nofield.md", text)
        self.assertIn("[ok] 2026-01-01-good.md", text)
        self.assertIn("2 OG-card problem(s)", text)

    def test_cross_post_image_collision_fails(self):
        # Two distinct posts, both with present cards, colliding on one og_image
        # target basename — the condition only a whole-batch pass can see.
        self.add_post("a", "social/images/2026-01-07-linkedin-a/og-card.png", og_basename="dup-og.png")
        self.add_post("b", "social/images/2026-01-08-linkedin-b/og-card.png", og_basename="dup-og.png")
        code, text = self.run_guard()
        self.assertEqual(code, 1, text)
        self.assertIn("collision", text.lower())

    # --- explicit-path mode ----------------------------------------------

    def test_explicit_paths_argument(self):
        good = self.add_post("good", "social/images/2026-01-09-linkedin-good/og-card.png")
        bad = self.add_post("bad", "social/images/none/og-card.png", write_card=False)
        self.assertEqual(self.run_guard([str(good)])[0], 0)
        self.assertEqual(self.run_guard([str(bad)])[0], 1)


if __name__ == "__main__":
    unittest.main()
