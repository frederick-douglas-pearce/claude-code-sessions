"""Tests for sidecar emission (issue #25).

Covers PRD section 10 (the ``.scrubbed`` sidecar contract):

  - Round-trip: parse the rendered YAML and confirm every required field
    is present and correctly typed.
  - Sidecar-never-leaks (section 14, I-3): given a config with known
    sensitive originals, assert none appear anywhere in the rendered
    sidecar.
  - Stripped-line counts in the sidecar match the number of dropped lines.
  - Substitution occurrence counts in the sidecar match the actual
    substitutions made.
  - Placeholder synthesis per architect-recommended Option A
    (``<git-branch>``, ``<uuid>``, ``<path-N>``, ``<identifier-N>``).
  - Field order in the rendered YAML matches the PRD section 10 example
    (sanitizer_version first, residual_scan last) -- a determinism
    property the sidecar-diff workflow depends on.
  - The I-3 emit-time leak guard fires on a constructed leak.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ccs_sanitize import __version__
from ccs_sanitize.orchestrator import sanitize_session
from ccs_sanitize.sidecar import (
    SidecarLeakError,
    SidecarMetadata,
    build_sidecar,
    sha256_hex,
    utc_now_iso8601,
)
from ccs_sanitize.subtable import SubstitutionTable

from ._helpers import (
    serialize_test_line as _line,
    write_config as _config,
)


# Synthetic identifiers only -- per CLAUDE.md "Security posture" the test
# suite must not commit real personal data.
_REAL_USER_HOME = "/home/realuser"
_REAL_USER_EMAIL = "user-old@example.test"
_REAL_BRANCH = "feature/SECRET-1234"
_BASE_CONFIG = f"""
version: 1
paths:
  - match: "{_REAL_USER_HOME}"
    replace: "/home/user"
identifiers:
  - match: "{_REAL_USER_EMAIL}"
    replace: "user@example.com"
"""

_FIXED_TS = "2026-05-31T12:00:00Z"


def _metadata(
    *, input_filename: str = "session.jsonl", input_sha256: str = "0" * 64
) -> SidecarMetadata:
    return SidecarMetadata(
        input_filename=input_filename,
        input_sha256=input_sha256,
        config_source="config.yaml",
        scrubbed_at=_FIXED_TS,
    )


# ----- helpers under test ------------------------------------------------


def test_sha256_hex_matches_known_vector() -> None:
    """Pin the helper to a known SHA-256: ``sha256(b"")`` is a well-known
    constant. A regression that swaps the algorithm (e.g., to SHA-1 or
    a non-canonical hex format) surfaces immediately."""
    assert (
        sha256_hex(b"")
        == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    )


def test_utc_now_iso8601_shape() -> None:
    """The CLI embeds this string in the sidecar verbatim, so the shape is
    part of the contract: ``YYYY-MM-DDTHH:MM:SSZ`` (no offset, no
    fractional seconds)."""
    ts = utc_now_iso8601()
    assert ts.endswith("Z")
    assert len(ts) == len("2026-05-31T12:00:00Z")
    # Must round-trip via fromisoformat (Z handling is 3.11+).
    from datetime import datetime
    datetime.fromisoformat(ts.replace("Z", "+00:00"))


# ----- round-trip: every required field present and well-typed -----------


def test_round_trip_all_required_fields_present(tmp_path: Path) -> None:
    config = _config(tmp_path, _BASE_CONFIG)
    secret = "sk-ant-" + "A" * 25
    lines = [
        _line(
            {
                "type": "user",
                "cwd": f"{_REAL_USER_HOME}/projects/foo",
                "message": {
                    "content": [
                        {"type": "text", "text": f"ping {_REAL_USER_EMAIL}"}
                    ]
                },
                "toolUseResult": {"stdout": f"token={secret}"},
            }
        ),
        _line({"type": "file-history-snapshot", "snapshot": {"trackedFileBackups": {}}}),
    ]
    out, counts, subtable, secret_counts = sanitize_session(lines, config)

    sidecar_yaml = build_sidecar(
        metadata=_metadata(),
        config=config,
        serialized_lines=out,
        counts=counts,
        subtable=subtable,
        secret_counts=secret_counts,
    )
    payload = yaml.safe_load(sidecar_yaml)

    # Required scalar fields (PRD section 10).
    assert payload["sanitizer_version"] == __version__
    assert payload["scrubbed_at"] == _FIXED_TS
    assert payload["input_filename"] == "session.jsonl"
    assert payload["input_sha256"] == "0" * 64
    assert payload["config_version"] == 1
    assert payload["config_source"] == "config.yaml"
    # 1 input line survived + 1 stripped (file-history-snapshot) = 2 processed.
    assert payload["lines_processed"] == 2
    assert payload["stripped_lines"] == {"file-history-snapshot": 1}

    # rules_applied shape.
    rules_applied = payload["rules_applied"]
    assert set(rules_applied) == {"paths", "identifiers", "secrets", "jitter"}
    assert rules_applied["paths"]["substitutions"] >= 1
    assert rules_applied["paths"]["distinct"] >= 1
    assert rules_applied["identifiers"]["substitutions"] >= 1
    assert rules_applied["identifiers"]["distinct"] >= 1
    assert rules_applied["secrets"] == {"matches": 1}
    assert rules_applied["jitter"] == "disabled"

    # substitutions list: each row has the four required columns.
    substitutions = payload["substitutions"]
    assert isinstance(substitutions, list)
    assert substitutions  # non-empty -- we scrubbed at least one path
    for row in substitutions:
        assert set(row) == {"rule", "placeholder", "replacement", "occurrences"}
        assert row["rule"] in {"paths", "identifiers"}
        assert row["placeholder"].startswith("<") and row["placeholder"].endswith(">")
        assert isinstance(row["replacement"], str)
        assert isinstance(row["occurrences"], int)
        assert row["occurrences"] >= 1

    assert payload["residual_scan"] == "clean"


def test_field_order_matches_prd_section_10(tmp_path: Path) -> None:
    """The PRD example pins the field order; a reviewer reads the sidecar
    top-down and downstream diff tooling (fixture validator, sibling
    projects) gets stable output. ``yaml.safe_dump(sort_keys=False)`` is
    what enforces this; pin it with a test so a future flip to
    ``sort_keys=True`` is loud rather than silent."""
    config = _config(tmp_path, _BASE_CONFIG)
    lines = [_line({"type": "user", "cwd": _REAL_USER_HOME})]
    out, counts, subtable, secret_counts = sanitize_session(lines, config)

    sidecar_yaml = build_sidecar(
        metadata=_metadata(),
        config=config,
        serialized_lines=out,
        counts=counts,
        subtable=subtable,
        secret_counts=secret_counts,
    )
    expected_order = [
        "sanitizer_version",
        "scrubbed_at",
        "input_filename",
        "input_sha256",
        "config_version",
        "config_source",
        "lines_processed",
        "stripped_lines",
        "rules_applied",
        "substitutions",
        "residual_scan",
    ]
    # Top-level keys only: skip lines that are indented (nested mapping
    # entries) or list-item markers (substitutions rows render as
    # ``- rule: paths`` and would otherwise look like top-level keys).
    actual_order = [
        line.split(":", 1)[0]
        for line in sidecar_yaml.splitlines()
        if line
        and not line.startswith(" ")
        and not line.startswith("-")
        and ":" in line
    ]
    assert actual_order == expected_order


# ----- the I-3 sidecar-never-leaks test (PRD section 14) -----------------


def test_sidecar_never_leaks_originals(tmp_path: Path) -> None:
    """No configured original sensitive token may appear anywhere in the
    rendered sidecar (PRD section 14, I-3). The originals here cover the
    three categories the PRD calls out: home dir (paths layer), email
    (identifiers layer), and a Tier-1 secret (built-in pattern)."""
    config = _config(tmp_path, _BASE_CONFIG)
    secret = "sk-ant-" + "A" * 25
    lines = [
        _line(
            {
                "type": "user",
                "cwd": f"{_REAL_USER_HOME}/projects/foo",
                "message": {
                    "content": [
                        {"type": "text", "text": f"ping {_REAL_USER_EMAIL}"}
                    ]
                },
                "toolUseResult": {"stdout": secret},
            }
        )
    ]
    out, counts, subtable, secret_counts = sanitize_session(lines, config)
    sidecar_yaml = build_sidecar(
        metadata=_metadata(),
        config=config,
        serialized_lines=out,
        counts=counts,
        subtable=subtable,
        secret_counts=secret_counts,
    )
    assert _REAL_USER_HOME not in sidecar_yaml
    assert _REAL_USER_EMAIL not in sidecar_yaml
    assert secret not in sidecar_yaml
    # Even the partial form must be absent: ``realuser`` (the path tail)
    # would be a half-leak.
    assert "realuser" not in sidecar_yaml
    # And the email's local-part alone leaks the identity if surfaced.
    assert "user-old" not in sidecar_yaml


def test_sidecar_never_leaks_gitbranch_and_uuid_originals(tmp_path: Path) -> None:
    """gitBranch and (when ``remap_uuids`` is on) UUID values are
    sensitive originals recorded by the field-anchored identifier
    transforms. Their replacement (``feature/example`` and the
    remapped UUID) is safe to show; the original never is."""
    config = _config(
        tmp_path,
        """
version: 1
options:
  remap_uuids: true
""",
    )
    real_uuid = "d4ea0acf-3f7e-44e5-b07d-2f0cb19c9da1"
    lines = [
        _line({"type": "user", "gitBranch": _REAL_BRANCH, "sessionId": real_uuid})
    ]
    out, counts, subtable, secret_counts = sanitize_session(lines, config)
    sidecar_yaml = build_sidecar(
        metadata=_metadata(),
        config=config,
        serialized_lines=out,
        counts=counts,
        subtable=subtable,
        secret_counts=secret_counts,
    )
    assert _REAL_BRANCH not in sidecar_yaml
    assert real_uuid not in sidecar_yaml


def test_sidecar_emit_guard_raises_on_constructed_leak(tmp_path: Path) -> None:
    """Defense-in-depth: if some future refactor accidentally smuggles an
    original into the sidecar output, the emit-time leak guard must
    catch it before the bytes reach the CLI. Construct the violation
    by hand-populating a subtable with an entry whose replacement
    contains its own original -- ``build_sidecar`` emits the
    replacement, which then contains the original, which the guard
    detects in the rendered YAML."""
    config = _config(tmp_path, _BASE_CONFIG)
    subtable = SubstitutionTable()
    # The original ``/home/realuser/secret`` is inside the replacement
    # ``[wraps /home/realuser/secret]`` -- the loader's I-3 check does
    # not run on this hand-built table, so the only safety net is the
    # sidecar's own emit-time scan.
    subtable.record(
        "/home/realuser/secret",
        "[wraps /home/realuser/secret]",
        label="paths",
    )
    from ccs_sanitize.pipeline import PipelineCounts
    from ccs_sanitize.rules.secrets import SecretCounts

    with pytest.raises(SidecarLeakError) as exc:
        build_sidecar(
            metadata=_metadata(),
            config=config,
            serialized_lines=[],
            counts=PipelineCounts(),
            subtable=subtable,
            secret_counts=SecretCounts(),
        )
    assert exc.value.category == "original"


def test_sidecar_emit_guard_does_not_false_positive_on_sha_substring(
    tmp_path: Path,
) -> None:
    """Regression for /simplify finding C1: the I-3 emit-time guard must
    not scan ``input_sha256`` (a one-way digest) for originals. A short
    original like ``"abc"`` that incidentally appears in the hex string
    of a real SHA-256 is not a leak -- false positives on every run
    would make the sanitizer unusable for any config with short
    identifier rules."""
    config = _config(
        tmp_path,
        """
version: 1
identifiers:
  - match: "re:^abc$"
    replace: "xyz"
""",
    )
    lines = [_line({"type": "user", "toolUseResult": {"stdout": "abc"}})]
    out, counts, subtable, secret_counts = sanitize_session(lines, config)
    # Construct a SHA-256 hex that contains the original "abc" as a
    # substring -- exactly what a real input file's hash could produce.
    sha_containing_abc = "abc" + "0" * 61
    md = SidecarMetadata(
        input_filename="session.jsonl",
        input_sha256=sha_containing_abc,
        config_source="config.yaml",
        scrubbed_at=_FIXED_TS,
    )
    # Must NOT raise -- this is a clean run, not a leak.
    build_sidecar(
        metadata=md,
        config=config,
        serialized_lines=out,
        counts=counts,
        subtable=subtable,
        secret_counts=secret_counts,
    )


def test_sidecar_emit_guard_does_not_false_positive_on_extras_matching_scaffolding(
    tmp_path: Path,
) -> None:
    """Regression for /simplify finding C2: a user-supplied extra_secret
    pattern that happens to match a sidecar structural literal (e.g.
    ``"disabled"`` from ``jitter: disabled``, or the synthesized
    ``<path-1>`` placeholders) must NOT fire SidecarLeakError on a
    clean run. The previous shape scanned the entire rendered YAML and
    would break the orchestrator's documented invariant that 'if
    sanitize_session returns, the sidecar can be built'."""
    config = _config(
        tmp_path,
        """
version: 1
extra_secret_patterns:
  - pattern: disabled
    kind: my-flag
  - pattern: "re:<path-\\\\d+>"
    kind: placeholder-shape
""",
    )
    lines = [
        _line({"type": "user", "cwd": _REAL_USER_HOME + "/x"}),
    ]
    out, counts, subtable, secret_counts = sanitize_session(lines, config)
    # Must NOT raise even though the rendered YAML contains literal
    # "disabled" (in jitter: disabled) and "<path-1>" (the synthesized
    # placeholder for the paths entry).
    build_sidecar(
        metadata=_metadata(),
        config=config,
        serialized_lines=out,
        counts=counts,
        subtable=subtable,
        secret_counts=secret_counts,
    )


def test_sidecar_emit_guard_fires_on_secret_pattern_in_payload(
    tmp_path: Path,
) -> None:
    """If a future refactor put a secret-shaped string into the sidecar
    (e.g., as a placeholder), the emit-time guard scans the rendered
    YAML against the built-in secret patterns. Pin that behavior by
    constructing a table whose replacement is itself a synthetic
    Tier-1 secret -- the loader would normally reject this at config
    time, but the table is hand-built here to bypass that check."""
    config = _config(tmp_path, _BASE_CONFIG)
    subtable = SubstitutionTable()
    subtable.record(
        "harmless-original", "sk-ant-" + "A" * 25, label="paths"
    )
    from ccs_sanitize.pipeline import PipelineCounts
    from ccs_sanitize.rules.secrets import SecretCounts

    with pytest.raises(SidecarLeakError) as exc:
        build_sidecar(
            metadata=_metadata(),
            config=config,
            serialized_lines=[],
            counts=PipelineCounts(),
            subtable=subtable,
            secret_counts=SecretCounts(),
        )
    assert exc.value.category == "anthropic-key"


# ----- count fidelity ----------------------------------------------------


def test_stripped_lines_counts_match_dropped_lines(tmp_path: Path) -> None:
    """The sidecar's ``stripped_lines`` must equal the per-type drop
    tally ``run_pipeline`` reports. Three ``file-history-snapshot`` and
    one ``attachment`` line; both default-stripped types."""
    config = _config(tmp_path, _BASE_CONFIG)
    lines = [
        _line({"type": "user"}),
        _line({"type": "file-history-snapshot", "snapshot": {}}),
        _line({"type": "file-history-snapshot", "snapshot": {}}),
        _line({"type": "file-history-snapshot", "snapshot": {}}),
        _line({"type": "attachment", "blob": "x"}),
    ]
    out, counts, subtable, secret_counts = sanitize_session(lines, config)
    sidecar_yaml = build_sidecar(
        metadata=_metadata(),
        config=config,
        serialized_lines=out,
        counts=counts,
        subtable=subtable,
        secret_counts=secret_counts,
    )
    payload = yaml.safe_load(sidecar_yaml)
    assert payload["stripped_lines"] == {
        "file-history-snapshot": 3,
        "attachment": 1,
    }
    # lines_processed = 1 survivor + 4 stripped = 5.
    assert payload["lines_processed"] == 5


def test_lines_processed_matches_input_iterable_length_with_blanks(
    tmp_path: Path,
) -> None:
    """PRD §10 audit semantic (#43): ``lines_processed`` equals the
    number of items the input iterable produced -- survivors + stripped
    + blank/whitespace input lines. A fixture-validator that diffs
    against ``len(input_text.split('\\n'))`` sees parity. Without the
    ``blank_lines`` tally, a file with interior whitespace lines
    undercounts by the number of blanks."""
    config = _config(tmp_path, _BASE_CONFIG)
    raw_lines = [
        _line({"type": "user"}),                              # survivor
        "",                                                   # interior blank
        _line({"type": "user"}),                              # survivor
        _line({"type": "file-history-snapshot", "snapshot": {}}),  # stripped
        "   ",                                                # whitespace-only
        "",                                                   # trailing blank
    ]
    out, counts, subtable, secret_counts = sanitize_session(raw_lines, config)
    sidecar_yaml = build_sidecar(
        metadata=_metadata(),
        config=config,
        serialized_lines=out,
        counts=counts,
        subtable=subtable,
        secret_counts=secret_counts,
    )
    payload = yaml.safe_load(sidecar_yaml)
    # 2 survivors + 1 stripped + 3 blank = 6, which is ``len(raw_lines)``.
    assert payload["lines_processed"] == len(raw_lines)
    assert payload["lines_processed"] == 6


def test_substitution_counts_match_table(tmp_path: Path) -> None:
    """``rules_applied.paths.substitutions`` equals the sum of occurrences
    across paths-labeled entries; ``distinct`` equals the count. Pin by
    feeding three lines that hit the same path twice and a different
    one once -- expect ``substitutions: 3, distinct: 2``."""
    config = _config(
        tmp_path,
        """
version: 1
paths:
  - match: "/home/realuser"
    replace: "/home/user"
  - match: "/home/other"
    replace: "/home/user2"
""",
    )
    lines = [
        _line({"type": "user", "cwd": "/home/realuser/a"}),
        _line({"type": "user", "cwd": "/home/realuser/b"}),
        _line({"type": "user", "cwd": "/home/other/c"}),
    ]
    out, counts, subtable, secret_counts = sanitize_session(lines, config)
    sidecar_yaml = build_sidecar(
        metadata=_metadata(),
        config=config,
        serialized_lines=out,
        counts=counts,
        subtable=subtable,
        secret_counts=secret_counts,
    )
    payload = yaml.safe_load(sidecar_yaml)
    paths = payload["rules_applied"]["paths"]
    assert paths == {"substitutions": 3, "distinct": 2}


def test_secret_counts_surface_as_matches(tmp_path: Path) -> None:
    """Layer 3 contributes ``rules_applied.secrets.matches`` and ONLY
    that field per PRD section 10 (D-2 -- no kind-level original, no
    matched bytes). Pin the count for a fixture with two distinct
    Tier-1 secrets, one of each kind."""
    config = _config(tmp_path, _BASE_CONFIG)
    anth = "sk-ant-" + "A" * 25
    gpat = "ghp_" + "B" * 30
    lines = [
        _line({"type": "user", "toolUseResult": {"stdout": anth}}),
        _line({"type": "user", "toolUseResult": {"stdout": gpat}}),
    ]
    out, counts, subtable, secret_counts = sanitize_session(lines, config)
    sidecar_yaml = build_sidecar(
        metadata=_metadata(),
        config=config,
        serialized_lines=out,
        counts=counts,
        subtable=subtable,
        secret_counts=secret_counts,
    )
    payload = yaml.safe_load(sidecar_yaml)
    secrets = payload["rules_applied"]["secrets"]
    # Two distinct kinds, one match each.
    assert secrets == {"matches": 2}
    # Per-kind detail must NOT leak into the sidecar (D-2).
    assert "anthropic-key" not in sidecar_yaml
    assert "github-pat" not in sidecar_yaml


# ----- placeholder synthesis ---------------------------------------------


def test_placeholder_for_paths_is_indexed(tmp_path: Path) -> None:
    config = _config(
        tmp_path,
        """
version: 1
paths:
  - match: "/home/realuser"
    replace: "/home/user"
  - match: "/home/other"
    replace: "/home/user2"
""",
    )
    lines = [
        _line({"type": "user", "cwd": "/home/realuser/a"}),
        _line({"type": "user", "cwd": "/home/other/b"}),
    ]
    out, counts, subtable, secret_counts = sanitize_session(lines, config)
    sidecar_yaml = build_sidecar(
        metadata=_metadata(),
        config=config,
        serialized_lines=out,
        counts=counts,
        subtable=subtable,
        secret_counts=secret_counts,
    )
    payload = yaml.safe_load(sidecar_yaml)
    placeholders = [row["placeholder"] for row in payload["substitutions"]]
    assert "<path-1>" in placeholders
    assert "<path-2>" in placeholders


def test_placeholder_for_gitbranch_is_fixed(tmp_path: Path) -> None:
    config = _config(tmp_path, "version: 1\n")
    lines = [_line({"type": "user", "gitBranch": _REAL_BRANCH})]
    out, counts, subtable, secret_counts = sanitize_session(lines, config)
    sidecar_yaml = build_sidecar(
        metadata=_metadata(),
        config=config,
        serialized_lines=out,
        counts=counts,
        subtable=subtable,
        secret_counts=secret_counts,
    )
    payload = yaml.safe_load(sidecar_yaml)
    rows = payload["substitutions"]
    assert any(
        row["rule"] == "identifiers"
        and row["placeholder"] == "<git-branch>"
        and row["replacement"] == "feature/example"
        for row in rows
    )


def test_placeholder_for_uuid_is_fixed(tmp_path: Path) -> None:
    config = _config(
        tmp_path,
        """
version: 1
options:
  remap_uuids: true
""",
    )
    real_uuid = "d4ea0acf-3f7e-44e5-b07d-2f0cb19c9da1"
    lines = [_line({"type": "user", "sessionId": real_uuid})]
    out, counts, subtable, secret_counts = sanitize_session(lines, config)
    sidecar_yaml = build_sidecar(
        metadata=_metadata(),
        config=config,
        serialized_lines=out,
        counts=counts,
        subtable=subtable,
        secret_counts=secret_counts,
    )
    payload = yaml.safe_load(sidecar_yaml)
    rows = payload["substitutions"]
    assert any(
        row["rule"] == "identifiers" and row["placeholder"] == "<uuid>"
        for row in rows
    )


# ----- determinism: same input -> same sidecar bytes ---------------------


def test_sidecar_is_byte_identical_across_runs(tmp_path: Path) -> None:
    """Two calls to ``build_sidecar`` with identical inputs produce
    byte-identical YAML. This is the determinism property the
    fixture-validator and reviewer-diff workflow depend on."""
    config = _config(tmp_path, _BASE_CONFIG)
    lines = [
        _line({"type": "user", "cwd": f"{_REAL_USER_HOME}/x"}),
        _line(
            {
                "type": "user",
                "message": {
                    "content": [{"type": "text", "text": f"ping {_REAL_USER_EMAIL}"}]
                },
            }
        ),
    ]
    # Sanitize twice so each sidecar sees its own freshly-populated
    # subtable/counts -- pinning that even the dataclass-internal state
    # round-trips deterministically.
    out_a, counts_a, subtable_a, secrets_a = sanitize_session(list(lines), config)
    out_b, counts_b, subtable_b, secrets_b = sanitize_session(list(lines), config)
    sidecar_a = build_sidecar(
        metadata=_metadata(),
        config=config,
        serialized_lines=out_a,
        counts=counts_a,
        subtable=subtable_a,
        secret_counts=secrets_a,
    )
    sidecar_b = build_sidecar(
        metadata=_metadata(),
        config=config,
        serialized_lines=out_b,
        counts=counts_b,
        subtable=subtable_b,
        secret_counts=secrets_b,
    )
    assert sidecar_a == sidecar_b


def test_empty_run_emits_well_formed_sidecar(tmp_path: Path) -> None:
    """A file with no substitutions, no stripped lines, and no secret
    matches still produces a valid sidecar -- empty maps/lists for the
    zero-count fields. The fixture-validator's existence check should
    pass on a no-op scrub."""
    config = _config(tmp_path, "version: 1\n")
    lines = [_line({"type": "user", "harmless": "data"})]
    out, counts, subtable, secret_counts = sanitize_session(lines, config)
    sidecar_yaml = build_sidecar(
        metadata=_metadata(),
        config=config,
        serialized_lines=out,
        counts=counts,
        subtable=subtable,
        secret_counts=secret_counts,
    )
    payload = yaml.safe_load(sidecar_yaml)
    assert payload["stripped_lines"] == {}
    assert payload["substitutions"] == []
    assert payload["rules_applied"]["paths"] == {"substitutions": 0, "distinct": 0}
    assert payload["rules_applied"]["identifiers"] == {
        "substitutions": 0,
        "distinct": 0,
    }
    assert payload["rules_applied"]["secrets"] == {"matches": 0}
    assert payload["lines_processed"] == 1
    assert payload["residual_scan"] == "clean"
