"""The content-free security-contract gate for scan.py (issue #97).

scan.py reads raw, unsanitized session transcripts and — by its own SECURITY
CONTRACT docstring — must NEVER emit their contents. The no-values discipline is
"this script's responsibility, not the hook's" (the block_secret_reads.py hook
deliberately does not block the scanner's read path). This test converts that
responsibility from a reviewer's eyeball into an automated gate:

  plant known sentinels (prompt text, a filesystem path, a UUID, a
  credential-shaped token) into every value-bearing surface the scanner reads —
  jsonl line values, subagent trace lines, meta.json manifest values, and
  tool-results file bytes — then run EVERY scanner mode and assert not one
  sentinel byte reaches stdout.

The sentinels are synthetic (never real session data); the suite is hermetic and
offline.

Run: ``python3 -m pytest tooling/format-scan/tests/``
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from ._helpers import BASELINE, SCAN_PY, make_session

# Distinct, high-entropy sentinels — one per kind of content the contract bans.
# None of these is a real secret; the point is that the scanner must not echo any
# value it reads, regardless of shape.
S_PROMPT = "PLANTEDpromptSENTINELzqx42"            # free-text prompt / description
S_PATH = "/Users/planteduser/PLANTEDpathSENTINEL"   # filesystem path PII
S_UUID = "deadbeef-1111-4222-8333-PLANTEDuuid01"    # an id value
S_CRED = "kElPLANTEDcredSHAPED1234567890abQZ"        # credential-shaped token
ALL_SENTINELS = (S_PROMPT, S_PATH, S_UUID, S_CRED)


@pytest.fixture
def planted_root(tmp_path):
    """A synthetic projects tree with a sentinel planted in every value the
    scanner touches: jsonl envelope values, content blocks, subagent trace
    lines, meta.json manifest values, and tool-results file bytes."""
    make_session(
        tmp_path,
        slug="-home-PLANTEDpathSENTINEL-proj",  # slug dir name carries a sentinel
        session_id="sess-1",
        lines=[
            {"type": "user", "uuid": S_UUID, "cwd": S_PATH, "version": "2.1.150",
             "message": {"content": [{"type": "text", "text": S_PROMPT}]}},
            {"type": "assistant", "uuid": "a1", "version": "2.1.150",
             "requestId": S_CRED,
             "message": {"content": [
                 {"type": "tool_use", "input": {"command": S_CRED}},
                 {"type": "tool_result",
                  "content": f"Preview (first 50) {S_PROMPT} truncated"},
             ]}},
        ],
        subagent_traces={
            "agent-abc.jsonl": [
                {"type": "assistant", "uuid": "s1", "isSidechain": True,
                 "message": {"content": [{"type": "text", "text": S_PROMPT}]}},
            ],
        },
        meta_manifests={
            "agent-abc.meta.json": {
                "agentType": "general-purpose",
                "description": S_PROMPT,
                "toolUseId": S_UUID,
                "worktreePath": S_PATH,
            },
        },
        tool_results={
            f"toolu_{S_CRED}.txt": (S_PROMPT + " " + S_PATH).encode("utf-8"),
        },
    )
    return tmp_path


def _run_scan(*args) -> str:
    """Run scan.py as the CLI and return combined stdout+stderr."""
    proc = subprocess.run(
        [sys.executable, str(SCAN_PY), *args],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout + proc.stderr


SCAN_MODES = [
    pytest.param([], id="default"),
    pytest.param(["--json"], id="json"),
    pytest.param(["--baseline", str(BASELINE)], id="baseline"),
    pytest.param(["--baseline", str(BASELINE), "--json"], id="baseline-json"),
    pytest.param(["--probe-tool-results"], id="probe-tool-results"),
    pytest.param(["--probe-tool-results", "--json"], id="probe-tool-results-json"),
]


@pytest.mark.parametrize("mode_args", SCAN_MODES)
def test_no_sentinel_reaches_stdout(planted_root, mode_args):
    out = _run_scan(str(planted_root), *mode_args)
    for sentinel in ALL_SENTINELS:
        assert sentinel not in out, (
            f"LEAK: sentinel {sentinel!r} surfaced in scanner output for "
            f"mode {mode_args!r}. This is a content-free-contract violation."
        )


@pytest.mark.parametrize("mode_args", SCAN_MODES)
def test_modes_still_emit_expected_structure(planted_root, mode_args):
    """Guard against a vacuous pass: confirm each mode produced real output and
    surfaced the (content-free) key names it is supposed to."""
    out = _run_scan(str(planted_root), *mode_args)
    assert out.strip()
    if "--probe-tool-results" in mode_args:
        assert "Preview (first" in out or "marker_counts" in out
    else:
        # The meta.json key NAMES are emittable; their values are not.
        assert "agentType" in out
        assert "worktreePath" in out


def test_sentinels_are_actually_present_in_fixtures(planted_root):
    """Sanity check the fixtures really contain the sentinels — otherwise the
    leak test above would pass vacuously."""
    blob = "".join(
        p.read_text(encoding="utf-8", errors="replace")
        for p in planted_root.rglob("*")
        if p.is_file()
    )
    for sentinel in (S_PROMPT, S_PATH, S_UUID, S_CRED):
        assert sentinel in blob
