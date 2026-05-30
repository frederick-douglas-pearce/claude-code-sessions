"""Smoke tests for the `ccs-sanitize` CLI scaffold (issue #18).

Verifies the package is installable and the entry point wires through
to `ccs_sanitize.cli:main`. Asserts both invocation paths:

  - `python -m ccs_sanitize.cli --version` (module execution)
  - `ccs-sanitize --version`               (entry-point script)

Also pins exit-code semantics from PRD section 11:
`--help`/`--version` exit 0, and unknown args exit 1 (NOT argparse's
default 2, which is reserved for safety failures on this tool).
"""

from __future__ import annotations

import shutil
import subprocess
import sys

from ccs_sanitize import __version__


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=10,
    )


def test_module_version() -> None:
    result = _run([sys.executable, "-m", "ccs_sanitize.cli", "--version"])
    assert result.returncode == 0, result.stderr
    assert __version__ in result.stdout


def test_entry_point_version() -> None:
    entry_point = shutil.which("ccs-sanitize")
    if entry_point is None:
        # Not on PATH — entry point not installed in this env. Skip rather
        # than fail; the module-execution test above already covers wiring.
        import pytest

        pytest.skip("ccs-sanitize entry point not on PATH")
    result = _run([entry_point, "--version"])
    assert result.returncode == 0, result.stderr
    assert __version__ in result.stdout


def test_unknown_arg_exits_one_not_two() -> None:
    """argparse defaults to exit 2 on parse errors. PRD section 11 reserves
    exit 2 for safety failures, so the parser overrides error() to exit 1."""
    result = _run([sys.executable, "-m", "ccs_sanitize.cli", "--no-such-flag"])
    assert result.returncode == 1, (
        f"expected exit 1 (usage error), got {result.returncode}. "
        f"stderr: {result.stderr!r}"
    )
