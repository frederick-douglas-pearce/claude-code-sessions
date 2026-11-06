#!/usr/bin/env python3
"""Pre-merge guard: every post under posts/ records a humanizer pass.

The humanizer skill (https://github.com/blader/humanizer) strips structural
AI-writing tells from a draft: not-X-but-Y staging, one-line closers, staged
run-ups, forced triads, dashes used as a universal connector, inflated
significance. It is a manual, judgment-heavy step, and nothing about a draft
reveals whether it ran. This guard makes the omission visible before merge
rather than after publication.

**It checks that the pass was recorded, not that the prose is clean** (#223, D-1).
The skill carries a "When not to act" section precisely because these calls need
judgment, and a pattern-matching lint cannot make them. Concretely, on the Part 5
pass a blocking lint would have failed the en dash in `v2.1.5-v2.1.243` (a numeric
range, not a connector), the phrase "unique within a session, not globally" (a
scope correction the reader needs), and four of six surviving uses of "actually"
(all load-bearing). A lint that wrong trains the writer to write around it, which
is worse than no lint. So the frontmatter field is an attestation, and the guard
only enforces that one was made.

One non-version value is valid (#223, D-5): `none` marks a pass deliberately
declined for that post. It keeps a post green without claiming work that never
happened, stays visible in the file instead of hidden in a script allowlist,
and is counted so the debt stays legible.

`predates` used to be a second one, marking the eight posts published before
this convention landed. #314 ran the pass over all eight, which emptied that
closed set, so the value is retired: the guard now rejects it with a pointed
message instead of letting a new post use it to skip the pass.

Frontmatter parsing is reused verbatim from publish-to-pages.py, so the guard
sees exactly the fields the publisher sees and cannot drift from it.

Usage:
    python3 tooling/check-humanizer-pass.py [posts/NNNN-*.md ...]

Defaults to every dated post (`posts/[0-9][0-9][0-9][0-9]-*.md`), matching the
publisher's own selection so the two see the same file set (and the guard skips
`posts/README.md`). Exit 0 if all record a pass, 1 with a per-post report otherwise.
"""

from __future__ import annotations

import argparse
import importlib.util
import re
import sys
from pathlib import Path

# Reuse publish-to-pages.py verbatim so the guard can't drift from the publisher's
# view of frontmatter. The script's filename is hyphenated (not importable by
# name), so we load it the same way check-og-cards.py and the tests do.
_SCRIPT = Path(__file__).resolve().parent / "publish-to-pages.py"
_spec = importlib.util.spec_from_file_location("publish_to_pages", _SCRIPT)
ptp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ptp)

FIELD = "humanizer_pass"

# The one accepted non-version value (#223, D-5): a pass deliberately declined
# for this post. Open-ended, and actionable debt, so the guard counts it.
DECLINED = "none"
NON_VERSION_VALUES = (DECLINED,)

# Retired in #314. It marked the eight posts published before #223, a closed
# set that could never grow; #314 ran the pass over all eight, leaving it empty.
# Rejected with its own message, because the likeliest way to hit it now is a
# post copied from an old branch, and "not a skill version" would not say why.
RETIRED_PREDATES = "predates"

# A recorded pass names the skill version that ran (#223, D-2), so that when the
# skill changes its pattern list, the field identifies which posts predate the
# change. A bare `true` would not, and is rejected on purpose. The leading `v` is
# optional because the plugin manifest reports "3.0.0" while the docs write
# "v3.0.0"; both are accepted, neither is rewritten.
_VERSION_RE = re.compile(r"^v?\d+\.\d+(\.\d+)?$")

# ` # ...` after a value is a YAML comment, not part of it. Recording the date
# beside the version is a natural thing to write, so accept it rather than
# rejecting the line with a message that shows a version and calls it invalid.
_INLINE_COMMENT_RE = re.compile(r"\s+#.*$")


def _normalize(raw: str | None) -> str:
    """The comparable value: inline comment dropped, quotes and space stripped.

    One implementation on purpose. This ran three times with two spellings, and
    the two that skipped the final strip() mis-sorted `"none "` as a recorded
    version, which under-reported the very count D-5 exists to keep legible."""
    if raw is None:
        return ""
    return _INLINE_COMMENT_RE.sub("", raw.strip()).strip().strip("\"'").strip()


def check_value(raw: str | None) -> str | None:
    """None if the recorded value is acceptable, else the reason it isn't."""
    if raw is None:
        return f"no `{FIELD}` in frontmatter"
    value = _normalize(raw)
    if not value:
        return f"`{FIELD}` is empty"
    if value in NON_VERSION_VALUES:
        return None
    if value == RETIRED_PREDATES:
        return (
            f"`{FIELD}: {RETIRED_PREDATES}` was retired in #314, once every post it "
            f"covered had a pass. Run the humanizer and record its version, or "
            f"record `{DECLINED}`"
        )
    if not _VERSION_RE.match(value):
        return (
            f"`{FIELD}: {value}` is not a skill version "
            f"(expected e.g. `v3.0.0`, or `{DECLINED}`)"
        )
    return None


def read_pass(src: Path) -> str | None:
    """The post's recorded `humanizer_pass`, or None if absent.

    Raises PublishError for an unreadable file, so a bad explicit path lands in
    the per-post report like every other failure instead of as a traceback,
    matching check-og-cards.py, whose validator already fails closed this way."""
    try:
        # Posts are UTF-8 and full of em dashes; without an explicit encoding a
        # runner with a non-UTF-8 locale decodes as ASCII and dies. And a
        # UnicodeDecodeError is a ValueError, so an OSError-only handler misses it.
        text = src.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        reason = getattr(e, "strerror", None) or e
        raise ptp.PublishError(f"cannot read {src.name}: {reason}") from e
    fm_block, _ = ptp.split_frontmatter(text)
    return ptp.read_field(fm_block, FIELD)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Guard: every post under posts/ records a humanizer pass "
        "(the pass itself is manual; this checks it was recorded).",
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
        print(
            f"no dated posts found under {ptp.REPO_ROOT / 'posts'}. Expected "
            "posts/[0-9][0-9][0-9][0-9]-*.md; has the directory moved, or is this "
            "script no longer two levels below the repo root?",
            file=sys.stderr,
        )
        return 1

    # Per-post, collecting EVERY failure rather than stopping at the first, so one
    # CI run reports the whole backlog (the check-og-cards.py behavior).
    results: list[tuple[str, str | None, str | None]] = []
    for src in posts:
        try:
            raw = read_pass(src)
        except ptp.PublishError as e:
            results.append((src.name, str(e), None))
            continue
        results.append((src.name, check_value(raw), raw))

    for name, err, raw in results:
        if err:
            print(f"  [FAIL] {name}: {err}")
        elif _normalize(raw) == DECLINED:
            print(f"  [ok]   {name}: {DECLINED} (pass deliberately declined)")
        else:
            print(f"  [ok]   {name}: {raw}")

    n_declined = sum(1 for _, err, raw in results if not err and _normalize(raw) == DECLINED)
    n_fail = sum(1 for _, err, _ in results if err)

    if n_fail:
        sys.stdout.flush()  # keep the per-post report ahead of the stderr summary in CI logs
        print(
            f"\n{n_fail} post(s) with no recorded humanizer pass. Run the humanizer skill over the\n"
            f"draft, then set `{FIELD}: v<version>` in its frontmatter. If the pass was\n"
            f"deliberately skipped, set `{FIELD}: {DECLINED}` to record that instead.",
            file=sys.stderr,
        )
        return 1

    summary = f"\nAll {len(posts)} post(s) record a humanizer pass."
    if n_declined:
        # The actionable number: posts that could have had a pass and did not.
        summary += f" {n_declined} declined a pass."
    print(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
