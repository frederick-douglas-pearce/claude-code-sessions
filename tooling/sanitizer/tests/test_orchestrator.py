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
from ccs_sanitize.pipeline import PipelineError
from ccs_sanitize.residual import ResidualSecretError
from ccs_sanitize.rules.identifiers import _remap_uuid
from ccs_sanitize.rules.secrets import COMPILED_SECRET_PATTERNS

from ._helpers import (
    serialize_test_line as _line,
    table_snapshot,
    write_config as _config,
)


# ----- helpers -----------------------------------------------------------


# Synthetic identifiers only -- per CLAUDE.md "Security posture" the test
# suite must not commit real personal data. ``user-old@example.test`` is
# RFC-2606 reserved (``.test`` TLD) so it can never collide with a real
# address, and it documents that the identifier rule maps an "old" user
# email to the placeholder.
_REAL_USER_HOME = "/home/realuser"
_REAL_USER_EMAIL = "user-old@example.test"
_BASE_CONFIG = f"""
version: 1
paths:
  - match: "{_REAL_USER_HOME}"
    replace: "/home/user"
identifiers:
  - match: "{_REAL_USER_EMAIL}"
    replace: "user@example.com"
"""


# ----- happy path: three-layer composition -------------------------------


def test_happy_path_paths_identifiers_secrets_all_scrub(tmp_path: Path) -> None:
    config = _config(tmp_path, _BASE_CONFIG)
    secret = "sk-ant-" + "A" * 25
    lines = [
        _line(
            {
                "type": "user",
                "cwd": "/home/realuser/projects/foo",
                "message": {"content": [{"type": "text", "text": "ping user-old@example.test"}]},
                "toolUseResult": {"stdout": f"token={secret}"},
            }
        ),
    ]
    out, counts, subtable, secret_counts = sanitize_session(lines, config)
    assert len(out) == 1
    blob = out[0]
    # All three originals are gone.
    assert "/home/realuser" not in blob
    assert "user-old@example.test" not in blob
    assert secret not in blob
    # The placeholders are present (replacement values from config / built-ins).
    assert "/home/user" in blob
    assert "user@example.com" in blob
    assert "<REDACTED:anthropic-key>" in blob
    # Secret counts populated; subtable contains the two non-secret rules.
    assert dict(secret_counts.as_mapping()) == {"anthropic-key": 1}
    originals = {entry.original for entry in subtable}
    assert "/home/realuser" in originals
    assert "user-old@example.test" in originals
    # Pipeline counts: no lines stripped (this fixture has no
    # file-history-snapshot/attachment).
    assert dict(counts.stripped_lines) == {}


def test_strip_types_passthrough_drops_lines(tmp_path: Path) -> None:
    """``strip_types`` must reach the underlying ``run_pipeline``. Passing a
    NON-default set ``{"junk"}`` and asserting that (a) ``junk`` lines are
    dropped, AND (b) ``file-history-snapshot``/``attachment`` lines (which
    would be dropped by ``DEFAULT_STRIP_TYPES``) now pass through, proves
    the kwarg is actually plumbed -- not just that the defaults work."""
    config = _config(tmp_path, _BASE_CONFIG)
    lines = [
        _line({"type": "user", "cwd": "/home/realuser"}),
        _line({"type": "junk", "payload": "DROPPED"}),
        _line({"type": "file-history-snapshot", "snapshot": {"trackedFileBackups": {"/a": "x"}}}),
        _line({"type": "attachment", "blob": "AAA"}),
    ]
    out, counts, _, _ = sanitize_session(
        lines, config, strip_types=frozenset({"junk"})
    )
    # junk dropped; the two normally-default-stripped types now survive.
    assert len(out) == 3
    assert dict(counts.stripped_lines) == {"junk": 1}
    assert any("file-history-snapshot" in line for line in out)
    assert any("attachment" in line for line in out)


# ----- determinism (PRD section 14, I-1) ---------------------------------


def test_determinism_same_input_byte_identical_output(tmp_path: Path) -> None:
    """Heterogeneous records (distinct content per line) -- a [x] * 5 fixture
    only proves that the same input yields the same output for a single
    shape. PRD section 14 I-1 requires byte-stability across distinct
    records too, so mix three shapes that exercise paths, identifiers, and
    secrets independently."""
    config = _config(tmp_path, _BASE_CONFIG)
    lines = [
        _line({"type": "user", "cwd": "/home/realuser/projects/foo"}),
        _line(
            {
                "type": "user",
                "message": {
                    "content": [
                        {"type": "text", "text": "ping user-old@example.test"}
                    ]
                },
            }
        ),
        _line({"type": "user", "toolUseResult": {"stdout": "sk-ant-" + "A" * 25}}),
        _line({"type": "user", "cwd": "/home/realuser", "gitBranch": "main"}),
        _line({"type": "user", "message": {"content": [{"type": "text", "text": "no-op"}]}}),
    ]
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
                "cwd": "/home/realuser/projects/foo",
                "message": {"content": [{"type": "text", "text": "ping user-old@example.test"}]},
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


@pytest.mark.parametrize(
    "kind",
    [kind for _, kind in COMPILED_SECRET_PATTERNS],
)
def test_redacted_placeholder_round_trip_clean_for_every_builtin_kind(
    tmp_path: Path, kind: str
) -> None:
    """Per-kind idempotency: each ``<REDACTED:kind>`` placeholder for every
    built-in pattern must survive a sanitize_session pass without firing
    the residual scan and without producing new substitutions. Pins the
    invariant that no built-in pattern accidentally matches its own
    placeholder (a future tightening of e.g. the bearer-token regex could
    silently break this without parametrization)."""
    config = _config(tmp_path, _BASE_CONFIG)
    placeholder = f"<REDACTED:{kind}>"
    lines = [
        _line({"type": "user", "toolUseResult": {"stdout": placeholder}})
    ]
    out, _, subtable, secrets = sanitize_session(lines, config)
    assert placeholder in out[0]
    assert list(subtable) == []
    assert dict(secrets.as_mapping()) == {}


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
    good = _line({"type": "user", "cwd": "/home/realuser"})
    bad = "{not valid json"
    lines = [good, good, good, good, bad, good, good]
    with pytest.raises(PipelineError) as exc:
        sanitize_session(lines, config)
    # Line number is 1-indexed and reports the *input* position (so blank
    # lines wouldn't skew it -- there are none here).
    assert "line 5" in str(exc.value)


def test_no_partial_scrub_on_missing_type_field(tmp_path: Path) -> None:
    """Sibling shape: a record missing the required ``type`` field also
    aborts via PipelineError. Pinning the line-number marker symmetrically
    with the malformed-JSON sibling guards against a regression that
    drops or zeroes the line marker on the missing-type branch only."""
    config = _config(tmp_path, _BASE_CONFIG)
    good = _line({"type": "user", "cwd": "/home/realuser"})
    bad = _line({"no_type": "missing"})  # well-formed JSON, wrong shape
    with pytest.raises(PipelineError) as exc:
        sanitize_session([good, bad, good], config)
    # bad record is at input index 1 (1-indexed line 2).
    assert "line 2" in str(exc.value)


# ----- remap_uuids coupling through the orchestrator (issue #39) ---------
#
# ``sanitize_session`` threads ``config.options.remap_uuids`` into two
# call sites that must agree -- ``make_skip_predicate`` (which decides
# whether UUID fields are visited at all) and ``build_identifier_transform``
# (which decides whether visited UUID leaves are remapped). If they ever
# disagree, the identifier layer silently no-ops on UUID fields and the
# residual scan does NOT fire (UUIDs aren't credential-shaped), so real
# ``uuid`` / ``parentUuid`` / ``sessionId`` / ``agentId`` values would
# ship to disk unchanged. Lower-level tests (test_identifiers.py,
# test_pipeline.py) cover each call site in isolation; these orchestrator-
# level tests pin the coupling end-to-end so a refactor that splits the
# orchestrator and accidentally passes False to one of the two sites
# fails loudly here.


_REMAP_UUID_SEED = "ccs-sanitize/v1"


def _remap(original: str) -> str:
    """Compute the orchestrator's expected remap for ``original`` under
    the default ``uuid_seed``. Comparing against this explicit value
    (rather than just asserting "the input is gone") is what catches the
    silent-no-op regression: a transform that passes the original through
    unchanged would defeat the absence check but not this equality check."""
    return _remap_uuid(_REMAP_UUID_SEED.encode("utf-8"), original)


def test_remap_uuids_true_remaps_uuid_graph_fields(tmp_path: Path) -> None:
    """``options.remap_uuids: true`` must reach BOTH the skip predicate
    (so UUID fields are visited) AND the identifier transform (so the
    visited leaves are actually remapped). This is the orchestrator's
    coupling contract per PRD §8 and the issue #39 failure scenario."""
    config = _config(
        tmp_path,
        "version: 1\noptions:\n  remap_uuids: true\n",
    )
    session_id = "00000000-0000-0000-0000-000000000001"
    line1_uuid = "11111111-1111-1111-1111-111111111001"
    line2_uuid = "11111111-1111-1111-1111-111111111002"
    agent_id = "22222222-2222-2222-2222-222222222001"
    lines = [
        _line(
            {
                "type": "user",
                "sessionId": session_id,
                "uuid": line1_uuid,
                "parentUuid": None,
            }
        ),
        _line(
            {
                "type": "assistant",
                "sessionId": session_id,
                "uuid": line2_uuid,
                "parentUuid": line1_uuid,
                "agentId": agent_id,
            }
        ),
    ]
    out, _, subtable, _ = sanitize_session(lines, config)
    serialized = "\n".join(out)

    # No raw UUID survives.
    for original in (session_id, line1_uuid, line2_uuid, agent_id):
        assert original not in serialized

    # Each output UUID equals the deterministic ``_remap_uuid`` value.
    # Pinning the exact expected bytes is what distinguishes "the
    # transform fired" from "the transform silently no-op'd and the
    # field was scrubbed elsewhere".
    assert f'"sessionId":"{_remap(session_id)}"' in out[0]
    assert f'"uuid":"{_remap(line1_uuid)}"' in out[0]
    assert f'"sessionId":"{_remap(session_id)}"' in out[1]
    assert f'"uuid":"{_remap(line2_uuid)}"' in out[1]
    assert f'"parentUuid":"{_remap(line1_uuid)}"' in out[1]
    assert f'"agentId":"{_remap(agent_id)}"' in out[1]

    # The subtable records every UUID remap under the ``identifiers:uuid``
    # label so the sidecar (#25) can surface them in the right section.
    by_original = {entry.original: entry for entry in subtable}
    for original in (session_id, line1_uuid, line2_uuid, agent_id):
        assert original in by_original, f"missing subtable entry for {original}"
        entry = by_original[original]
        assert entry.replacement == _remap(original)
        assert entry.label == "identifiers:uuid"
    # ``sessionId`` appears on both lines -- one entry, two occurrences --
    # which proves cross-line consistency went through the table.
    assert by_original[session_id].occurrences == 2


def test_remap_uuids_false_default_leaves_uuid_fields_unchanged(
    tmp_path: Path,
) -> None:
    """Complementary negative case: the PRD default is
    ``remap_uuids: false``. UUID-graph fields are skip-listed and never
    visited, so they must appear unchanged in the output and never
    surface in the subtable. Pins that the orchestrator does not
    over-remap when the config does not opt in."""
    config = _config(tmp_path, "version: 1\n")
    session_id = "00000000-0000-0000-0000-000000000001"
    line_uuid = "11111111-1111-1111-1111-111111111001"
    lines = [
        _line(
            {
                "type": "user",
                "sessionId": session_id,
                "uuid": line_uuid,
                "parentUuid": None,
            }
        )
    ]
    out, _, subtable, _ = sanitize_session(lines, config)
    blob = out[0]
    # Inputs survive verbatim.
    assert f'"sessionId":"{session_id}"' in blob
    assert f'"uuid":"{line_uuid}"' in blob
    # And nothing UUID-labelled landed in the subtable.
    assert not any(entry.label == "identifiers:uuid" for entry in subtable)
