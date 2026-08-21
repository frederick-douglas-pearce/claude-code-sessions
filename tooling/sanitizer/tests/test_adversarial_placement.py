"""Adversarial placement matrix: does scrubbing depend on WHERE a value sits?

The rest of this suite covers what a sensitive value looks like -- every
Tier-1/Tier-2 pattern, every rule layer -- with the value in a
straightforward position. This module varies the other axis. It plants one
value at each of ~14 structural positions in a session line and asserts the
outcome is the same everywhere.

Real sessions bury content in nested tool inputs, tool_result content
arrays, thinking blocks, top-level ``toolUseResult`` siblings, and
JSON-encoded-inside-a-JSON-string. A traversal that handles the flat case
and misses one of those is the failure mode this module exists to catch.
It is the parametrized form of the structural-traversal test PRD section 14
calls C-1.

Two verdict classes, which matter very differently (see #190):

  REDACTED     The value is gone from the output. What every cell should do.
  FAIL-CLOSED  The run aborted and wrote nothing. Safe but degraded: for a
               secret this means the transform missed it and the residual
               scan caught it, which is the PRD section 5 contract working
               as designed rather than a silently bad file.
  LEAKED       Output written, exit 0, value still present. The only
               genuinely unacceptable outcome, and the one that produces a
               sidecar reading ``residual_scan: clean`` over a leaky file.

Why this drives the console script instead of importing the orchestrator:
PRD D-5a declares the module surface private and the CLI + sidecar the
supported contract, so testing through ``ccs-sanitize`` tests the thing
that is actually promised. It also means one file covers two targets. Run
from a checkout it exercises the source tree; run from the unpacked sdist
with the wheel's entry point on PATH (or via ``CCS_SANITIZE_BIN``) it
exercises the published artifact. This matrix found #190 against the wheel
installed from PyPI, not against a checkout.

No credential-shaped literal appears in this file -- every payload is built
by concatenation, matching ``test_residual.py``. Matched values are never
printed, per the D-2 invariant.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys

import pytest

pytestmark = pytest.mark.adversarial

# --------------------------------------------------------------- payloads
# Built piecewise so no key-shaped literal exists in this source file and
# the file cannot match its own detectors.
SECRET = "sk-" + "ant-" + ("Q7x" * 9)
HOME = "/home/" + "testsubject"
EMAIL = "test" + ".person@" + "example.net"
NAME = "Testy " + "McTestface"

# The secret is caught by a built-in pattern and needs no config. The three
# PII payloads are config-driven, which is exactly the asymmetry #190 is
# about: nothing re-scans the output for these after the fact.
PAYLOADS = {
    "secret": SECRET,
    "pii-home": HOME,
    "pii-email": EMAIL,
    "pii-name": NAME,
}

CONFIG = f"""version: 1
paths:
  - match: "{HOME}"
    replace: "/home/user"
identifiers:
  - match: "{EMAIL}"
    replace: "user@example.com"
  - match: "{NAME}"
    replace: "Example Author"
"""

BASE = {
    "sessionId": "00000000-0000-0000-0000-0000000000aa",
    "uuid": "11111111-1111-1111-1111-1111111111aa",
    "parentUuid": None,
    "isSidechain": False,
    "cwd": "/home/user/proj",
    "version": "2.1.150",
    "timestamp": "2026-08-19T00:00:00.000Z",
}

# Cells that are known-broken today. Keyed by (cell, payload); the value is
# the tracking issue. Secrets in a dict key fail closed, which is safe, so
# only the PII rows are xfailed.
KNOWN_LEAKS = {
    ("13-dict-key-not-value", "pii-home"): 190,
    ("13-dict-key-not-value", "pii-email"): 190,
    ("13-dict-key-not-value", "pii-name"): 190,
}


def placements(payload: str) -> dict[str, dict]:
    """Return ``{cell_id: session_line}`` with ``payload`` planted in each spot."""

    def rec(**kw: object) -> dict:
        d = dict(BASE)
        d.update(kw)
        return d

    return {
        # Controls: shapes the rest of the suite already reaches.
        "01-user-content-string": rec(
            type="user",
            message={"role": "user", "content": f"see {payload} here"},
        ),
        "02-assistant-text-block": rec(
            type="assistant",
            message={
                "role": "assistant",
                "content": [{"type": "text", "text": f"got {payload}"}],
            },
        ),
        # The placement gap starts here.
        "03-tool-use-input-flat": rec(
            type="assistant",
            message={
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_a",
                        "name": "Bash",
                        "input": {"command": f"export TOKEN={payload}"},
                    }
                ],
            },
        ),
        "04-tool-use-input-nested-3-deep": rec(
            type="assistant",
            message={
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_b",
                        "name": "X",
                        "input": {"outer": {"middle": {"inner": payload}}},
                    }
                ],
            },
        ),
        "05-tool-use-input-array-of-strings": rec(
            type="assistant",
            message={
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_c",
                        "name": "X",
                        "input": {"args": ["--flag", payload, "--other"]},
                    }
                ],
            },
        ),
        "06-tool-result-string": rec(
            type="user",
            message={
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_a",
                        "content": f"out: {payload}",
                    }
                ],
            },
        ),
        "07-tool-result-content-array": rec(
            type="user",
            message={
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_a",
                        "content": [{"type": "text", "text": f"out: {payload}"}],
                    }
                ],
            },
        ),
        "08-tooluseresult-sibling-field": rec(
            type="user",
            message={"role": "user", "content": "ok"},
            toolUseResult={
                "stdout": f"printed {payload}",
                "stderr": "",
                "exitCode": 0,
            },
        ),
        "09-thinking-block": rec(
            type="assistant",
            message={
                "role": "assistant",
                "content": [
                    {
                        "type": "thinking",
                        "thinking": f"the value is {payload}",
                        "signature": "sig",
                    }
                ],
            },
        ),
        "10-multiline-buried-line-3": rec(
            type="user",
            message={
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_a",
                        "content": "line one\nline two\nline three has "
                        + payload
                        + "\nline four",
                    }
                ],
            },
        ),
        "11-json-encoded-inside-a-string": rec(
            type="user",
            message={
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_a",
                        "content": json.dumps({"config": {"key": payload}}),
                    }
                ],
            },
        ),
        "12-adjacent-to-quotes-and-punctuation": rec(
            type="user",
            message={"role": "user", "content": f'{{"k":"{payload}","n":1}}'},
        ),
        "13-dict-key-not-value": rec(
            type="user",
            message={
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_a",
                        "content": {payload: "this value is innocuous"},
                    }
                ],
            },
        ),
        "14-url-query-parameter": rec(
            type="user",
            message={
                "role": "user",
                "content": (
                    f"curl https://api.example.com/v1?token={payload}&x=1"
                ),
            },
        ),
    }


CELLS = sorted(placements("PLACEHOLDER"))


def _entry_point() -> list[str]:
    """Resolve the CLI under test, as an argv prefix.

    Three tiers, in descending order of how much they prove:

      1. ``CCS_SANITIZE_BIN`` -- CI points this at a specific artifact (the
         wheel installed into a clean venv) rather than whatever the test
         environment happens to have on PATH. This is the tier that makes
         the matrix evidence about the published package.
      2. ``ccs-sanitize`` on PATH -- the console script, wherever it lives.
      3. ``python -m ccs_sanitize.cli`` -- the module entry point.

    Tier 3 exists so this module cannot silently skip. ``test_cli_smoke.py``
    can afford to skip its entry-point case because its module-execution
    case already covers the wiring; here a skip would drop 57 security
    assertions while still reporting green, which is the exact hollow-gate
    failure ``sanitizer-ci.yml`` is built to prevent. The two invocation
    paths are pinned equivalent by ``test_cli_smoke.py``, so falling back
    costs coverage of the script shim and nothing else.
    """
    override = os.environ.get("CCS_SANITIZE_BIN")
    if override:
        return [override]
    found = shutil.which("ccs-sanitize")
    if found is not None:
        return [found]
    if importlib.util.find_spec("ccs_sanitize") is None:
        pytest.skip("ccs_sanitize is neither on PATH nor importable")
    return [sys.executable, "-m", "ccs_sanitize.cli"]


def _classify(tmp_path, cell: str, line: dict, payload: str) -> str:
    """Run one cell and return its verdict. Never returns the payload."""
    work = tmp_path / cell
    work.mkdir(parents=True, exist_ok=True)
    cfg = work / "cfg.yaml"
    cfg.write_text(CONFIG, encoding="utf-8")
    src = work / "in.jsonl"
    src.write_text(json.dumps(line) + "\n", encoding="utf-8")
    out = work / "out.jsonl"

    # --no-check is the documented test-suite override of the pre-run
    # gitignore guard (PRD section 12b). tmp_path is normally outside any
    # repository, where the guard would warn and proceed anyway, but pinning
    # it keeps the verdict independent of where TMPDIR points. The guard
    # itself is covered by test_init_and_check.py.
    proc = subprocess.run(
        [
            *_entry_point(),
            str(src),
            "-o",
            str(out),
            "-c",
            str(cfg),
            "--no-check",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )

    if not out.exists():
        return "FAIL-CLOSED" if proc.returncode != 0 else "NO-OUTPUT"
    if payload in out.read_text(encoding="utf-8"):
        return "LEAKED"
    return "REDACTED" if proc.returncode == 0 else "CLEAN-BUT-NONZERO"


def _params():
    for label in PAYLOADS:
        for cell in CELLS:
            issue = KNOWN_LEAKS.get((cell, label))
            marks = ()
            if issue is not None:
                marks = pytest.mark.xfail(
                    strict=True,
                    reason=(
                        f"#{issue}: dict keys are never transformed, so a "
                        "config-driven rule cannot reach this position. "
                        "Strict, so fixing #190 turns this red and forces "
                        "the entry to be removed from KNOWN_LEAKS."
                    ),
                )
            yield pytest.param(label, cell, marks=marks, id=f"{label}:{cell}")


@pytest.mark.parametrize("label,cell", list(_params()))
def test_payload_does_not_survive_placement(tmp_path, label: str, cell: str) -> None:
    """No structural position may yield a written output containing the payload.

    Asserting on the verdict rather than on output bytes keeps this stable
    across the jitter work planned for v1 (PRD section 9b); byte-exactness
    is owned by test_golden_determinism.py.
    """
    payload = PAYLOADS[label]
    verdict = _classify(tmp_path, cell, placements(payload)[cell], payload)
    assert verdict in {"REDACTED", "FAIL-CLOSED"}, (
        f"cell {cell} with {label} returned {verdict}; a written output must "
        f"never contain the planted value"
    )


def test_secret_never_survives_any_placement(tmp_path) -> None:
    """The fail-closed contract, stated once over the whole matrix.

    Separate from the parametrized test because this is the property the
    residual scan (PRD section 5) promises unconditionally: a secret is
    either scrubbed or the run writes nothing, regardless of where it sits.
    No cell here is expected to xfail -- if this ever needs an exemption,
    the exemption is the bug.
    """
    survivors = [
        cell
        for cell in CELLS
        if _classify(tmp_path, cell, placements(SECRET)[cell], SECRET) == "LEAKED"
    ]
    assert not survivors, f"secret survived in written output at: {survivors}"
