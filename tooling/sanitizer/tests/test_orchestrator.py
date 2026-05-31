"""Tests for the session-level orchestrator (issue #24).

Covers PRD section 5 (residual gate runs after every successful pass),
section 6 (three-layer composition: paths -> identifiers -> secrets),
section 11 (fail-closed: any failure aborts, no partial result), and
section 14 (determinism, idempotency, residual fail-closed, no-partial-
scrub).

The realistic "secret survives" path plants a Tier-1 secret inside a
``thinking.signature`` field. The pipeline's skip predicate skips
``("content", "signature")`` so the secret transform never touches it,
but the residual scan over the serialized output catches it -- exactly
the defense-in-depth interaction PRD section 5 describes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ccs_sanitize.orchestrator import sanitize_session
from ccs_sanitize.pipeline import PipelineError, serialize_line
from ccs_sanitize.residual import ResidualSecretError

from ._helpers import table_snapshot, write_config as _config


# ----- helpers -----------------------------------------------------------


_BASE_CONFIG = """
version: 1
paths:
  - match: "/home/fdpearce"
    replace: "/home/user"
identifiers:
  - match: "fpearce@gmail.com"
    replace: "user@example.com"
"""


def _line(obj: dict) -> str:
    return serialize_line(obj)


# ----- happy path: three-layer composition -------------------------------


def test_happy_path_paths_identifiers_secrets_all_scrub(tmp_path: Path) -> None:
    config = _config(tmp_path, _BASE_CONFIG)
    secret = "sk-ant-" + "A" * 25
    lines = [
        _line(
            {
                "type": "user",
                "cwd": "/home/fdpearce/projects/foo",
                "message": {"content": [{"type": "text", "text": "ping fpearce@gmail.com"}]},
                "toolUseResult": {"stdout": f"token={secret}"},
            }
        ),
    ]
    out, counts, subtable, secret_counts = sanitize_session(lines, config)
    assert len(out) == 1
    blob = out[0]
    # All three originals are gone.
    assert "/home/fdpearce" not in blob
    assert "fpearce@gmail.com" not in blob
    assert secret not in blob
    # The placeholders are present (replacement values from config / built-ins).
    assert "/home/user" in blob
    assert "user@example.com" in blob
    assert "<REDACTED:anthropic-key>" in blob
    # Secret counts populated; subtable contains the two non-secret rules.
    assert dict(secret_counts.as_mapping()) == {"anthropic-key": 1}
    originals = {entry.original for entry in subtable}
    assert "/home/fdpearce" in originals
    assert "fpearce@gmail.com" in originals
    # Pipeline counts: no lines stripped (this fixture has no
    # file-history-snapshot/attachment).
    assert dict(counts.stripped_lines) == {}


def test_strip_types_passthrough_drops_lines(tmp_path: Path) -> None:
    """``strip_types`` should reach the underlying ``run_pipeline``
    untouched; verifies the orchestrator does not swallow the kwarg."""
    config = _config(tmp_path, _BASE_CONFIG)
    lines = [
        _line({"type": "user", "cwd": "/home/fdpearce"}),
        _line({"type": "file-history-snapshot", "snapshot": {"trackedFileBackups": {"/a": "x"}}}),
        _line({"type": "attachment", "blob": "AAA"}),
    ]
    out, counts, _, _ = sanitize_session(lines, config)
    assert len(out) == 1
    assert dict(counts.stripped_lines) == {
        "file-history-snapshot": 1,
        "attachment": 1,
    }


# ----- determinism (PRD section 14, I-1) ---------------------------------


def test_determinism_same_input_byte_identical_output(tmp_path: Path) -> None:
    config = _config(tmp_path, _BASE_CONFIG)
    lines = [
        _line(
            {
                "type": "user",
                "cwd": "/home/fdpearce/projects/foo",
                "message": {
                    "content": [{"type": "text", "text": "ping fpearce@gmail.com"}]
                },
                "toolUseResult": {"stdout": "token=" + "sk-ant-" + "A" * 25},
            }
        )
    ] * 5  # repeat to exercise within-file consistency
    out_a, counts_a, subtable_a, secrets_a = sanitize_session(list(lines), config)
    out_b, counts_b, subtable_b, secrets_b = sanitize_session(list(lines), config)
    assert out_a == out_b
    assert dict(counts_a.stripped_lines) == dict(counts_b.stripped_lines)
    assert table_snapshot(subtable_a) == table_snapshot(subtable_b)
    assert dict(secrets_a.as_mapping()) == dict(secrets_b.as_mapping())


# ----- idempotency (PRD section 14) --------------------------------------


def test_idempotency_second_pass_no_substitutions(tmp_path: Path) -> None:
    config = _config(tmp_path, _BASE_CONFIG)
    lines = [
        _line(
            {
                "type": "user",
                "cwd": "/home/fdpearce/projects/foo",
                "message": {"content": [{"type": "text", "text": "ping fpearce@gmail.com"}]},
                "toolUseResult": {"stdout": "token=" + "sk-ant-" + "A" * 25},
            }
        )
    ]
    out1, _, _, _ = sanitize_session(lines, config)
    out2, counts2, subtable2, secrets2 = sanitize_session(out1, config)
    # Second pass produces the same bytes (already clean).
    assert out1 == out2
    # No new substitutions: the first pass already redacted/replaced every
    # original. (The replacements -- ``/home/user``, ``user@example.com``,
    # ``<REDACTED:anthropic-key>`` -- by design don't match any rule.)
    assert list(subtable2) == []
    assert dict(secrets2.as_mapping()) == {}
    assert dict(counts2.stripped_lines) == {}


# ----- fail-closed: residual gate catches a survivor ---------------------


def test_residual_scan_fires_when_secret_planted_in_skiplisted_field(
    tmp_path: Path,
) -> None:
    """Realistic survival path: ``thinking.signature`` is on the skip-list
    (``message.content[].signature`` per PRD section 6b B), so the secret
    transform never touches it. The residual scan over the serialized
    output catches it. This is the defense-in-depth interaction PRD
    section 5 documents -- the residual scan is the backstop for any
    transform-stage miss, including skip-list interactions."""
    config = _config(tmp_path, _BASE_CONFIG)
    secret = "sk-ant-" + "A" * 25
    lines = [
        _line(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "thinking", "signature": secret}
                    ]
                },
            }
        )
    ]
    with pytest.raises(ResidualSecretError) as exc:
        sanitize_session(lines, config)
    assert exc.value.kind == "anthropic-key"


def test_residual_scan_fires_when_transform_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pure unit test of the gate: monkeypatch ``build_secret_transform``
    to identity so a Tier-1 secret in a normally-scrubbed field survives.
    The residual scan must still fire. Pairs with the skip-list test
    above to cover both 'transform bug' and 'skip-list interaction'
    survival paths."""
    def identity_transform_factory(extras, counts):  # noqa: ARG001
        def transform(leaf, path):  # noqa: ARG001
            return leaf
        return transform

    # The orchestrator imports build_secret_transform at module load, so
    # patch the orchestrator-module-level name (where the bound reference
    # actually lives) -- patching rules.secrets is a no-op for the
    # already-bound import.
    import ccs_sanitize.orchestrator as orch
    monkeypatch.setattr(orch, "build_secret_transform", identity_transform_factory)

    config = _config(tmp_path, _BASE_CONFIG)
    secret = "sk-ant-" + "A" * 25
    lines = [
        _line({"type": "user", "toolUseResult": {"stdout": f"token={secret}"}})
    ]
    with pytest.raises(ResidualSecretError) as exc:
        sanitize_session(lines, config)
    assert exc.value.kind == "anthropic-key"


# ----- no-partial-scrub: PipelineError aborts before any return ----------


def test_no_partial_scrub_on_midfile_malformed_json(tmp_path: Path) -> None:
    """A malformed line halfway through the file must abort the run
    cleanly: ``PipelineError`` propagates and the four-tuple is never
    returned. ``run_pipeline`` accumulates output eagerly into a list
    before any return, so 'partial output leaking out' is structurally
    impossible -- this test pins that contract end-to-end through the
    orchestrator."""
    config = _config(tmp_path, _BASE_CONFIG)
    good = _line({"type": "user", "cwd": "/home/fdpearce"})
    bad = "{not valid json"
    lines = [good, good, good, good, bad, good, good]
    with pytest.raises(PipelineError) as exc:
        sanitize_session(lines, config)
    # Line number is 1-indexed and reports the *input* position (so blank
    # lines wouldn't skew it -- there are none here).
    assert "line 5" in str(exc.value)


def test_no_partial_scrub_on_missing_type_field(tmp_path: Path) -> None:
    """Sibling shape: a record missing the required ``type`` field also
    aborts via PipelineError, not via a swallowed exception or partial
    output."""
    config = _config(tmp_path, _BASE_CONFIG)
    good = _line({"type": "user", "cwd": "/home/fdpearce"})
    bad = serialize_line({"no_type": "missing"})  # well-formed JSON, wrong shape
    with pytest.raises(PipelineError):
        sanitize_session([good, bad, good], config)
