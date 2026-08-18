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

**Two cells, one input.** The same synthetic session is scrubbed under two
pinned configs:

  - ``golden-config.yaml`` -- the shipped default, ``remap_uuids: false``.
  - ``golden-config-remap.yaml`` -- ``remap_uuids: true`` with a pinned
    ``uuid_seed``. This is the only *generative* path in the sanitizer:
    every UUID-graph field is rewritten via SHA-256(seed + original) and
    each distinct original earns a sidecar row in encounter order. Value
    stability comes from the hash; row order comes from insertion order in
    the substitution table, and the second is what a dict-iteration
    dependency would break. Covering only the default cell would leave that
    path outside the byte assertion (architect review, 2026-08-18).

The fixtures are synthetic and documented in
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

#: ``cell -> (config, expected output, expected sidecar)``. Parametrizing on
#: the key keeps failure output naming the cell ("default" vs "remap")
#: rather than a path triple.
_CELLS: dict[str, tuple[Path, Path, Path]] = {
    "default": (
        _GOLDEN_DIR / "golden-config.yaml",
        _GOLDEN_DIR / "golden-session.expected.jsonl",
        _GOLDEN_DIR / "golden-session.expected.jsonl.scrubbed",
    ),
    "remap": (
        _GOLDEN_DIR / "golden-config-remap.yaml",
        _GOLDEN_DIR / "golden-session.expected.remap.jsonl",
        _GOLDEN_DIR / "golden-session.expected.remap.jsonl.scrubbed",
    ),
}
_CELL_IDS = sorted(_CELLS)

# The two sidecar fields that are per-run by construction: the version moves
# on every release, the timestamp on every run. Both are asserted separately
# below rather than dropped -- normalizing without re-asserting would leave
# them untested.
_NORMALIZED = "<normalized>"
_VERSION_LINE = re.compile(r"^sanitizer_version: (.*)$", re.M)
_TIMESTAMP_LINE = re.compile(r"^scrubbed_at: (.*)$", re.M)
_ISO8601_Z = re.compile(r"^'?\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z'?$")

_REGENERATE_HINT = (
    "This is the determinism contract failing, not a stale fixture. Read "
    "tests/golden/golden-session.jsonl.generator.md before regenerating -- "
    "an intended output change is a version bump, not a `cp`."
)


def _normalize_sidecar(text: str) -> str:
    """Blank out the two per-run sidecar fields so the rest can be diffed."""
    text = _VERSION_LINE.sub(f"sanitizer_version: {_NORMALIZED}", text)
    return _TIMESTAMP_LINE.sub(f"scrubbed_at: {_NORMALIZED}", text)


def _run_golden(
    tmp_path: Path, config: Path, *, hash_seed: str | None = None
) -> tuple[Path, Path]:
    """Scrub the golden input into ``tmp_path``; return (output, sidecar) paths.

    ``--no-check`` is correct here: the golden configs are committed on
    purpose because they hold no real PII, so the pre-run gitignore guard has
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
            str(config),
            "--no-check",
        ],
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )
    assert result.returncode == 0, (
        f"ccs-sanitize exited {result.returncode} on the golden fixture "
        f"with {config.name}. stderr: {result.stderr!r}"
    )
    return out_path, out_path.with_name(out_path.name + ".scrubbed")


@pytest.mark.parametrize("cell", _CELL_IDS)
def test_golden_output_bytes_match(tmp_path: Path, cell: str) -> None:
    """The scrubbed output is byte-identical to the committed artifact.

    This is the cross-interpreter assertion. If it fails on one matrix cell
    and passes on another, the sanitizer's output depends on the interpreter
    and the determinism contract is broken. If it fails on every cell, the
    sanitizer's output changed.

    Compared as bytes, not as decoded text: the contract is about bytes, and
    a str comparison would pass on a host whose default encoding differed
    while the files on disk did not match.
    """
    config, expected_output, _ = _CELLS[cell]
    out_path, _ = _run_golden(tmp_path, config)
    assert out_path.read_bytes() == expected_output.read_bytes(), (
        f"Scrubbed output for the {cell!r} cell diverged from "
        f"tests/golden/{expected_output.name}. {_REGENERATE_HINT}"
    )


@pytest.mark.parametrize("cell", _CELL_IDS)
def test_golden_output_keeps_non_ascii_unescaped(tmp_path: Path, cell: str) -> None:
    """``ensure_ascii=False`` is part of the serialization contract.

    The byte comparison above would already catch escaping to ``\\uXXXX``,
    but it would report it as an opaque byte diff. This names the property
    so the diagnostic points at the cause.
    """
    config, _, _ = _CELLS[cell]
    out_path, _ = _run_golden(tmp_path, config)
    produced = out_path.read_bytes()
    for token in ("café", "résumé", "✅"):
        assert token.encode("utf-8") in produced, (
            f"{token!r} was escaped or transcoded in the {cell!r} cell; "
            f"ensure_ascii=False is part of the serialization contract "
            f"(PRD section 8)"
        )


@pytest.mark.parametrize("cell", _CELL_IDS)
def test_golden_sidecar_matches(tmp_path: Path, cell: str) -> None:
    """The sidecar matches byte for byte once the two per-run fields are
    normalized. That covers ``input_sha256``, the strip-type counts, the
    per-layer substitution totals, and the substitution rows -- all of which
    are insertion-ordered and would drift if key ordering ever stopped being
    stable. In the ``remap`` cell the rows also carry the SHA-256-derived
    UUID replacements, so the hash output itself is pinned."""
    config, _, expected_sidecar = _CELLS[cell]
    _, sidecar_path = _run_golden(tmp_path, config)
    produced = _normalize_sidecar(sidecar_path.read_text(encoding="utf-8"))
    assert produced == expected_sidecar.read_text(encoding="utf-8"), (
        f"Sidecar for the {cell!r} cell diverged from "
        f"tests/golden/{expected_sidecar.name}. {_REGENERATE_HINT}"
    )


def test_golden_sidecar_normalized_fields_are_still_asserted(
    tmp_path: Path,
) -> None:
    """The two fields excluded from the byte comparison are checked here, so
    normalizing them does not amount to not testing them."""
    config, _, _ = _CELLS["default"]
    _, sidecar_path = _run_golden(tmp_path, config)
    produced = sidecar_path.read_text(encoding="utf-8")
    version_match = _VERSION_LINE.search(produced)
    timestamp_match = _TIMESTAMP_LINE.search(produced)
    assert version_match is not None, "sidecar is missing sanitizer_version"
    assert timestamp_match is not None, "sidecar is missing scrubbed_at"
    assert version_match.group(1).strip() == __version__
    assert _ISO8601_Z.match(timestamp_match.group(1).strip()), (
        f"scrubbed_at is not ISO 8601 UTC ending in Z: "
        f"{timestamp_match.group(1)!r}"
    )


def test_golden_cells_differ(tmp_path: Path) -> None:
    """Guard against the two cells silently collapsing into one.

    If a future edit pointed both cells at the same config, or turned the
    remap option off, every other test here would still pass while the
    generative path quietly left coverage. The UUID-remap cell must actually
    rewrite the UUID graph.
    """
    default_output = _CELLS["default"][1].read_bytes()
    remap_output = _CELLS["remap"][1].read_bytes()
    assert default_output != remap_output, (
        "the default and remap golden outputs are identical; the remap cell "
        "is not exercising remap_uuids"
    )
    assert b"11111111-1111-1111-1111-111111111001" in default_output, (
        "the default cell should preserve the input UUIDs (remap_uuids is "
        "off, which is what keeps committed fixtures graph-readable)"
    )
    assert b"11111111-1111-1111-1111-111111111001" not in remap_output, (
        "the remap cell still carries an input UUID; remap_uuids did not "
        "take effect (it also requires the pipeline skip-predicate to be "
        "built with remap_uuids=True -- see rules/identifiers.py)"
    )


@pytest.mark.parametrize("cell", _CELL_IDS)
@pytest.mark.parametrize("hash_seed", ["0", "1", "4242"])
def test_golden_output_is_hash_seed_independent(
    tmp_path: Path, cell: str, hash_seed: str
) -> None:
    """Output must not depend on ``PYTHONHASHSEED``.

    Python randomizes str hashing per process by default, so a latent
    dependence on set or dict iteration order would surface as a flaky
    failure on one CI run in N rather than as a clean red build. Pinning
    three seeds turns that into a deterministic failure. Most relevant to the
    ``remap`` cell, where each distinct UUID is hashed and recorded in
    encounter order, but it applies to the whole scrub path: the config
    carries rules in a list while the pipeline builds lookup structures from
    them, and ``--strip-types`` is a ``frozenset``.
    """
    config, expected_output, _ = _CELLS[cell]
    out_path, _ = _run_golden(tmp_path / hash_seed, config, hash_seed=hash_seed)
    assert out_path.read_bytes() == expected_output.read_bytes(), (
        f"golden output for the {cell!r} cell changed under "
        f"PYTHONHASHSEED={hash_seed}; something in the scrub path iterates "
        f"a set or dict whose order is not pinned"
    )
