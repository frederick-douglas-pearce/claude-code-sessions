"""Cross-interpreter golden test for the determinism contract (issue #162).

The sanitizer's published promise is "same input + same config produces
byte-identical output", and external consumers gate on it. The determinism
tests in ``test_paths.py``, ``test_secrets.py``, ``test_sidecar.py``, and
``test_orchestrator.py`` all run the same input twice **on the same
interpreter**, which proves an interpreter agrees with itself and nothing
more. That is not the property being sold: consumers do not scrub and
validate on the same host, so someone scrubs on 3.11 and the
fixture-validator checks on 3.13.

This module closes that gap by asserting a *committed* artifact. The CI
matrix runs it on 3.11 / 3.12 / 3.13, so every interpreter must match the
same bytes on disk rather than merely matching itself. Serialization is
pinned in ``pipeline.serialize_line`` (``separators=(",", ":")``,
``ensure_ascii=False``, insertion order preserved) and in
``sidecar.build_sidecar`` (``yaml.safe_dump(sort_keys=False)``), so this is
a regression guard on a latent risk rather than a fix for a live bug.

The fixture is synthetic and documented in
``tests/golden/golden-session.jsonl.generator.md``, which also carries the
regeneration procedure. **Read it before regenerating anything**: a change
in the golden bytes is a version bump under the CHANGELOG policy, not a
chore, and "the test went red so I re-ran the generator" is precisely the
failure mode the doc exists to prevent.

The CLI is driven as a subprocess rather than via an in-process import so
the assertion covers the whole shipped path -- argument parsing, config
discovery, atomic write ordering, and the bytes that land on disk -- which
is what a consumer actually runs.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from ccs_sanitize import __version__

_GOLDEN_DIR = Path(__file__).resolve().parent / "golden"
_INPUT = _GOLDEN_DIR / "golden-session.jsonl"
_CONFIG = _GOLDEN_DIR / "golden-config.yaml"
_EXPECTED_OUTPUT = _GOLDEN_DIR / "golden-session.expected.jsonl"
_EXPECTED_SIDECAR = _GOLDEN_DIR / "golden-session.expected.jsonl.scrubbed"

# The two sidecar fields that are per-run by construction: the version moves
# on every release, the timestamp on every run. Both are asserted separately
# below rather than dropped -- normalizing without re-asserting would leave
# them untested.
_NORMALIZED = "<normalized>"
_VERSION_LINE = re.compile(r"^sanitizer_version: (.*)$", re.M)
_TIMESTAMP_LINE = re.compile(r"^scrubbed_at: (.*)$", re.M)
_ISO8601_Z = re.compile(r"^'?\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z'?$")


def _normalize_sidecar(text: str) -> str:
    """Blank out the two per-run sidecar fields so the rest can be diffed."""
    text = _VERSION_LINE.sub(f"sanitizer_version: {_NORMALIZED}", text)
    return _TIMESTAMP_LINE.sub(f"scrubbed_at: {_NORMALIZED}", text)


def _run_golden(tmp_path: Path, *, hash_seed: str | None = None) -> tuple[str, str]:
    """Scrub the golden input into ``tmp_path``; return (output, sidecar) text.

    ``--no-check`` is correct here: ``golden-config.yaml`` is committed on
    purpose because it holds no real PII, so the pre-run gitignore guard has
    nothing to protect. This is the documented test-suite use of the
    override, not a workaround for exit 3 on a live config (PRD section 12b).
    """
    tmp_path.mkdir(parents=True, exist_ok=True)
    out_path = tmp_path / "golden-out.jsonl"
    env = dict(os.environ)
    if hash_seed is not None:
        env["PYTHONHASHSEED"] = hash_seed
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ccs_sanitize.cli",
            str(_INPUT),
            "-o",
            str(out_path),
            "-c",
            str(_CONFIG),
            "--no-check",
        ],
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )
    assert result.returncode == 0, (
        f"ccs-sanitize exited {result.returncode} on the golden fixture. "
        f"stderr: {result.stderr!r}"
    )
    sidecar_path = out_path.with_name(out_path.name + ".scrubbed")
    return (
        out_path.read_text(encoding="utf-8"),
        sidecar_path.read_text(encoding="utf-8"),
    )


def test_golden_output_bytes_match(tmp_path: Path) -> None:
    """The scrubbed output is byte-identical to the committed artifact.

    This is the cross-interpreter assertion. If it fails on one matrix cell
    and passes on another, the sanitizer's output depends on the interpreter
    and the determinism contract is broken. If it fails on every cell, the
    sanitizer's output changed -- see the generator doc before regenerating.
    """
    produced, _ = _run_golden(tmp_path)
    expected = _EXPECTED_OUTPUT.read_text(encoding="utf-8")
    assert produced == expected, (
        "Scrubbed output diverged from tests/golden/"
        "golden-session.expected.jsonl. This is the determinism contract "
        "failing, not a stale fixture. Read tests/golden/"
        "golden-session.jsonl.generator.md before regenerating -- an "
        "intended output change is a version bump, not a `cp`."
    )


def test_golden_output_is_utf8_bytes(tmp_path: Path) -> None:
    """Byte-level, not str-level, equality.

    ``read_text`` decodes, so the test above would pass on a host whose
    default encoding differed while the bytes on disk did not match. The
    contract is about bytes, so assert bytes -- and specifically that the
    non-ASCII characters in the fixture survive unescaped, which is what
    pins ``ensure_ascii=False``.
    """
    out_path = tmp_path / "golden-out.jsonl"
    _run_golden(tmp_path)
    assert out_path.read_bytes() == _EXPECTED_OUTPUT.read_bytes()
    assert "café".encode("utf-8") in out_path.read_bytes(), (
        "non-ASCII text was escaped or transcoded; ensure_ascii=False is "
        "part of the serialization contract (PRD section 8)"
    )


def test_golden_sidecar_matches(tmp_path: Path) -> None:
    """The sidecar matches byte for byte once the two per-run fields are
    normalized. That covers ``input_sha256``, the strip-type counts, the
    per-layer substitution totals, and the placeholder numbering -- all of
    which are insertion-ordered and would drift if key ordering ever stopped
    being stable."""
    _, produced = _run_golden(tmp_path)
    expected = _EXPECTED_SIDECAR.read_text(encoding="utf-8")
    assert _normalize_sidecar(produced) == expected, (
        "Sidecar diverged from tests/golden/"
        "golden-session.expected.jsonl.scrubbed. See that fixture's "
        "generator doc; a legitimate change is a version bump."
    )


def test_golden_sidecar_normalized_fields_are_still_asserted(
    tmp_path: Path,
) -> None:
    """The two fields excluded from the byte comparison are checked here, so
    normalizing them does not amount to not testing them."""
    _, produced = _run_golden(tmp_path)
    version_match = _VERSION_LINE.search(produced)
    timestamp_match = _TIMESTAMP_LINE.search(produced)
    assert version_match is not None, "sidecar is missing sanitizer_version"
    assert timestamp_match is not None, "sidecar is missing scrubbed_at"
    assert version_match.group(1).strip() == __version__
    assert _ISO8601_Z.match(timestamp_match.group(1).strip()), (
        f"scrubbed_at is not ISO 8601 UTC ending in Z: "
        f"{timestamp_match.group(1)!r}"
    )


@pytest.mark.parametrize("hash_seed", ["0", "1", "4242"])
def test_golden_output_is_hash_seed_independent(
    tmp_path: Path, hash_seed: str
) -> None:
    """Output must not depend on ``PYTHONHASHSEED``.

    Python randomizes str hashing per process by default, so a latent
    dependence on set or dict iteration order would surface as a flaky
    failure on one CI run in N rather than as a clean red build. Pinning
    three seeds turns that into a deterministic failure. Relevant because
    the config carries rules in a list but the pipeline builds lookup
    structures from them, and ``--strip-types`` is a ``frozenset``.
    """
    produced, _ = _run_golden(tmp_path / hash_seed, hash_seed=hash_seed)
    assert produced == _EXPECTED_OUTPUT.read_text(encoding="utf-8"), (
        f"golden output changed under PYTHONHASHSEED={hash_seed}; something "
        f"in the scrub path iterates a set or dict whose order is not pinned"
    )
