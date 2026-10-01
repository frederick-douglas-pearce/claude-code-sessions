"""Tests for probes/denial_kind.py (issue #276).

Four jobs:

  - functional: the probe counts each `toolDenialKind` value, its versions,
    its `is_error` split and its marker matches correctly, and keeps "no
    tool_result block", "is_error absent" and "is_error null" apart.
  - robust: malformed envelopes and unreadable files are counted, not fatal.
  - content-free: plant sentinels in every surface the probe reads and assert
    none reaches stdout or stderr in either output mode. The one deliberate
    exception is pinned rather than hidden: an enum-shaped value IS printed,
    because naming unattested values is the probe's whole job (see its OUTPUT
    CONTRACT). Its edges (length, spaces, trailing newline) are pinned too, so
    the exception cannot widen silently.
  - attested: run over the one committed sanitized fixture that holds a denial.

Synthetic data only, except the attested test, which reads a committed
sanitized fixture. Run: ``python3 -m pytest tooling/format-scan/tests/``
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from ._helpers import PROBE_PY, load_probe, make_session

probe_mod = load_probe()

REPO_ROOT = Path(__file__).resolve().parents[3]
DENIAL_FIXTURE = REPO_ROOT / "fixtures" / "sanitized" / "hook-trace-denial-and-stop-ladder.jsonl"

S_PROMPT = "PLANTEDpromptSENTINELzqx42"
S_PATH = "/Users/planteduser/PLANTEDpathSENTINEL"
S_UUID = "deadbeef-1111-4222-8333-PLANTEDuuid01"
S_CRED = "kElPLANTEDcredSHAPED1234567890abQZ"
S_VERSION = "2.1.PLANTEDversion"
# Lowercase sentinels that sit just outside ENUM_RE's edges. Each would be
# printed if the bar were widened in that one direction.
S_LONG = "plantedlongsentinel" + "x" * 22  # 41 characters
S_SPACES = "planted spaces sentinel"
S_NEWLINE = "plantednewlinesentinel\n"
S_DIGIT_FIRST = "9plantedfirstcharsentinel"
ALL_SENTINELS = (S_PROMPT, S_PATH, S_UUID, S_CRED, S_VERSION, S_LONG, S_SPACES, S_NEWLINE.strip(), S_DIGIT_FIRST)


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
    assert report["summary"]["lines_scanned"] == 6
    rows = report["by_kind"]
    assert rows["permission-rule"]["lines"] == 2
    assert rows["permission-rule"]["markers"] == {"hook-error-prefix": 1, "blocked-by-hook-phrase": 1}
    assert (rows["permission-rule"]["first_version"], rows["permission-rule"]["last_version"]) == ("2.1.201", "2.1.286")
    assert rows["user-rejected"]["markers"] == {"user-declined": 1}
    assert rows["automode-blocked"]["markers"] == {"permission-phrase": 1}
    assert rows["automode-unavailable"]["markers"] == {"no-marker": 1}
    for row in rows.values():
        assert set(row["is_error"]) == {"true"}
        assert row["multi_tool_result_lines"] == 0


def test_version_order_is_numeric(tmp_path):
    make_session(
        tmp_path,
        "proj",
        "s1",
        lines=[denial("user-rejected", "x", version=v) for v in ("2.1.99", "2.1.250", "2.1.4")],
    )
    row = probe_mod.probe(tmp_path)["by_kind"]["user-rejected"]
    assert (row["first_version"], row["last_version"]) == ("2.1.4", "2.1.250")


def test_absent_null_and_missing_block_stay_apart(tmp_path):
    no_key = denial("user-rejected", "x")
    del no_key["message"]["content"][0]["is_error"]
    no_block = denial("user-rejected", "x")
    no_block["message"]["content"] = [{"type": "text", "text": "not a tool result"}]
    make_session(tmp_path, "proj", "s1", lines=[no_key, denial("user-rejected", "x", is_error=None), no_block])
    row = probe_mod.probe(tmp_path)["by_kind"]["user-rejected"]
    assert row["is_error"] == {"<absent>": 1, "<null>": 1, "<no-tool-result>": 1}
    assert row["markers"] == {"no-marker": 2, "<no-tool-result>": 1}


def test_multi_tool_result_lines_are_counted(tmp_path):
    line = denial("permission-rule", "PreToolUse:Read hook error: x")
    line["message"]["content"].append({"type": "tool_result", "tool_use_id": "t2", "content": "ok", "is_error": False})
    make_session(tmp_path, "proj", "s1", lines=[line])
    assert probe_mod.probe(tmp_path)["by_kind"]["permission-rule"]["multi_tool_result_lines"] == 1


def test_blank_lines_and_parse_errors_count_like_scan(tmp_path):
    session = tmp_path / "proj" / "s1.jsonl"
    session.parent.mkdir(parents=True)
    session.write_text("\n\n" + json.dumps(denial("user-rejected", "x")) + "\n{not json\n[1, 2]\n", encoding="utf-8")
    s = probe_mod.probe(tmp_path)["summary"]
    assert (s["lines_scanned"], s["parse_errors"]) == (1, 1)


def test_malformed_envelopes_do_not_crash(tmp_path):
    bad = []
    for message in ("a string", ["a", "list"], None, {"content": "string content"}, {"content": [{"type": "tool_result"}]}):
        line = denial("permission-rule", "x")
        line["message"] = message
        bad.append(line)
    make_session(tmp_path, "proj", "s1", lines=bad)
    row = probe_mod.probe(tmp_path)["by_kind"]["permission-rule"]
    assert row["lines"] == 5


def test_unreadable_file_is_counted_not_named(tmp_path):
    make_session(tmp_path, "proj", "s1", lines=[denial("user-rejected", "x")])
    (tmp_path / "proj" / f"{S_PROMPT}.jsonl").mkdir()  # a directory named *.jsonl
    out = run_cli(tmp_path, "--json")
    assert S_PROMPT not in out
    report = json.loads(out)
    assert report["summary"]["files_dropped"] == 1
    assert report["by_kind"]["user-rejected"]["lines"] == 1


@pytest.mark.parametrize("mode", [(), ("--json",)])
def test_no_sentinel_reaches_output(tmp_path, mode):
    make_session(
        tmp_path,
        "proj",
        "s1",
        lines=[
            # Sentinels in the tool_result text, string and list forms.
            denial("permission-rule", f"PreToolUse:Read hook error: {S_PROMPT} {S_PATH} {S_CRED}"),
            denial("user-rejected", f"{S_CRED} user doesn't want to proceed {S_PATH}", as_list=True),
            # Sentinels AS the toolDenialKind value. None is enum-shaped, and
            # the last four each miss ENUM_RE by exactly one property.
            denial(S_PROMPT, "x"),
            denial(S_PATH, "x"),
            denial(S_UUID, "x"),
            denial(S_CRED, "x"),
            denial(S_LONG, "x"),
            denial(S_SPACES, "x"),
            denial(S_NEWLINE, "x"),
            denial(S_DIGIT_FIRST, "x"),
            # Non-string values.
            denial({"nested": S_PROMPT}, "x"),
            denial([S_PROMPT], "x"),
            # Sentinels in version and is_error.
            denial("permission-rule", "x", version=S_VERSION),
            denial("permission-rule", "x", version="2.1.250\n"),
            denial("permission-rule", "x", is_error=S_PROMPT),
        ],
    )
    out = run_cli(tmp_path, *mode)
    for s in ALL_SENTINELS:
        assert s not in out, f"sentinel leaked: {s!r}"
    assert "<non-enum len=" in out
    assert "<other>" in out


def test_newline_terminated_version_is_not_recorded(tmp_path):
    make_session(tmp_path, "proj", "s1", lines=[denial("user-rejected", "x", version="2.1.250\n")])
    row = probe_mod.probe(tmp_path)["by_kind"]["user-rejected"]
    assert row["distinct_versions"] == 0


def test_enum_shaped_value_is_printed_by_design(tmp_path):
    # The documented weaker bar: a short lowercase value is printed as itself,
    # up to and including the 40-character limit. If this ever needs to stop
    # being true, the probe has lost its purpose.
    at_limit = "a" * 40
    make_session(tmp_path, "proj", "s1", lines=[denial("some-new-kind", "x"), denial(at_limit, "x")])
    out = run_cli(tmp_path)
    assert "some-new-kind" in out
    assert at_limit in out


def test_json_output_is_valid(tmp_path):
    make_session(tmp_path, "proj", "s1", lines=[denial("permission-rule", "x")])
    report = json.loads(run_cli(tmp_path, "--json"))
    assert report["tool"] == "ccs-denial-kind-probe"
    assert report["by_kind"]["permission-rule"]["lines"] == 1


def test_attested_fixture_denial(tmp_path):
    # One committed fixture, copied alone, so new fixtures elsewhere in
    # fixtures/sanitized/ cannot move these counts. Fails, not skips, if the
    # fixture is gone: the reference cites this attestation.
    assert DENIAL_FIXTURE.is_file(), f"attested fixture missing: {DENIAL_FIXTURE.name}"
    shutil.copy(DENIAL_FIXTURE, tmp_path / DENIAL_FIXTURE.name)
    row = probe_mod.probe(tmp_path)["by_kind"]["permission-rule"]
    assert row["lines"] == 1
    assert row["markers"] == {"hook-error-prefix": 1}
    assert row["is_error"] == {"true": 1}
