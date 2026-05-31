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
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from ccs_sanitize.rules.secrets import BATCH_PATTERNS, VENDORED_PATTERNS

_REPO_ROOT = Path(__file__).resolve().parents[3]
_HOOK_PATH = _REPO_ROOT / ".claude" / "hooks" / "detect_secrets_in_output.py"


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
