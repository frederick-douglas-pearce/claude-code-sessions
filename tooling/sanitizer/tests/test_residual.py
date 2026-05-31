"""Tests for the post-scrub residual secret scan (issue #24).

Covers PRD section 5 (the residual scan philosophy) and the unit-level
contract of ``scan_residual``: matched patterns raise
``ResidualSecretError`` with only the pattern's ``kind`` label, never the
matched bytes (D-2 invariant extended to exception state).

Per PRD section 14 the fixtures here contain **pattern-matching-but-fake
secrets** -- never a real key.
"""

from __future__ import annotations

import re

import pytest

from ccs_sanitize.config import ExtraSecretPattern
from ccs_sanitize.residual import ResidualSecretError, scan_residual


# ----- happy path --------------------------------------------------------


def test_clean_text_returns_none() -> None:
    assert scan_residual("nothing-credential-shaped here", ()) is None


def test_empty_text_is_clean() -> None:
    assert scan_residual("", ()) is None


def test_redacted_placeholder_is_clean() -> None:
    """``<REDACTED:anthropic-key>`` must not itself match any secret pattern,
    otherwise the scan would flag every successfully-redacted output."""
    assert scan_residual("prefix <REDACTED:anthropic-key> suffix", ()) is None


# ----- built-in patterns -------------------------------------------------


def test_tier1_anthropic_key_raises_with_kind_only() -> None:
    survivor = "sk-ant-" + "A" * 25
    with pytest.raises(ResidualSecretError) as exc:
        scan_residual(f"residue: {survivor} here", ())
    assert exc.value.kind == "anthropic-key"
    # D-2: the matched bytes must not appear in the exception's str/repr.
    rendered = str(exc.value)
    assert survivor not in rendered
    assert "anthropic-key" in rendered


def test_tier1_github_pat_raises() -> None:
    survivor = "ghp_" + "B" * 36
    with pytest.raises(ResidualSecretError) as exc:
        scan_residual(survivor, ())
    assert exc.value.kind == "github-pat-classic"


def test_tier2_jwt_raises() -> None:
    survivor = (
        "eyJ" + "a" * 12 + "." + "b" * 12 + "." + "c" * 12
    )
    with pytest.raises(ResidualSecretError) as exc:
        scan_residual(survivor, ())
    assert exc.value.kind == "jwt"


def test_pem_armor_raises_even_on_single_line() -> None:
    """The residual joiner uses ``\\n`` and PEM armor matches a single
    header line; verifies the join-separator invariant from
    ``scan_residual``'s docstring."""
    survivor = "-----BEGIN OPENSSH PRIVATE KEY-----"
    with pytest.raises(ResidualSecretError) as exc:
        scan_residual(f"line1\n{survivor}\nline3", ())
    assert exc.value.kind == "pem-private-key"


# ----- extras -----------------------------------------------------------


def _make_regex_extra(pattern: str, kind: str) -> ExtraSecretPattern:
    """Build a regex ExtraSecretPattern.

    ``ExtraSecretPattern.__post_init__`` validates that ``compiled`` matches
    the source derived from ``pattern`` (with ``re:`` prefix stripped for
    regex shapes), so we build the ``pattern`` field with the prefix and
    compile the suffix -- exactly what the loader does internally."""
    return ExtraSecretPattern(
        pattern=f"re:{pattern}",
        kind=kind,
        compiled=re.compile(pattern),
    )


def test_extra_pattern_raises_with_extra_kind() -> None:
    extra = _make_regex_extra(r"CORP-[A-Z0-9]{16}", "corp-token")
    with pytest.raises(ResidualSecretError) as exc:
        scan_residual("found CORP-" + "A" * 16, (extra,))
    assert exc.value.kind == "corp-token"


def test_extras_run_after_builtins_so_builtin_kind_wins_on_overlap() -> None:
    """If a string matches both a built-in and an extra, the built-in label
    is the one reported. This mirrors ``build_secret_transform``'s order
    (built-ins first) so detect-during-scrub and verify-after-scrub agree."""
    extra = _make_regex_extra(r"sk-ant-[A-Za-z0-9_-]+", "custom-anthropic")
    with pytest.raises(ResidualSecretError) as exc:
        scan_residual("sk-ant-" + "A" * 25, (extra,))
    assert exc.value.kind == "anthropic-key"  # built-in wins


def test_no_extras_no_builtin_hit_passes() -> None:
    extra = _make_regex_extra(r"CORP-[A-Z0-9]{16}", "corp-token")
    assert scan_residual("plain text only", (extra,)) is None
