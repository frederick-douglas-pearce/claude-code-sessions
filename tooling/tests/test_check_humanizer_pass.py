#!/usr/bin/env python3
"""
Tests for tooling/check-humanizer-pass.py (issue #223). Stdlib only.

Run directly:
    python3 tooling/tests/test_check_humanizer_pass.py
or via pytest. The guard checks that a post RECORDS a humanizer pass, never that
its prose is clean (#223, D-1), so these tests pin the recording contract: a
missing, empty, or non-version value fails; an explicit `none` passes and is
counted; every failing post is reported, not just the first.
"""

from __future__ import annotations

import importlib.util
import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

GUARD = Path(__file__).resolve().parent.parent / "check-humanizer-pass.py"
_spec = importlib.util.spec_from_file_location("check_humanizer_pass", GUARD)
chp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(chp)


POST_TEMPLATE = """\
---
layout: post
title: "Test post"
date: 2026-01-01 00:00:00-0800
claude_code_version_verified: v2.1.150
{field_line}---

Body line.
"""


class GuardTestCase(unittest.TestCase):
    """A throwaway repo per test, with the publisher module's REPO_ROOT (which the
    guard's default glob reads) pointed at it."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name) / "repo"
        self.posts = self.repo / "posts"
        self.posts.mkdir(parents=True, exist_ok=True)
        chp.ptp.REPO_ROOT = self.repo

    def tearDown(self):
        self._tmp.cleanup()

    def add_post(self, slug, value=chp.DECLINED, *, omit=False):
        """Write a dated post named to match the publisher glob. `value` is the
        humanizer_pass value; `omit=True` leaves the field out entirely."""
        field_line = "" if omit else f"humanizer_pass: {value}\n"
        src = self.posts / f"2026-01-01-{slug}.md"
        src.write_text(POST_TEMPLATE.format(field_line=field_line))
        return src

    def run_guard(self, argv=None):
        """Run the guard; return (exit_code, combined_stdout_stderr)."""
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = chp.main([] if argv is None else argv)
        return code, out.getvalue() + err.getvalue()

    # --- happy path -------------------------------------------------------

    def test_recorded_version_passes(self):
        self.add_post("anatomy", "v3.0.0")
        code, text = self.run_guard()
        self.assertEqual(code, 0, text)
        self.assertIn("record a humanizer pass", text)

    def test_version_without_leading_v_passes(self):
        """The plugin manifest reports "3.0.0"; the docs write "v3.0.0". Both count."""
        self.add_post("anatomy", "3.0.0")
        code, text = self.run_guard()
        self.assertEqual(code, 0, text)

    def test_quoted_value_passes(self):
        self.add_post("anatomy", '"v3.0.0"')
        code, text = self.run_guard()
        self.assertEqual(code, 0, text)

    def test_two_part_version_passes(self):
        self.add_post("anatomy", "v3.1")
        code, text = self.run_guard()
        self.assertEqual(code, 0, text)

    # --- the declined value -----------------------------------------------

    def test_none_passes_and_is_counted(self):
        """`none` is a deliberate record of no pass (#223, D-5), not an absence."""
        self.add_post("anatomy", chp.DECLINED)
        self.add_post("retry", "v3.0.0")
        code, text = self.run_guard()
        self.assertEqual(code, 0, text)
        self.assertIn("1 carry", text)
        self.assertIn("no pass recorded", text)

    # --- failures ---------------------------------------------------------

    def test_missing_field_fails(self):
        self.add_post("anatomy", omit=True)
        code, text = self.run_guard()
        self.assertEqual(code, 1, text)
        self.assertIn("no `humanizer_pass` in frontmatter", text)

    def test_empty_field_fails(self):
        self.add_post("anatomy", "")
        code, text = self.run_guard()
        self.assertEqual(code, 1, text)
        self.assertIn("is empty", text)

    def test_boolean_value_fails(self):
        """A bare `true` records no version, so it can't identify which pattern
        list ran (#223, D-2). Rejected on purpose."""
        self.add_post("anatomy", "true")
        code, text = self.run_guard()
        self.assertEqual(code, 1, text)
        self.assertIn("is not a skill version", text)

    def test_missing_frontmatter_fails(self):
        src = self.posts / "2026-01-01-broken.md"
        src.write_text("no frontmatter here\n")
        code, text = self.run_guard()
        self.assertEqual(code, 1, text)
        self.assertIn("frontmatter", text)

    def test_declined_with_stray_space_is_still_counted(self):
        """`check_value` and the declined count must normalize identically; they
        used to differ by one strip(), so `"none "` passed but was not counted."""
        self.add_post("anatomy", '"none "')
        code, text = self.run_guard()
        self.assertEqual(code, 0, text)
        self.assertIn("1 carry", text)

    def test_inline_yaml_comment_is_accepted(self):
        """Recording the date beside the version is natural; a comment is not
        part of the value."""
        self.add_post("anatomy", "v3.0.0  # ran 2026-09-08")
        code, text = self.run_guard()
        self.assertEqual(code, 0, text)

    def test_non_utf8_locale_does_not_traceback(self):
        """Posts are full of em dashes; the read must not depend on the runner's
        locale. UnicodeDecodeError is a ValueError, so an OSError handler misses it."""
        src = self.add_post("anatomy", "v3.0.0")
        src.write_bytes(src.read_bytes().replace(b"Body line.", "Body \u2014 line.".encode()))
        code, text = self.run_guard()
        self.assertEqual(code, 0, text)

    def test_unreadable_path_is_reported_not_raised(self):
        """A bad explicit path belongs in the report, not in a traceback."""
        code, text = self.run_guard([str(self.posts / "2026-01-01-nope.md")])
        self.assertEqual(code, 1, text)
        self.assertIn("cannot read 2026-01-01-nope.md", text)
        self.assertTrue(text.isascii(), "report must survive an ASCII-locale runner")
        self.assertNotIn(str(self.repo), text)

    def test_reports_every_failing_post(self):
        """One CI run should surface the whole backlog, not stop at the first."""
        self.add_post("one", omit=True)
        self.add_post("two", omit=True)
        self.add_post("three", "v3.0.0")
        code, text = self.run_guard()
        self.assertEqual(code, 1, text)
        self.assertIn("2026-01-01-one.md", text)
        self.assertIn("2026-01-01-two.md", text)
        self.assertIn("2 post(s) with no recorded humanizer pass", text)

    # --- selection --------------------------------------------------------

    def test_explicit_paths_override_the_glob(self):
        self.add_post("good", "v3.0.0")
        bad = self.add_post("bad", omit=True)
        code, _ = self.run_guard([str(self.posts / "2026-01-01-good.md")])
        self.assertEqual(code, 0)
        code, _ = self.run_guard([str(bad)])
        self.assertEqual(code, 1)

    def test_readme_is_not_checked(self):
        """The glob is dated posts only, matching the publisher's own selection."""
        (self.posts / "README.md").write_text("# Posts\n\nNo frontmatter.\n")
        self.add_post("anatomy", "v3.0.0")
        code, text = self.run_guard()
        self.assertEqual(code, 0, text)
        self.assertNotIn("README", text)

    def test_empty_glob_fails_rather_than_reporting_green(self):
        """An empty posts/ means the layout moved or REPO_ROOT mis-resolved. A
        guard that passes while checking zero posts is worse than one that fails."""
        code, text = self.run_guard()
        self.assertEqual(code, 1, text)
        self.assertIn("no dated posts found", text)

    # --- value checking, directly -----------------------------------------

    def test_check_value_matrix(self):
        for raw, ok in [
            ("v3.0.0", True),
            ("3.0.0", True),
            ("v3.1", True),
            ("  v3.0.0  ", True),
            ("'v3.0.0'", True),
            (chp.DECLINED, True),
            (None, False),
            ("", False),
            ("   ", False),
            ("true", False),
            ("yes", False),
            ("done", False),
            ("v3.0.0 (partial)", False),
        ]:
            with self.subTest(raw=raw):
                self.assertEqual(chp.check_value(raw) is None, ok)


if __name__ == "__main__":
    unittest.main(verbosity=2)
