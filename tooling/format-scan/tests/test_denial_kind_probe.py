"""Tests for probes/denial_kind.py (issue #276).

Three jobs:

  - functional: the probe counts each `toolDenialKind` value, its versions,
    its `is_error` split and its marker matches correctly.
  - content-free: plant sentinels in every surface the probe reads and assert
    none reaches stdout in either output mode. The one deliberate exception is
    pinned rather than hidden: an enum-shaped value IS printed, because naming
    unattested values is the probe's whole job (see its OUTPUT CONTRACT).
  - attested: run over fixtures/sanitized/ and find the one committed denial.

Synthetic data only, except the attested test, which reads committed sanitized
fixtures. Run: ``python3 -m pytest tooling/format-scan/tests/``
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from ._helpers import make_session

PROBE_PY = Path(__file__).resolve().parent.parent / "probes" / "denial_kind.py"
REPO_ROOT = Path(__file__).resolve().parents[3]
SANITIZED = REPO_ROOT / "fixtures" / "sanitized"

_spec = importlib.util.spec_from_file_location("ccs_denial_kind_probe", PROBE_PY)
probe_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(probe_mod)

S_PROMPT = "PLANTEDpromptSENTINELzqx42"
S_PATH = "/Users/planteduser/PLANTEDpathSENTINEL"
S_UUID = "deadbeef-1111-4222-8333-PLANTEDuuid01"
S_CRED = "kElPLANTEDcredSHAPED1234567890abQZ"
S_VERSION = "2.1.PLANTEDversion"
ALL_SENTINELS = (S_PROMPT, S_PATH, S_UUID, S_CRED, S_VERSION)


def denial(kind, text, *, version="2.1.250", is_error=True, as_list=False):
    content = [{"type": "text", "text": text}] if as_list else text
    return {
        "type": "user",
        "uuid": S_UUID,
        "cwd": S_PATH,
        "version": version,
        "message": {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": S_UUID, "content": content, "is_error": is_error}],
        },
        "toolUseResult": f"Error: {S_PROMPT}",
        "toolDenialKind": kind,
    }


def run_cli(root: Path, *extra: str) -> str:
    out = subprocess.run(
        [sys.executable, str(PROBE_PY), str(root), *extra],
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout + out.stderr


def test_counts_values_versions_and_markers(tmp_path):
    make_session(
        tmp_path,
        "proj",
        "s1",
        lines=[
            denial("permission-rule", "PreToolUse:Read hook error: Blocked by x hook", version="2.1.201"),
            denial("permission-rule", "Blocked by the secrets hook", version="2.1.286"),
            denial("user-rejected", "The user doesn't want to proceed with this tool use.", as_list=True),
            denial("automode-blocked", "Permission for this action was denied by auto mode"),
            denial("automode-unavailable", "something else entirely"),
            {"type": "user", "message": {"role": "user", "content": "no denial here"}},
        ],
    )
    report = probe_mod.probe(tmp_path)
    assert report["summary"]["tool_denial_lines"] == 5
    rows = report["by_kind"]
    assert rows["permission-rule"]["lines"] == 2
    assert rows["permission-rule"]["markers"] == {"hook-error-prefix": 1, "blocked-by-hook-phrase": 1}
    assert (rows["permission-rule"]["first_version"], rows["permission-rule"]["last_version"]) == ("2.1.201", "2.1.286")
    assert rows["user-rejected"]["markers"] == {"user-declined": 1}
    assert rows["automode-blocked"]["markers"] == {"permission-phrase": 1}
    assert rows["automode-unavailable"]["markers"] == {"no-marker": 1}
    assert all(r["is_error"] == {"true": 1} or r["is_error"] == {"true": 2} for r in rows.values())


def test_version_order_is_numeric(tmp_path):
    make_session(
        tmp_path,
        "proj",
        "s1",
        lines=[denial("user-rejected", "x", version=v) for v in ("2.1.99", "2.1.250", "2.1.4")],
    )
    row = probe_mod.probe(tmp_path)["by_kind"]["user-rejected"]
    assert (row["first_version"], row["last_version"]) == ("2.1.4", "2.1.250")


@pytest.mark.parametrize("mode", [(), ("--json",)])
def test_no_sentinel_reaches_stdout(tmp_path, mode):
    make_session(
        tmp_path,
        "proj",
        "s1",
        lines=[
            # Sentinels in the tool_result text, string and list forms.
            denial("permission-rule", f"PreToolUse:Read hook error: {S_PROMPT} {S_PATH} {S_CRED}"),
            denial("user-rejected", f"{S_CRED} user doesn't want to proceed {S_PATH}", as_list=True),
            # Sentinels AS the toolDenialKind value: none is enum-shaped.
            denial(S_PROMPT, "x"),
            denial(S_PATH, "x"),
            denial(S_UUID, "x"),
            denial(S_CRED, "x"),
            denial(f"automode blocked {S_PROMPT}", "x"),
            # A non-string value.
            denial({"nested": S_PROMPT}, "x"),
            # A sentinel in version.
            denial("permission-rule", "x", version=S_VERSION),
        ],
    )
    out = run_cli(tmp_path, *mode)
    for s in ALL_SENTINELS:
        assert s not in out, f"sentinel leaked: {s}"
    assert "<non-enum len=" in out
    assert "<dict>" in out


def test_enum_shaped_value_is_printed_by_design(tmp_path):
    # The documented weaker bar: a short lowercase value is printed as itself.
    # If this ever needs to stop being true, the probe has lost its purpose.
    make_session(tmp_path, "proj", "s1", lines=[denial("some-new-kind", "x")])
    assert "some-new-kind" in run_cli(tmp_path)


def test_json_output_is_valid(tmp_path):
    make_session(tmp_path, "proj", "s1", lines=[denial("permission-rule", "x")])
    report = json.loads(run_cli(tmp_path, "--json"))
    assert report["tool"] == "ccs-denial-kind-probe"
    assert report["by_kind"]["permission-rule"]["lines"] == 1


@pytest.mark.skipif(not SANITIZED.is_dir(), reason="fixtures/sanitized not present")
def test_attested_fixture_denial():
    # hook-trace-denial-and-stop-ladder.jsonl holds one PreToolUse hook denial.
    report = probe_mod.probe(SANITIZED)
    row = report["by_kind"]["permission-rule"]
    assert row["lines"] == 1
    assert row["markers"] == {"hook-error-prefix": 1}
    assert row["is_error"] == {"true": 1}
