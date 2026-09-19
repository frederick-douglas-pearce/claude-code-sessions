"""The content-free security-contract gate for scan.py (issue #97).

scan.py reads raw, unsanitized session transcripts and — by its own SECURITY
CONTRACT docstring — must NEVER emit their contents. The no-values discipline is
"this script's responsibility, not the hook's" (the block_secret_reads.py hook
deliberately does not block the scanner's read path). This test converts that
responsibility from a reviewer's eyeball into an automated gate:

  plant known sentinels (prompt text, a filesystem path, a UUID, a
  credential-shaped token, a model identifier) into every value-bearing surface
  the scanner reads — jsonl line values, subagent trace lines, meta.json
  manifest values, and tool-results file bytes — then run EVERY scanner mode and
  assert not one sentinel byte reaches stdout.

Issue #237 extended the planted surfaces to everything its five statistic
families read: `message.stop_reason` (see below), `message.stop_sequence`,
`message.stop_details.explanation`, `message.model`, `tool_use.id` and the
matching `tool_result.tool_use_id` (the join keys, which nothing planted
before), an unmatched `tool_use_id` for the orphan path, an unallowlisted
MCP-shaped `tool_use.name`, dict and bare-string `toolUseResult` bodies, and a
string-shaped `user` `message.content`.

`stop_reason` is the load-bearing one. It is the single field that issue
promotes to EMITTABLE_VALUE_FIELDS, and the two sources disagree about it:
scan.py's whitelist bar is "a closed, content-free vocabulary", while
reference/data-dictionary.md:99 says to "treat this as an open enum, not a
closed switch". The resolution is that the scanner emits the documented values
from a fixed constant and folds anything unrecognized into a fixed bucket — so
planting a sentinel there is not a contradiction of the whitelist, it is the
assertion that the fold happens. A scanner that echoed the value would fail
here, which was confirmed by deliberately making it echo one.

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
S_MODEL = "claude-PLANTEDmodelSENTINEL-9"            # a model identifier
ALL_SENTINELS = (S_PROMPT, S_PATH, S_UUID, S_CRED, S_MODEL)


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
            # --- The stop_* surfaces (issue #237). `stop_reason` itself carries
            # a sentinel: it is the one field being newly promoted to
            # EMITTABLE_VALUE_FIELDS, and reference/data-dictionary.md:99 calls
            # it an OPEN enum while scan.py's whitelist bar is a CLOSED
            # vocabulary. So the scanner must fold an unrecognized value into a
            # fixed bucket rather than echo it, and this is what proves it does.
            # `stop_sequence` and `stop_details` stay off the whitelist entirely.
            {"type": "assistant", "uuid": "a2", "version": "2.1.150",
             "message": {
                 "model": S_MODEL,
                 "stop_reason": S_PROMPT,
                 "stop_sequence": S_CRED,
                 "stop_details": {"type": "refusal", "explanation": S_PROMPT},
                 "content": [
                     # An allowlisted tool name with a REAL id, so the join key
                     # itself is sentinel-covered — the previous fixture planted
                     # no `id` and no `tool_use_id` at all.
                     {"type": "tool_use", "id": S_UUID + "-tu", "name": "Edit",
                      "input": {"file_path": S_PATH}},
                     # An MCP-shaped tool name. Tool names are NOT a closed
                     # vocabulary (server- and author-derived), which is the same
                     # disqualifier scan.py already applies to `agentType`, so an
                     # unallowlisted name must fold rather than surface.
                     {"type": "tool_use", "id": S_UUID + "-mcp",
                      "name": "mcp__" + S_PROMPT + "__do",
                      "input": {"q": S_CRED}},
                 ],
             }},
            # --- The Edit result: a dict `toolUseResult` carrying the diff body.
            {"type": "user", "uuid": "u2", "version": "2.1.150",
             "isSidechain": False,
             "toolUseResult": {
                 "filePath": S_PATH,
                 "oldString": S_PROMPT,
                 "newString": S_CRED,
                 "structuredPatch": [{"lines": [S_PROMPT, S_PATH]}],
             },
             "message": {"content": [
                 {"type": "tool_result", "tool_use_id": S_UUID + "-tu",
                  "content": S_PROMPT},
             ]}},
            # --- An ORPHAN tool_result: its tool_use_id matches no tool_use
            # anywhere in this file. Family 4 is DEFINED by this case, and the
            # natural debug output for an unresolvable set is the set itself.
            {"type": "user", "uuid": "u3", "version": "2.1.150",
             "isSidechain": True,
             "message": {"content": [
                 {"type": "tool_result", "tool_use_id": S_UUID + "-orphan",
                  "content": S_CRED},
             ]}},
            # --- An Agent spawn and its conditional-key envelope. `toolStats`
            # keys are tool names (tool-invocation.md:539), so a key histogram
            # over it would leak by the same route as a free tool-name table.
            {"type": "assistant", "uuid": "a3", "version": "2.1.150",
             "message": {"model": S_MODEL, "stop_reason": "tool_use", "content": [
                 {"type": "tool_use", "id": S_UUID + "-agent", "name": "Agent",
                  "input": {"prompt": S_PROMPT}},
             ]}},
            {"type": "user", "uuid": "u4", "version": "2.1.150",
             "toolUseResult": {
                 "prompt": S_PROMPT,
                 "toolStats": {"readCount": 3, S_PROMPT: 1},
             },
             "message": {"content": [
                 {"type": "tool_result", "tool_use_id": S_UUID + "-agent",
                  "content": S_CRED},
             ]}},
            # --- A BARE-STRING `toolUseResult` (tool-invocation.md:195 counts
            # 240 Edit results in this shape) alongside a STRING-shaped
            # `message.content` on a user line — family 2's minority bucket.
            {"type": "user", "uuid": "u5", "version": "2.1.150",
             "toolUseResult": S_PROMPT + " " + S_PATH,
             "message": {"content": S_CRED}},
        ],
        subagent_traces={
            "agent-abc.jsonl": [
                {"type": "assistant", "uuid": "s1", "isSidechain": True,
                 "version": "2.1.226",
                 "message": {"content": [{"type": "text", "text": S_PROMPT}]}},
            ],
            # A depth-2 subagent, so --probe-nesting and the per-version manifest
            # buckets both have a populated surface to (not) leak from.
            "agent-nested.jsonl": [
                {"type": "assistant", "uuid": "s2", "isSidechain": True,
                 "version": "2.1.226",
                 "message": {"content": [{"type": "text", "text": S_PROMPT}]}},
            ],
        },
        meta_manifests={
            "agent-abc.meta.json": {
                "agentType": "general-purpose",
                "description": S_PROMPT,
                "toolUseId": S_UUID,
                "worktreePath": S_PATH,
                "spawnDepth": 1,
            },
            "agent-nested.meta.json": {
                "agentType": "general-purpose",
                "description": S_PROMPT,
                "toolUseId": S_UUID + "-nested",
                "spawnDepth": 2,
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
    pytest.param(["--probe-nesting"], id="probe-nesting"),
    pytest.param(["--probe-nesting", "--json"], id="probe-nesting-json"),
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
    elif "--probe-nesting" in mode_args:
        # The depth histogram is content-free structure and must be present.
        assert "spawn_depth_histogram" in out or "spawnDepth" in out
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
    for sentinel in ALL_SENTINELS:
        assert sentinel in blob
