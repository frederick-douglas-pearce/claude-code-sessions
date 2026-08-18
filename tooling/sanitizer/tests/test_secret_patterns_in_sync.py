"""I-4 drift guard: vendored Tier-1 patterns vs the hook's SECRET_PATTERNS.

PRD section 9 / D-6: ``rules/secrets.py`` vendors the Tier-1 patterns from
``.claude/hooks/detect_secrets_in_output.py`` instead of importing them at
runtime. The hook is a security boundary that must remain stdlib-only and
must not take a dependency on the sanitizer package. Vendoring is the
right call -- and the sync test is what makes the duplication safe.

This file is the only place both the hook's compiled patterns and the
sanitizer's raw-string patterns are imported together. Failure here means
either side has drifted (added, removed, reordered, or modified a Tier-1
pattern) without the other -- and either side merging without the other
is a security regression.

Loading the hook:

  The hook lives outside the sanitizer's package tree
  (``.claude/hooks/`` vs ``tooling/sanitizer/src/``) so a regular import
  does not see it. Rather than mutate ``sys.path`` -- which leaks into the
  rest of the test session and could silently shadow unrelated modules --
  we use ``importlib.util.spec_from_file_location`` to load the hook file
  directly. The hook is stdlib-only with no top-level side effects, so
  ``exec_module`` is safe.

  Two parent jumps from this test file land at ``tooling/sanitizer/``;
  one more lands at the repo root. If this file ever moves the path math
  needs to update.

Running from an unpacked sdist (issue #182):

  ``tests`` ships in the sdist on purpose, so that a packager or an auditor
  can re-run this suite against the exact published source. An sdist has no
  repo root and no ``.claude/``, so the hook is simply not there and these
  three tests used to fail. Three red tests in the secret-pattern drift
  guard is a bad first impression for a security tool, and the correct
  reading -- an environment assumption, not real drift -- costs a code read.

  So the module skips there. What it must NOT do is skip inside the repo:
  this is the D-6 gate, and a hook deleted or moved in a PR has to be loud.
  The discriminator is ``PKG-INFO``, which every sdist carries at its root
  (PEP 625) and a checkout never does. Deliberately not "the hook file is
  missing" on its own: that reads a deleted hook as a reason to stop
  checking, which is the failure mode this file exists to prevent. In a
  checkout the hook being absent stays a failure, reported by
  ``test_the_hook_is_reachable_in_a_checkout`` below.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from ccs_sanitize.rules.secrets import BATCH_PATTERNS, VENDORED_PATTERNS

_PACKAGE_ROOT = Path(__file__).resolve().parents[1]
_REPO_ROOT = _PACKAGE_ROOT.parents[1]
_HOOK_PATH = _REPO_ROOT / ".claude" / "hooks" / "detect_secrets_in_output.py"

# True only in an unpacked sdist. See the module docstring for why this is
# the condition rather than the hook's absence.
_IN_SDIST = (_PACKAGE_ROOT / "PKG-INFO").exists()

if _IN_SDIST and not _HOOK_PATH.exists():  # pragma: no cover - sdist only
    pytest.skip(
        "the hook is not shipped in the sdist; the D-6 drift guard runs in-repo",
        allow_module_level=True,
    )


def _load_hook_secret_patterns() -> list[tuple[str, str]]:
    """Return the hook's SECRET_PATTERNS normalized to (raw_pattern, label).

    The hook stores compiled ``re.Pattern`` objects; we extract ``.pattern``
    to compare against the sanitizer's raw-string list. The module is loaded
    via importlib (no ``sys.path`` mutation, no leftover state for sibling
    tests) and discarded; only the constant survives.
    """
    spec = importlib.util.spec_from_file_location(
        "ccs_test_hook_under_load", _HOOK_PATH
    )
    assert spec is not None, f"failed to build import spec for {_HOOK_PATH}"
    assert spec.loader is not None, "import spec has no loader"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return [(pattern.pattern, label) for pattern, label in module.SECRET_PATTERNS]


def test_the_hook_is_reachable_in_a_checkout() -> None:
    """Absent hook, inside a checkout, is a failure and not a skip.

    The three tests below would fail anyway, with a ``FileNotFoundError``
    raised from ``exec_module`` several frames down. This one names the
    condition, so that deleting or moving the hook reads as "the drift
    guard lost its other half" rather than as an import problem."""
    assert _HOOK_PATH.exists(), (
        f"the hook is missing at {_HOOK_PATH}. Inside the repo that is a "
        "removed security boundary, not an environment quirk: "
        "VENDORED_PATTERNS in rules/secrets.py has nothing left to be "
        "checked against. Restore it, or retire the vendoring contract in "
        "PRD section 9 / D-6 on purpose."
    )


def test_vendored_patterns_match_hook_element_wise() -> None:
    """The full ordered comparison. Order matters because the hook iterates
    SECRET_PATTERNS in declaration order, and so does
    ``build_secret_transform``; a reorder on one side without the other
    would silently change which pattern fires first on an overlapping
    input."""
    hook_patterns = _load_hook_secret_patterns()
    assert hook_patterns == VENDORED_PATTERNS, (
        "VENDORED_PATTERNS in rules/secrets.py has drifted from "
        ".claude/hooks/detect_secrets_in_output.py SECRET_PATTERNS. "
        "Either reconcile the lists or, if intentional, update both sides "
        "in the same PR. PRD section 9 / D-6."
    )


def test_batch_patterns_are_sanitizer_only() -> None:
    """Tier 2 is explicitly excluded from the sync contract (PRD section 9):
    these are sanitizer-only additions for credential shapes the hook does
    not catch (bearer tokens, JWTs, conn strings, Slack tokens). If a
    Tier-2 label appears in the hook, the architect-review path for
    promoting it to Tier 1 (and removing it from BATCH_PATTERNS) was
    skipped."""
    hook_patterns = _load_hook_secret_patterns()
    hook_labels = {label for _pattern, label in hook_patterns}
    batch_labels = {label for _pattern, label in BATCH_PATTERNS}
    leaked = hook_labels & batch_labels
    assert not leaked, (
        f"BATCH_PATTERNS labels appear in the hook: {sorted(leaked)}. "
        "Tier-2 promotion requires an architect-reviewed PR that moves the "
        "pattern from BATCH_PATTERNS to VENDORED_PATTERNS and adds it to "
        "the hook -- it should not appear in only the hook."
    )


def test_hook_has_no_extra_patterns_beyond_vendored() -> None:
    """Length parity catches a hook-only addition that the equality test
    in ``test_vendored_patterns_match_hook_element_wise`` would also
    catch, but with a clearer error message pointing at "the hook grew
    a pattern" specifically."""
    hook_patterns = _load_hook_secret_patterns()
    assert len(hook_patterns) == len(VENDORED_PATTERNS), (
        f"Hook has {len(hook_patterns)} patterns, sanitizer's "
        f"VENDORED_PATTERNS has {len(VENDORED_PATTERNS)}. A pattern was "
        "added to one side without the other -- update both."
    )
