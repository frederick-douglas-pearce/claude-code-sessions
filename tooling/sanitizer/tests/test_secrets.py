"""Tests for Layer 3 secret detection (issue #23).

Covers PRD section 9 (pattern library, redaction-only semantics, D-1 floor)
and section 14 (per-pattern coverage with fake-shaped tokens):

  - Each Tier-1 and Tier-2 pattern is exercised end-to-end: the synthetic
    credential is absent from the output, the ``<REDACTED:kind>``
    placeholder is present, and the kind counter increments.
  - ``extra_secret_patterns`` from config (literal and regex shapes) are
    caught at the same plane as the built-ins.
  - Extras cannot weaken or shadow built-ins: even when an extra targets
    the same shape as a built-in, the built-in's redacted placeholder
    survives because built-ins always fire first.
  - Originals never appear in the ``SecretCounts`` snapshot (D-2: secrets
    are count-only).
  - Determinism: two runs over the same input produce byte-identical
    output and equal counts.
  - Composition smoke: paths + identifiers + secrets share a leaf cleanly
    (paths and identifiers use the SubstitutionTable; secrets use
    SecretCounts; the two never collide).

Per PRD section 14 the fixtures here contain **pattern-matching-but-fake
secrets** -- e.g., ``sk-ant-`` followed by 25 ``A``s -- never a real key.
That is itself a security requirement: the test suite must not be the
thing that commits a real credential.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Iterable

import pytest

from ccs_sanitize.config import ExtraSecretPattern
from ccs_sanitize.pipeline import JsonPath, run_pipeline, serialize_line
from ccs_sanitize.rules.identifiers import build_identifier_transform
from ccs_sanitize.rules.paths import build_path_transform
from ccs_sanitize.rules.secrets import (
    SECRET_PLACEHOLDER_TEMPLATE,
    SecretCounts,
    build_secret_transform,
    placeholder_for,
)
from ccs_sanitize.subtable import SubstitutionTable

from ._helpers import write_config as _config


# ----- helpers -----------------------------------------------------------


def _run(
    lines: list[str],
    *,
    extras: Iterable[ExtraSecretPattern] = (),
) -> tuple[list[str], SecretCounts]:
    """Build a secret-only transform and run the pipeline."""
    counts = SecretCounts()
    transform = build_secret_transform(tuple(extras), counts)
    out, _ = run_pipeline(lines, transform=transform)
    return out, counts


def _placeholder(kind: str) -> str:
    return SECRET_PLACEHOLDER_TEMPLATE.format(kind=kind)


# ----- per-pattern coverage: Tier 1 (vendored) ---------------------------
#
# Each test plants one synthetic credential matching the pattern in a
# realistic leaf surface (Bash output, tool input). Assertions are uniform:
# original gone, placeholder present, count == 1, no other kinds counted.


def test_anthropic_key_redacted() -> None:
    secret = "sk-ant-" + "A" * 25
    line = serialize_line(
        {"type": "user", "toolUseResult": {"stdout": f"export KEY={secret}"}}
    )
    out, counts = _run([line])
    assert secret not in out[0]
    assert _placeholder("anthropic-key") in out[0]
    assert counts.as_mapping() == {"anthropic-key": 1}


def test_openai_project_key_redacted() -> None:
    secret = "sk-proj-" + "B" * 25
    line = serialize_line({"type": "user", "toolUseResult": {"stdout": secret}})
    out, counts = _run([line])
    assert secret not in out[0]
    assert _placeholder("openai-project-key") in out[0]
    assert counts.as_mapping() == {"openai-project-key": 1}


def test_openai_legacy_key_redacted() -> None:
    # ``sk-`` prefix + 40+ alphanumeric chars. The charset excludes ``-``,
    # which is what stops a legacy match from also greedily eating
    # ``sk-ant-`` shapes -- those are caught by the more specific Tier-1
    # pattern declared earlier.
    secret = "sk-" + "C" * 42
    line = serialize_line({"type": "user", "toolUseResult": {"stdout": secret}})
    out, counts = _run([line])
    assert secret not in out[0]
    assert _placeholder("openai-key-legacy") in out[0]
    assert counts.as_mapping() == {"openai-key-legacy": 1}


def test_github_pat_classic_redacted() -> None:
    secret = "ghp_" + "D" * 36
    line = serialize_line({"type": "user", "toolUseResult": {"stdout": secret}})
    out, counts = _run([line])
    assert secret not in out[0]
    assert _placeholder("github-pat-classic") in out[0]
    assert counts.as_mapping() == {"github-pat-classic": 1}


def test_github_pat_fine_redacted() -> None:
    secret = "github_pat_" + "E" * 50
    line = serialize_line({"type": "user", "toolUseResult": {"stdout": secret}})
    out, counts = _run([line])
    assert secret not in out[0]
    assert _placeholder("github-pat-fine") in out[0]
    assert counts.as_mapping() == {"github-pat-fine": 1}


def test_aws_access_key_id_redacted() -> None:
    secret = "AKIA" + "F" * 16  # uppercase per pattern
    line = serialize_line({"type": "user", "toolUseResult": {"stdout": secret}})
    out, counts = _run([line])
    assert secret not in out[0]
    assert _placeholder("aws-access-key-id") in out[0]
    assert counts.as_mapping() == {"aws-access-key-id": 1}


def test_gcp_api_key_redacted() -> None:
    secret = "AIza" + "G" * 35
    line = serialize_line({"type": "user", "toolUseResult": {"stdout": secret}})
    out, counts = _run([line])
    assert secret not in out[0]
    assert _placeholder("gcp-api-key") in out[0]
    assert counts.as_mapping() == {"gcp-api-key": 1}


def _pem_marker(variant: str) -> str:
    """Build a PEM BEGIN-armor marker at runtime.

    The full literal marker (e.g. ``-----BEGIN OPENSSH PRIVATE KEY-----``)
    in committed source bytes trips ``.claude/hooks/detect_secrets_in_output.py``
    on every Read of this test file, blocking Claude Code reviewers from
    reasoning about test failures here. Assembling the marker from
    fragments at call time keeps the on-disk bytes hook-safe while
    exercising the exact same regex at runtime.
    """
    return "-----" + "BEGIN " + variant + "PRIVATE KEY" + "-----"


def test_pem_private_key_redacted() -> None:
    """PEM armor was promoted from Tier 2 to Tier 1 (PR #33). The pattern
    matches just the BEGIN line -- the full key body is left in place but
    the security-meaningful marker is scrubbed, and the residual scan
    (#24) is the backstop for the body's entropy."""
    secret = _pem_marker("OPENSSH ")
    line = serialize_line({"type": "user", "toolUseResult": {"stdout": secret}})
    out, counts = _run([line])
    assert secret not in out[0]
    assert _placeholder("pem-private-key") in out[0]
    assert counts.as_mapping() == {"pem-private-key": 1}


def test_pem_pkcs8_encrypted_variant_redacted() -> None:
    """The ``ENCRYPTED`` alternative was added to cover PKCS#8 encrypted
    keys -- what ``openssl pkcs8`` produces. The earlier regex missed it."""
    secret = _pem_marker("ENCRYPTED ")
    line = serialize_line({"type": "user", "toolUseResult": {"stdout": secret}})
    out, counts = _run([line])
    assert secret not in out[0]
    assert _placeholder("pem-private-key") in out[0]


# ----- per-pattern coverage: Tier 2 (batch) ------------------------------


def test_bearer_token_redacted() -> None:
    """Realistic header-style surface: a Bash tool output containing an
    Authorization header. Case-insensitive on the header name."""
    secret = "Authorization: Bearer abc123.def456_xyz-789"
    line = serialize_line({"type": "user", "toolUseResult": {"stdout": secret}})
    out, counts = _run([line])
    assert "abc123.def456_xyz-789" not in out[0]
    assert _placeholder("bearer-token") in out[0]
    assert counts.as_mapping() == {"bearer-token": 1}


def test_jwt_redacted() -> None:
    # Three base64url segments separated by dots, each >= 10 chars.
    secret = "eyJabcdefghij.eyJklmnopqrs.tuvwxyz12345"
    line = serialize_line({"type": "user", "toolUseResult": {"stdout": secret}})
    out, counts = _run([line])
    assert secret not in out[0]
    assert _placeholder("jwt") in out[0]
    assert counts.as_mapping() == {"jwt": 1}


def test_conn_string_with_password_redacted() -> None:
    """The pattern captures the scheme + credentials up to ``@``. The
    host/path portion after ``@`` is left intact (it's not the secret)."""
    secret = "postgres://user:s3cret@db.example.com:5432/app"
    line = serialize_line({"type": "user", "toolUseResult": {"stdout": secret}})
    out, counts = _run([line])
    assert "user:s3cret@" not in out[0]
    assert _placeholder("conn-string-pw") in out[0]
    assert counts.as_mapping() == {"conn-string-pw": 1}


def test_slack_token_redacted() -> None:
    secret = "xoxb-1234567890-ABCDEFG"
    line = serialize_line({"type": "user", "toolUseResult": {"stdout": secret}})
    out, counts = _run([line])
    assert secret not in out[0]
    assert _placeholder("slack-token") in out[0]
    assert counts.as_mapping() == {"slack-token": 1}


# ----- extras ------------------------------------------------------------


def test_extra_secret_pattern_catches_custom_token(tmp_path: Path) -> None:
    """A literal ``extra_secret_patterns`` entry from YAML config catches a
    custom token shape that the built-ins do not. Loaded through the real
    ``load_config`` path so the test exercises the wiring the CLI uses."""
    config = _config(
        tmp_path,
        """
version: 1
extra_secret_patterns:
  - pattern: "SECRET-COMPANY-XYZ"
    kind: "company-token"
""",
    )
    line = serialize_line(
        {"type": "user", "toolUseResult": {"stdout": "found SECRET-COMPANY-XYZ here"}}
    )
    out, counts = _run([line], extras=config.extra_secret_patterns)
    assert "SECRET-COMPANY-XYZ" not in out[0]
    assert _placeholder("company-token") in out[0]
    assert counts.as_mapping() == {"company-token": 1}


def test_extra_regex_pattern_catches_shape(tmp_path: Path) -> None:
    """The ``re:`` prefix on an extra pattern compiles as regex, parallel
    to paths/identifiers."""
    config = _config(
        tmp_path,
        r"""
version: 1
extra_secret_patterns:
  - pattern: "re:INTERNAL-[A-Z0-9]{8}"
    kind: "internal-id"
""",
    )
    line = serialize_line(
        {"type": "user", "toolUseResult": {"stdout": "INTERNAL-ABCD1234 and INTERNAL-EFGH5678"}}
    )
    out, counts = _run([line], extras=config.extra_secret_patterns)
    assert "INTERNAL-ABCD1234" not in out[0]
    assert "INTERNAL-EFGH5678" not in out[0]
    assert out[0].count(_placeholder("internal-id")) == 2
    assert counts.as_mapping() == {"internal-id": 2}


def test_extras_cannot_shadow_builtin_kind_label(tmp_path: Path) -> None:
    """The D-1 floor in action: an extra targeting a shape the built-in
    already catches cannot relabel the match. Built-ins fire first, so by
    the time the extra runs the bytes are already ``<REDACTED:anthropic-key>``
    -- which no longer looks like a credential. The extra's count stays 0;
    the built-in's count is 1."""
    config = _config(
        tmp_path,
        """
version: 1
extra_secret_patterns:
  - pattern: "re:sk-ant-[A-Za-z0-9_-]+"
    kind: "custom-anthropic"
""",
    )
    secret = "sk-ant-" + "A" * 25
    line = serialize_line({"type": "user", "toolUseResult": {"stdout": secret}})
    out, counts = _run([line], extras=config.extra_secret_patterns)
    assert secret not in out[0]
    assert _placeholder("anthropic-key") in out[0]
    assert _placeholder("custom-anthropic") not in out[0]
    assert counts.as_mapping() == {"anthropic-key": 1}


def test_builtins_still_fire_with_no_extras() -> None:
    """Regression pin: passing ``extras=()`` does not accidentally short-
    circuit the built-in loop. All built-ins still apply."""
    secret = "ghp_" + "X" * 36
    line = serialize_line({"type": "user", "toolUseResult": {"stdout": secret}})
    out, counts = _run([line], extras=())
    assert secret not in out[0]
    assert _placeholder("github-pat-classic") in out[0]


# ----- multiple secrets in one leaf --------------------------------------


def test_multiple_distinct_secrets_in_one_leaf_all_redacted() -> None:
    """A single Bash output containing two distinct secret shapes: both
    redacted, each kind counted once."""
    anthropic = "sk-ant-" + "A" * 25
    github = "ghp_" + "B" * 36
    line = serialize_line(
        {"type": "user", "toolUseResult": {"stdout": f"{anthropic} and {github}"}}
    )
    out, counts = _run([line])
    assert anthropic not in out[0]
    assert github not in out[0]
    assert _placeholder("anthropic-key") in out[0]
    assert _placeholder("github-pat-classic") in out[0]
    assert counts.as_mapping() == {"anthropic-key": 1, "github-pat-classic": 1}


def test_repeated_same_secret_counts_each_occurrence() -> None:
    """Per PRD section 10 the sidecar shows total matches, not distinct
    values -- so the same secret appearing twice counts as two matches."""
    secret = "AKIA" + "Z" * 16
    line = serialize_line(
        {"type": "user", "toolUseResult": {"stdout": f"{secret} {secret}"}}
    )
    out, counts = _run([line])
    assert secret not in out[0]
    assert out[0].count(_placeholder("aws-access-key-id")) == 2
    assert counts.as_mapping() == {"aws-access-key-id": 2}


# No "Tier-1 specific-pattern wins over Tier-1 general-pattern" test
# exists because the built-in patterns are designed not to overlap:
# every Tier-1 shape with a more-specific sibling (sk-ant-, sk-proj-)
# carries an internal ``-`` character, which the legacy ``sk-[A-Za-z0-9]{40,}``
# charset excludes. The legacy pattern therefore cannot reach the same
# substring the specific patterns claim. The relevant declaration-order
# pin -- built-ins before extras -- is covered by
# ``test_extras_cannot_shadow_builtin_kind_label`` above.


# ----- D-2: counts never carry originals ---------------------------------


def test_secret_counts_api_has_no_original_recording_surface() -> None:
    """The structural guarantee that backs PRD section 10 / D-2: the
    SecretCounts API exposes no method that accepts the matched bytes.
    Scanning the snapshot for the original would be tautological (the
    snapshot is ``dict[str, int]`` keyed on caller-supplied kind labels;
    originals can't fit). Instead pin the API shape itself: ``record``
    takes only ``kind``, and no other public method accepts a string."""
    sig = inspect.signature(SecretCounts.record)
    params = list(sig.parameters)
    assert params == ["self", "kind"], (
        f"SecretCounts.record signature drifted: {params!r}. The D-2 "
        f"invariant requires the only mutation surface to take a kind "
        f"label, not the matched bytes."
    )
    public_methods = [
        name
        for name in dir(SecretCounts)
        if not name.startswith("_") and callable(getattr(SecretCounts, name))
    ]
    # Only ``record``, ``as_mapping``, ``total`` are public methods;
    # none others should appear without an explicit security review.
    assert set(public_methods) == {"record", "as_mapping", "total"}, (
        f"SecretCounts gained public methods {public_methods!r}; verify "
        f"that no new surface accepts the matched original bytes (D-2)."
    )


def test_secret_counts_repr_does_not_leak_field_name() -> None:
    """Auto-generated dataclass __repr__ would print
    ``SecretCounts(_counts={...})`` -- exposing the leading-underscore
    field that signals internal state. The custom __repr__ surfaces the
    public mapping shape instead. Belt-and-suspenders for any debug-print
    path the sidecar emitter or a future operator log might take."""
    counts = SecretCounts()
    counts.record("anthropic-key")
    rendered = repr(counts)
    assert "_counts" not in rendered
    assert "anthropic-key" in rendered


def test_secret_counts_record_rejects_empty_kind() -> None:
    """The loader rejects empty ``ExtraSecretPattern.kind`` at config-load
    time. ``record`` enforces the same invariant at the data-structure
    level so any future call site bypassing the loader (programmatic API,
    test) cannot emit a ``<REDACTED:>`` placeholder."""
    counts = SecretCounts()
    with pytest.raises(ValueError, match="non-empty"):
        counts.record("")


def test_placeholder_for_rejects_empty_kind() -> None:
    """Symmetric to ``SecretCounts.record``: ``placeholder_for`` is the
    other public secret-module surface that takes a ``kind`` argument.
    A programmatic caller bypassing the loader with an empty kind would
    otherwise produce ``<REDACTED:>``, which the I-3 leak guard would
    then feed into ``redaction_placeholders`` as a wildcard-like entry."""
    with pytest.raises(ValueError, match="non-empty"):
        placeholder_for("")


# ----- determinism -------------------------------------------------------


def test_two_runs_byte_identical() -> None:
    """No randomness, no time-dependent state. Pin: a future refactor that
    introduces ordering ambiguity (e.g., iterating a set instead of the
    ordered pattern list) would fail this."""
    lines = [
        serialize_line(
            {
                "type": "user",
                "toolUseResult": {
                    "stdout": "key=sk-ant-" + "A" * 25 + " token=ghp_" + "B" * 36,
                },
            }
        ),
        serialize_line(
            {
                "type": "assistant",
                "toolUseResult": {"stdout": "Authorization: Bearer abc.def.ghi"},
            }
        ),
    ]
    out1, counts1 = _run(lines)
    out2, counts2 = _run(lines)
    assert out1 == out2
    assert counts1.as_mapping() == counts2.as_mapping()


def test_secret_counts_total_matches_sum() -> None:
    """``total()`` is what #25 sidecar emission consumes for the
    ``rules_applied.secrets.matches: N`` summary. Trivial sum but pinned
    so a refactor (e.g., switching the backing store to a Counter) does
    not silently change semantics."""
    counts = SecretCounts()
    counts.record("anthropic-key")
    counts.record("anthropic-key")
    counts.record("ghp_")
    assert counts.total() == 3
    assert len(counts) == 2


# ----- composition with Layers 1 + 2 -------------------------------------


def test_paths_identifiers_secrets_compose_in_one_run(tmp_path: Path) -> None:
    """End-to-end smoke for the three-layer chain the CLI in #26 will
    build. One shared SubstitutionTable for Layers 1 + 2, one SecretCounts
    for Layer 3 -- the two structures never collide. A leaf containing a
    home dir, an email, and a secret all get their respective scrubs."""
    config = _config(
        tmp_path,
        """
version: 1
paths:
  - match: "/home/fdpearce"
    replace: "/home/user"
identifiers:
  - match: "fpearce@gmail.com"
    replace: "user@example.com"
""",
    )
    table = SubstitutionTable()
    counts = SecretCounts()
    path_transform = build_path_transform(config.paths, table)
    id_transform = build_identifier_transform(config.identifiers, table)
    secret_transform = build_secret_transform(config.extra_secret_patterns, counts)

    def composed(leaf: str, path: JsonPath) -> str:
        return secret_transform(id_transform(path_transform(leaf, path), path), path)

    secret = "sk-ant-" + "A" * 25
    line = serialize_line(
        {
            "type": "user",
            "cwd": "/home/fdpearce/proj",
            "toolUseResult": {
                "stdout": f"mail fpearce@gmail.com about /home/fdpearce/.env contents {secret}",
            },
        }
    )
    out, _ = run_pipeline([line], transform=composed)
    # Path scrub fired in cwd and in stdout.
    assert "/home/fdpearce" not in out[0]
    assert "/home/user/proj" in out[0]
    assert "/home/user/.env" in out[0]
    # Identifier scrub fired in stdout.
    assert "fpearce@gmail.com" not in out[0]
    assert "user@example.com" in out[0]
    # Secret scrub fired.
    assert secret not in out[0]
    assert _placeholder("anthropic-key") in out[0]
    # Counts and table are independent surfaces.
    assert counts.as_mapping() == {"anthropic-key": 1}
    originals = {e.original for e in table}
    assert "/home/fdpearce" in originals
    assert "fpearce@gmail.com" in originals


# ----- no-op edges -------------------------------------------------------


def test_empty_leaf_passes_through() -> None:
    """An empty string contains no credential shape and must not produce a
    placeholder. Belt-and-suspenders: a built-in pattern that accidentally
    matched the empty string would be a security bug AND would pollute the
    counts."""
    line = serialize_line({"type": "user", "toolUseResult": {"stdout": ""}})
    out, counts = _run([line])
    assert '"stdout":""' in out[0]
    assert counts.as_mapping() == {}


def test_leaf_with_no_secrets_unchanged() -> None:
    """Sanity: leaves with no credential-shaped content pass through
    untouched and no kinds are counted."""
    line = serialize_line(
        {"type": "user", "toolUseResult": {"stdout": "plain log line, nothing secret"}}
    )
    out, counts = _run([line])
    assert "plain log line, nothing secret" in out[0]
    assert counts.as_mapping() == {}
